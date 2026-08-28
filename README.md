# API Rate-Window Clock

A static calculator for one concrete API-cost decision: **will the same DeepSeek batch cost less if it starts in the next price window?**

**Live site:** https://greattombproductions.github.io/api-rate-window-clock/

DeepSeek's current declared schedule has weekday peak rates at 01:00–04:00 and 06:00–10:00 UTC. All other hours—including weekends—are off-peak. The calculator keeps cache-hit input, cache-miss input, and output tokens separate, then reports:

- declared cost at a current or planned start time;
- exact rate band, model version, and effective basis;
- the earliest cheaper boundary in the next eight days;
- absolute and percentage savings; and
- source receipts and coverage gaps.

No API key, model call, backend, account, analytics, or usage upload is involved. All calculation stays in the browser.

## Why this exists

A vendor can publish every price and still leave the actual decision opaque. UTC windows, weekdays, effective dates, model versions, and three token classes turn “what will this run cost?” into manual schedule arithmetic. The portage layer is not another table—it is the answer at the launch boundary.

## Authority

The 2026-08-28 build independently parsed DeepSeek's English and Chinese Models & Pricing pages:

- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/zh-cn/quick_start/pricing/

Both urllib and curl returned byte-identical payloads per page. The two language surfaces agree on model IDs/versions, weekday scope, equivalent windows, and the stated 2:1 peak/off-peak relationship. USD and CNY are independent vendor price surfaces; the build does not use FX conversion as an agreement test.

Normalized semantic records are pinned. A changed model, window, weekday, or rate fails the build pending inspection. Missing or conflicting rates become `unavailable`, never zero.

## Calculation

For cache-hit tokens `h`, cache-miss tokens `m`, output tokens `o`, and per-million rates `rh`, `rm`, and `ro`:

```text
cost = (h × rh + m × rm + o × ro) / 1,000,000
```

Peak intervals are half-open and apply Monday–Friday only:

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

## Repository layout

- `pipeline/fetch.py` — deadline-bounded multi-transport fetch
- `pipeline/parser.py` — dependency-free EN/ZH semantic parser
- `pipeline/calculator.py` — Python reference engine
- `pipeline/expected_semantics.json` — reviewed semantic pin
- `frontend/calculator.js` — browser mirror
- `tests/cases.json` — shared cross-language fixtures
- `data/rates.json` — static schema consumed by the browser
- `data/raw/` — authority captures and response headers

## License

MIT. Vendor documentation remains subject to its publisher's terms; the raw captures are included for reproducibility and source criticism.
