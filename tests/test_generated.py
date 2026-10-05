from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DATA = json.loads((PROJECT / "data" / "rates.json").read_text())
MANIFEST = json.loads((PROJECT / "manifest.json").read_text())


def test_generated_rate_contract() -> None:
    assert DATA["schema_version"] == 1
    assert DATA["coverage_status"] == "matched"
    assert DATA["currency"] == "USD"
    assert DATA["unit_tokens"] == 1_000_000
    assert DATA["current_as_of"] == "2026-10-05T22:40:57Z"
    assert len(DATA["price_bases"]) == 1
    assert DATA["announced_future_bases"] == []
    basis = DATA["price_bases"][0]
    assert [m["id"] for m in basis["models"]] == ["deepseek-flash", "deepseek-v4-pro"]
    assert basis["effective_at"] == DATA["current_as_of"]  # claimed only from the verifying capture
    assert basis["schedule"]["holiday_exclusion"] == "cn_public_holidays"
    prior = DATA["superseded_bases"][0]
    assert prior["id"] == "deepseek-2026-08-16-banded" and "never used" in prior["note"]
    assert len(DATA["sources"]) == 2


def test_manifest_release_contract() -> None:
    assert MANIFEST["status"] == "released"
    assert MANIFEST["github"] == "https://github.com/GreatTombProductions/api-rate-window-clock"
    assert MANIFEST["url"] == "https://greattombproductions.github.io/api-rate-window-clock/"
    assert MANIFEST["released_date"] == "2026-08-28"


def test_static_files_exist_and_use_flat_data_path() -> None:
    for name in ["index.html", "methodology.html", "sources.html", "app.js", "calculator.js", "style.css"]:
        assert (PROJECT / "frontend" / name).is_file()
    assert "fetch('data/rates.json'" in (PROJECT / "frontend" / "app.js").read_text()
    assert (PROJECT / "LICENSE").is_file()
    assert (PROJECT / ".nojekyll").is_file()
