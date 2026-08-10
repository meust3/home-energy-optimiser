# Changelog

## Unreleased

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
