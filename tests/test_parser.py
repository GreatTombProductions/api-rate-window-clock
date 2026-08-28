from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
from parser import compare_surfaces, parse_file  # noqa: E402

EN = PROJECT / "data" / "raw" / "deepseek-pricing-en-20260828T095809Z.html"
ZH = PROJECT / "data" / "raw" / "deepseek-pricing-zh-20260828T095810Z.html"
PIN = json.loads((PROJECT / "pipeline" / "expected_semantics.json").read_text())


def test_live_capture_semantics_match_reviewed_pin() -> None:
    en, zh = parse_file(EN, "en"), parse_file(ZH, "zh")
    assert en["semantic_sha256"] == PIN["en_semantic_sha256"]
    assert zh["semantic_sha256"] == PIN["zh_semantic_sha256"]
    assert en["raw_sha256"] == "cf2c6fb2dd8a32a538f12a8176175b8809a3516326a5cb30dfe52d63c490a968"
    assert zh["raw_sha256"] == "899affbdbc33d0be620d8dea59e86f5036c11b5410b14d060b8d2874c74f38e5"


def test_surfaces_agree_structurally_without_fx_conversion() -> None:
    en, zh = parse_file(EN, "en"), parse_file(ZH, "zh")
    comparison = compare_surfaces(en, zh)
    assert comparison["status"] == "matched"
    assert en["currency"] == "USD"
    assert zh["currency"] == "CNY"
    assert en["schedule"]["peak_weekdays"] == [1, 2, 3, 4, 5]
    assert en["schedule"]["peak_windows"] == [
        {"start": "01:00", "end": "04:00"},
        {"start": "06:00", "end": "10:00"},
    ]


def test_three_models_and_separate_components() -> None:
    en = parse_file(EN, "en")
    assert [model["id"] for model in en["models"]] == [
        "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"
    ]
    assert en["rates"]["deepseek-v4-pro"]["peak"] == {
        "cache_hit": 0.044, "cache_miss": 1.32, "output": 3.96
    }
