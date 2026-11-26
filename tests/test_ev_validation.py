from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from energy_optimizer.arbitrage.capture import CaptureRepository
from energy_optimizer.arbitrage.decision_types import digest
from energy_optimizer.ev_chart import LIVE
from energy_optimizer.ev_validation import REPORT_KIND, EVValidator
from energy_optimizer.ev_validation_metrics import summarize
from energy_optimizer.persistence import open_repository

START = datetime(2025, 1, 1, tzinfo=UTC)
PREFIX = "sensor.ev_charger_test"


def test_first_ten_with_retry_restart_duplicate_and_missing_reference(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{(tmp_path / 'archive.db').as_posix()}"
    repo = open_repository(url)
    repo.create_schema_for_tests()
    archive = CaptureRepository(repo)

    def capture(start, receipt):
        body = {
            "station_key": digest(PREFIX),
            "last_session_reported_times": {
                "last_session_start": start.isoformat(),
                "last_session_end": (start + timedelta(minutes=10)).isoformat(),
            },
        }
        archive.save(
            kind=LIVE,
            origin=receipt.isoformat(),
            at=receipt,
            body=body,
            clock=lambda: receipt,
        )

    # First station completion began before the cutoff.
    for i in range(12):
        start = START + timedelta(minutes=20 * i - 5)
        capture(start, start + timedelta(minutes=10))
        capture(start, start + timedelta(minutes=15))

    def history(ids, left, right):
        site, station, energy, load = ids
        start = left + timedelta(minutes=10)

        def row(entity, seconds, value, unit):
            return {
                "entity_id": entity,
                "last_updated": (start + timedelta(seconds=seconds)).isoformat(),
                "state": str(value),
                "attributes": {"unit_of_measurement": unit},
            }

        return [
            [row(site, 0, 5000, "W")],
            [row(station, 0, 3, "kW")],
            [row(energy, i, i / 1800, "kWh") for i in (0, 120, 240, 360, 480, 599)],
            [] if start == START + timedelta(minutes=15) else [row(load, 0, 2000, "W")],
        ]

    reader = Mock(side_effect=history)

    def validator():
        return EVValidator(
            directory=tmp_path / "app-data",
            frozen=START,
            prefix=PREFIX,
            reference="sensor.home_load",
            timezone="UTC",
            repository_factory=lambda: open_repository(url),
            read_history=reader,
        )

    now = START + timedelta(hours=5)
    reader.side_effect = TimeoutError
    with pytest.raises(TimeoutError):
        validator().step(now)
    reader.side_effect = history
    # Simulate the original installation before loading the candidate.
    with monkeypatch.context() as old_app:
        old_app.setattr(EVValidator, "_review", lambda *args: None)
        for _ in range(9):
            validator().step(now)
    assert "comparison" not in validator().status()
    validator().step(now)
    first = validator().status()["comparison"]
    validator().step(now)
    validator().step(now)
    assert validator().status()["all_completed"] == 11
    assert validator().status()["comparison"] == first
    assert reader.call_count == 12
    assert first["sessions_with_matched_reference"] == 9
    assert first["aligned"]["station"]["mean_absolute_disagreement_w"] == 0
    assert first["including_fallbacks"]["reference_counter"]["bias_w"] == pytest.approx(
        1000
    )
    assert first["decision"] == "inspect evidence before promotion"
    assert archive.latest(REPORT_KIND)["body"] == first
    for _ in range(7):
        validator().step(now)
    candidate = validator().status()["candidate_review"]
    assert candidate["completed"] == 10
    assert candidate["status"] == "inspect evidence before promotion"
    assert candidate["aligned"] == first["aligned"]
    assert reader.call_count == 12
    (validator().directory / "review-v2.json").write_text("{", encoding="utf-8")
    assert validator().status()["comparison"] == first
    repo.close()


def test_counter_reset_and_stale_points_keep_missing_slots():
    streams = {
        "site": [(0, 4000)],
        "load": [(0, 1500)],
        "station": [(0, 2500)],
        "energy": [(0, 0), (150, 0.1), (300, 0.2), (450, 0)],
    }
    s = summarize(0, 900, streams)
    assert s["counter_reset"] and s["revised_pairs"] == 0
    assert s["aligned_seconds"] == 600 and s["other_seconds"] == 300
