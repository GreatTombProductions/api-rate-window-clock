#!/usr/bin/env python3
"""Fetch DeepSeek pricing authorities with multi-transport and hard deadlines."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from parser import EN_URL, ZH_URL

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
DEADLINE_SECONDS = 70
UA = "GreatTombProductions pricing audit contact@greattombproductions.com"
SOURCES = {"en": EN_URL, "zh": ZH_URL}


def _urllib(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read(), dict(response.headers.items())


def _curl(url: str) -> tuple[bytes, dict[str, str]]:
    process = subprocess.run(
        ["curl", "-sS", "--http1.1", "--max-time", "55", "-D", "-", "-A", UA, url],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(f"curl exit {process.returncode}: {process.stderr.decode(errors='replace')[:240]}")
    marker = b"\r\n\r\n"
    header, separator, body = process.stdout.partition(marker)
    if not separator or b" 200 " not in header.splitlines()[0]:
        raise RuntimeError(f"curl returned unexpected response: {header[:160]!r}")
    headers = {}
    for line in header.decode(errors="replace").splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return body, headers


def fetch(url: str) -> tuple[bytes, dict[str, str], str, list[str]]:
    result: dict = {}

    def work() -> None:
        errors: list[str] = []
        for name, transport in (("urllib", _urllib), ("curl", _curl)):
            try:
                body, headers = transport(url)
                if not body.strip():
                    raise RuntimeError("empty body")
                result.update(body=body, headers=headers, transport=name, errors=errors)
                return
            except Exception as error:  # external transport boundary
                errors.append(f"{name}: {error}")
        result["errors"] = errors

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(DEADLINE_SECONDS)
    if thread.is_alive():
        raise RuntimeError(f"hard deadline exceeded after {DEADLINE_SECONDS}s")
    if "body" not in result:
        raise RuntimeError("; ".join(result.get("errors", ["unknown fetch failure"])))
    return result["body"], result["headers"], result["transport"], result["errors"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cross-check", action="store_true", help="Fetch with both transports and require byte equality")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"fetched_at": timestamp, "sources": {}}

    for language, url in SOURCES.items():
        body, headers, transport, prior_errors = fetch(url)
        transports = {transport: hashlib.sha256(body).hexdigest()}
        if args.cross_check:
            other_name, other = ("curl", _curl) if transport == "urllib" else ("urllib", _urllib)
            other_body, _ = other(url)
            transports[other_name] = hashlib.sha256(other_body).hexdigest()
            if other_body != body:
                raise RuntimeError(f"{language}: urllib/curl payloads differ")
        html_path = RAW / f"deepseek-pricing-{language}-{timestamp}.html"
        html_path.write_bytes(body)
        receipt["sources"][language] = {
            "url": url,
            "file": html_path.name,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "transport": transport,
            "transport_hashes": transports,
            "prior_errors": prior_errors,
            "headers": {key: headers[key] for key in headers if key.lower() in {"content-type", "etag", "last-modified", "date"}},
        }
        print(f"OK {language}: {len(body):,} bytes via {transport} -> {html_path.name}")

    receipt_path = RAW / f"fetch-receipt-{timestamp}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(f"Receipt: {receipt_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
