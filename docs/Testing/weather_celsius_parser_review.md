# Weather Celsius parser correction: review notes

## Problem and result

The provider adapters contain the literal `U+00C2 U+00B0 C` (`Â°C`) instead of
`U+00B0 C` (`°C`). One Call metric temperature, feels-like temperature and dew
point therefore receive an invalid normalized unit label. Open-Meteo's hourly
temperature adapter also expects the malformed label and rejects a canonical
Celsius response. Numeric values are not affected by this label defect.

Use the ASCII source escape `\u00b0C` for these four mappings. The resulting
runtime unit is exactly `°C`; this is not a temperature conversion. One Call
still requires explicitly metric input. Open-Meteo still rejects mismatched
provider units. Missing and null values retain their original meaning.

## Versioning and preservation

- New captures and request reservations use `weather-v2`. Parser identity is
  already part of the normalized version hash, so old and new interpretations
  remain distinguishable, including versions whose values happen to be equal.
- Delivery records the parser that actually normalized the response. This
  handles a pending raw receipt reserved under v1 and replayed under v2 after
  an eventual update. It does not make another provider request.
- Completed receipts remain idempotent: redelivery returns the existing cycle
  before any archive writes. No completed attempt, payload, target link, version
  body, hash or timestamp is rewritten.
- Identical raw payloads can still share storage; every new receipt retains its
  own links. New corrected versions are appended under the normal archive rules.
- No migration, backfill, deletion, read-time relabeling or schema change is
  included. Existing malformed historical labels remain visible as originally
  stored. Historical analysis may use a separately documented derived mapping;
  it must not replace archived values or reinterpret old hashes as v2.

The existing unknown provider/model/resolution provenance stays unknown. This
patch changes only Celsius mappings; it is not a general unit/encoding rewrite.

## Validation

Focused suite: **107 passed, 33 skipped**:

```text
python -m pytest tests/test_weather_units.py tests/test_weather_collection.py \
  tests/test_forecast_context.py tests/test_context_integration.py -q
```

Synthetic tests cover all temperature-bearing One Call products, nested daily
temperatures, Open-Meteo canonical units, negative temperatures, unchanged
numeric values and response bytes, missing/null handling, nonmetric rejection,
and compatibility with the existing strict Celsius consumer.

SQLite regression tests store synthetic v1 captures, then collect v2 captures
with identical raw data and verify every previous weather-table row remains
unchanged while corrected versions are added. They also replay a pending v1
receipt with v2, verify version hashes against the recorded parser, and confirm
duplicate delivery cannot change an already completed attempt. Existing quota,
cadence, receipt durability, as-of access and archive tests pass.

Ruff and `git diff --check` pass. PostgreSQL variants were not run locally:
27 require `WEATHER_TEST_POSTGRES_URL` and six require `TEST_POSTGRES_URL`.
The local Docker engine was unavailable. The existing release-validation CI
provisions PostgreSQL 17 and both test databases; those checks remain required
before merge/release. These local results do not establish a CI result; consult
the pull request checks for the published commit.

## Review boundary

Prepared on `codex/weather-celsius-label-fix`, based on main commit
`088f0070be342300a225eaf11337a38f91812845`. No release/version bump or deployment
is included. Production was not connected to, restarted or changed. Collection,
ten-minute cadence, the 1,000-call provider cap and 900-attempt local guard remain
unchanged. All weather test responses are synthetic; no weather requests were
made. Existing unrelated worktrees and local changes are preserved.
