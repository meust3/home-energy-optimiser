# Phase 1 architecture

The project keeps collection, forecasting, optimisation, and execution as separate
layers. Phase 1 implements only read-only collection and a basic historical load
profile. It does not contain an optimiser or executor.

`HomeAssistantClient` performs one allowlisted `GET /api/states` request per
collection. `Collector` parses the selected Amber, Solcast, and GoodWe entities,
evaluates domain-specific health, and creates one timezone-aware
`EnergyObservation` aligned to a five-minute UTC slot. `Historian` persists that
observation in SQLite. CLI programs only assemble these reusable components.

Health has independent telemetry, price, solar, and optional weather domains. The
overall display summary currently derives from telemetry because Phase 1 observation
integrity means trustworthy household and inverter measurements, not availability
of every forecast. Price or solar failure remains visible without invalidating an
otherwise useful telemetry observation.

The load profile reads telemetry-healthy observations and groups house power by
local weekday and five-minute slot. A group needs the configured minimum sample
count; otherwise the result explicitly uses the conservative fallback. It is an
explainable mean, not machine learning.

Readiness is consumer-specific: load profiling requires telemetry; future
grid-charge and battery-export recommendations require telemetry, price, and solar.
These readiness checks are advisory gates only and cannot issue commands.

Freshness policies are entity-specific. Live powers use five minutes, SOC and
current Amber prices use ten minutes, Amber forecasts use one hour, and the three
required Solcast summaries use six hours by default. Home Assistant `last_updated`
may remain unchanged for a stable value, so freshness checks are used only for
entities expected to update periodically. Mode, work-mode, and price-spike values
have no freshness penalty.

Power signs are stored exactly as Home Assistant reports them. No charge/discharge,
import/export interpretation is applied until those conventions are measured.

History analysis remains a separate read-only concern. Gap analysis compares stored
UTC slots with an inclusive five-minute sequence. Domain issue analysis reads the
structured health JSON. CSV export selects an inclusive timezone-aware range. The
power-sign validator evaluates all four grid/battery multiplier combinations using
the balance `PV + signed grid + signed battery ≈ house`, alongside battery-mode
groups. It reports residuals and confidence but does not select or persist a sign
convention.

Weather entity IDs are optional configuration. When configured, temperature and
condition are collected in the existing bulk GET. Missing weather may make only the
weather domain unhealthy; it cannot affect overall Phase 1 observation health.

The future executor is deliberately absent. Adding it requires a separate safety
review and explicit approval.
