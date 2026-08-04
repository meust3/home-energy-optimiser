from datetime import UTC, timedelta

import pytest

from energy_optimizer.collector import build_observation
from energy_optimizer.ev_annotation import (
    annotate_ev_session,
    parse_aware_timestamp,
    remove_ev_session,
)
from energy_optimizer.historian import Historian


def _historian_with_rows(healthy_states, config, now, count=2):
    historian = Historian(config.database_path)
    for index in range(count):
        historian.save(
            build_observation(
                healthy_states, config, observed_at=now + timedelta(minutes=5 * index)
            )
        )
    return historian


def _range(now, count=2):
    return now, now + timedelta(minutes=5 * (count - 1))


def test_dry_run_makes_no_changes(healthy_states, config, now):
    historian = _historian_with_rows(healthy_states, config, now)
    start, end = _range(now)
    before = historian.observation_rows()
    report = annotate_ev_session(historian, start=start, end=end, session_id="ev-1")
    assert report.dry_run
    assert report.matching_observation_count == 2
    assert historian.observation_rows() == before
    with historian.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ev_session_annotations"
            ).fetchone()[0]
            == 0
        )


def test_apply_excludes_without_inventing_power_and_preserves_raw(
    healthy_states, config, now
):
    historian = _historian_with_rows(healthy_states, config, now)
    start, end = _range(now)
    before = historian.observation_rows()
    report = annotate_ev_session(
        historian, start=start, end=end, session_id="ev-1", note="known", apply=True
    )
    after = historian.observation_rows()
    assert report.audit_record_created
    for old, new in zip(before, after, strict=True):
        assert new["ev_charging_active"] == 1
        assert new["ev_source"] == "manual_annotation"
        assert new["ev_detection_confidence"] == "confirmed_manual"
        assert new["ev_power_w"] is None
        assert new["baseline_training_eligible"] == 0
        assert new["baseline_exclusion_reason"] == "known_ev_session_without_ev_power"
        for column in (
            "house_consumption_w",
            "grid_power_w",
            "battery_power_w",
            "pv_power_w",
        ):
            assert new[column] == old[column]
    with historian.connect() as connection:
        audit = connection.execute("SELECT * FROM ev_session_annotations").fetchone()
    assert audit["affected_row_count"] == 2
    assert audit["note"] == "known"
    assert audit["annotation_source"] == "manual_annotation"


def test_direct_ev_power_is_preserved_and_retained(healthy_states, config, now):
    historian = _historian_with_rows(healthy_states, config, now, count=1)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET ev_power_w=700, baseline_training_eligible=0"
        )
    report = annotate_ev_session(
        historian, start=now, end=now, session_id="direct", apply=True
    )
    row = historian.latest_observation()
    assert row["ev_power_w"] == 700
    assert row["baseline_house_consumption_w"] == max(
        row["house_consumption_w"] - 700, 0
    )
    assert row["baseline_training_eligible"] == 1
    assert report.direct_ev_power_rows_retained == 1


def test_overlapping_annotations_and_reversal(healthy_states, config, now):
    historian = _historian_with_rows(healthy_states, config, now)
    start, end = _range(now)
    annotate_ev_session(historian, start=start, end=end, session_id="first", apply=True)
    annotate_ev_session(
        historian, start=start, end=start, session_id="second", apply=True
    )
    remove_ev_session(historian, session_id="second", apply=True)
    rows = historian.observation_rows()
    assert rows[0]["ev_session_id"] == "first"
    assert rows[1]["ev_session_id"] == "first"
    preview = remove_ev_session(historian, session_id="first")
    assert preview.dry_run and preview.matching_observation_count == 2
    remove_ev_session(historian, session_id="first", apply=True)
    assert all(row["ev_session_id"] is None for row in historian.observation_rows())
    with historian.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ev_session_annotations"
            ).fetchone()[0]
            == 4
        )


def test_timezone_parsing_and_equivalent_range(healthy_states, config, now):
    historian = _historian_with_rows(healthy_states, config, now, count=1)
    utc = now.astimezone(UTC)
    alternate = utc.astimezone(
        parse_aware_timestamp("2026-01-01T00:00:00+11:00").tzinfo
    )
    report = annotate_ev_session(historian, start=alternate, end=alternate)
    assert report.matching_observation_count == 1
    with pytest.raises(ValueError, match="timezone offset"):
        parse_aware_timestamp("2026-08-01T12:00:00")
    with pytest.raises(ValueError, match="end must"):
        annotate_ev_session(historian, start=now, end=now - timedelta(minutes=5))
