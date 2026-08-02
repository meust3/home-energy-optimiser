from datetime import UTC

from energy_optimizer import entity_ids as ids
from energy_optimizer.parsing import (
    parse_amber_intervals,
    parse_number,
    parse_solar_summary,
)


def test_unknown_unavailable_empty_and_malformed_are_missing():
    for value in ("unknown", "unavailable", "", "abc", None):
        assert parse_number(value) is None
    assert parse_number("0") == 0


def test_amber_interval_preserves_documented_fields(healthy_states):
    interval = parse_amber_intervals(healthy_states[ids.AMBER_IMPORT_FORECAST])[0]
    assert interval.duration == 30
    assert interval.start_time.tzinfo == UTC
    assert interval.per_kwh == 0.22
    assert interval.spot_per_kwh == 0.18
    assert interval.renewables == 55
    assert interval.descriptor == "neutral"
    assert interval.spike_status == "none"


def test_solcast_preserves_uncertainty(healthy_states):
    summary = parse_solar_summary(healthy_states[ids.SOLCAST_NEXT_HOUR])
    assert summary.estimate_kwh == 1.8
    assert summary.estimate10_kwh == 0.001
    assert summary.estimate90_kwh == 0.003
    assert summary.source_estimate == 1800
    assert summary.source_unit == "Wh"


def test_solcast_next_hour_wh_is_converted_to_kwh(healthy_states):
    state = healthy_states[ids.SOLCAST_NEXT_HOUR]
    state.state = "6796"
    state.attributes["estimate"] = 6796
    summary = parse_solar_summary(state)
    assert summary.estimate_kwh == 6.796
    assert summary.source_estimate == 6796
    assert summary.conversion_status == "converted_from_wh"


def test_solcast_remaining_today_kwh_is_unchanged(healthy_states):
    state = healthy_states[ids.SOLCAST_REMAINING_TODAY]
    state.state = "19.0476"
    state.attributes["estimate"] = 19.0476
    summary = parse_solar_summary(state)
    assert summary.estimate_kwh == 19.0476
    assert summary.source_estimate == 19.0476
    assert summary.conversion_status == "native_kwh"


def test_solcast_missing_unit_is_not_silently_assumed(healthy_states):
    state = healthy_states[ids.SOLCAST_NEXT_HOUR]
    state.attributes.pop("unit_of_measurement")
    summary = parse_solar_summary(state)
    assert summary.estimate_kwh is None
    assert summary.source_estimate == 1800
    assert summary.source_unit is None
    assert summary.conversion_status == "unit_missing"
