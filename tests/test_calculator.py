from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
from calculator import calculate  # noqa: E402

DATA = json.loads((PROJECT / "data" / "rates.json").read_text())
CASES = json.loads((PROJECT / "tests" / "cases.json").read_text())


def assert_expected(result: dict, expected: dict) -> None:
    assert result["status"] == expected["status"]
    if result["status"] != "ok":
        assert result["reason"]
        return
    assert result["regime"] == expected["regime"]
    assert result["cost"] == pytest.approx(expected["cost"], abs=1e-12)
    if expected.get("next_cheaper") is None and "next_timestamp" not in expected:
        assert result["next_cheaper"] is None
    if "next_timestamp" in expected:
        next_cheaper = result["next_cheaper"]
        assert next_cheaper["timestamp"] == expected["next_timestamp"]
        assert next_cheaper["cost"] == pytest.approx(expected["next_cost"], abs=1e-12)
        assert next_cheaper["wait_seconds"] == expected["wait_seconds"]
        assert next_cheaper["savings_percent"] == pytest.approx(expected["savings_percent"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_shared_cases(case: dict) -> None:
    assert_expected(calculate(DATA, case["request"]), case["expected"])


def test_conflicting_authority_fails_open_as_unavailable() -> None:
    data = copy.deepcopy(DATA)
    data["coverage_status"] = "conflict"
    result = calculate(data, CASES[0]["request"])
    assert result["status"] == "unavailable"
    assert "conflict" in result["reason"].lower()


def test_missing_rate_is_not_zero() -> None:
    data = copy.deepcopy(DATA)
    data["price_bases"][0]["models"][0]["rates"]["off_peak"]["output"] = None
    result = calculate(data, CASES[0]["request"])
    assert result["status"] == "unavailable"


def test_announced_future_basis_is_not_applied_early_and_can_be_next_cheaper() -> None:
    data = copy.deepcopy(DATA)
    future = copy.deepcopy(data["price_bases"][0])
    future["id"] = "future-lower-test"
    future["status"] = "announced"
    future["effective_at"] = "2026-09-01T02:30:00Z"
    for model in future["models"]:
        for band in model["rates"].values():
            for category in band:
                band[category] /= 4
    data["price_bases"].append(future)
    request = {
        "timestamp": "2026-09-01T02:00:00Z", "model": "deepseek-v4-flash",
        "cache_hit": 10_000_000, "cache_miss": 1_000_000, "output": 1_000_000,
    }
    result = calculate(data, request)
    assert result["basis_id"] == "deepseek-2026-08-16-banded"
    assert result["cost"] == pytest.approx(1.9)
    assert result["next_cheaper"]["timestamp"] == "2026-09-01T02:30:00Z"
    assert result["next_cheaper"]["basis_id"] == "future-lower-test"
    assert result["next_cheaper"]["cost"] == pytest.approx(0.475)


@pytest.mark.parametrize("field", ["cache_hit", "cache_miss", "output"])
def test_invalid_token_count_rejected(field: str) -> None:
    request = copy.deepcopy(CASES[0]["request"])
    request[field] = -1
    with pytest.raises(ValueError, match="non-negative integer"):
        calculate(DATA, request)


def test_offsetless_timestamp_rejected() -> None:
    request = copy.deepcopy(CASES[0]["request"])
    request["timestamp"] = "2026-09-01T01:00:00"
    with pytest.raises(ValueError, match="offset"):
        calculate(DATA, request)
