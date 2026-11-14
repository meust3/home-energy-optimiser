# Dashboard product review — 14 November 2026

## Scope and verdict

Reviewed the v0.8.8 dashboard source at `a2adc680082192244c9a55d45fd4e4b094932e01`, its documented contracts, the supplied Forecast Operations and Weather archive screenshots, and synthetic frontend/API tests. Changes are isolated on `codex/dashboard-product-review-v088`.

**Local regression and Chromium responsive checks pass. All eleven installed screens loaded in the existing signed-in Home Assistant tab.** Restarting Codex restored browser connectivity. Live checks reproduced the cancellation error and weather phone-layout problem. These fixes are local and have not been deployed. Synthetic responsive checks cover every screen at four widths; live checks establish populated rendering and selected interactions, not exhaustive production filter coverage or measured API latency.

Production, App options, collection cadence, provider cap, local call guard, database records and archives were not changed. No provider weather requests, deployment, database migration, commit or publication was performed. The earlier App documentation worktree remains separate.

## Findings and local fixes

| Priority | Finding and impact | Resolution |
| --- | --- | --- |
| P1 | Most loaders displayed intentional AbortError cancellations as failures. Hiding a document aborts requests, but returning only reloaded status/live. Analytical screens could remain blank or show the screenshot's abort error until their next five-minute refresh. Live rapid History range changes reproduced the same error text. | Ignore intentional cancellation in every loader; reload loaded analytics on visibility restoration; clean completed controllers. Real service errors remain visible. The original screenshot's exact triggering event remains unknown. |
| P2 | An obsolete response could finish decoding after its replacement started. | Check the abort signal after JSON decoding. An older completion cannot discard the replacement controller. |
| P2 | Access to localStorage was unguarded before dashboard initialisation. An embedded browser denying storage could prevent the whole dashboard starting. | Treat saved card mode as optional; startup and in-session selection continue without storage. |
| P2 | Navigation accepted any existing element ID as a page. The built-in `#main` skip link therefore hid all page sections. | Validate hashes against actual page sections; non-page hashes retain Overview. |
| P2 | Forecast Operations connected predictions from overlapping runs as one time series under All scheduled runs. It also hid predictions wherever actuals were ineligible. | Keep aggregate metrics with an explicit overlap explanation. Draw a curve only for a selected run, preserving predictions while leaving excluded actuals as gaps. No scores or archived predictions change. |
| P2 | Weather's `table-scroll` class had no stylesheet rule. Long timestamps and hashes extended beyond the visible viewport. Controls also lacked consistent styling. Reproduced in the installed App at phone width. | Use the existing bounded table container, make it keyboard focusable and labelled, and apply scoped input/button layout. Local Chromium layout and keyboard scrolling verified at four widths; deployment verification remains pending. |
| P2 | Weather reported the length of a list bounded to 100 as the archive count. | Explicitly label the recent-cycle list as bounded and not the total archive. This is not evidence of record loss. Older history remains accessed through the as-of query; this patch does not introduce full-history pagination. |
| P2 | Weather selections had no cancellation protection, allowing an older response to replace a newer selection. | Cancel superseded reads and check the signal after decoding. Failed reads explicitly warn that retained results may be stale. |
| P2 | Live Forecast Operations returned exactly 2,500 points for a seven-day query, without disclosing the bounded earliest-point subset. Coverage could be mistaken for completeness across the selected period. | Disclose returned point count and scope of coverage. At the existing 2,500-point cap, warn that the range may be incomplete and suggest a single run or shorter range. No queries, limits or stored metrics changed. Reaching the cap is a conservative warning, not proof that an additional row exists. |
| P2 | Data Quality said Weather measurements unavailable while the separate archive had complete captures. | Relabel as Observation weather context and explain that it does not describe the separately collected forecast archive. |

Updated stylesheet/script cache identifiers ensure the changed assets can be fetched when this candidate is eventually deployed.

## Initial source and synthetic coverage

All ten dashboard tabs were exercised through synthetic navigation, request initiation, cancellation and visibility-resume tests. Weather has a separate request/selection test. The following additional evidence is local and synthetic, not a claim that every live screen has passed. The follow-up below adds actual Chromium layout and interaction coverage to this initial inventory.

| Screen | Evidence inspected or exercised | Original live checklist (results below) |
| --- | --- | --- |
| Overview | Read-only status/live API; absent observation and nullable vehicle data; directional-flow limitations; forecast card pending-score and missing-value handling; HOLD evidence labels. | Current cards, freshness, dark mode and layout. |
| History | Time bounds, resolutions, aggregation, UTC bucket alignment, missing series, chart points and data tables. | Each range, long-range query latency, pointer/keyboard tooltips and narrow viewport. |
| Forecasts | 288-point horizon, missing actual gaps, run selection, late-response protection, preserved selected run during list refresh. | Selector changes and latest production run consistency. |
| Forecast Operations | Empty API states, scheduler/scoring tests, cancellation/error handling, overlap-safe presentation and per-series eligibility. | Original screenshot reproduction and recovery; 24h/7d/30d filters on populated data. |
| Calibration | Cohort/rollup integrity and sparse evidence tests; cancellation/resume wiring. | Populated cards, warning explanations and query latency. |
| Solar diagnostics | Five-minute integration, partial-day and low-coverage handling, cautious curtailment interpretation. | Completed/current-day display and long labels. |
| Reserve | Persisted subset, explicit unavailable fields, empty history and advisory labels. | Populated history table and responsive layout. |
| Arbitrage | Read-only board, immutable captures, source identity and legacy-mode presentation. | Available/empty live state and chart interaction. |
| Decisions | Latest/history/outcome routes; evidence-v2 versus historical HOLD labels; missing and blocked selections. | Populated tables, overflow and current evidence labels. |
| Data Quality | Sign configuration, nullable vehicle context, collection gaps versus telemetry incidents and training exclusions. | Long incident lists, fresh counts and responsive cards. |
| Weather archive | Bounded GET/as-of validation and privacy tests, archive/version tests, raced selection, bounded-count label, corrected container source. | Scroll to all columns, keyboard access, cycle/as-of selection and historical UTC labels. |

## Verification

- JavaScript: **18 passed**, including seven new lifecycle/product regressions and eleven existing chart/evidence tests.
- Python selection: **218 passed, 41 skipped** across dashboard, forecast operations, calibration, weather collection/units and arbitrage programme tests. The broad run initially had one expected-asset-version assertion failure (217 passed); after updating that assertion, its focused rerun passed. PostgreSQL-dependent cases were skipped with the external test database unset. These results do not establish PostgreSQL production performance.
- `git diff --check` passed. Tests use synthetic local repositories, fake provider transports and a loopback HTTP server; no production configuration was loaded.
- Initial test-harness obstacles were a missing local temporary parent directory and sandbox denial of loopback sockets. Creating the isolated temporary directory and running the local HTTP tests with permitted loopback access resolved those obstacles.

## Remaining release acceptance sequence

1. Read-only installed-App checks are complete as recorded below. No new sign-in was required; the existing tab was reused. Precise production latency was not measured.
2. Local synthetic browser checks are complete as detailed below. Repeat against the deployed candidate after a separately approved update; injected visibility events are not a native mobile-app lifecycle test.
3. Review the patch and publish through the normal PR/CI flow. Only an explicitly approved controlled App update can apply these fixes to production.
4. After that update, verify the original Forecast Operations symptom and all screen filters against populated data. Preserve every archive version and existing quota/collection configuration throughout.

The remaining gate is review, CI and a separately approved deployment, followed by verification of the installed fixes. The supplied production screens are not yet repaired by this local patch.


## Local Chromium follow-up

The fallback used the already installed Chrome executable and Playwright runtime, without installing software or attaching to a personal browser profile. Every test request was intercepted in memory at a synthetic origin; no external origin was allowed. Fixtures came from a newly created local synthetic SQLite database plus explicit presentation stress cases. These are test values, not household data.

- Eleven screens at **1440, 768, 390 and 320 pixels**, with both sparse and populated variants. The final populated pass has **44 successful screen/width combinations**, no page JavaScript errors, no visible error states, and no page-width overflow. Expanded forecast and decision tables were included. The earlier sparse pass also passed 44 combinations.
- Screenshot inspection caught a narrow Forecast Operations filter overflow missed by the initial leaf-only geometry check. The harness now includes controls and checks document width. Fixed flex wrapping and control bounds; verified the final phone screenshot.
- Expanded Arbitrage interval tables used an undefined scrolling class. Applied the bounded, focusable table wrapper. Full capture hashes also overflowed cards; hashes now wrap without changing their content.
- Added anchor spacing for sticky navigation, dark-mode link colours and visible keyboard focus. Missing Arbitrage forecast/reserve IDs now display Unavailable instead of literal undefined.
- **Eleven interaction checks passed**: six History ranges, keyboard chart tooltip, History error/recovery, 288-row forecast rendering, accuracy ranges and run selection, rapid filter changes, injected visibility cancellation/resume, keyboard skip link, as-of validation/recovery, weather horizontal keyboard scrolling, and startup/card selection when storage is blocked. All recorded requests were GET.
- Dark mode and reduced-motion preferences were exercised on the narrow weather view. The weather table was keyboard focused and scrolled horizontally (40 pixels); its bounded container retained the complete wide table.
- Frontend regression total is now **19 passing tests**, including the new capture-hash check. Python production/API code was not changed in this follow-up; earlier Python results above remain the applicable baseline.

Private local evidence is under `.local/browser-review/`: `responsive-results.json`, `interaction-results.json`, synthetic fixtures, test scripts and screenshots. These files are intentionally ignored. The browser harness covers desktop Chromium with resized viewports, not physical iOS/Android webviews.

## Live browser follow-up after Codex restart

Used the existing signed-in Home Assistant Chrome tab for presentation-only reads. No provider request, configuration edit, command, restart or deployment was performed. Temporary viewport emulation was reset and the tab was left on Overview. A long mobile-navigation batch timed out; its lost per-screen results are not counted as successful responsive checks.

| Screen | Observed installed behaviour |
| --- | --- |
| Overview | Populated cards; collector, PostgreSQL and Home Assistant healthy; stored observation advanced during the review. Existing completed-forecast card mode retained. |
| History | 24-hour and 30-day ranges completed with points and missing-data coverage. Rapid range changes reproduced the abort error. Individual completion of every intermediate range was not established live; all six ranges passed local synthetic interaction checks. |
| Forecasts | Current and selected older runs rendered; older run retained its 288-point horizon with explicit missing actuals. |
| Forecast Operations | Scheduled status and accuracy groups rendered. Seven-day all-run results exposed the undisclosed 2,500-point bound addressed above. |
| Calibration | Populated independent-day evidence and acceptable calibration status displayed. |
| Solar diagnostics | Completed/current-day results rendered with partial-day and missing-comparison labels after loading. |
| Reserve | Persisted reserve, warnings, provenance and history rendered. |
| Arbitrage | Populated expired opportunity with execution disabled; this is a valid advisory state, not a UI failure. |
| Decisions | HOLD-only selection, candidates, provenance, history and outcomes rendered; unavailable counterfactual comparisons remained labelled. |
| Data Quality | Coverage, gaps and health cards rendered; misleading weather-context wording identified and clarified locally. |
| Weather archive | Complete 48-hour capture with 192 forecast rows; older cycle selection and historical known-as-of query completed. Clearing the query returned to current reads. Phone view reproduced the table/control layout issue. |

Final frontend regression run: **20 passed**, including a new saturated-query disclosure test and removal of that warning for a smaller response. Earlier Python validation remains applicable because no Python source changed in this follow-up. The last two changes are text-only presentation changes, checked by regression tests; the earlier 44-case responsive matrix predates those text changes. Production load/performance, native mobile lifecycle behaviour and every live filter permutation are not exhaustively certified by this review.
