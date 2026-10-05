from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
from parser import compare_surfaces, parse_file  # noqa: E402

EN = PROJECT / "data" / "raw" / "deepseek-pricing-en-20261005T224057Z.html"
ZH = PROJECT / "data" / "raw" / "deepseek-pricing-zh-20261005T224057Z.html"
EN_AUG = PROJECT / "data" / "raw" / "deepseek-pricing-en-20260828T095809Z.html"
ZH_AUG = PROJECT / "data" / "raw" / "deepseek-pricing-zh-20260828T095810Z.html"
PIN = json.loads((PROJECT / "pipeline" / "expected_semantics.json").read_text())


def test_live_capture_semantics_match_reviewed_pin() -> None:
    en, zh = parse_file(EN, "en"), parse_file(ZH, "zh")
    assert en["semantic_sha256"] == PIN["en_semantic_sha256"]
    assert zh["semantic_sha256"] == PIN["zh_semantic_sha256"]
    assert en["raw_sha256"] == "210f102275ccf1a6542f08a3bc9e4b4c7c83278cb74b35217bffa112df6363b2"
    assert zh["raw_sha256"] == "5a7b1832592387340f2fc456399b34b89b05f3fa167c2e35909e2fa4afe021e3"


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


def test_october_models_rates_and_holiday_exclusion() -> None:
    en, zh = parse_file(EN, "en"), parse_file(ZH, "zh")
    assert [model["id"] for model in en["models"]] == ["deepseek-flash", "deepseek-v4-pro"]  # "(1)" marker stripped
    assert en["rates"]["deepseek-flash"]["off_peak"] == {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.6}
    assert en["rates"]["deepseek-v4-pro"]["peak"] == {"cache_hit": 0.044, "cache_miss": 1.32, "output": 3.96}
    assert en["schedule"]["holiday_exclusion"] == zh["schedule"]["holiday_exclusion"] == "cn_public_holidays"
    assert en["schedule"]["quote"].endswith("including weekends and Chinese public holidays in full.")
    assert "不含中国法定节假日" in zh["schedule"]["quote"]


def test_august_layout_still_parses_without_holiday_exclusion() -> None:
    en, zh = parse_file(EN_AUG, "en"), parse_file(ZH_AUG, "zh")
    assert [model["id"] for model in en["models"]] == ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]
    assert en["schedule"]["holiday_exclusion"] is None and zh["schedule"]["holiday_exclusion"] is None
    assert compare_surfaces(en, zh)["status"] == "matched"


def test_unrecognized_schedule_wording_fails_closed() -> None:
    import pytest
    from parser import parse_page

    body = EN.read_bytes().replace(b"excluding Chinese public holidays", b"excluding some holidays")
    with pytest.raises(ValueError, match="Incomplete semantic authority"):
        parse_page(body, "en")
