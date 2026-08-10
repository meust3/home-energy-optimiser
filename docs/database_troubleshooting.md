# Database troubleshooting

Run `python tools/check_database.py` first. It safely reports backend/target, connectivity, Alembic revision, counts, observation age, duplicate slots, and orphan checks without printing a password.

Use `python tools/check_database.py --application-readiness` to verify each
application capability during readiness checks or troubleshooting. A PostgreSQL
connection error never causes an automatic SQLite fallback.

- Connection failure: check NAS reachability, trusted network/VPN, listener rules, TLS, database name, and role grants.
- Revision mismatch: back up, then run `python -m alembic upgrade head` against the displayed target.
- Existing SQLite v6 without revision: dry-run `tools/adopt_database.py`, inspect, then repeat with `--apply`.
- Transaction failure: preserve the credential-redacted message. The collector rolls back and waits for the next scheduled boundary.
- Migration conflict: never overwrite it silently; compare the business key and values or restart from a clean restore.
