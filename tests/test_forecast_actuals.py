import pytest

from energy_optimizer.forecast_actuals import evaluate_actual_rows


def row(**updates):
    return {
        "baseline_house_consumption_w": 1500,
        "house_consumption_w": 1500,
        "telemetry_is_healthy": True,
        "baseline_training_eligible": True,
        "baseline_exclusion_reason": None,
        **updates,
    }


@pytest.mark.parametrize(
    "rows,reason,eligible",
    [
        ([], "no_observation", False),
        ([row(baseline_house_consumption_w=None)], "actual_value_missing", False),
        ([row(telemetry_is_healthy=False)], "actual_unhealthy_or_ineligible", False),
        (
            [
                row(
                    baseline_training_eligible=False,
                    baseline_exclusion_reason="known_ev_session_without_ac_power",
                )
            ],
            "actual_unhealthy_or_ineligible",
            False,
        ),
        (
            [row(house_consumption_w=-100)],
            "invalid_actual_negative_household_demand",
            False,
        ),
        ([row()], None, True),
    ],
)
def test_shared_actual_rules_reject_missing_unhealthy_excluded_and_negative(
    rows, reason, eligible
):
    evidence = evaluate_actual_rows(rows)
    assert evidence.missing_reason == reason
    assert evidence.health_eligible == eligible


def test_negative_evidence_blocks_a_mixed_legacy_interval():
    evidence = evaluate_actual_rows([row(), row(house_consumption_w=-100)])
    assert not evidence.health_eligible
    assert evidence.actual_value == -100
