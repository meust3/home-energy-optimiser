# Lossless capture storage — local v0.8.2 candidate

The canonical capture hash distinguishes numeric `-0.0` from `0.0`. PostgreSQL
JSONB stores both as positive zero when they are ordinary JSON numbers. A source
containing signed zero can therefore fail its own integrity check after storage.
The strict failure is correct; accepting a recomputed hash would erase provenance.

New captures store an explicit `canonical-capture-body-v1` envelope in the existing
JSON/JSONB `body` column:

```json
{"storage_format":"canonical-capture-body-v1","canonical_body_json":"{\"per_kwh\":-0.0}"}
```

The enclosed string is the exact existing canonical JSON, not a normalization of
numeric values. `CaptureRepository.latest` decodes the envelope for all current
application consumers. Logical bodies, capture ID version, canonical hash
algorithm, quote signs, receipt times and witness semantics remain unchanged.
New saves verify the persisted body's hash before admitting a commit witness.
An envelope must have the exact known shape, canonical object JSON and existing
byte bound. Unknown/malformed envelopes fail; duplicates/noncanonical JSON do not
become admitted data. Both logical bodies and serialized envelopes must fit 2 MiB.

Existing object bodies are read unchanged. No migration, update, rehash, signed-zero
reconstruction, replay or history repair runs. Old hash-invalid rows stay invalid;
even retrying the same original ID cannot overwrite or bless them. New captures
of subsequent normal cycles use the lossless format.

This changes storage representation, not the source/decision/opportunity contracts
or economic rules. Direct SQL audit clients must decode the envelope before hashing
or inspecting a new logical body. The old App reader does not understand envelopes;
containment after a future update must keep v0.8.2 (capture/profile disabled as
separately approved), not downgrade to v0.8.1. The source bundle identity of new
receipts changes honestly; recomputing old receipts requires their matching source.

Regression coverage includes PostgreSQL's original failure, exact numeric/type and
Unicode/string round trips, all three capture kinds, hashes/IDs/witnesses, immutable
duplicates, unchanged valid/invalid legacy objects, linked full-capacity reserve
admission, future-witness rejection, malformed envelopes and byte-bound rollback.
Related existing tests cover the optional collector/coordinator failure boundary,
GET-only dashboard, profile/coverage/terminal rules and disabled fake executor.

Local resource checks reuse a retained real-shaped rehearsal body, without new
production reads or any selector/outcome replay. The 1,379,567-byte opportunity body
occupies a 1,592,164-byte serialized envelope (504,988-byte margin). Three local
owned PostgreSQL save/read samples took 0.130–0.191 seconds; these are host storage
measurements, not NUC latency or whole-calculation guarantees. Escaping can reject
a logical body that previously fit; the limit is not enlarged and optional failure
is isolated from core collection. Index/TOAST/WAL/backup growth is not inferred.

No deployment, publication, production migration, profile/reserve/selector change,
new device capability, hardware command or API inference is part of this local fix.
