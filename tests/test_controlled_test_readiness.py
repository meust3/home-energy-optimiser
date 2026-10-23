import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from energy_optimizer.arbitrage.readiness import review_readiness

ROOT = Path(__file__).resolve().parents[1]
T = datetime(2030, 1, 1, tzinfo=UTC)


def template() -> dict[str, Any]:
    return json.loads(
        (ROOT / "docs/examples/controlled_test_readiness.json").read_text(
            encoding="utf-8"
        )
    )


def synthetic_complete() -> dict[str, Any]:
    """Synthetic field-review inputs only; never installation recommendations."""
    record = template()
    record["plan"].update(
        equipment="synthetic device",
        operator="synthetic owner",
        manual_supervision_confirmed=True,
        owner_generation=1,
        valid_from_utc="2030-01-01T00:00:00+00:00",
        valid_until_utc="2030-01-01T00:05:00+00:00",
    )
    record["limits"] = {field: 1.0 for field in record["limits"]}
    record["limits"].update(
        capacity_kwh=1.0,
        min_soc_percent=20.0,
        max_soc_percent=90.0,
        min_stored_energy_kwh=0.3,
    )
    record["interface"] = {field: "synthetic evidence" for field in record["interface"]}
    record["feedback"] = {field: True for field in record["feedback"]}
    record["feedback"].update(
        send_freshness_seconds=10,
        initial_effect_timeout_seconds=10,
        sustained_feedback_period_seconds=20,
        battery_discharge_deadband_w=0,
    )
    for group in ("controllers", "recovery"):
        record[group] = {field: True for field in record[group]}
    record["security"].update(
        disposition="EXPIRED_REVOKED_NOT_REUSED_CONFIRMED",
        service_identity_confirmed=True,
        consumers_reviewed=True,
        remediation_or_expiry_evidence="synthetic evidence only",
    )
    return record


def test_actual_template_preserves_unknowns_and_cannot_authorize_hardware() -> None:
    record = template()
    original = deepcopy(record)
    report = review_readiness(record, at=T)
    assert record == original
    assert report["status"] == "BLOCKED"
    assert "plan.finite_current_utc_window_required" in report["blockers"]
    assert "limits.min_soc_percent_required" in report["blockers"]
    assert "security.credential_disposition_unresolved" in report["blockers"]
    assert report["hardware_authorized"] is False
    assert record["plan"]["max_duration_seconds"] == 120
    assert all(value is None for value in record["limits"].values())


def test_field_complete_record_is_still_unverified_and_unauthorized() -> None:
    record = synthetic_complete()
    record["recovery"]["native_expiry_verified"] = False
    report = review_readiness(record, at=T)
    assert report["blockers"] == []
    assert report["status"] == "FIELDS_COMPLETE_REVIEW_ONLY"
    assert report["hardware_authorized"] is False
    assert report["live_dispatch"] is False
    assert report["independently_verified_by_checker"] is False
    assert "installed_bytes_not_independently_verified" in report["limitations"]
    assert record["recovery"]["native_expiry_verified"] is False


@pytest.mark.parametrize(
    "value", [None, True, float("nan"), float("inf"), -1, 10**1000]
)
def test_unknown_or_malformed_numeric_limits_fail_closed(value: object) -> None:
    record = synthetic_complete()
    record["limits"]["max_battery_power_kw"] = value
    assert (
        "limits.max_battery_power_kw_required"
        in review_readiness(record, at=T)["blockers"]
    )


@pytest.mark.parametrize(
    "group,field,value,code",
    [
        (
            "plan",
            "valid_until_utc",
            "2029-12-31T23:59:59Z",
            "plan.finite_current_utc_window_required",
        ),
        (
            "plan",
            "valid_from_utc",
            "2030-01-01T01:00:00Z",
            "plan.finite_current_utc_window_required",
        ),
        (
            "plan",
            "valid_from_utc",
            "2030-01-01T00:00:00",
            "plan.finite_current_utc_window_required",
        ),
        (
            "plan",
            "valid_until_utc",
            "2030-01-01T00:00:30Z",
            "plan.insufficient_window_remaining",
        ),
        ("plan", "max_duration_seconds", 121, "plan.duration_invalid"),
        ("plan", "max_duration_seconds", True, "plan.duration_invalid"),
        ("plan", "start_mode", "sell_power", "plan.preservation_only_modes_required"),
        ("plan", "owner_generation", True, "plan.owner_generation_required"),
        (
            "limits",
            "min_stored_energy_kwh",
            0.1,
            "limits.stored_energy_floor_inconsistent",
        ),
        ("limits", "max_soc_percent", 101, "limits.capacity_soc_inconsistent"),
        (
            "feedback",
            "sustained_feedback_period_seconds",
            120,
            "feedback.observation_exceeds_duration",
        ),
        (
            "controllers",
            "goodwe_fast_export_excluded",
            1,
            "controllers.goodwe_fast_export_excluded_unconfirmed",
        ),
        (
            "recovery",
            "independent_route_verified",
            "yes",
            "recovery.independent_route_verified_unconfirmed",
        ),
        ("security", "disposition", {}, "security.credential_disposition_unresolved"),
        (
            "scope",
            "execution_authorized",
            True,
            "scope.execution_authorized_must_remain_false",
        ),
        (
            "scope",
            "real_transport_provisioned",
            True,
            "scope.real_transport_provisioned_must_remain_false",
        ),
    ],
)
def test_material_contradictions_are_reported(
    group: str, field: str, value: object, code: str
) -> None:
    record = synthetic_complete()
    record[group][field] = value
    assert code in review_readiness(record, at=T)["blockers"]


def test_unreviewed_human_route_cannot_replace_native_expiry() -> None:
    record = synthetic_complete()
    record["recovery"].update(
        native_expiry_verified=False, human_procedure_reviewed=None
    )
    assert "recovery.expiry_or_separately_reviewed_human_procedure_required" in (
        review_readiness(record, at=T)["blockers"]
    )


@pytest.mark.parametrize("change", ["unknown", "missing", "not_object"])
def test_schema_drift_is_not_silently_accepted(change: str) -> None:
    record = synthetic_complete()
    if change == "unknown":
        record["plan"]["extra"] = "not echoed"
    elif change == "missing":
        del record["plan"]["valid_until_utc"]
    else:
        record["plan"] = []
    assert "plan.fields_invalid" in review_readiness(record, at=T)["blockers"]


@pytest.mark.parametrize(
    "payload", ["template", "complete", "malformed", "duplicate", "oversized"]
)
def test_cli_is_bounded_read_only_and_does_not_echo_input(
    tmp_path: Path, payload: str
) -> None:
    source = tmp_path / "review.json"
    contents = {
        "template": json.dumps(template()),
        "complete": json.dumps(synthetic_complete()),
        "malformed": '{"private_marker": DO_NOT_ECHO_THIS}',
        "duplicate": '{"version": "DO_NOT_ECHO_THIS", "version": "other"}',
        "oversized": "DO_NOT_ECHO_THIS" * 1100,
    }[payload]
    source.write_text(contents, encoding="utf-8")
    before = source.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/review_controlled_test.py"),
            "--review",
            str(source),
            "--at",
            T.isoformat(),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == (
        0 if payload == "complete" else 1 if payload == "template" else 2
    )
    assert json.loads(result.stdout)["hardware_authorized"] is False
    assert "DO_NOT_ECHO_THIS" not in result.stdout + result.stderr
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize(
    "field", ["native_expiry_verified", "human_procedure_reviewed"]
)
@pytest.mark.parametrize("malformed", [[], {}, "true", 1, 0, 1.0])
def test_malformed_recovery_alternative_blocks_even_with_other_verified_route(
    field: str, malformed: object
) -> None:
    record = synthetic_complete()
    record["recovery"][field] = malformed
    original = deepcopy(record)
    report = review_readiness(record, at=T)
    assert report["status"] == "BLOCKED"
    assert f"recovery.{field}_invalid_type" in report["blockers"]
    assert report["hardware_authorized"] is False
    assert report["live_dispatch"] is False
    assert record == original


@pytest.mark.parametrize(
    "field", ["native_expiry_verified", "human_procedure_reviewed"]
)
@pytest.mark.parametrize("value", [None, False, True])
def test_valid_recovery_alternative_retains_its_value_without_granting_authority(
    field: str, value: bool | None
) -> None:
    record = synthetic_complete()
    record["recovery"][field] = value
    report = review_readiness(record, at=T)
    assert report["blockers"] == []
    assert report["status"] == "FIELDS_COMPLETE_REVIEW_ONLY"
    assert record["recovery"][field] is value
    assert report["hardware_authorized"] is False
    assert report["live_dispatch"] is False


@pytest.mark.parametrize(
    "at_text",
    ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"],
)
def test_extreme_offset_review_time_is_a_validation_error(at_text: str) -> None:
    with pytest.raises(ValueError, match="review_time_outside_utc_range"):
        review_readiness(template(), at=datetime.fromisoformat(at_text))


@pytest.mark.parametrize(
    "at_text",
    ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"],
)
def test_cli_extreme_offset_review_time_returns_structured_refusal(
    at_text: str,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/review_controlled_test.py"),
            "--review",
            str(ROOT / "docs/examples/controlled_test_readiness.json"),
            "--at",
            at_text,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "error": "offline_review_refused",
        "hardware_authorized": False,
    }
    assert result.stderr == ""


@pytest.mark.parametrize(
    "at_text,expected_utc",
    [
        ("2030-01-01T01:00:00+01:00", "2030-01-01T00:00:00+00:00"),
        ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00+00:00"),
        ("9999-12-31T23:59:59Z", "9999-12-31T23:59:59+00:00"),
    ],
)
def test_representable_review_times_still_normalize_to_utc(
    at_text: str, expected_utc: str
) -> None:
    report = review_readiness(template(), at=datetime.fromisoformat(at_text))
    assert report["review_at_utc"] == expected_utc
    assert report["status"] == "BLOCKED"
    assert report["hardware_authorized"] is False
