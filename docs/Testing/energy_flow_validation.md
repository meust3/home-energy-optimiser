# Energy Flow Validation

This document records real-world validation of the energy flow model.

The purpose is to confirm that derived energy flows correctly represent the
behaviour of the GoodWe inverter before any optimisation or automation is
implemented.

---

## Validation 001 — Manual Grid Fast Charge

**Date**

2026-08-02

### Scenario

Fast Charging was manually enabled from the GoodWe application.

The Home Energy Optimiser was operating in read-only mode.

No commands were issued by this project.

### Raw observations

| Metric | Value |
|---------|------:|
| PV generation | 1,177 W |
| House consumption | 2,817 W |
| Grid power (raw) | -11,462 W |
| Battery power (raw) | -9,811 W |

### Derived flows

| Flow | Value |
|------|------:|
| Grid import | 11,462 W |
| Grid export | 0 W |
| Battery charge | 9,811 W |
| Battery discharge | 0 W |
| Baseline house load | 2,817 W |
| Balance residual | 11 W |

### Event classification

```
grid_battery_charge
```

### Expected behaviour

Manual fast charging should:

- import power from the grid;
- charge the battery;
- continue supplying the house;
- not classify battery charging as household consumption.

### Result

PASS

The derived energy-flow model correctly separated:

- Grid → Battery
- Grid → House
- PV → House

The energy balance residual remained within tolerance.

### Notes

This observation confirms:

- Grid positive = Export
- Grid negative = Import
- Battery positive = Discharge
- Battery negative = Charge

These conventions are now treated as confirmed.

## Confirmed grid-charge event

Manual fast charging enabled from the GoodWe app.

Observed:

- grid import: 11.436 kW
- battery charge: 9.700 kW
- house consumption: 2.818 kW
- PV contribution: 1.073 kW
- event label: grid_battery_charge
- balance residual: -9 W

Conclusion:

The derived flow model correctly separates grid-to-battery and grid-to-house power.