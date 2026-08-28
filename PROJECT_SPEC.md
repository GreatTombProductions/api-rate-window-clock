# API Rate-Window Clock — Projection Contract

## Receiver decision

An independent developer, researcher, or small business is about to start a DeepSeek API batch. They need to know whether the declared marginal price changes with the planned start time, what waiting for the next cheaper band would save, and exactly which token classes produce the estimate.

## Authority and scope

- Current semantic authorities: DeepSeek's English and Chinese Models & Pricing pages.
- Current live schedule verified 2026-08-28 through both urllib and curl.
- USD and CNY are independent vendor price surfaces. Cross-language agreement means model coverage, weekday/window structure, and the stated off-peak-to-peak relationship agree; it does not mean one currency is converted into the other.
- The historical effective boundary, `2026-08-16T16:00:00Z`, comes from DeepSeek's transition notice captured on 2026-08-15. The current pages present the schedule as active and no longer repeat that transition date. This provenance distinction must remain visible.
- The v1 calculator estimates USD charges only. The Chinese page is a structural cross-check and is displayed as a second authority surface.

## Data contract

A schema-versioned `rates.json` contains:

- provider, unit, currency, build timestamp, and current-source status;
- one or more effective-dated price bases;
- explicit UTC weekday and half-open peak windows;
- model/version records;
- separate cache-hit input, cache-miss input, and output rates for each band;
- announced-future bases kept separate from current bases;
- source URL, fetch timestamp, raw SHA-256, normalized semantic SHA-256, extraction status, and cross-language findings.

Unknown values are `null`/unavailable. They are never converted to zero. Conflicting authority surfaces set coverage to `conflict` and disable estimates rather than averaging.

## Calculation contract

For token counts `h`, `m`, and `o`, unit `U = 1,000,000`, and rates `rh`, `rm`, `ro`:

```text
cost = (h × rh + m × rm + o × ro) / U
```

Peak windows are half-open and apply only Monday through Friday:

- `[01:00, 04:00)` UTC
- `[06:00, 10:00)` UTC

All other times are off-peak. Boundary candidates are calculated exactly; no periodic browser scrape or hidden clock authority is used. "Next cheaper" means the earliest future schedule/effective-date boundary within eight days at which the same token mix has a strictly lower declared cost.

## Required receiver behavior

- Prominent current UTC and local time.
- Now/planned timestamp modes plus inspectable boundary fixtures.
- Separate token inputs for cache-hit, cache-miss, and output.
- Selected-band cost, next-cheaper cost, absolute and percentage savings, wait duration, rate basis, model version, and effective date.
- Explicit no-cheaper-band state when already off-peak.
- Source status, quotes, hashes, fetch timestamps, and coverage gaps.
- Companion methodology and sources pages.
- Responsive static site; all calculation remains in the browser.

## Tests

- Python unit tests for arithmetic, weekdays/weekends, all exact boundaries, date rollover, effective transitions, unavailable values, and next-cheaper selection.
- JavaScript tests over the same shared case table.
- Full-object Python/JavaScript differential parity.
- Generated-data contract and known-record tests.
- Browser smoke: default estimate, peak-to-off-peak savings, weekend behavior, unavailable/conflict fixture, companion pages, and 390px viewport.
- Hygiene, path, manifest, license, `.nojekyll`, live-page, and hub-projection release gates.

## Not building

- No API key, model call, account, backend, analytics, usage upload, runtime scraping, or persistent data.
- No model-quality recommendation or "cheapest model" claim.
- No guessed multi-provider breadth.
- No invoice reconciliation or actuals uploader in v1.
- No historical price reconstruction before the effective boundary.
- No claim that a start-time estimate captures tax, retries, reseller markup, provider token-count differences, or actual provider-side billing evidence.
