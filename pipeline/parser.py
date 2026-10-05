#!/usr/bin/env python3
"""Parse DeepSeek EN/ZH pricing pages into normalized semantic records."""
from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

EN_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
ZH_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


class TableParser(HTMLParser):
    """Small dependency-free HTML table parser; the authority page has one table."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", html_module.unescape("".join(self._cell))).strip(" \x00")
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def semantic_hash(record: dict[str, Any]) -> str:
    body = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(body)


def _money(text: str) -> float:
    match = re.search(r"(?:\$)?([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        raise ValueError(f"No numeric price in {text!r}")
    return float(match.group(1))


def _whole_text(markup: str) -> str:
    stripped = re.sub(r"<script\b[^>]*>.*?</script>", " ", markup, flags=re.I | re.S)
    stripped = re.sub(r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.I | re.S)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", html_module.unescape(stripped)).strip(" \x00")


def _extract_table(markup: str) -> list[list[str]]:
    parser = TableParser()
    parser.feed(markup)
    if len(parser.tables) != 1:
        raise ValueError(f"Expected exactly one pricing table, found {len(parser.tables)}")
    return parser.tables[0]


def _parse_rate_rows(rows: list[list[str]], models: list[str], language: str) -> dict[str, Any]:
    rate_rows = []
    for row in rows:
        if language == "en":
            if any(label in cell.upper() for cell in row for label in ("OFF-PEAK", "PEAK")):
                rate_rows.append(row)
        else:
            if any(label in cell for cell in row for label in ("空闲时段", "高峰时段")):
                rate_rows.append(row)
    if len(rate_rows) != 6:
        raise ValueError(f"Expected six pricing rows for {language}, found {len(rate_rows)}")

    categories = ["cache_hit", "cache_hit", "cache_miss", "cache_miss", "output", "output"]
    bands = ["off_peak", "peak", "off_peak", "peak", "off_peak", "peak"]
    rates = {model: {"off_peak": {}, "peak": {}} for model in models}
    for row, category, band in zip(rate_rows, categories, bands):
        values = [_money(cell) for cell in row[-len(models):]]
        for model, value in zip(models, values):
            rates[model][band][category] = value
    return rates


def parse_page(body: bytes, language: str) -> dict[str, Any]:
    markup = body.decode("utf-8")
    rows = _extract_table(markup)
    text = _whole_text(markup)
    # Schedule sentences are quoted verbatim from the page. Two generations are
    # recognized; anything else fails closed.
    #   2026-08: "... UTC, Monday through Friday (all other hours are off-peak)."
    #   2026-10: "... UTC, Monday through Friday, excluding Chinese public holidays.
    #             All other hours are off-peak, including weekends and Chinese public
    #             holidays in full."  (ZH: 不含中国法定节假日 — statutory public holidays)
    if language == "en":
        model_row = next((row for row in rows if row and row[0].upper() == "MODEL"), None)
        version_row = next((row for row in rows if row and row[0].upper() == "MODEL VERSION"), None)
        currency = "USD"
        window_match = re.search(
            r"Peak hours are\s+01:00\s*-\s*04:00\s+and\s+06:00\s*-\s*10:00\s+UTC,\s+Monday through Friday"
            r"(?:\s*\(all other hours are off-peak\)\.|,\s*excluding Chinese public holidays\.\s*All other hours are off-peak, including weekends and Chinese public holidays in full\.)",
            text,
            flags=re.I,
        )
        holiday = bool(window_match and "excluding Chinese public holidays" in window_match.group(0))
    elif language == "zh":
        model_row = next((row for row in rows if row and row[0] == "模型"), None)
        version_row = next((row for row in rows if row and row[0] == "模型版本"), None)
        currency = "CNY"
        window_match = re.search(
            r"高峰时段为北京时间周一至周五\s*9:00\s*-\s*12:00、14:00\s*-\s*18:00（其余为空闲时段）。"
            r"|北京时间周一至周五（不含中国法定节假日）\s*9:00\s*-\s*12:00、14:00\s*-\s*18:00\s*为高峰时段；其余时段，包括周末及中国法定节假日全天均为空闲时段。",
            text,
        )
        holiday = bool(window_match and "不含中国法定节假日" in window_match.group(0))
    else:
        raise ValueError(f"Unsupported language {language!r}")

    if model_row is None or version_row is None:
        raise ValueError(f"Missing model/version row on {language} page")
    models = [re.sub(r"\(\d+\)$", "", cell).strip() for cell in model_row[1:]]
    versions = version_row[1:]
    if not models or len(models) != len(versions) or not window_match:
        raise ValueError(f"Incomplete semantic authority on {language} page")
    quote = re.sub(r"\s+", " ", window_match.group(0)).strip()

    rates = _parse_rate_rows(rows, models, language)
    for model in models:
        for category in ("cache_hit", "cache_miss", "output"):
            off_peak = rates[model]["off_peak"][category]
            peak = rates[model]["peak"][category]
            if abs(off_peak * 2 - peak) > 1e-12:
                raise ValueError(f"{language} {model} {category}: off-peak is not half peak")

    record = {
        "language": language,
        "currency": currency,
        "unit_tokens": 1_000_000,
        "models": [{"id": model, "version": version} for model, version in zip(models, versions)],
        "schedule": {
            "timezone": "UTC",
            "peak_weekdays": [1, 2, 3, 4, 5],
            "peak_windows": [
                {"start": "01:00", "end": "04:00"},
                {"start": "06:00", "end": "10:00"},
            ],
            "holiday_exclusion": "cn_public_holidays" if holiday else None,
            "quote": quote,
        },
        "rates": rates,
    }
    record["semantic_sha256"] = semantic_hash(record)
    return record


def compare_surfaces(en: dict[str, Any], zh: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if en["models"] != zh["models"]:
        findings.append("Model IDs or versions differ between EN and ZH surfaces.")
    if en["schedule"]["peak_weekdays"] != zh["schedule"]["peak_weekdays"]:
        findings.append("Peak weekdays differ between EN and ZH surfaces.")
    if en["schedule"]["peak_windows"] != zh["schedule"]["peak_windows"]:
        findings.append("Peak windows differ after Beijing-to-UTC normalization.")
    if en["schedule"].get("holiday_exclusion") != zh["schedule"].get("holiday_exclusion"):
        findings.append("Holiday exclusion differs between EN and ZH surfaces.")
    return {
        "status": "conflict" if findings else "matched",
        "findings": findings or [
            "EN and ZH pages agree on model IDs/versions, weekday scope, holiday exclusion, UTC windows, and the 2:1 peak/off-peak relationship. Currency amounts are independent local price surfaces and were not FX-converted."
        ],
    }


def parse_file(path: Path, language: str) -> dict[str, Any]:
    body = path.read_bytes()
    record = parse_page(body, language)
    record["raw_sha256"] = _sha256_bytes(body)
    return record
