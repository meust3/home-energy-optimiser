# Changelog

## Unreleased

- Fixed access to Supervisor's root-owned `0600` options file by copying it into a
  mode-`0600` ephemeral runtime location during a narrowly scoped root bootstrap.
- Kept the Python application, collector, and health server at UID/GID 10001 after
  bootstrap; collector, database, forecast, and read-only behaviour are unchanged.
- Added a portable SQLite/PostgreSQL persistence architecture and completed the
  application-wide repository refactor.
- Added production PostgreSQL cutover, adoption, validation, backup, and recovery
  support.
- Improved reserve forecasting with deterministic replay, explicit forecast
  horizons, sequential replenishment evaluation, and stronger safety invariants.
- Added Home Assistant App release-candidate packaging for an external PostgreSQL
  database and Supervisor-proxied read-only Home Assistant access.
- Hardened credential redaction, ignored-file coverage, Docker build context, and
  non-root container execution.
- Expanded architecture, database, deployment, troubleshooting, security, and
  multi-platform operational documentation.
