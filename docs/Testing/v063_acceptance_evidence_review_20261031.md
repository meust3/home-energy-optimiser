# Historical v0.6.3 acceptance evidence review - 31 October 2026

Baseline main: `eaf9d6840ea4635ec6c820a7d4128303ee151291`.
Scope: reconcile the uncommitted September acceptance follow-up from the original
AI consumer worktree into the current acceptance document. The original candidate
and every evidence file were read only. No monitoring script was executed, no
database was opened, and no live integration or automation was queried or changed.

## Evidence and verification

The retained evidence directory is `data/soc_freshness_gate/v063-deployment/` in
the original `home-energy-optimiser-v0.6.0` consumer checkout. Raw household evidence
remains there, untracked; only this verification record and the qualified historical
document are reconciled. Hashes below identify the exact local bytes reviewed;
they establish identity at review time, not independent authenticity of collection.

| File | SHA-256 |
| --- | --- |
| `monitor-window.json` | `aa8eca10c610346dbd98798afa777f41562f37c8364de4eff14b1d64ee5f5dfb` |
| `final-window-audit.json` | `5f8a411552a5f5a4f911d33d17a3227833d31351f46551f266e000a7191b7e44` |
| `monitor-history.jsonl` | `64a1124e42da5d46279da06516a05712224f2f7f3662df56228b72201e912a30` |
| `monitor-latest.json` | `c5262c17b95747b47e80e1fffb941a4dbb63fa3318995462f61b0f631c0b0073` |
| `soc-exceptions-20260927T1119.json` | `b633dc532168cd087e7240e9ad0602355f2984f03b2db45b1ae03f60bbbc4e7b` |
| `monitor.py` (read as inert query definitions only) | `3373263462b106528c4f8c39d4f143a790653a4f6282a9d8f2ea4f2b16603d20` |

Original uncommitted acceptance-document SHA-256:
`985680f3f2203f6a8a12fd3f9cde372dbc2ae5c1692a9ba187021a03428f032b`.

## Claim decisions

| Proposed claim | Evidence and adopted treatment |
| --- | --- |
| First two scheduled cycles succeeded; 13 fresh observations | History entry `2026-09-26T23:09:59.460857+00:00`: two success rows, 288 points each, non-null forecast/reserve IDs, 36.3585/12.6588-second durations; 13/13 fresh observations, two HOLD/no-command decisions. Adopted as the check around 09:10 Brisbane. |
| Two unavailable readings; 26 successful cycles | History entry `2026-09-27T11:18:54.447264+00:00`: 158 observations, 156 fresh, 26 successful HOLD/no-command cycles. Exception receipt explicitly records null SOC, unhealthy telemetry and unavailable entities/clock at 20:25 and 20:35. Adopted without claiming a stale-clock decision-boundary test. |
| Fixed-window operation passed | Audit records 576 observations, 96 successful operations, 574 fresh/two unavailable SOC reasons, 96 HOLD/no-command decisions, no failures/retention, and runtimes 11.8326–55.3916 seconds. Adopted as retained aggregate evidence. |
| Every cycle independently verified to have 288 persisted points and a linked reserve | Audit contains an `actual_points` tuple `[96,288,288]`, but its query definitions/column labels are not retained alongside it. Report that tuple and its consistency with 288 points; do not claim independently reconstructed per-run points/reserve joins. |
| No gaps/PV flags; valid revision/index | Latest monitor covers the larger interval beginning at the same start and reports zero gaps/PV flags, revision `20260927_01`, valid index. `monitor.py` defines these checks. Adopted as recorded monitor results, not a new database audit. |
| 40.38-hour monitoring gap and retrospective tail | Recomputed from all 46 ordered history entries. Largest gap: 40.3843979844 hours. Window end minus last pre-gap check: 5:27:35.693870. Adopted with exact rounded times; no cause inferred. |
| Later scoring cancellation and recovery | Latest receipt records one failed cycle at 29 September 19:30 with `phase=score_forecast_points`, 47.2419-second duration; subsequent successes include 30 September 19:00. Adopted as historical recurrence, not current runtime status. |
| Index reduced work; NAS contention explains failure | These receipts do not establish comparative performance or causation. Omitted from the follow-up conclusions. |
| Automation disabled after final assessment | No confirming automation-state receipt among the reviewed evidence. Omitted; no current automation query or change was made. |

`monitor-latest.json` matches the final history entry exactly. The monitor stamps
its check before sequential autocommit queries; it is not an atomic database
snapshot. Approximate check times are therefore used for early receipts. The
window itself is exactly 48 hours from `2026-09-26T22:08:58.856579+00:00` to
`2026-09-28T22:08:58.856579+00:00`.

## Validation and limits

Offline JSON assertions checked the adopted counts, times, statuses, missing SOC,
decision flags, durations, gap calculation and final-history equality. File hashes
were rechecked after editing. The acceptance document's Windows-encoded heading
was converted to valid UTF-8, and whitespace/link checks were performed. No runtime
tests were needed for this documentation-only change.

Preexisting release, backup, migration and rollback sections were retained, not
reaudited. Historical rollback instructions are not permission to run them now.
The private source receipts are neither committed nor changed. Existing uncommitted
review reports, original Jev/SEMS files and the original acceptance update remain
preserved. This change makes no present-day deployment, integration, automation,
timeout-resolution or safety-gate claim.
