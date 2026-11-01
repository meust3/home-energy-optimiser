# Optional One Call 4.0 archive

The app can archive a complete 48-hour One Call 4.0 15-minute forecast on a
ten-minute cadence. **Collection is disabled by default and has not been deployed
or activated by this change.** Solcast remains the primary solar forecast; this
archive does not feed estimators, decisions, calibration or hardware controls.

## Collection and safety

`ForecastCoordinator` uses its existing one worker. Forecast/reserve work runs
first. Weather advances one page per cooperative step, only after a successful
core collection and outside the collector's boundary guard windows. It can run
independently of demand forecasting without enabling or changing demand forecasts.
There is no second collector, daemon, timer thread, cron or action endpoint.

The cadence is ten minutes, with no catch-up storm after downtime. A cycle captures
192 quarter-hour targets in a 48-hour half-open window, with at most five requests
(normally four). Every request uses the fixed HTTPS
`api.openweathermap.org/data/4.0/onecall/timeline/15min` endpoint and explicit metric
units. Provider navigation links are never requested directly. An HTTP link is
accepted only as a timestamp hint for the exact known host/path and is rebuilt as
HTTPS. Redirects, automatic retries, historical traversal, product fallback and
Solar Irradiance calls are absent. Requests have bounded connect/read timeouts and payload size. A per-request
socket-read deadline covers slow headers and body chunks, rather than waiting
for a full response chunk before checking elapsed time. DNS resolution remains
subject to the operating system resolver timeout.

Expected use is approximately 576 calls/day at four pages per cycle; five-page
cycles have a 720-call/day bound. The app reserves every attempt durably before
network I/O, under an account-wide database lock. Its local guard allows at most
900 attempts per rolling 24 hours. Failed, timed-out, interrupted and unknown
outcomes keep their reservation. Concurrent workers and restarts share the same
canonical ledger. The provider's separate **1,000/day account cap must be confirmed
before enabling**; the app cannot inspect or change the provider billing setting.
Other tools/keys on that account also count at the provider. The earlier desktop
pilot has a separate local ledger and must not be mistaken for the app ledger.

HTTP 401/403 blocks optional weather requests for an hour. HTTP 429 blocks them
until the next UTC daily reset guard. Weather failures affect optional weather
status only, never core observation health. An interrupted in-flight request is
recorded UNKNOWN and its cycle remains partial; it is never automatically retried.
Committed pages resume without being fetched again. On restart the coordinator
checks pending work promptly, still respecting core collector readiness and guards. A stale cycle or changed
location/key configuration terminates visibly partial.

## Private settings and disabled behaviour

Supervisor options add:

| Option | Default / contract |
|---|---|
| `weather_collection_enabled` | `false` |
| `weather_provider_cap_confirmed` | `false` |
| `weather_provider_daily_cap` | exactly `1000` |
| `weather_openweather_api_key` | empty password field |
| `weather_latitude`, `weather_longitude` | absent private coordinates |

Both disabled and unconfigured collection perform no weather database writes or
provider requests. The secret is a `SecretStr` in app options and is passed only in
memory; it is not exported to the collector environment. Key/location values are
excluded from object representations, logs, fixtures, Ingress responses and source
control. No existing live credential or precise household location is part of this
implementation. A Windows DPAPI pilot blob is not copied to the Linux app.

The provider-cap confirmation is an operator assertion, not a fabricated live
provider attestation. Review the account cap and shared account consumers before
activation, and reconfirm after any external billing/entitlement change.

## Canonical persistence and versions

Migration `20261101_01` follows `20261024_01` and adds only optional weather tables.
The app uses its configured PostgreSQL database, never a SQLite fallback. SQLite
remains supported for isolated development/tests. Startup runs no migration.

A private delivery spool under `/data/weather-spool` is checked for writeability
before any reservation or GET. Received pages are sanitized, fsynced and atomically
saved before navigation/normalization or database delivery; files and directory
use private permissions. Unacknowledged pages replay before any new request,
including after a process restart or a database commit whose acknowledgement was
interrupted. Delivery is idempotent. Corrupt/incomplete spool files stop acquisition
and are retained for recovery. The spool is a delivery buffer, never a database
or quota fallback; the canonical ledger is still required before GET. Include it
in private app backup/recovery. A crash or storage failure before receipt fsync can
still lose an unacknowledged in-flight response, which remains counted UNKNOWN.

Every received page keeps its request and receipt times, original response-body
SHA-256, separately hashed sanitized response, parser version and page/cycle
identity. Credential-bearing navigation links and echoed keys are redacted before
storage. Missing values, explicit nulls, units and field semantics remain explicit.

Normalized values are grouped by target timestamp. A content hash reuses identical
target versions; changed values create another immutable version. Each page still
links every target version it received, so deduplication does not erase receipt
history. Raw pages outside the selected 48-hour window remain retained; coverage
and presentation use the requested window only. Nothing prunes weather evidence.
Migration downgrade refuses a nonempty archive rather than silently deleting it.

A cycle is COMPLETE only with all 192 distinct expected timestamps and no overlaps.
Partial/gapped/failed cycles are visible. The 48-hour window is anchored to the
first requested quarter-hour, rather than measured anew at completion. A target
can precede receipt, so archived weather must not be represented as known before
its receipt. Provider issue time, model identity and native model resolution remain
UNKNOWN when not returned. A multi-page retrieval is not proof of one upstream run.

## Read-only presentation

The administrator Ingress dashboard links to `/weather`. `GET /api/v1/weather`
supports a selected cycle, aware `as_of`, bounded limit (1–200 targets) and offset.
It lists at most 100 cycles and returns normalized values with page receipts/hashes;
it never exposes raw response bodies, keys, coordinates or billing information.
Historical queries suppress later receipts and future completion state, and omit
current operational health. Late provider rejections still apply account cooldowns
without shortening an already longer block. GETs do
not fetch weather, change settings, schedule work or persist comparisons.

## Review and release gates

Review the code, immutable history behaviour, provider account cap and storage
growth before any enablement. At ten-minute cadence, four full pages can create
28,800 page-target references/day; identical content versions are shared, but real
growth depends on provider updates. Retention remains disabled. Do not discard old
forecasts silently to meet a storage target.

Validate an isolated PostgreSQL 17 upgrade, empty rollback/re-upgrade, restart and
quota concurrency before release. Deployment requires the usual fresh recovery
and acceptance checks and explicit authorization. Existing runtime options and
production are unchanged. Do not deploy the older preserved checkout.

Official contract: [One Call 4.0](https://openweathermap.org/api/one-call-4),
[quota and activation FAQ](https://openweathermap.org/faq),
[licensing](https://openweathermap.org/full-price).

Collection is for private context. Preserve visible OpenWeather attribution and
verify the account's accepted terms before externally distributing archived data.
