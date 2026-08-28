#!/usr/bin/env python3
"""Build the static rate schema from pinned DeepSeek authority snapshots."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from parser import EN_URL, ZH_URL, compare_surfaces, parse_file

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
OUTPUT = PROJECT / "data" / "rates.json"
PIN = PROJECT / "pipeline" / "expected_semantics.json"
EFFECTIVE_AT = "2026-08-16T16:00:00Z"


def _latest(language: str) -> Path:
    candidates = sorted(RAW.glob(f"deepseek-pricing-{language}-*.html"))
    if not candidates:
        raise FileNotFoundError(f"No raw {language} pricing capture. Run pipeline/fetch.py.")
    return candidates[-1]


def _capture_timestamp(path: Path) -> str:
    match = re.search(r"-(\d{8}T\d{6}Z)\.html$", path.name)
    if not match:
        raise ValueError(f"Raw capture filename lacks UTC timestamp: {path.name}")
    parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _pin_record(en: dict, zh: dict, agreement: dict) -> dict:
    return {
        "schema_version": 1,
        "en_semantic_sha256": en["semantic_sha256"],
        "zh_semantic_sha256": zh["semantic_sha256"],
        "agreement_status": agreement["status"],
        "model_ids": [model["id"] for model in en["models"]],
        "effective_at": EFFECTIVE_AT,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accept-source-change", action="store_true", help="Review and replace the normalized semantic pin")
    args = parser.parse_args()

    en_path, zh_path = _latest("en"), _latest("zh")
    en, zh = parse_file(en_path, "en"), parse_file(zh_path, "zh")
    agreement = compare_surfaces(en, zh)
    pin = _pin_record(en, zh, agreement)

    if args.accept_source_change:
        PIN.write_text(json.dumps(pin, indent=2) + "\n")
        print(f"Accepted semantic pin: {PIN}")
    elif not PIN.exists():
        raise RuntimeError("No semantic pin exists. Inspect parsed records, then rerun with --accept-source-change.")
    else:
        expected = json.loads(PIN.read_text())
        if expected != pin:
            raise RuntimeError(
                "Normalized vendor pricing semantics changed; build failed closed. "
                "Inspect EN/ZH records before using --accept-source-change.\n"
                f"expected={json.dumps(expected, sort_keys=True)}\n"
                f"actual={json.dumps(pin, sort_keys=True)}"
            )

    captured_at = max(_capture_timestamp(en_path), _capture_timestamp(zh_path))
    display_names = {
        "deepseek-v4-flash": "DeepSeek V4 Flash",
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "deepseek-v4-flash-vision-exp": "DeepSeek V4 Flash Vision Exp",
    }
    models = []
    for model in en["models"]:
        models.append({
            "id": model["id"],
            "name": display_names.get(model["id"], model["id"]),
            "version": model["version"],
            "rates": en["rates"][model["id"]],
        })

    output = {
        "schema_version": 1,
        "provider": "DeepSeek",
        "currency": "USD",
        "unit_tokens": 1_000_000,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "current_as_of": captured_at,
        "coverage_status": agreement["status"],
        "coverage_findings": agreement["findings"],
        "price_bases": [{
            "id": "deepseek-2026-08-16-banded",
            "status": "current",
            "effective_at": EFFECTIVE_AT,
            "effective_date_provenance": {
                "type": "historical_vendor_transition_notice",
                "captured_at": "2026-08-15T00:00:00Z",
                "quote": "The new prices take effect at 16:00 UTC on August 16, 2026.",
                "note": "The live authority now presents this basis as current and no longer repeats the transition date.",
            },
            "schedule": en["schedule"],
            "models": models,
        }],
        "announced_future_bases": [],
        "sources": [
            {
                "language": "English",
                "url": EN_URL,
                "captured_at": _capture_timestamp(en_path),
                "raw_file": en_path.name,
                "raw_sha256": en["raw_sha256"],
                "semantic_sha256": en["semantic_sha256"],
                "currency": en["currency"],
                "schedule_quote": en["schedule"]["quote"],
            },
            {
                "language": "Chinese",
                "url": ZH_URL,
                "captured_at": _capture_timestamp(zh_path),
                "raw_file": zh_path.name,
                "raw_sha256": zh["raw_sha256"],
                "semantic_sha256": zh["semantic_sha256"],
                "currency": zh["currency"],
                "schedule_quote": zh["schedule"]["quote"],
                "local_currency_rates": zh["rates"],
            },
        ],
        "limitations": [
            "Estimate uses declared USD prices and the batch start time; it does not model a job spanning multiple bands.",
            "Taxes, reseller markups, retries, credits, undocumented discounts, and provider-side token-count differences are excluded.",
            "No provider invoice or per-request billing ledger is available here; this is a declared-price estimate, not a billing audit.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"Built {OUTPUT}: {len(models)} models, coverage={agreement['status']}, as of {captured_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
