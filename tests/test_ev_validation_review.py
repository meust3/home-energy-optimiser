import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from energy_optimizer import ev_validation_review as review
from energy_optimizer.ev_validation_metrics import summarize


def test_counter_reset_recovers_only_whole_segments():
    streams = {
        k: [(t, w) for t in range(0, 901, 60)]
        for k, w in (("site", 8000), ("load", 2000), ("station", 6000))
    }

    def count(energy):
        return summarize(0, 900, dict(streams, energy=energy), recover_resets=True)[
            "counter_energy_slots"
        ]

    energy = [(t, t / 2000 if t < 480 else (t - 480) / 2000) for t in range(0, 901, 60)]
    assert summarize(0, 900, dict(streams, energy=energy))["counter_energy_slots"] == 0
    assert count(energy) == 2
    assert (
        count(
            [
                (0, 1),
                (60, 1.1),
                (270, 1.3),
                (300, 1.4),
                (360, None),
                (420, 0),
                (480, 0.1),
                (600, 0.3),
            ]
        )
        == 0
    )
    assert (
        count(
            [
                (0, 0),
                (150, 0.1),
                (300, 0.2),
                (450, 0.3),
                (600, 0),
                (750, 0.2),
                (900, 1.1),
            ]
        )
        == 1
    )


def test_provisional_detection_rewinds_on_late_witness_and_matches_provider():
    def iso(t):
        return datetime.fromtimestamp(t, UTC).isoformat()

    with closing(sqlite3.connect(":memory:")) as db:
        review.prepare(db)
        db.execute("INSERT INTO review_progress_v2 VALUES(1,1800,0)")

        def store(slot, mode, updated, watts, at):
            body = {
                "channels": {
                    "status": {"value": mode, "updated": iso(updated)},
                    "charging_power": {"value": watts, "updated": iso(at), "unit": "W"},
                }
            }
            review.store_capture(db, slot, slot, body)

        store(300, "charging", 250, 6000, 275)
        store(900, "available", 890, 6000, 305)
        store(1200, "available", 890, 0, 950)
        original = {"discovery_through": iso(1800)}

        def result(windows):
            return review.review_status(db, [], windows, [], original, 0, 1800)[
                "provisional_sessions"
            ]

        assert not result([])  # A missing slot interrupts the charging evidence.
        store(600, "charging", 250, 6100, 590)
        assert result([]) == [
            {
                "start": iso(250),
                "end": iso(890),
                "status": "provisional",
                "final_kwh": None,
            }
        ]
        store(600, "charging", 250, 6100, 590)
        assert result([(260, 900)]) == []
        assert result([(260, 900), (270, 920)])[0]["status"] == "ambiguous"


def test_stale_power_and_stale_zero_cannot_confirm_a_window():
    pending = review.Pending()
    pending, _ = pending.observe(600, "charging", 550, 6000, None, 0)
    pending, _ = pending.observe(900, "available", 890, 0, 890, 0)
    assert not pending.positive
    pending = review.Pending(start=250, positive=True)
    pending, found = pending.observe(1200, "available", 1100, 0, 300, 0)
    assert found is None
