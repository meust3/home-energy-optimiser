# Home Assistant add-on plan

This is a future deployment plan, not an add-on package.

The add-on will run the collector as a supervised Home Assistant OS add-on. Local
access remains limited to allowlisted Home Assistant GET endpoints. SQLite, exports,
and operational state will use persistent `/data`. Collection will start
automatically after connectivity, align to five-minute boundaries, and preserve
duplicate-slot upserts.

Health checks will cover process liveness, recent collection, SQLite access, and
domain health. Structured logs will redact tokens. Options will cover entity IDs,
timezone, freshness, signs, tolerance, optional EV settings, inference, and forecast
retention. Secrets will use protected add-on configuration.

Development and release stages:

1. Validate package behavior and migrations outside Home Assistant.
2. Add a development container and read-only health endpoint.
3. Build an unpublished image with persistent `/data` tests.
4. Test install, upgrade, rollback, logs, and recovery off production hardware.
5. Document releases and checksums before repository publication.

Packaging does not authorize an executor or Home Assistant/hardware writes.
