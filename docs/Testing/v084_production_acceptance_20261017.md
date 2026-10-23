# v0.8.4 retained production acceptance - 17 October 2026

This reconciles current release prose against retained acceptance receipts. It
does not rerun production checks, change instructions or supersede sealed evidence.
The safety requirements in AGENTS.md remain applicable; its older v0.6.2 runtime
paragraph describes a historical acceptance point.

| Evidence layer | Recorded result |
|---|---|
| Published source | Exact commit `72a446cf28abb89217d76030004d6829b1c3007e`; [PR 17](https://github.com/meust3/home-energy-optimiser/pull/17) and [v0.8.4 release](https://github.com/meust3/home-energy-optimiser/releases/tag/v0.8.4) |
| Build validation | Actual CI, remote-commit and tag-download builds passed; retained recovery artifact saved/reloaded |
| Installed/runtime | Existing App reported v0.8.4 Running; startup, all 55 protected options and two normal cycles accepted |
| Independent installed bytes | **Not independently verified under the approved amendment**; matching runtime-generated source-wrapper hash is metadata, not independent image/source/dependency attestation |
| Pilot preparation | Fake-only source starts at `fb1a4042b9d4654d8f82165a37dbcdccd5590236`, directly based on accepted v0.8.4; software integration does not install or activate it |
| This readiness change | Software source, tests and documentation only; CI validation images are separate from installed runtime or physical certification |

Acceptance completed at `2026-10-17T04:01:32.823382+00:00`. Schema remained
`20261008_01`; no production migration/restore occurred. A stopped-snapshot backup
and isolated restore passed before the accepted update. Historical failure receipts
remain preserved. No repeat migration or cutover follows from this summary.

The 13:30 and 14:00 Brisbane cycles each produced 288 forecast points with exact
linked reserve snapshots and HOLD decisions. Scoring processed 561/276 selected
rows in 5.897/3.082 seconds. Twelve new source captures and two linked research
input/opportunity records passed their recorded integrity checks. This establishes
initial acceptance only, with no prospective performance or savings claim.

Capture, boot and watchdog were ON. Automatic updates, operational non-HOLD and
retention were OFF; hardware execution and Gate B remained disabled. The research
SOC admission bound remained 600 seconds. That research bound is not a proposed
hardware feedback deadline. Two accepted cycles do not establish day/week growth,
long-term reliability or hardware-test readiness.

Intermittent Ingress shell loading remains recorded, with unproven root cause.
No restart/configuration workaround was applied to resolve it.

The source acceptance receipts and sealed evidence remain privately retained by
the owner. Their private locations and continuation identifiers are intentionally
omitted from this public summary. The public source/release links above identify
the published baseline; they do not independently attest installed bytes.

The [controlled-test review](../controlled_test_readiness.md) lists the remaining
Gate B requirements. None of these acceptance layers grants hardware authority.
