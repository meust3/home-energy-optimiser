"""Offline field review for a proposed manual preservation test.

No settings, credentials, journal, transport, network or executor dependency.
Claims in an input record are not independently verified by this checker.
"""

import math
from datetime import UTC, datetime

VERSION = "controlled-test-readiness-v1"
RELEASE_COMMIT = "72a446cf28abb89217d76030004d6829b1c3007e"
LIMITS = (
    "capacity_kwh",
    "min_soc_percent",
    "max_soc_percent",
    "min_stored_energy_kwh",
    "max_battery_power_kw",
    "max_energy_ac_kwh",
    "max_throughput_stored_kwh",
    "max_site_import_kw",
    "max_site_export_kw",
    "max_gross_import_cost_aud",
)
FIELDS = {
    "baseline": (
        "version",
        "release_commit",
        "schema_revision",
        "cutover_evidence",
        "installed_bytes_independently_verified",
        "approved_attestation_amendment",
    ),
    "plan": (
        "equipment",
        "operator",
        "manual_supervision_confirmed",
        "start_mode",
        "return_mode",
        "operation_mode",
        "max_duration_seconds",
        "valid_from_utc",
        "valid_until_utc",
        "owner_generation",
    ),
    "limits": LIMITS,
    "interface": (
        "device_identity",
        "firmware",
        "source_semantics_evidence",
        "delivery_retry_evidence",
        "ordinary_state_evidence",
        "backup_conditions_evidence",
    ),
    "feedback": (
        "send_freshness_seconds",
        "initial_effect_timeout_seconds",
        "sustained_feedback_period_seconds",
        "battery_discharge_deadband_w",
        "advancing_post_approval_frames_verified",
        "discharge_baseline_verified",
        "limits_supported_by_site_evidence",
        "grid_bms_communications_healthy",
        "stop_and_return_criteria_reviewed",
    ),
    "controllers": (
        "exclusive_window_verified",
        "goodwe_fast_export_excluded",
        "manufacturer_schedules_excluded",
        "cloud_vpp_excluded",
        "other_writers_excluded",
    ),
    "recovery": (
        "independent_route_verified",
        "physical_return_verified",
        "native_expiry_verified",
        "human_procedure_reviewed",
        "reachable_operator_confirmed",
        "newer_owner_wins_confirmed",
        "no_retry_after_ambiguity_confirmed",
        "failed_return_requires_reconciliation",
    ),
    "security": (
        "disposition",
        "service_identity_confirmed",
        "consumers_reviewed",
        "remediation_or_expiry_evidence",
    ),
    "scope": ("execution_authorized", "real_transport_provisioned"),
}


def _number(value: object) -> bool:
    if type(value) not in (int, float) or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at if at.tzinfo is not None and at.utcoffset() == UTC.utcoffset(at) else None


def review_readiness(record: dict, *, at: datetime) -> dict:
    """Return omissions/contradictions only; never grant execution authority.

    `at` is explicit so an archived record is not treated as current by default.
    Field completeness is not device certification or an execution precheck.
    """
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware_review_time_required")
    try:
        at = at.astimezone(UTC)
    except OverflowError as error:
        raise ValueError("review_time_outside_utc_range") from error
    blockers: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            blockers.append(code)

    def result() -> dict:
        return {
            "version": VERSION,
            "review_at_utc": at.isoformat(),
            "status": "BLOCKED" if blockers else "FIELDS_COMPLETE_REVIEW_ONLY",
            "blockers": blockers,
            "live_dispatch": False,
            "hardware_authorized": False,
            "independently_verified_by_checker": False,
            "limitations": [
                "input_claims_only_no_physical_or_runtime_verification",
                "human_procedure_does_not_enable_fake_adapter_or_prove_native_expiry",
                "separate_exact_execution_approval_required",
            ],
        }

    require(type(record) is dict, "record_object_required")
    if type(record) is not dict:
        return result()
    require(set(record) == {"version", *FIELDS}, "record_fields_invalid")
    require(record.get("version") == VERSION, "record_version_invalid")
    for group, names in FIELDS.items():
        body = record.get(group)
        require(
            type(body) is dict and set(body) == set(names), f"{group}.fields_invalid"
        )
    if blockers:
        return result()

    baseline, plan = record["baseline"], record["plan"]
    require(
        baseline["version"] == "0.8.4"
        and baseline["release_commit"] == RELEASE_COMMIT
        and baseline["schema_revision"] == "20261008_01"
        and _text(baseline["cutover_evidence"]),
        "baseline.accepted_v084_evidence_required",
    )
    attested = baseline["installed_bytes_independently_verified"]
    amendment = baseline["approved_attestation_amendment"]
    require(
        type(attested) is bool
        and type(amendment) is bool
        and (attested is True or amendment is True),
        "baseline.attestation_or_approved_amendment_required",
    )
    if attested is not True:
        # The approved amendment is a limitation, not a new claim of attestation.
        report_limitation = "installed_bytes_not_independently_verified"
    else:
        report_limitation = "installed_attestation_is_an_input_claim_only"
    for field in ("equipment", "operator"):
        require(_text(plan[field]), f"plan.{field}_required")
    require(
        plan["manual_supervision_confirmed"] is True, "plan.supervision_unconfirmed"
    )
    require(
        (plan["start_mode"], plan["return_mode"], plan["operation_mode"])
        == ("conserve", "auto", "general"),
        "plan.preservation_only_modes_required",
    )
    duration = plan["max_duration_seconds"]
    require(type(duration) is int and 0 < duration <= 120, "plan.duration_invalid")
    generation = plan["owner_generation"]
    require(
        type(generation) is int and generation >= 0, "plan.owner_generation_required"
    )
    start, end = _time(plan["valid_from_utc"]), _time(plan["valid_until_utc"])
    window_valid = start is not None and end is not None and start <= at < end
    require(window_valid, "plan.finite_current_utc_window_required")
    if window_valid and type(duration) is int:
        require(
            (end - at).total_seconds() >= duration, "plan.insufficient_window_remaining"
        )

    limits = record["limits"]
    for field in FIELDS["interface"]:
        require(_text(record["interface"][field]), f"interface.{field}_required")
    for field in LIMITS:
        require(_number(limits[field]), f"limits.{field}_required")
    if all(_number(limits[field]) for field in LIMITS):
        capacity = limits["capacity_kwh"]
        low, high = limits["min_soc_percent"], limits["max_soc_percent"]
        require(
            capacity > 0 and 0 <= low < high <= 100, "limits.capacity_soc_inconsistent"
        )
        require(
            capacity * low / 100
            <= limits["min_stored_energy_kwh"]
            <= capacity * high / 100,
            "limits.stored_energy_floor_inconsistent",
        )
    feedback = record["feedback"]
    for field in (
        "send_freshness_seconds",
        "initial_effect_timeout_seconds",
        "sustained_feedback_period_seconds",
        "battery_discharge_deadband_w",
    ):
        require(_number(feedback[field]), f"feedback.{field}_required")
        if field != "battery_discharge_deadband_w" and _number(feedback[field]):
            require(feedback[field] > 0, f"feedback.{field}_must_be_positive")
            if type(duration) is int:
                require(
                    feedback[field] <= duration, f"feedback.{field}_exceeds_duration"
                )
    for field in (
        "advancing_post_approval_frames_verified",
        "discharge_baseline_verified",
        "limits_supported_by_site_evidence",
        "grid_bms_communications_healthy",
        "stop_and_return_criteria_reviewed",
    ):
        require(feedback[field] is True, f"feedback.{field}_unconfirmed")
    initial = feedback["initial_effect_timeout_seconds"]
    sustained = feedback["sustained_feedback_period_seconds"]
    if _number(initial) and _number(sustained) and type(duration) is int:
        require(
            initial + sustained <= duration, "feedback.observation_exceeds_duration"
        )
    for field in FIELDS["controllers"]:
        require(
            record["controllers"][field] is True, f"controllers.{field}_unconfirmed"
        )
    recovery = record["recovery"]
    for field in FIELDS["recovery"]:
        if field in {"native_expiry_verified", "human_procedure_reviewed"}:
            require(
                recovery[field] is None or type(recovery[field]) is bool,
                f"recovery.{field}_invalid_type",
            )
        else:
            require(recovery[field] is True, f"recovery.{field}_unconfirmed")
    require(
        recovery["native_expiry_verified"] is True
        or recovery["human_procedure_reviewed"] is True,
        "recovery.expiry_or_separately_reviewed_human_procedure_required",
    )
    security = record["security"]
    require(
        isinstance(security["disposition"], str)
        and security["disposition"]
        in {
            "REMEDIATION_CONFIRMED",
            "EXPIRED_REVOKED_NOT_REUSED_CONFIRMED",
        },
        "security.credential_disposition_unresolved",
    )
    for field in ("service_identity_confirmed", "consumers_reviewed"):
        require(security[field] is True, f"security.{field}_unconfirmed")
    require(
        _text(security["remediation_or_expiry_evidence"]), "security.evidence_required"
    )
    for field in FIELDS["scope"]:
        require(record["scope"][field] is False, f"scope.{field}_must_remain_false")
    report = result()
    report["limitations"].append(report_limitation)
    return report
