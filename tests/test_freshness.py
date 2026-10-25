"""Fixture tests for pipeline/freshness.py: agree (0), changed (1), incomplete (2)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
import freshness  # noqa: E402

RATES = json.loads((PROJECT / "data" / "rates.json").read_text())
CURRENT = {s["language"]: s["raw_file"] for s in RATES["sources"]}
STORED = {
    "en": (PROJECT / "data" / "raw" / CURRENT["English"]).read_bytes(),
    "zh": (PROJECT / "data" / "raw" / CURRENT["Chinese"]).read_bytes(),
}
LOCAL = freshness.published_loader(str(PROJECT))
PAGES = PROJECT / "frontend" if (PROJECT / "frontend").is_dir() else PROJECT


def fetcher(en: bytes | None = None, zh: bytes | None = None, fail: set[str] = frozenset()):
    bodies = {"en": en if en is not None else STORED["en"], "zh": zh if zh is not None else STORED["zh"]}

    def fetch(language: str, url: str):
        if language in fail:
            raise RuntimeError("HTTP 503")
        return bodies[language], {"transport": "fixture"}

    return fetch


def check(fetch, loader=LOCAL):
    before = freshness.tree_digest(PROJECT)
    result = freshness.run_check(fetch, loader, project=PROJECT, published_label="fixture")
    assert result["source_tree_unchanged"] is True
    assert freshness.tree_digest(PROJECT) == before  # stored captures, pin and published data untouched
    return result


def fields(result) -> set[str]:
    return {d["field"] for d in result["differences"]}


# ------------------------------------------------------------------ exit 0

def test_identical_authorities_agree() -> None:
    result = check(fetcher())
    assert result["exit_code"] == 0, result["differences"] or result["incomplete"]
    assert result["sources_opened"] == result["sources_total"] == 2
    assert result["reviewed_pin"]["status"] == "matches"
    assert result["retained_historical_evidence"][0]["file"].startswith("deepseek-pricing-en-20260828")
    moved = {d["field"] for d in result["informational"]["capture_provenance_moves_on_rebuild"]}
    assert "data/rates.json:current_as_of" in moved  # re-capture time is provenance, not a difference


def test_transport_and_template_churn_is_not_a_price_change() -> None:
    noisy = {
        language: body.replace(b"anchorWithStickyNavbar_YAqC", b"anchorWithStickyNavbar_Zz9Q")
        .replace(b"</head>", b'<script src="/assets/js/main.4f2a9c.js"></script><style>.x{}</style></head>', 1)
        for language, body in STORED.items()
    }
    result = check(fetcher(en=noisy["en"], zh=noisy["zh"]))
    assert result["exit_code"] == 0, result["differences"]
    assert result["informational"]["raw_bytes_changed_vs_stored"] == {"en": True, "zh": True}
    assert result["sources"]["en"]["text"]["page_text_changed"] is False


# ------------------------------------------------------------------ exit 1

def test_changed_rate_is_reported_even_though_the_reviewed_pin_refuses_it() -> None:
    en = STORED["en"].replace(b"<td>$0.15</td>", b"<td>$0.14</td>", 1).replace(b"<td>$0.3</td>", b"<td>$0.28</td>", 1)
    assert en != STORED["en"]
    result = check(fetcher(en=en))
    assert result["exit_code"] == 1
    assert "data/rates.json:price_bases[current].models[deepseek-flash].rates.off_peak.cache_miss" in fields(result)
    assert "data/rates.json:price_bases[current].models[deepseek-flash].rates.peak.cache_miss" in fields(result)
    assert "sources.html:DeepSeek Flash off_peak (cache hit, cache miss, output)" in fields(result)
    assert result["reviewed_pin"]["status"].startswith("ordinary build would refuse")


def test_changed_model_version_is_reported() -> None:
    en = STORED["en"].replace(b"DeepSeek-V4.1-Flash-1017</td>", b"DeepSeek-V4.2-Flash</td>", 1)
    zh = STORED["zh"].replace(b"DeepSeek-V4.1-Flash-1017</td>", b"DeepSeek-V4.2-Flash</td>", 1)
    result = check(fetcher(en=en, zh=zh))
    assert result["exit_code"] == 1
    assert "data/rates.json:price_bases[current].models[deepseek-flash].version" in fields(result)
    assert "sources.html:DeepSeek Flash version" in fields(result)


def test_changed_holiday_rule_on_both_surfaces_is_reported() -> None:
    en = STORED["en"].replace(
        b"Monday through Friday, excluding Chinese public holidays. All other hours are off-peak, including weekends and Chinese public holidays in full.",
        b"Monday through Friday (all other hours are off-peak).",
    )
    zh = STORED["zh"].replace(
        "北京时间周一至周五（不含中国法定节假日）9:00 - 12:00、14:00 - 18:00 为高峰时段；其余时段，包括周末及中国法定节假日全天均为空闲时段。".encode(),
        "高峰时段为北京时间周一至周五 9:00 - 12:00、14:00 - 18:00（其余为空闲时段）。".encode(),
    )
    assert en != STORED["en"] and zh != STORED["zh"]
    result = check(fetcher(en=en, zh=zh))
    assert result["exit_code"] == 1, result["incomplete"]
    assert "data/rates.json:price_bases[current].schedule.holiday_exclusion" in fields(result)
    assert "sources.html:schedule quote (English, Chinese)" in fields(result)


def test_new_search_fetch_price_moves_the_semantic_hash() -> None:
    en = STORED["en"].replace(b"<td>$0.75</td>", b"<td>$0.90</td>", 1)
    result = check(fetcher(en=en))
    assert result["exit_code"] == 1
    assert "data/rates.json:sources[English].semantic_sha256" in fields(result)


def test_stale_published_page_is_reported(tmp_path: Path) -> None:
    published = tmp_path / "site"
    (published / "data").mkdir(parents=True)
    stale = json.loads(json.dumps(RATES))
    stale["price_bases"][0]["models"][1]["rates"]["peak"]["output"] = 4.0
    (published / "data" / "rates.json").write_text(json.dumps(stale))
    shutil.copy2(PAGES / "sources.html", published / "sources.html")
    result = check(fetcher(), freshness.published_loader(str(published)))
    assert result["exit_code"] == 1
    [difference] = result["differences"]
    assert difference == {
        "field": "data/rates.json:price_bases[current].models[deepseek-v4-pro].rates.peak.output",
        "published": 4.0,
        "fresh": 3.96,
    }


# ------------------------------------------------------------------ exit 2

def test_unreachable_authority_is_incomplete_not_clean() -> None:
    result = check(fetcher(fail={"zh"}))
    assert result["exit_code"] == 2
    assert result["sources_opened"] == 1 and result["sources_total"] == 2
    assert result["sources"]["zh"]["status"] == "unreachable"
    assert result["differences"] == []


def test_unparseable_authority_is_incomplete() -> None:
    en = STORED["en"].replace(b"<table", b"<div", 1)
    result = check(fetcher(en=en))
    assert result["exit_code"] == 2
    assert result["sources"]["en"]["status"] == "unparseable"


def test_language_conflict_is_incomplete_even_with_differences() -> None:
    en = STORED["en"].replace(
        b"Monday through Friday, excluding Chinese public holidays. All other hours are off-peak, including weekends and Chinese public holidays in full.",
        b"Monday through Friday (all other hours are off-peak).",
    )
    result = check(fetcher(en=en))
    assert result["exit_code"] == 2
    assert any("conflict" in reason for reason in result["incomplete"])


def test_unreadable_published_baseline_is_incomplete(tmp_path: Path) -> None:
    result = check(fetcher(), freshness.published_loader(str(tmp_path)))
    assert result["exit_code"] == 2
    assert any("data/rates.json could not be read" in reason for reason in result["incomplete"])


def test_unrecognized_sources_page_layout_is_incomplete(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    shutil.copy2(PROJECT / "data" / "rates.json", tmp_path / "data" / "rates.json")
    (tmp_path / "sources.html").write_text("<html><body>redesigned</body></html>")
    result = check(fetcher(), freshness.published_loader(str(tmp_path)))
    assert result["exit_code"] == 2
    assert any("layout not recognized" in reason for reason in result["incomplete"])


def test_cli_refuses_to_write_inside_the_project() -> None:
    with pytest.raises(SystemExit) as raised:
        freshness.main(["--output", str(PROJECT / "data" / "receipt.json")])
    assert raised.value.code == 2
