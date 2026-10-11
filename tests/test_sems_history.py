"""Synthetic session evidence and non-mutating context joins."""

from copy import deepcopy

import pytest

from energy_optimizer.sems_history import prepare_sessions, preview_join


def evidence(energy="3.25"):
    return {
        "observed_at_utc": "2026-01-02T01:00:00Z",
        "session_records": [
            {
                "display_interval": "02-01-2026 07:01:00 - 02-01-2026 08:00:00",
                "charged_energy_display_kwh": energy,
            }
        ],
    }


def test_preserves_raw_energy_without_inventing_power_or_timezone():
    ledger = prepare_sessions(evidence())
    session = ledger["sessions"][0]
    assert session["charged_energy_display_kwh"] == "3.25"
    assert session["ev_power_w"] is None
    assert session["start_utc"] is None
    assert session["training_eligible"] is False
    assert ledger["coverage_complete"] is False


def test_duplicates_and_conflicts():
    data = evidence()
    data["session_records"] *= 2
    assert len(prepare_sessions(data)["sessions"]) == 1
    data["session_records"].append(evidence("4.00")["session_records"][0])
    with pytest.raises(ValueError, match="Conflicting"):
        prepare_sessions(data)


@pytest.mark.parametrize("energy", ["NaN", "Infinity", "-1", "bad"])
def test_invalid_energy(energy):
    with pytest.raises(ValueError, match="energy"):
        prepare_sessions(evidence(energy))


def test_missing_energy_stays_missing():
    assert (
        prepare_sessions(evidence(None))["sessions"][0]["charged_energy_display_kwh"]
        is None
    )


def test_join_is_half_open_at_observation_instants_and_non_mutating():
    rows = [
        {"slot_utc": stamp, "house_consumption_w": "5000"}
        for stamp in (
            "2026-01-01T21:00:00Z",
            "2026-01-01T21:05:00Z",
            "2026-01-01T22:00:00Z",
        )
    ]
    original = deepcopy(rows)
    result = preview_join(
        rows, prepare_sessions(evidence()), confirmed_utc_offset_hours=10
    )
    assert [r["context"] for r in result] == [
        "unknown",
        "within_recorded_session",
        "unknown",
    ]
    assert rows == original
    assert all(not r["training_change_authorized"] for r in result)


def test_naive_observation_rejected():
    with pytest.raises(ValueError, match="offsets"):
        preview_join(
            [{"slot_utc": "2026-01-01T21:05:00"}],
            prepare_sessions(evidence()),
            confirmed_utc_offset_hours=10,
        )
