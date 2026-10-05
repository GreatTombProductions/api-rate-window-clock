#!/usr/bin/env python3
"""Full-object Python/JavaScript differential parity."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
from calculator import calculate  # noqa: E402


def main() -> int:
    data = json.loads((PROJECT / "data" / "rates.json").read_text())
    cases = json.loads((PROJECT / "tests" / "cases.json").read_text())
    requests = [case["request"] for case in cases]
    # Add second-precision and cross-date checks beyond the shared assertion table.
    requests.extend([
        {"timestamp": "2026-10-16T09:59:37Z", "model": "deepseek-v4-pro", "cache_hit": 123456789, "cache_miss": 2345678, "output": 345678},
        {"timestamp": "2026-10-19T01:00:00-07:00", "model": "deepseek-flash", "cache_hit": 987654321, "cache_miss": 123456, "output": 789012},
        {"timestamp": "2026-12-31T23:59:59Z", "model": "deepseek-flash", "cache_hit": 1, "cache_miss": 2, "output": 3},
        {"timestamp": "2026-10-12T17:30:00Z", "model": "deepseek-flash", "cache_hit": 5, "cache_miss": 7, "output": 11, "cn_holiday": True},
        {"timestamp": "2026-10-15T07:00:00+08:00", "model": "deepseek-v4-pro", "cache_hit": 1000, "cache_miss": 2000, "output": 3000, "cn_holiday": True},
        {"timestamp": "2026-10-15T09:30:00+08:00", "model": "deepseek-v4-pro", "cache_hit": 1000, "cache_miss": 2000, "output": 3000, "cn_holiday": False},
    ])
    expected = [calculate(data, request) for request in requests]
    process = subprocess.run(
        ["node", str(PROJECT / "tests" / "parity_runner.js")],
        input=json.dumps({"data": data, "requests": requests}),
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    actual = json.loads(process.stdout)
    if actual != expected:
        for index, (python_result, js_result) in enumerate(zip(expected, actual)):
            if python_result != js_result:
                print(f"Parity mismatch at case {index}:\nPY={python_result}\nJS={js_result}", file=sys.stderr)
        return 1
    print(f"Differential parity passed: {len(requests)} full result objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
