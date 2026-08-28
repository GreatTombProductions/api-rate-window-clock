#!/usr/bin/env python3
"""Reference implementation for effective-dated, weekday-aware API pricing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

TOKEN_FIELDS = ("cache_hit", "cache_miss", "output")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(timezone.utc)


def _basis_at(data: dict[str, Any], timestamp: datetime) -> dict[str, Any] | None:
    eligible = [basis for basis in data["price_bases"] if parse_timestamp(basis["effective_at"]) <= timestamp]
    return max(eligible, key=lambda basis: basis["effective_at"]) if eligible else None


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _regime(basis: dict[str, Any], timestamp: datetime) -> str:
    schedule = basis["schedule"]
    iso_weekday = timestamp.isoweekday()
    minute = timestamp.hour * 60 + timestamp.minute
    if iso_weekday in schedule["peak_weekdays"]:
        for window in schedule["peak_windows"]:
            if _minutes(window["start"]) <= minute < _minutes(window["end"]):
                return "peak"
    return "off_peak"


def _model(basis: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    return next((model for model in basis["models"] if model["id"] == model_id), None)


def _cost_at(data: dict[str, Any], timestamp: datetime, model_id: str, tokens: dict[str, int]) -> dict[str, Any] | None:
    basis = _basis_at(data, timestamp)
    if basis is None:
        return None
    model = _model(basis, model_id)
    if model is None:
        return None
    regime = _regime(basis, timestamp)
    rates = model["rates"].get(regime)
    if not rates or any(rates.get(field) is None for field in TOKEN_FIELDS):
        return None
    total = sum(tokens[field] * rates[field] for field in TOKEN_FIELDS) / data["unit_tokens"]
    return {
        "basis_id": basis["id"],
        "effective_at": basis["effective_at"],
        "regime": regime,
        "model_version": model["version"],
        "rates": {field: rates[field] for field in TOKEN_FIELDS},
        "cost": round(total, 12),
    }


def _candidate_boundaries(data: dict[str, Any], timestamp: datetime) -> list[datetime]:
    candidates: set[datetime] = set()
    midnight = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in range(0, 10):
        day = midnight + timedelta(days=day_offset)
        candidates.add(day)
        candidates.add(day + timedelta(days=1))
        for basis in data["price_bases"]:
            for window in basis["schedule"]["peak_windows"]:
                for edge in (window["start"], window["end"]):
                    candidates.add(day + timedelta(minutes=_minutes(edge)))
    for basis in data["price_bases"]:
        candidates.add(parse_timestamp(basis["effective_at"]))
    return sorted(candidate for candidate in candidates if timestamp < candidate <= timestamp + timedelta(days=8))


def calculate(data: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    timestamp = parse_timestamp(request["timestamp"])
    model_id = str(request["model"])
    tokens: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        value = request.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        tokens[field] = value

    unavailable = {
        "status": "unavailable",
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "model": model_id,
        "tokens": tokens,
    }
    if data.get("coverage_status") != "matched":
        return {**unavailable, "reason": "Authority surfaces conflict or are unavailable."}

    selected = _cost_at(data, timestamp, model_id, tokens)
    if selected is None:
        return {**unavailable, "reason": "No complete declared rate basis covers this model and timestamp."}

    next_cheaper = None
    for candidate in _candidate_boundaries(data, timestamp):
        compared = _cost_at(data, candidate, model_id, tokens)
        if compared is not None and compared["cost"] < selected["cost"] - 1e-15:
            savings = selected["cost"] - compared["cost"]
            next_cheaper = {
                "timestamp": candidate.isoformat().replace("+00:00", "Z"),
                "basis_id": compared["basis_id"],
                "regime": compared["regime"],
                "cost": compared["cost"],
                "savings": round(savings, 12),
                "savings_percent": round((savings / selected["cost"] * 100) if selected["cost"] else 0.0, 9),
                "wait_seconds": int((candidate - timestamp).total_seconds()),
            }
            break

    return {
        "status": "ok",
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "model": model_id,
        "tokens": tokens,
        **selected,
        "next_cheaper": next_cheaper,
    }
