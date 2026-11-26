from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from energy_optimizer import household_shadow as shadow
from energy_optimizer.persistence import open_repository

T = datetime(2030, 1, 1, 8, 0, 20, tzinfo=UTC)
GRID = T.replace(second=0)


def samples(age, error, demand):
    slots = [GRID - (age + n + 1) * shadow.STEP for n in range(12)]
    return {t: shadow.Sample(t, error, demand) for t in slots}


def test_route_and_turn_down():
    delayed = samples(8, -1200, None)
    fresh = samples(0, 1400, 3000)
    assert shadow.select_offset(T, {}, delayed)["offset_w"] == -1000
    assert shadow.select_offset(T, {}, samples(9, 500, None))["source"] == "issued"
    assert shadow.select_offset(T, fresh, delayed)["offset_w"] == 1000
    for n in (1, 2, 3):
        t = GRID - n * shadow.STEP
        fresh[t] = shadow.Sample(t, 110, 2400)
    selected = shadow.select_offset(T, fresh, delayed)
    assert selected == dict(
        source="fresh", offset_w=110, age_seconds=20, input_count=12, eased=True
    )
    del fresh[GRID - 2 * shadow.STEP]
    assert shadow.select_offset(T, fresh, delayed)["offset_w"] == 1000
    assert shadow.select_offset(T, samples(0, 0, 1200), delayed)["source"] == "fresh"


@pytest.mark.parametrize("witness_delay", [0, 300])
def test_pair_requires_postcommit_witness_before_target(
    tmp_path, monkeypatch, witness_delay
):
    repo = open_repository(f"sqlite:///{(tmp_path/'pair.db').as_posix()}")
    try:
        repo.create_schema_for_tests()
        first = GRID + shadow.STEP
        run = SimpleNamespace(
            created_at_utc=T,
            horizon_start_utc=first,
            model_version=shadow.CURRENT_FORECAST_MODEL_VERSION,
            metadata=dict(
                training_policy="verified_preferred", alignment_version="full_5m_v1"
            ),
            points=[
                SimpleNamespace(period_start_utc=t, expected_value=1200)
                for t in (first, first + timedelta(hours=4))
            ],
        )
        monkeypatch.setattr(
            shadow, "read_inputs", lambda *args: (samples(0, 800, 2000), {})
        )
        clocks = iter((T, T, T + timedelta(seconds=witness_delay)))
        shadow.record(repo, run, 42, lambda: next(clocks))
        pair = shadow.read_pair(repo, 42)
        if witness_delay:
            assert pair is None
        else:
            assert pair["points"][0][1:] == [1200, 1200 + 800 * (1 - 280 / 10800)]
            assert pair["points"][1][1:] == [1200, 1200]
            assert pair["decision"]["source"] == "fresh"
        assert shadow.read_pair(repo, 41) is None
    finally:
        repo.close()
