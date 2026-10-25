#!/usr/bin/env python3
"""Check whether the published calculator still agrees with DeepSeek's live pricing pages.

One command, no arguments needed:

    python3 pipeline/freshness.py [--published-base URL|DIR] [--output receipt.json] [--captures-dir DIR]

What it does:
  1. Re-fetches both current pricing authorities the build reads (English and Chinese
     Models & Pricing pages) into a temporary directory. Stored captures are never touched.
  2. Rebuilds with this project's own parser and build script in a scratch copy of the
     project, so the fresh result is exactly what a refresh would publish.
  3. Compares the rebuilt rate data, field by field, with the published `data/rates.json`
     that backs the calculator, and checks the hand-written values on the published
     sources page (USD table, schedule quotes, semantic hashes) against the fresh parse.
  4. Exits 0 when no published value differs, 1 when one does, and 2 when the check is
     incomplete (a page could not be fetched or parsed, the two languages conflict, the
     published baseline could not be read, or the scratch build failed). Incomplete takes
     precedence over a clean or changed result.

Contents, not containers: the raw HTML changes with every site rebuild (asset hashes,
class names). Raw-byte and page-text changes are reported as information only; a
difference is counted only when a parsed model, version, rate, token class, weekday,
window, holiday rule, quote or local-currency amount differs. Capture timestamps and
raw hashes that every re-capture moves are reported separately, never as differences.

This tool has one current price basis and no monthly dimension, so there is no month
argument: every run checks the whole published table. The 2026-08-28 English capture
that supplies the superseded (history-only) table is retained evidence; the live page
no longer carries that table, so it is not re-fetched, only re-derived for consistency.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_module
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PIPELINE = Path(__file__).resolve().parent
PROJECT = PIPELINE.parent
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from parser import EN_URL, ZH_URL, _whole_text, parse_page  # noqa: E402

LIVE_BASE = "https://greattombproductions.github.io/api-rate-window-clock/"
AUTHORITIES = {"en": EN_URL, "zh": ZH_URL}
PUBLISHED_FILES = ("data/rates.json", "sources.html")
BUILD_TIMEOUT = 120

# Fields every re-capture moves even when nothing upstream changed. Reported, not counted.
PROVENANCE_PATTERNS = (
    re.compile(r"^generated_at$"),
    re.compile(r"^current_as_of$"),
    re.compile(r"^price_bases\[current\]\.(id|effective_at|effective_date_provenance\.captured_at)$"),
    re.compile(r"^sources\[[^\]]+\]\.(captured_at|raw_file|raw_sha256)$"),
)
# Lists of records are compared by identity, not position.
LIST_KEYS = {"price_bases": "status", "superseded_bases": "id", "models": "id", "sources": "language"}


Fetcher = Callable[[str, str], tuple[bytes, dict[str, Any]]]
Loader = Callable[[str], bytes]


# ---------------------------------------------------------------- comparison helpers

def flatten(value: Any, path: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {} if out is None else out
    if isinstance(value, dict):
        for key in sorted(value):
            flatten(value[key], f"{path}.{key}" if path else key, out)
    elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        field = LIST_KEYS.get(path.rsplit(".", 1)[-1].split("[")[0])
        keys = [item.get(field) for item in value] if field else []
        if field and all(isinstance(k, str) for k in keys) and len(set(keys)) == len(keys):
            for key, item in zip(keys, value):
                flatten(item, f"{path}[{key}]", out)
        else:
            for index, item in enumerate(value):
                flatten(item, f"{path}[{index}]", out)
    else:
        out[path] = value
    return out


def is_provenance(path: str) -> bool:
    return any(pattern.match(path) for pattern in PROVENANCE_PATTERNS)


def compare_rates(published: dict, fresh: dict) -> tuple[list[dict], list[dict]]:
    left, right = flatten(published), flatten(fresh)
    differences, provenance = [], []
    for path in sorted(set(left) | set(right)):
        before, after = left.get(path, "<absent>"), right.get(path, "<absent>")
        if before == after:
            continue
        entry = {"field": f"data/rates.json:{path}", "published": before, "fresh": after}
        (provenance if is_provenance(path) else differences).append(entry)
    return differences, provenance


def _money_list(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", text)]


def sources_page_values(markup: str) -> dict[str, Any]:
    """Extract the hand-written values on sources.html. Unknown layout raises."""
    semantic = re.findall(r"Semantic SHA-256:</strong>\s*([0-9a-f]{64})", markup)
    quotes = [html_module.unescape(q) for q in re.findall(r"Schedule quote:</strong>\s*“(.*?)”", markup, flags=re.S)]
    section = re.search(r"<h2>Current USD table</h2>(.*?)<h2>", markup, flags=re.S)
    if len(semantic) != 2 or len(quotes) != 2 or not section:
        raise ValueError(
            f"published sources page layout not recognized (semantic hashes={len(semantic)}, "
            f"quotes={len(quotes)}, current table={'found' if section else 'missing'})"
        )
    models = {}
    for block in re.findall(r"<p><strong>(.*?)</strong>\s*\((.*?)\)</p>\s*<ul>(.*?)</ul>", section.group(1), flags=re.S):
        name, version_note, items = block
        off = re.search(r"Off-peak:(.*?)</li>", items, flags=re.S)
        peak = re.search(r"<li>Peak:(.*?)</li>", items, flags=re.S)
        if not off or not peak:
            raise ValueError(f"published sources page: rate lines missing for {name!r}")
        models[html_module.unescape(name).strip()] = {
            "version": re.split(r"[;\s]", version_note.strip(), maxsplit=1)[0],
            "off_peak": _money_list(off.group(1)),
            "peak": _money_list(peak.group(1)),
        }
    if not models:
        raise ValueError("published sources page: no current-table models found")
    return {"semantic_sha256": semantic, "schedule_quotes": [re.sub(r"\s+", " ", q).strip() for q in quotes], "models": models}


def compare_sources_page(markup: str, fresh: dict) -> list[dict]:
    page = sources_page_values(markup)
    by_language = {s["language"]: s for s in fresh["sources"]}
    expected_semantic = [by_language["English"]["semantic_sha256"], by_language["Chinese"]["semantic_sha256"]]
    expected_quotes = [by_language["English"]["schedule_quote"], by_language["Chinese"]["schedule_quote"]]
    differences = []
    for label, shown, wanted in (
        ("semantic SHA-256 (English, Chinese)", page["semantic_sha256"], expected_semantic),
        ("schedule quote (English, Chinese)", page["schedule_quotes"], expected_quotes),
    ):
        if shown != wanted:
            differences.append({"field": f"sources.html:{label}", "published": shown, "fresh": wanted})
    current = next(b for b in fresh["price_bases"] if b["status"] == "current")
    fresh_models = {m["name"]: m for m in current["models"]}
    for name in sorted(set(page["models"]) | set(fresh_models)):
        shown, model = page["models"].get(name), fresh_models.get(name)
        if shown is None or model is None:
            differences.append({"field": f"sources.html:current USD table model {name!r}",
                                "published": "listed" if shown else "<absent>",
                                "fresh": "listed" if model else "<absent>"})
            continue
        if shown["version"] != model["version"]:
            differences.append({"field": f"sources.html:{name} version", "published": shown["version"], "fresh": model["version"]})
        for band in ("off_peak", "peak"):
            wanted = [model["rates"][band][k] for k in ("cache_hit", "cache_miss", "output")]
            if shown[band] != wanted:
                differences.append({"field": f"sources.html:{name} {band} (cache hit, cache miss, output)",
                                    "published": shown[band], "fresh": wanted})
    return differences


def text_sentences(body: bytes) -> list[str]:
    text = _whole_text(body.decode("utf-8", errors="replace"))
    return [s.strip() for s in re.split(r"(?<=[.。；!?])\s+", text) if s.strip()]


def text_change(stored: bytes, fresh: bytes, limit: int = 12) -> dict[str, Any]:
    old, new = text_sentences(stored), text_sentences(fresh)
    removed = [s for s in old if s not in set(new)]
    added = [s for s in new if s not in set(old)]
    return {"page_text_changed": bool(removed or added), "removed": removed[:limit], "added": added[:limit],
            "removed_total": len(removed), "added_total": len(added)}


# ---------------------------------------------------------------- environment

def tree_digest(project: Path) -> str:
    """Hash every input/output the check must leave untouched."""
    digest = hashlib.sha256()
    pages = project / "frontend" if (project / "frontend").is_dir() else project  # published repo: root
    roots = [project / "data", project / "pipeline" / "expected_semantics.json"]
    roots += [pages / name for name in ("index.html", "methodology.html", "sources.html", "app.js", "calculator.js")]
    for root in roots:
        if root.is_file():
            paths = [root]
        else:
            paths = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            digest.update(str(path.relative_to(project)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def live_fetcher(language: str, url: str) -> tuple[bytes, dict[str, Any]]:
    from fetch import fetch  # the producer's own deadline-bounded urllib -> curl transport

    body, headers, transport, errors = fetch(url)
    return body, {"transport": transport, "prior_transport_errors": errors,
                  "headers": {k: v for k, v in headers.items() if k.lower() in {"etag", "last-modified", "date", "content-type"}}}


def published_loader(base: str) -> Loader:
    if re.match(r"^https?://", base):
        from fetch import fetch

        root = base if base.endswith("/") else base + "/"
        return lambda name: fetch(root + name)[0]
    directory = Path(base)

    def load(name: str) -> bytes:
        candidates = [directory / name]
        if name == "sources.html":
            candidates.append(directory / "frontend" / name)  # source checkout layout
        for candidate in candidates:
            if candidate.is_file():
                return candidate.read_bytes()
        raise FileNotFoundError(f"{name} not found under {directory}")

    return load


def stored_latest(project: Path, language: str) -> Path | None:
    captures = sorted((project / "data" / "raw").glob(f"deepseek-pricing-{language}-*.html"))
    return captures[-1] if captures else None


# ---------------------------------------------------------------- the check

def run_check(fetcher: Fetcher, loader: Loader, project: Path = PROJECT, published_label: str = LIVE_BASE,
              captures_dir: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    result: dict[str, Any] = {
        "tool": "API Rate-Window Clock",
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "published_baseline": published_label,
        "scope": ("Both current pricing authorities the build reads, rebuilt with this project's parser and "
                  "build in a scratch tree; compared with published data/rates.json (calculator) and the "
                  "hand-written values on sources.html. No monthly dimension: one current basis."),
        "sources_total": len(AUTHORITIES),
        "sources_opened": 0,
        "sources": {},
        "retained_historical_evidence": [],
        "incomplete": [],
        "differences": [],
        "informational": {},
    }
    before = tree_digest(project)
    with tempfile.TemporaryDirectory(prefix="rate-window-freshness-") as temporary:
        scratch = Path(temporary) / "project"
        shutil.copytree(project / "pipeline", scratch / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(project / "data" / "raw", scratch / "data" / "raw")

        # 1. fresh authorities -> scratch only
        fresh_records: dict[str, dict] = {}
        for language, url in AUTHORITIES.items():
            entry: dict[str, Any] = {"url": url}
            result["sources"][language] = entry
            try:
                body, meta = fetcher(language, url)
                if not body.strip():
                    raise RuntimeError("empty body")
            except Exception as error:  # transport boundary: unreachable is incomplete, never clean
                entry["status"] = "unreachable"
                entry["error"] = str(error)
                result["incomplete"].append(f"{language} authority could not be fetched: {error}")
                continue
            result["sources_opened"] += 1
            entry.update(meta)
            entry.update(bytes=len(body), raw_sha256=hashlib.sha256(body).hexdigest())
            (scratch / "data" / "raw" / f"deepseek-pricing-{language}-{stamp}.html").write_bytes(body)
            if captures_dir:
                captures_dir.mkdir(parents=True, exist_ok=True)
                (captures_dir / f"deepseek-pricing-{language}-{stamp}.html").write_bytes(body)
            stored = stored_latest(project, language)
            if stored is not None:
                stored_bytes = stored.read_bytes()
                entry["stored_capture"] = stored.name
                entry["raw_bytes_match_stored_capture"] = stored_bytes == body
                entry["text"] = text_change(stored_bytes, body)
            try:
                record = parse_page(body, language)
            except Exception as error:  # unknown layout/wording fails closed as incomplete
                entry["status"] = "unparseable"
                entry["error"] = str(error)
                result["incomplete"].append(f"{language} authority fetched but not parseable by the build's parser: {error}")
                continue
            entry["status"] = "parsed"
            entry["semantic_sha256"] = record["semantic_sha256"]
            fresh_records[language] = record

        earliest = sorted((project / "data" / "raw").glob("deepseek-pricing-en-*.html"))
        if earliest:
            result["retained_historical_evidence"].append({
                "file": earliest[0].name,
                "role": "superseded (history-only) table; not re-fetched because the live page no longer carries it",
            })

        # 2. scratch rebuild with the producer's build (pin acceptance only inside scratch)
        fresh_rates = None
        if len(fresh_records) == len(AUTHORITIES):
            process = subprocess.run(
                [sys.executable, str(scratch / "pipeline" / "build.py"), "--accept-source-change"],
                cwd=scratch, capture_output=True, text=True, timeout=BUILD_TIMEOUT, check=False,
            )
            if process.returncode:
                result["incomplete"].append(f"scratch build failed: {(process.stderr or process.stdout).strip()[-600:]}")
            else:
                fresh_rates = json.loads((scratch / "data" / "rates.json").read_text())
                fresh_pin = json.loads((scratch / "pipeline" / "expected_semantics.json").read_text())
                reviewed = json.loads((project / "pipeline" / "expected_semantics.json").read_text())
                moved = sorted(k for k in set(reviewed) | set(fresh_pin)
                               if k != "effective_at" and reviewed.get(k) != fresh_pin.get(k))
                result["reviewed_pin"] = {
                    "status": "matches" if not moved else "ordinary build would refuse (semantic change)",
                    "changed_fields": moved,
                    "note": "effective_at is the capture time and moves with every re-capture; it is not compared.",
                }
                if fresh_rates.get("coverage_status") != "matched":
                    result["incomplete"].append(
                        "English and Chinese authorities conflict: " + "; ".join(fresh_rates.get("coverage_findings", [])))
        else:
            result["incomplete"].append("scratch rebuild skipped: not every authority was fetched and parsed")

        # 3. published baseline
        published_rates, sources_markup = None, None
        try:
            published_rates = json.loads(loader("data/rates.json").decode("utf-8"))
        except Exception as error:
            result["incomplete"].append(f"published data/rates.json could not be read: {error}")
        try:
            sources_markup = loader("sources.html").decode("utf-8")
        except Exception as error:
            result["incomplete"].append(f"published sources.html could not be read: {error}")

        # 4. compare
        if fresh_rates is not None and published_rates is not None:
            differences, provenance = compare_rates(published_rates, fresh_rates)
            result["differences"].extend(differences)
            result["informational"]["capture_provenance_moves_on_rebuild"] = provenance
        if fresh_rates is not None and sources_markup is not None:
            try:
                result["differences"].extend(compare_sources_page(sources_markup, fresh_rates))
            except ValueError as error:
                result["incomplete"].append(str(error))
        result["informational"]["raw_bytes_changed_vs_stored"] = {
            lang: not e.get("raw_bytes_match_stored_capture", True) for lang, e in result["sources"].items() if "raw_sha256" in e}

    after = tree_digest(project)
    result["source_tree_unchanged"] = before == after
    if before != after:
        result["incomplete"].append("project inputs or published data changed during the check (must never happen)")
    result["exit_code"] = 2 if result["incomplete"] else int(bool(result["differences"]))
    result["verdict"] = {0: "fresh: no published value differs from the live authorities",
                         1: "changed: published values differ from the live authorities",
                         2: "incomplete: the check could not establish agreement or difference"}[result["exit_code"]]
    return result


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 160 else text[:157] + "..."


def report(result: dict[str, Any]) -> None:
    print(f"API Rate-Window Clock freshness — {result['checked_at']}")
    print(f"Published baseline: {result['published_baseline']}")
    print(f"Opened {result['sources_opened']} of {result['sources_total']} current pricing authorities the build reads:")
    for language, entry in result["sources"].items():
        line = f"  {language}: {entry.get('status')} {entry['url']}"
        if "raw_sha256" in entry:
            line += f" ({entry['bytes']:,} bytes via {entry.get('transport', 'fixture')}"
            line += ", raw bytes identical to stored capture)" if entry.get("raw_bytes_match_stored_capture") else \
                f", raw bytes differ from {entry.get('stored_capture', 'stored capture')}; page text changed: {entry.get('text', {}).get('page_text_changed')})"
        print(line)
    for item in result["retained_historical_evidence"]:
        print(f"  retained, not re-fetched: {item['file']} — {item['role']}")
    if "reviewed_pin" in result:
        print(f"Reviewed semantic pin: {result['reviewed_pin']['status']}"
              + (f" ({', '.join(result['reviewed_pin']['changed_fields'])})" if result["reviewed_pin"]["changed_fields"] else ""))
    moves = result["informational"].get("capture_provenance_moves_on_rebuild", [])
    if moves:
        print(f"Informational: {len(moves)} capture-provenance fields would move on a rebuild (timestamps/raw hashes; not differences)")
    if result["differences"]:
        print(f"{len(result['differences'])} published value(s) differ:")
        for d in result["differences"]:
            print(f"  {d['field']}: published {_short(d['published'])} -> live {_short(d['fresh'])}")
    for reason in result["incomplete"]:
        print(f"INCOMPLETE: {reason}")
    print(f"Exit {result['exit_code']}: {result['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--published-base", default=LIVE_BASE,
                        help="Published site URL (default: the live site) or a local directory "
                             "(assembled site, or this source checkout)")
    parser.add_argument("--output", type=Path, help="Write the full JSON receipt here (outside this project)")
    parser.add_argument("--captures-dir", type=Path,
                        help="Also save the fetched pages here for producer review (outside this project)")
    args = parser.parse_args(argv)
    for option in (args.output, args.captures_dir):
        if option is not None and _inside(option, PROJECT):
            parser.error(f"{option} is inside the project; the check never writes into its own inputs")
    try:
        result = run_check(live_fetcher, published_loader(args.published_base), published_label=args.published_base,
                           captures_dir=args.captures_dir)
    except Exception as error:  # anything unexpected is an incomplete check, never a clean one
        result = {"exit_code": 2, "verdict": "incomplete", "incomplete": [f"check crashed: {error}"]}
        print(f"INCOMPLETE: check crashed: {error}")
        print("Exit 2: incomplete")
        return 2
    report(result)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(f"Receipt: {args.output}")
        except OSError as error:
            print(f"INCOMPLETE: could not write receipt: {error}")
            return 2
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
