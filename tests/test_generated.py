from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DATA = json.loads((PROJECT / "data" / "rates.json").read_text())
MANIFEST = json.loads((PROJECT / "manifest.json").read_text())
# Source checkout keeps pages in frontend/; the published repository serves them from the root.
PAGES = PROJECT / "frontend" if (PROJECT / "frontend").is_dir() else PROJECT


def test_generated_rate_contract() -> None:
    assert DATA["schema_version"] == 1
    assert DATA["coverage_status"] == "matched"
    assert DATA["currency"] == "USD"
    assert DATA["unit_tokens"] == 1_000_000
    assert DATA["current_as_of"] == "2026-10-25T03:07:32Z"
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
        assert (PAGES / name).is_file()
    assert "fetch('data/rates.json'" in (PAGES / "app.js").read_text()
    assert (PROJECT / "LICENSE").is_file()
    assert (PROJECT / ".nojekyll").is_file()


def test_fixture_dates_follow_the_current_basis() -> None:
    """A refresh moves the verified basis forward; earlier fixtures would show 'unavailable'."""
    import re
    from datetime import datetime

    effective = datetime.fromisoformat(DATA["price_bases"][0]["effective_at"].replace("Z", "+00:00"))
    page = (PAGES / "index.html").read_text()
    stamps = re.findall(r'data-fixture="([^"]+)"', page)
    assert stamps, "boundary fixture buttons missing"
    cases = json.loads((PROJECT / "tests" / "cases.json").read_text())
    stamps += [c["request"]["timestamp"] for c in cases if c["id"] != "before-verified-basis-is-unavailable"]
    for stamp in stamps:
        assert datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= effective, stamp
