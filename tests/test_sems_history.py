"""Synthetic session evidence and non-mutating context joins."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from energy_optimizer.sems_history import (
    prepare_sessions,
    preview_join,
    qualify_session_times,
)


def qualify(ledger, zone="Australia/Brisbane", refs=None):
    return qualify_session_times(
        ledger,
        timezone_name=zone,
        evidence_references=(
            refs if refs is not None else ["synthetic-station-and-history"]
        ),
        validated_at=datetime(2026, 12, 1, tzinfo=UTC),
    )


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


def test_qualification_preserves_raw_data_and_does_not_activate_training():
    ledger = prepare_sessions(evidence())
    original = deepcopy(ledger)
    row = qualify(ledger)["sessions"][0]
    assert row["start_utc"] == "2026-01-01T21:01:00+00:00"
    assert row["end_utc"] == "2026-01-01T22:00:00+00:00"
    assert row["context_known_at_utc"] == "2026-12-01T00:00:00+00:00"
    assert row["ev_power_w"] is None
    assert not row["training_eligible"]
    assert not row["continuous_charging_verified"]
    assert ledger == original


@pytest.mark.parametrize("refs", [[], [""]])
def test_qualification_requires_evidence(refs):
    with pytest.raises(ValueError, match="evidence"):
        qualify(prepare_sessions(evidence()), refs=refs)


@pytest.mark.parametrize(
    "interval",
    [
        "05-04-2026 02:15:00 - 05-04-2026 03:00:00",
        "04-10-2026 02:15:00 - 04-10-2026 03:00:00",
    ],
)
def test_dst_ambiguous_and_nonexistent_times_rejected(interval):
    data = evidence()
    data["observed_at_utc"] = "2026-11-01T00:00:00Z"
    data["session_records"][0]["display_interval"] = interval
    with pytest.raises(ValueError, match="Ambiguous or nonexistent"):
        qualify(prepare_sessions(data), zone="Australia/Sydney")


def test_overlapping_single_charger_sessions_rejected():
    data = evidence()
    data["session_records"].append(
        {
            "display_interval": "02-01-2026 07:30:00 - 02-01-2026 08:30:00",
            "charged_energy_display_kwh": "1.00",
        }
    )
    with pytest.raises(ValueError, match="Overlapping"):
        qualify(prepare_sessions(data))


def test_completed_session_must_precede_acquisition():
    data = evidence()
    data["observed_at_utc"] = "2026-01-01T21:30:00Z"
    with pytest.raises(ValueError, match="after evidence"):
        qualify(prepare_sessions(data))


def test_validation_must_not_be_backdated():
    with pytest.raises(ValueError, match="precede"):
        qualify_session_times(
            prepare_sessions(evidence()),
            timezone_name="Australia/Brisbane",
            evidence_references=["fixture"],
            validated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
