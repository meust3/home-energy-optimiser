# Database architecture

Application services depend on `ApplicationRepository`, not a database driver.
`DATABASE_URL` selects exactly one backend for every component in a process. The
legacy SQLite `Historian` remains only for schema-v6 adoption and compatibility
tests; application and CLI code never constructs it.

```text
collector / forecasts / reserve / audits / inspection
                         |
                  persistence API
                   /             \
              SQLite          PostgreSQL
          local/offline     production/shared
```

`DATABASE_URL` is canonical. If absent, the effective default is
`sqlite:///data/energy_history.db`. There is no fallback after a PostgreSQL URL has
been selected: connection failure is explicit. Transactions are owned by cohesive
repository operations and sessions never escape into business logic.

SQLAlchemy models are the portable schema and Alembic is the deployment migration mechanism. Generic JSON becomes JSONB on PostgreSQL. Timestamps are timezone-aware and UTC is used for internal keys.

## Timestamp contract

Repository timestamp fields have one application-layer type on both backends:
timezone-aware Python `datetime` objects. UTC keys and audit times are normalized to
UTC; explicitly local fields retain their recorded offset. SQLite stores those
values as offset-bearing ISO 8601 text, while PostgreSQL uses `TIMESTAMPTZ`.
Conversion to ISO 8601 strings happens only at JSON, CSV, or terminal-display
boundaries. Naive datetimes are rejected unless a narrowly scoped compatibility
reader explicitly identifies a legacy UTC value.

JSON and JSONB columns likewise have one application contract: repositories return
native Python lists, dictionaries, scalars, or `None`. Compatibility readers may
parse legacy SQLite JSON text into that contract. JSON CLI output retains native
structure; terminal tables deliberately render lists and dictionaries as compact
JSON text, and CSV exports serialize structured values as valid JSON strings.
