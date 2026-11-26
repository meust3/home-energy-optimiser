# EV validator 0.8.12 release review

The existing dashboard GET for EV validation retains the original provider-completed cohort, cutoff, scores and publication. Its new `candidate_review` field contains the versioned local comparison. The existing coordinator invokes both methods. The candidate reuses the original four Recorder channels and their stored readings.

When a session counter falls, the candidate looks for full five-minute intervals inside continuous, nondecreasing runs. Both boundary values must be supported by readings at most 150 seconds apart. Gaps, invalid values and decreases split a run. The maximum interval increase is 1 kWh. The ten-minute limit for holding station power is independent of counter recovery.

The app tracks a provisional charge from witnessed charging status, positive station power, an idle transition and zero power within two minutes before to five minutes after that transition. Missing collection slots and unknown states interrupt detection. A single provider window with both endpoints within two minutes resolves the flag. Multiple matches require review. A provisional charge carries no final kWh and cannot enter the original ten-session comparison. An external provider receipt can support a private manual reconciliation.

On upgrade, the candidate reads at most twelve hours of witnessed historical captures per pass, processes up to 144 local slots, and scores at most one previously completed window from stored Recorder data. Retries reuse the station-specific validation directory and versioned local tables. A late witness replays the affected prefix from its previous checkpoint. Once caught up, normal discovery shares the frozen validator's capture batch. Candidate report failures are isolated from the frozen publication.

## Acceptance

1. Compare the original report before and after upgrade for the same inputs and cohort. Verify restart, late witnesses, duplicated receipts, near-boundary resets, freshness limits and unavailable reference readings.
2. Review the first ten provider-completed sessions with 90% directly aligned coverage, no unresolved gaps or unmatched charging, and improvement in both absolute disagreement and absolute bias in a majority of sessions. Check the pooled improvement after omitting each session. Inspect the direct and fallback-inclusive comparisons separately.
3. Keep household forecast promotion on its separately frozen, prospective 14-complete-day assessment. EV validation measures the quality of household actuals during charging.

The change uses additive tables in the validator's existing private SQLite cache. It requires no change to the canonical PostgreSQL schema. A rollback to 0.8.11 can read the original scores and cursor. The versioned cache tables and JSON can remain in the app data directory. A controlled installation still requires exact-source release CI, container validation, a fresh backup and app readback.
