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
    assert summary.estimate == 1.8
    assert summary.estimate10 == 1.0
    assert summary.estimate90 == 3.0
