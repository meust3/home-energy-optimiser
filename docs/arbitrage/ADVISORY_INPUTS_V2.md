# Conditional research input contract v2

This opt-in local candidate is separate from operational non-HOLD selection and
hardware execution. Defaults remain capture off and profile empty. It requires
no database migration. Production adoption needs separate source/profile approval.

The exact top-level profile keys are `schema_version`, `assumptions`, `evidence`,
`state_bridge`, `soc_report_age_seconds`, `forecast_report_age_seconds`,
`uncontrolled_load_kw`, `uncontrolled_load_basis`, `price_interpretation`, and
`reserve_binding`. `schema_version` is `conditional-research-profile-v2`.
Other declarations use the existing explicit profile construction/admission rules.
Unknown keys/modes fail closed. The original eight-key profile remains supported
with its fixed `floor_kwh` and original strict/raw construction and context bytes.

`price_interpretation` is exactly one of:

```json
{"mode":"strict_raw_v1"}
```

```json
{"mode":"conditional_amber_boundary_start_plus_one_v1","source":"recorded_amber_forecasts_v1"}
```

The conditional convention applies only to decision-price forecasts from the
capture-v1 producer's fixed Amber general/feed-in alias mapping in AUD/kWh.
Capture v1 does not independently record provider identity; attribution relies
on this reviewed producer contract. Conflicting identity/channel metadata, when
present, is rejected. Integration code forwards timestamps; provider intent and
provider issuance remain unverified. Quoted prices/signs are never converted.

For each raw row, metadata duration must be exactly 5 or 30 minutes, with an
aligned end and start at the appropriate grid boundary or exactly one second
after it. Half-hour rows must start on a half-hour boundary. Interpretation
changes only that start to the boundary: 299/1799 raw seconds become 300/1800
canonical seconds. Canonical rows pass unchanged. Complete missing periods,
overlaps, duplicates, other offsets, invalid times/quotes and inconsistent
metadata fail. Both series must then pass the original strict coverage validator;
no horizon is padded. This helper is never used for actual/outcome/settlement
prices, F3 calculations or historical replay coverage.

The existing forecast `basis` stores a compact bounded segment ledger of index,
raw start, interpreted start, end, raw duration and canonical duration, plus
interpretation/source IDs and raw/derived hashes. Existing context/receipt hashing
includes it. Raw captures and receipt/witness/availability times stay immutable.
The public projection exposes hashes and mode; it does not duplicate the ledger.

`reserve_binding` is exactly one of:

```json
{"mode":"fixed_research_floor_v1","floor_kwh":2.0}
```

```json
{"mode":"linked_capacity_capped_reserve_v1","quantity":"capacity_capped_reserve_kwh","unit":"stored_kWh"}
```

The fixed example is authored, not an installed limit. Linked mode reads the
exact snapshot already embedded by `capture_forecast` using its specific reserve
ID. The supported `reserve-estimator-v1` quantity is the capacity-capped required
reserve, in analytical stored kWh. IDs, forecast target/model, capacity, duplicate
estimate fields, telemetry health, valid horizon, as-of/readiness/witness timing
and the existing 600-second reserve-observation age ceiling are checked. Missing
or incompatible evidence blocks; there is no latest-row lookup, regeneration,
fallback or unit conversion. The scalar is frozen once for R/P/G and the original
terminal rule. Binding details and the whole snapshot hash enter `Reserve.basis`.

SOC times capacity remains the captured branch-energy proxy. Initially
below-reserve energy is retained with its shortfall; it is never clamped up.
A floor equal to capacity permits no model discharge, so R/P identity under that
scenario is expected. Linking does not lower the reserve or manufacture energy.

Baseline demand plus a declared zero additional EV load is conditional total
load, not proof of future EV absence. PV remains the declared Solcast AC-equivalent
exogenous proxy. Equipment limits, efficiencies and physical applicability remain
research hypotheses. Calculated HOLD and evidence-blocked HOLD are distinct.

Selection/kernel, reserve engine, calibration, terminal rules, outcome accounting,
optional failure isolation, finite bounds and GET-only presentation remain in
place. SQL timeouts do not prove a CPU deadline. Local resource measurements are
not NUC/PostgreSQL guarantees. No transport, action endpoint or new scheduler is
introduced.
