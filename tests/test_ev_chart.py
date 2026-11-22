from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from energy_optimizer.collector import Collector
from energy_optimizer.db.models import ArbitrageCapture
from energy_optimizer.ev_chart import (
    WINDOW,
    attach_chart_evidence,
    capture_charger,
    charger_sample,
    import_history,
    interval_counter,
    prepare_history,
)
from energy_optimizer.models import HomeAssistantState
from energy_optimizer.persistence import open_repository

START = datetime(2026, 11, 1, tzinfo=UTC)
PREFIX = "sensor.ev_charger_test"


def states(at, energy=1, duration=10):
    values = {
        "charging_power": (6, "kW"),
        "session_energy": (energy, "kWh"),
        "session_duration": (duration, "min"),
        "status": ("charging", None),
    }
    result = {}
    for channel, (value, unit) in values.items():
        entity = f"{PREFIX}_{channel}"
        result[entity] = HomeAssistantState(
            entity_id=entity,
            state=str(value),
            last_updated=at,
            last_changed=at,
            attributes={"unit_of_measurement": unit, "private_unused": "omitted"},
        )
    return result


def test_optional_station_evidence_uses_same_get_and_keeps_baseline(
    healthy_states, config, now
):
    client = Mock()
    client.get_states.return_value = healthy_states | states(now)
    original = Collector(client, config).collect(observed_at=now)
    client.reset_mock()
    candidate = config.model_copy(update={"ev_chart_charger_prefix": PREFIX})
    observed, cached = Collector(client, candidate).collect_with_states(observed_at=now)
    client.get_states.assert_called_once()
    assert (
        f"{PREFIX}_charging_power"
        in client.get_states.call_args.kwargs["optional_entity_ids"]
    )
    assert cached[f"{PREFIX}_charging_power"].state == "6"
    assert original.ev_power_w == observed.ev_power_w
    assert (
        original.baseline_house_consumption_w == observed.baseline_house_consumption_w
    )
    assert original.baseline_training_eligible == observed.baseline_training_eligible


def test_counter_requires_fresh_adjacent_same_session():
    first = charger_sample(states(START), PREFIX, START, START)
    end = START + WINDOW
    current = charger_sample(states(end, 1.5, 15), PREFIX, end, end)
    assert first["watts"] == 6000
    assert "private_unused" not in str(first)
    assert interval_counter(first, current, START)["watts"] == 6000
    for energy, duration in ((0, 15), (1.5, 1), (2.1, 15)):
        sample = charger_sample(states(end, energy, duration), PREFIX, end, end)
        assert interval_counter(first, sample, START) is None
    stale = charger_sample(states(START), PREFIX, end, end + timedelta(seconds=1))
    assert stale["watts"] is None
    assert interval_counter(first, stale, START) is None


def test_history_context_and_estimated_watts_remain_distinct():
    review = dict(slot=START.isoformat(), review_as_of=(START + WINDOW).isoformat())
    assert (
        prepare_history(dict(review, state_estimate="BYD likely idle"))[2]["watts"]
        is None
    )
    only_power = dict(
        review, power_only=True, estimated_session_counter_kwh_from_power=0.25
    )
    assert prepare_history(only_power)[2]["watts"] == 3000
    assert (
        prepare_history(dict(only_power, charger_counter_delta_kwh=0.5))[2]["watts"]
        == 6000
    )
    with pytest.raises(ValueError):
        prepare_history(dict(review, charger_counter_delta_kwh=float("nan")))
    with pytest.raises(ValueError):
        prepare_history(dict(review, review_as_of=START.isoformat()))


def test_persisted_history_and_live_overlay_are_read_only_and_idempotent(tmp_path):
    url = f"sqlite:///{(tmp_path / 'chart.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    history = dict(
        slot=START.isoformat(),
        review_as_of=(START + WINDOW).isoformat(),
        charger_counter_delta_kwh=0.25,
    )
    for _ in range(2):
        assert import_history(repository, [history]) == 1
    later = {**history, "review_as_of": (START + 2 * WINDOW).isoformat()}
    assert import_history(repository, [later]) == 1
    with pytest.raises(ValueError, match="Conflicting historical EV evidence"):
        import_history(repository, [dict(later, charger_counter_delta_kwh=0.5)])
    for i in range(3):
        at = START + i * WINDOW
        capture_charger(
            states(at, i * 0.5, (i + 1) * 5),
            PREFIX,
            at,
            at,
            lambda: open_repository(url),
        )
    points = [
        dict(
            period_start_utc=START + i * WINDOW,
            period_end_utc=START + (i + 1) * WINDOW,
            actual_value=None,
        )
        for i in range(4)
    ]
    with repository.transaction() as session:
        count = select(func.count()).select_from(ArbitrageCapture)
        assert session.scalar(count) == 6
        assert (
            attach_chart_evidence(
                session, {"id": 123, "forecast_type": "baseline_household_load"}, points
            )
            == []
        )
        assert session.scalar(count) == 6
    assert [p.get("ev_adjustment_w") for p in points] == [3000, 6000, 6000, None]
    assert points[1]["ev_source"] == "Session counter mean between reports"
    assert points[2]["ev_source"] == "Station reported power sample"
    assert all(p["actual_value"] is None for p in points)
    repository.close()
