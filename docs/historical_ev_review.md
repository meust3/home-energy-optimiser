# Historical EV review

Detection is conservative, read-only, and never establishes that a session is EV:

```text
python tools/detect_historical_ev_candidates.py --days 90 --markdown
python tools/detect_historical_ev_candidates.py --after 2026-06-01T00:00:00Z --before 2026-08-01T00:00:00Z --json
```

Defaults surface eligible pre-verified history above 5 kW for at least 60 minutes
and 5 kWh, with at most a 10-minute internal gap and plateau MAD ratio <=0.15.
Ovens, hot water, air conditioning, pools, battery/grid behavior, and other large
loads are explicit false-positive risks. Every result remains `unreviewed`.

After human review, preview the existing audited workflow, then apply explicitly:

```text
python tools/annotate_ev_session.py --start <UTC> --end <UTC> --session-id <ID>
python tools/annotate_ev_session.py --start <UTC> --end <UTC> --session-id <ID> --apply
```

That workflow snapshots prior derived eligibility, preserves raw/BYD telemetry,
and supports its established reversal command. Never bulk approve candidates.
