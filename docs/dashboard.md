# Read-only Ingress dashboard

Version 0.3.2 is an experimental release candidate that presents existing stored
energy data through Home Assistant Ingress. It has not yet been installed or
verified on the production NUC. Home Assistant App v0.2.1 remains the confirmed
working collector.

## Architecture

The App still has one container, one Python process, and one collector. The existing
standard-library `ThreadingHTTPServer` now serves `/health`, a server-rendered HTML
shell, package-local CSS/JavaScript, and `/api/v1` GET routes. The collector remains
in the main thread with its unchanged clock-aligned five-minute loop. SIGTERM and
SIGINT set its existing stop event, then shut down the web server. Browser threads
use short-lived repositories and cannot stop or mark the collector unhealthy.

The implementation deliberately adds no Uvicorn/Gunicorn worker, second collector,
cron process, forecast worker, reserve scheduler, Node build pipeline, or database
migration. The frontend has no runtime or third-party chart dependency and therefore
adds no separate licence obligation beyond the repository licence.

## Ingress and access

Home Assistant authenticates users. `panel_admin: true` restricts this experimental
panel to administrators. The App authorizes dashboard, API, and static requests
from their actual socket peer: `172.30.32.2`, the current Ingress gateway. Loopback
is permitted for internal tests. Direct requests return 403 even when they spoof
`X-Forwarded-For` or an Ingress header. `/health` stays exempt so Supervisor watchdog
continues to work.

After authorization, a normalized `X-Ingress-Path` becomes the HTML `<base>` path.
All assets and API calls are relative, so root development, a nested prefix,
trailing slashes, refreshes, and hash-based client navigation remain inside the
Ingress origin.

## Pages and refresh

- **Overview** shows collector/PostgreSQL/Home Assistant state, latest stored KPIs,
  normalized flow directions, and a limited persisted reserve summary. Missing
  normalized directions produce one explanation instead of repeated labels.
- **History** charts house/baseline, PV, grid, battery, SOC, and Amber prices over
  6 hours through 30 days. Missing buckets remain gaps, wholly missing series use
  explicit empty states, and partially available series remain chartable.
- **Forecasts** selects existing persisted runs and compares their stored expected
  values with observations at request time without a database write.
- **Reserve** shows only fields currently persisted with the latest
  `reserve_estimator` run and distinguishes unavailable run values from fields not
  stored by the current schema.
- **Data Quality** summarizes coverage, gaps, domain health, baseline eligibility,
  forecast tiers, EV limitations, sign confidence, and balance residuals.

Status and live data refresh no faster than every 30 seconds. Loaded analytical
pages refresh every five minutes. Polling pauses while the document is hidden, and
superseded requests are aborted. Collection remains five-minute resolution.

## Safety and limitations

The dashboard is presentation only. It has no settings page, buttons that apply an
action, mutation route, Home Assistant service call, control entity, Modbus write,
forecast trigger, or reserve trigger. Sparse forecast data receives an explicit
empty state. Independent EV telemetry is not available in production, so no EV
power is inferred for display and a contamination warning remains visible.

Current reserve persistence is intentionally incomplete. The dashboard cannot show
unpersisted SOC, tradable energy, opportunity reasoning, EV demand, or readiness and
does not invent them. See [dashboard data contract](dashboard_data_contract.md).

## Responsive and accessible presentation

System fonts, semantic sections/headings, keyboard-operable navigation and selects,
high-contrast status text plus shapes, light/dark color schemes, narrow-screen
layouts, and reduced-motion preferences support desktop, tablet, and Home Assistant
mobile views. Charts include text legends, units, pointer tooltips, missing-gap
semantics, explicit screen-reader-readable empty states, and expandable data
tables. Metadata grids wrap long values by words and collapse to stacked label/value
pairs on narrow screens.
