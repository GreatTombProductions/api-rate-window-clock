# API Rate-Window Clock

A static calculator for one concrete API-cost decision: **will the same DeepSeek batch cost less if it starts in the next price window?**

**Live site:** https://greattombproductions.github.io/api-rate-window-clock/

DeepSeek's current declared schedule has weekday peak rates at 01:00–04:00 and 06:00–10:00 UTC, excluding Chinese public holidays. All other hours—including weekends and those holidays—are off-peak. DeepSeek publishes no holiday list, so the calculator asks whether the start's Beijing date is a Chinese public holiday instead of guessing, and shows the holiday price whenever the answer would change the band. The calculator keeps cache-hit input, cache-miss input, and output tokens separate, then reports:

- declared cost at a current or planned start time;
- exact rate band, model version, and effective basis;
- the earliest cheaper boundary in the next eight days;
- absolute and percentage savings; and
- source receipts and coverage gaps.

No API key, model call, backend, account, analytics, or usage upload is involved. All calculation stays in the browser.

## Why this exists

A vendor can publish every price and still leave the actual decision opaque. UTC windows, weekdays, effective dates, model versions, and three token classes turn “what will this run cost?” into manual schedule arithmetic. This page gives the answer at the moment you decide when to launch, not another table.

## Authority

The 2026-10-25 refresh independently parsed DeepSeek's English and Chinese Models & Pricing pages (the first build used 2026-08-28 captures; that table is kept as labeled history):

- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/zh-cn/quick_start/pricing/

The two language surfaces agree on model IDs/versions, weekday scope, the holiday exclusion, equivalent windows, and the stated 2:1 peak/off-peak relationship. USD and CNY are independent vendor price surfaces; the build does not use FX conversion as an agreement test. Both pages also list per-request Search and Fetch APIs; they are recorded in the semantic pin but are not token-priced, so the calculator does not include them.

Normalized semantic records are pinned. A changed model, window, weekday, holiday rule, or rate fails the build pending inspection. The vendor publishes no effective timestamp for the current table, so estimates start at the capture that verified it. Missing or conflicting rates become `unavailable`, never zero.

## Calculation

For cache-hit tokens `h`, cache-miss tokens `m`, output tokens `o`, and per-million rates `rh`, `rm`, and `ro`:

```text
cost = (h × rh + m × rm + o × ro) / 1,000,000
```

Peak intervals are half-open and apply Monday–Friday only, except on a Beijing date you mark as a Chinese public holiday:

```text
[01:00, 04:00) UTC
[06:00, 10:00) UTC
```

The estimate assigns one band from the batch start time. It does not model a long job crossing a boundary, taxes, retries, credits, reseller terms, or provider-side token counting. It is a declared-price estimate, not an invoice audit.

## Rebuild and verify

Requirements: Python 3.11+, Node.js, `pytest`, and Playwright's Chromium for browser smoke.

```bash
python3 pipeline/build.py
python3 -m pytest -q
node tests/test_calculator.js
python3 tests/test_parity.py
python3 tests/run_browser_smoke.py
```

To fetch new authority snapshots with urllib/curl cross-checking:

```bash
python3 pipeline/fetch.py --cross-check
python3 pipeline/build.py
```

A semantic change makes the second command fail closed. Inspect the new EN/ZH records before explicitly accepting it:

```bash
python3 pipeline/build.py --accept-source-change
```

The public source receipts page contains the exact hashes for the deployed build and should be updated whenever a new semantic pin is accepted.

### Check whether the live calculator still matches DeepSeek

One command re-fetches both pricing pages, rebuilds with this repository's own parser and build script in a temporary copy, and compares the result with the published site:

```bash
python3 pipeline/freshness.py --output /tmp/rate-window-freshness.json
```

It needs Python 3.11+ and network access, and it works from this repository as published. It compares every value behind the calculator (`data/rates.json`: models, versions, rates by token class and band, weekdays, windows, holiday rule, schedule quotes, Chinese-page CNY amounts, semantic hashes), plus the hand-written table, quotes and hashes on the sources page. It never writes to `data/`, `pipeline/expected_semantics.json` or the pages. Use `--published-base DIR` to compare a local checkout or an assembled site instead of the live one, and `--captures-dir DIR` to keep the fetched pages for review.

- **Exit 0:** no published value differs from the live pages.
- **Exit 1:** at least one published value differs. Each one is printed with its field, the published value and the live value. A change is still reported when the reviewed pin would refuse it.
- **Exit 2:** incomplete. A page could not be fetched or parsed, the English and Chinese pages conflict, or the published site could not be read. Incomplete takes precedence over clean or changed.

Every run states how many of the two current pricing pages it opened. Raw HTML changes on every docs-site rebuild (asset names, class names), so raw-byte and page-text changes are reported for information only. So are the capture timestamps and raw hashes that a rebuild would move. The 2026-08-28 English capture behind the superseded table is retained evidence and is not re-fetched, because the live page no longer carries that table. The tool has one current price basis and no monthly dimension, so there is no month argument. Deciding what to do about an exit 1 (re-fetch, review, `--accept-source-change`, redeploy) is the maintainer's call.

## Repository layout

- `pipeline/fetch.py` — deadline-bounded multi-transport fetch
- `pipeline/parser.py` — dependency-free EN/ZH semantic parser
- `pipeline/freshness.py` — re-fetch, scratch rebuild and comparison against the published site
- `pipeline/calculator.py` — Python reference engine
- `pipeline/expected_semantics.json` — reviewed semantic pin
- `calculator.js`, `app.js`, `index.html`, `methodology.html`, `sources.html` — the page and its browser calculator mirror (in a frontend directory in the source checkout; at the repository root as published)
- `tests/cases.json` — shared cross-language fixtures
- `data/rates.json` — static schema consumed by the browser
- `data/raw/` — authority captures and response headers

## License

MIT. Vendor documentation remains subject to its publisher's terms; the raw captures are included for reproducibility and source criticism.
