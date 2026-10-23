# Offline preservation-test readiness review

The review is software-only. `review_controlled_test.py` reads one explicit JSON
record of at most 16 KiB and writes a report to stdout. It loads no environment,
application settings, credentials, database, transport or executor. Duplicate JSON
keys, unexpected/missing fields and malformed input are refused. It does not fetch
evidence references, inspect production or independently validate input claims.

Both recovery alternatives must be booleans or null, even when the other route is
verified. Null remains unresolved; it is never coerced into a positive claim.
Review times normalize to UTC before evaluation. An offset conversion outside
Python's representable UTC range produces the same structured refusal as other
invalid input, including exit 2 and hardware authorization false.

Use the supplied [review record](examples/controlled_test_readiness.json) as an
unsealed, owner-populated worksheet. It records the published software baseline,
`conserve`, conditional `auto`, unchanged `general` and a 120-second review ceiling.
Equipment, operator, supervision, physical limits, feedback, test window, ownership
generation, recovery and credential review require explicit evidence. The ceiling
is not a safe installation default or device expiry. No site values are inferred.

From the source root, with dependencies available and `src` on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python tools/review_controlled_test.py --review docs/examples/controlled_test_readiness.json --at 2026-10-20T00:00:00Z
```

Supply the actual review time for a current review; the example time is for
repeatable offline inspection. Exit 1 means unresolved/contradictory fields; exit 2
means unreadable/malformed input. Exit 0 means only `FIELDS_COMPLETE_REVIEW_ONLY`.
**Every report keeps `hardware_authorized=false` and `live_dispatch=false`.**
Editing a worksheet, supplying evidence references or passing tests grants no
authority. There is no connection from this tool to the collector, dashboard,
configuration, journal or dispatcher. It is not an execution-time safety monitor.

| Required review | Evidence required before a separately approved physical test |
|---|---|
| Baseline | [v0.8.4 initial acceptance](Testing/v084_production_acceptance_20261017.md) complete; installed bytes independently unverified under approved amendment |
| Interface | Freeze exact device identity/firmware, source semantics, retry/delivery evidence and ordinary settings; cached names/options alone do not prove physical behavior |
| Independent recovery | Verify an existing recovery route that works without HA, its connection/last-update evidence and usable recovery controls. Account access alone is insufficient |
| Controllers | Inventory all manual, automation, manufacturer, cloud/VPP and other writers. GoodWe Fast Export is one possible competing writer; helper changes may change EMS power/mode. Establish exclusive test-window ownership without assuming any current site configuration |
| Finite window/ownership | Freeze UTC start/end, approval expiry, current owner/generation and exclusive window. Retain the selected maximum 120 seconds; it is not native expiry or guaranteed physical return |
| Limits | Evidence-backed capacity/SOC/storage/backup floor, permitted battery/PV charging power, AC energy, stored throughput, separate net site import/export and gross import cost caps. Existing numbers/model assumptions are not permissions |
| Feedback | Natural pre-action discharge baseline, advancing post-approval frames, source-supported deadband, freshness/effect deadline and sustained observation. A short observed cadence is not a worst-case deadline. Worksheet feedback values remain null |
| Stop/return | Stop on deadline or bounds, stale/repeated/missing feedback, faults, unexpected flows, ownership change or ambiguous delivery. No repeated HA request after ambiguity. Conditional `auto` must preserve other settings and never overwrite a newer choice; failed return requires reconciliation and fresh physical evidence |
| Credential review | Resolve the credential's service/category, consumers, validity and any required remediation using non-secret evidence. Unknown status remains unresolved. Do not retrieve or publish secret values; resource removal alone does not establish revocation |

PV charging may continue during `conserve`, and grid import/cost may rise. Idle
telemetry cannot certify discharge inhibition. No load or battery command should
be used to manufacture a baseline. Do not equate ACK/cached selector state with a
measured physical effect. Protocol retry behavior can outlive a request timeout;
the selected manual duration supplies no device lease.

The worksheet requires either native expiry evidence or a separately reviewed
human procedure, plus independent recovery/physical return evidence in both
cases. That field-review distinction **does not** amend the existing fake adapter:
it still refuses to substitute human recovery for device-native expiry. There is
no real transport. No induced outage, control operation or recovery demonstration
is authorized by this software milestone.

Owner-specific evidence and sealed action manifests remain private and unchanged.
This public template contains no account, private task or incident locators and
does not replace those records. A future exact action package must incorporate
the owner's evidence and receive separate approval. Never use a worksheet as an
amendment to an existing seal.

## Simulation coverage and remaining physical gaps

Existing tests already cover exact approval, duplicate requests, lost ACK, outage,
restart before/after send, stale/repeated frames, clock faults, manual override,
capacity/SOC/site limits, ambiguous/partial delivery and witnessed return. They
also reject real transports/subclasses and human recovery claimed as native expiry.

New regression coverage addresses cumulative energy/throughput/import-cost
regression after a missing sample, both uninterrupted and after journal restart.
The rehearsal now searches bounded durable feedback history for the last known
cumulative values; missing samples remain missing. A separate combined scenario
checks failed return across restart, stale return evidence and held ownership,
with no retry or automatic release. Further annotated tests cover malformed
recovery alternatives, preserved boolean/null declarations, extreme-offset UTC
overflow and valid boundary/offset times. Explicit service-health fields are
required; preservation refuses unknown or exceeded gross import cost, including
at return verification. These tests certify local behavior only.

The next step is to complete missing owner-specific evidence through read-only
checks. Recovery, exclusive control, justified limits and security confirmations
remain gates; this software work does not advance to a hardware trial.
