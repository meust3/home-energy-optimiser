# Dashboard API

All endpoints are versioned, GET-only, and intended solely for authenticated Home
Assistant Ingress. Direct clients receive 403. POST, PUT, PATCH, and DELETE receive
405. API and HTML responses use `Cache-Control: no-store`; versioned local assets
may be cached for one hour.

## Routes

| Route | Purpose | Bounds |
| --- | --- | --- |
| `/health` | Lightweight Supervisor watchdog state | No history query |
| `/api/v1/status` | In-process health plus lightweight database revision check | No history query |
| `/api/v1/live` | Latest persisted observation and normalized flow | One row |
| `/api/v1/timeseries` | Historical charts and coverage | 31 days, 9,000 source rows, 2,500 points |
| `/api/v1/forecast-runs` | Existing forecast-run metadata | Limit 1–100 |
| `/api/v1/forecast-comparison` | One stored run versus actual observations | Limit 1–2,500 points |
| `/api/v1/reserve/latest` | Latest existing reserve-estimator run | At most 2,500 forecast points |
| `/api/v1/data-quality` | Coverage and persisted health summary | 31 days, 9,000 source rows |

`/api/v1/timeseries` supports `range=6h|24h|48h|7d|14d|30d`, or timezone-aware
`start` and `end`, plus `resolution=auto|5m|15m|30m|1h`. Auto chooses the finest
resolution below 2,500 points. Power and price aggregation uses the mean; SOC uses
the last available value in a bucket. An empty bucket is returned with null values
and `has_observation=false`; it is never interpolated.

Version 0.4.1 adds
`normalized_flow_unavailable_due_to_unconfigured_signs` to the timeseries response
and the persisted `sign_convention_status` to live/bucket data. The frontend uses
these presentation-only fields to distinguish unknown sign configuration from an
empty observation period. Data Quality also reports the runtime-configured grid
sign, battery sign, confidence, supporting sample count, and balance tolerance.

Version 0.4.0 extends `/api/v1/live` with nullable, privacy-minimized vehicle SOC,
raw vehicle battery power, charging/plugged/online/at-home booleans, telemetry
timestamp/age/freshness, status, and issue codes. `/api/v1/timeseries` adds vehicle
SOC and charging/plugged states. `/api/v1/data-quality` adds configured,
available/fresh, independent charger-AC availability, known excluded-row count,
and contamination-warning fields. `/api/v1/reserve/latest` may expose latest
vehicle SOC as context only. No response contains full Home Assistant attributes,
VIN, coordinates, exact location, credentials, or a control route.

`/api/v1/forecast-runs` supports `forecast_type`, `after`, `before`, and `limit`.
`/api/v1/forecast-comparison` supports `forecast_run_id`, `forecast_type`, `start`,
`end`, and `limit`. It uses the existing forecast-type-to-observation mapping and
calculates actual, error, MAE, and bias in a read-only query. It does not call the
existing materializing comparison/scoring operations.

`/api/v1/data-quality` accepts the same named or custom range without a resolution.
It reuses the existing gap and structured-health summary helpers and the same 90%
complete-day/overnight definition as demand forecasting.

## Errors

Safe errors have one stable shape:

```json
{"error":{"code":"invalid_time_range","message":"Start must be earlier than end."}}
```

Responses never include exceptions, tracebacks, SQL, database URLs, usernames,
passwords, Supervisor tokens, Home Assistant authorization headers, App options, or
filesystem paths. Unknown and duplicate parameters are rejected rather than passed
to SQL. Column names, ordering, forecast actual mappings, and filters are fixed in
repository/service code.

## Security headers

The server sets correct content types, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, and a local-only Content Security Policy. The policy
allows same-origin framing required by Home Assistant Ingress and does not emit a
frame-blocking `X-Frame-Options` header. CORS is not enabled.
