# Versioned captured SOC freshness

`goodwe-runtime-soc-freshness-v1` is an additive source-capture evidence contract.
The existing `goodwe_soc_timestamp_enabled` option controls emission. When enabled,
new captures retain the already fetched GoodWe runtime timestamp state and HA
last_updated receipt, configured timezone, observation slot and exact SOC digest.
No extra request, scheduler, service call or option is introduced.

Admission requires the device clock AND HA receipt each to be within the profile's
existing positive age limit, capped at 600 seconds, at the decision commit witness.
Future, invalid, missing, unknown-version, hash-mismatched and cross-slot evidence
fails closed. The linked reserve observation must fall within the same five-minute
slot and precede source receipt. Microsecond observation precision is retained.
Ambiguous or nonexistent naive local times fail closed. Branch evidence retains
its own version/hash and expires at the earlier clock/receipt plus the limit.

This is the existing conditional GoodWe runtime-frame interpretation, not proof of
an atomic device measurement or independently measured physical applicability.
The SOC/capacity branch-energy proxy and all profile, PV, reserve, selection and
terminal assumptions remain unchanged. Original SOC `reported_at` remains the
HA value/attribute-change timestamp; source_ages_seconds still reports that age.

Old captures without the new block keep their original interpretation, bytes and
hashes. Never add the block to historical records, rewrite hashes, or reinterpret
frozen studies automatically. New readers must understand this contract; generic
capture-envelope readers may preserve it without interpreting it. Raw runtime
clock evidence is bounded to 128 characters. Existing envelope and logical byte
limits remain 2 MiB. No schema migration is needed.

Validation: authored stale/future/corrupt/missing/version/600-second boundary and
DST cases, old-envelope compatibility, fixed/linked reserve invariants, SQLite and
PostgreSQL persistence, dashboard execution-disabled checks and collector wiring.
Private retained-input rehearsals are derived local experiments, never replacements
for historical receipts or evidence of realised savings. Production deployment and
normal-cycle acceptance require separate approval.
