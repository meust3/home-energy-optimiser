import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from energy_optimizer.arbitrage.decision_types import canonical, digest
from energy_optimizer.arbitrage.executor import FakeTransport, Intent, Journal, Precheck
from energy_optimizer.arbitrage.supervised_pilot import (
    Envelope,
    Feedback,
    PilotState,
    SupervisedPilot,
    parse_feedback,
)

T = datetime(2030, 1, 1, tzinfo=UTC)


def proposal():
    return Intent(
        proposal_sha256=digest("synthetic commissioning proposal"),
        actor="synthetic-owner",
        action="CHARGE_BATTERY_FROM_GRID",
        device_identity="synthetic-device",
        input_sha256=digest("synthetic inputs"),
        owner="synthetic-owner",
        ownership_generation=1,
        approved_at=T,
        expires_at=T + timedelta(seconds=60),
        max_duration_seconds=60,
        max_power_ac_kw=0.3,
        max_energy_ac_kwh=0.0002,
        max_import_cost_aud=0.01,
        max_throughput_stored_kwh=0.0002,
        min_energy_stored_kwh=0.2,
        expected_feedback="fresh bounded battery and site flows",
        neutral_contract="synthetic native expiry and witnessed ordinary state",
        permitted_actions=("CHARGE_BATTERY_FROM_GRID",),
    )


def envelope():
    return Envelope(
        source_scope="synthetic firmware only",
        start_interface="synthetic grid charge",
        return_interface="synthetic ordinary state",
        ordinary_mode="ordinary",
        allowed_modes=("ordinary",),
        capacity_kwh=1.0,
        min_soc_percent=20,
        max_soc_percent=90,
        send_freshness_seconds=15,
        feedback_timeout_seconds=10,
        approval_max_age_seconds=20,
        independent_recovery="synthetic native expiry",
        approved_import_price_aud_per_kwh=0.1,
        site_import_limit_kw=0.5,
        site_export_limit_kw=0.05,
    )


def current(**changes):
    core = Precheck(
        at=T + timedelta(seconds=2),
        input_sha256=digest("synthetic inputs"),
        device_identity="synthetic-device",
        owner="synthetic-owner",
        ownership_generation=1,
        fresh=True,
        healthy=True,
        bms_healthy=True,
        clock_continuous=True,
        energy_stored_kwh=0.5,
        effective_power_ac_kw=0.3,
        effective_import_kw=0.3,
        effective_export_kw=0,
        import_price_aud_per_kwh=0.1,
        export_price_aud_per_kwh=0,
        expected_direction="charge",
        device_expiry_verified=True,
        neutral_verified=True,
    )
    return PilotState(
        **(
            dict(
                core=core,
                device_at=T + timedelta(seconds=1),
                received_at=T + timedelta(seconds=1),
                monotonic_seconds=2,
                source_scope="synthetic firmware only",
                mode="ordinary",
                grid_available=True,
                control_owners=("synthetic-owner",),
                capacity_kwh=1.0,
                soc_percent=50,
                net_site_import_kw=0.1,
                net_site_export_kw=0,
                network_available=True,
                ha_available=True,
                app_available=True,
                database_available=True,
            )
            | changes
        )
    )


def test_exact_approval_dispatches_once_with_existing_fake_executor(tmp_path):
    journal = Journal(tmp_path / "pilot.db")
    transport = FakeTransport()
    pilot = SupervisedPilot(journal, transport, fake_rehearsal=True)
    proposed = pilot.propose(proposal(), envelope(), at=T, monotonic_seconds=0)
    pilot.approve(
        proposed["intent_id"],
        binding=proposed["approval_binding"],
        operator="synthetic-owner",
        at=T,
        monotonic_seconds=0,
    )
    assert pilot.dispatch(proposed["intent_id"], current()) == "ACKNOWLEDGED"
    assert transport.calls == [proposed["intent_id"]]


def approved(tmp_path, *, lost_ack=False, changed_intent=None, changed_envelope=None):
    journal = Journal(tmp_path / "pilot.db")
    transport = FakeTransport(lost_ack=lost_ack)
    pilot = SupervisedPilot(journal, transport, fake_rehearsal=True)
    proposed = pilot.propose(
        changed_intent or proposal(),
        changed_envelope or envelope(),
        at=T,
        monotonic_seconds=0,
    )
    pilot.approve(
        proposed["intent_id"],
        binding=proposed["approval_binding"],
        operator="synthetic-owner",
        at=T,
        monotonic_seconds=0,
    )
    return pilot, journal, transport, proposed["intent_id"]


def feedback(**changes):
    return Feedback(
        **(
            dict(
                at=T + timedelta(seconds=3),
                device_at=T + timedelta(seconds=2),
                received_at=T + timedelta(seconds=2),
                monotonic_seconds=3,
                device_identity="synthetic-device",
                owner="synthetic-owner",
                ownership_generation=1,
                mode="ordinary",
                grid_available=True,
                direction="charge",
                battery_power_ac_kw=0.3,
                net_site_import_kw=0.4,
                net_site_export_kw=0,
                energy_ac_kwh=0.00005,
                throughput_stored_kwh=0.00005,
                energy_stored_kwh=0.50005,
                import_cost_aud=0.000005,
                effect_observed=True,
                ordinary_state_observed=False,
                bms_healthy=True,
                network_available=True,
                ha_available=True,
                app_available=True,
                database_available=True,
            )
            | changes
        )
    )


def test_hardware_path_cannot_be_enabled_by_accidental_transport(tmp_path):
    class PretendFake(FakeTransport):
        pass

    journal = Journal(tmp_path / "pilot.db")
    for transport in (object(), PretendFake()):
        with pytest.raises(ValueError, match="real_transport_not_supported"):
            SupervisedPilot(journal, transport, fake_rehearsal=True)
    pilot = SupervisedPilot(journal)
    proposed = pilot.propose(proposal(), envelope(), at=T, monotonic_seconds=0)
    pilot.approve(
        proposed["intent_id"],
        binding=proposed["approval_binding"],
        operator="synthetic-owner",
        at=T,
        monotonic_seconds=0,
    )
    with pytest.raises(PermissionError, match="hardware_execution_disabled"):
        pilot.dispatch(proposed["intent_id"], current())


@pytest.mark.parametrize(
    "change",
    [
        {"binding": digest("other")},
        {"operator": "other"},
        {"at": T + timedelta(seconds=21), "monotonic_seconds": 21},
        {"at": T + timedelta(seconds=61), "monotonic_seconds": 61},
        {"at": T - timedelta(seconds=1)},
    ],
)
def test_approval_requires_exact_original_operator_binding_and_time(tmp_path, change):
    pilot = SupervisedPilot(
        Journal(tmp_path / "pilot.db"), FakeTransport(), fake_rehearsal=True
    )
    record = pilot.propose(proposal(), envelope(), at=T, monotonic_seconds=0)
    kwargs = dict(
        binding=record["approval_binding"],
        operator="synthetic-owner",
        at=T,
        monotonic_seconds=0,
    )
    with pytest.raises(ValueError):
        pilot.approve(record["intent_id"], **(kwargs | change))
    assert pilot.status(record["intent_id"])["state"] == "PROPOSED"


def test_rejection_never_sends_and_original_approval_cannot_replay(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    pilot.reject(key, at=T)
    with pytest.raises(ValueError, match="not_proposed_or_replayed"):
        pilot.approve(
            key,
            binding=pilot.status(key)["approval_binding"],
            operator="synthetic-owner",
            at=T,
            monotonic_seconds=0,
        )
    with pytest.raises(ValueError, match="not_approved"):
        pilot.dispatch(key, current())
    assert transport.calls == []


def test_duplicate_request_does_not_send_twice(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    assert pilot.dispatch(key, current()) == "ACKNOWLEDGED"
    with pytest.raises(ValueError, match="already_dispatched"):
        pilot.dispatch(key, current())
    with pytest.raises(ValueError, match="duplicate_pilot_proposal"):
        pilot.propose(proposal(), envelope(), at=T, monotonic_seconds=0)
    assert transport.calls == [key]


def test_at_most_one_active_intent_even_after_uncertain_delivery(tmp_path):
    pilot, _, _, key = approved(tmp_path, lost_ack=True)
    assert pilot.dispatch(key, current()) == "UNKNOWN_DELIVERY"
    other = replace(proposal(), proposal_sha256=digest("different commissioning"))
    second = pilot.propose(
        other, envelope(), at=T + timedelta(seconds=2), monotonic_seconds=2
    )
    with pytest.raises(sqlite3.IntegrityError):
        pilot.approve(
            second["intent_id"],
            binding=second["approval_binding"],
            operator="synthetic-owner",
            at=T + timedelta(seconds=2),
            monotonic_seconds=2,
        )
    assert pilot.status(key)["state"] == "UNKNOWN_DELIVERY"


@pytest.mark.parametrize(
    "core_change,state_change",
    [
        ({"input_sha256": digest("changed tariff or inputs")}, {}),
        ({"import_price_aud_per_kwh": 10}, {}),
        ({"energy_stored_kwh": 0.8999}, {"soc_percent": 89.99}),
        ({"device_expiry_verified": False}, {}),
        ({"neutral_verified": False}, {}),
        ({"healthy": False}, {}),
        ({"bms_healthy": False}, {}),
        ({"device_identity": "other"}, {}),
        ({"owner": "other"}, {}),
        ({"ownership_generation": 2}, {}),
        ({"at": T + timedelta(seconds=21)}, {"monotonic_seconds": 21}),
        ({}, {"device_at": T - timedelta(seconds=16)}),
        ({}, {"received_at": T + timedelta(seconds=3)}),
        ({}, {"source_scope": "other firmware"}),
        ({}, {"mode": "other mode"}),
        ({}, {"grid_available": False}),
        ({}, {"control_owners": ("synthetic-owner", "other writer")}),
        ({}, {"capacity_kwh": 0.8}),
        ({}, {"soc_percent": 90.1}),
        ({}, {"monotonic_seconds": 20}),
        ({}, {"network_available": False}),
        ({}, {"ha_available": False}),
        ({}, {"app_available": False}),
        ({}, {"database_available": False}),
    ],
)
def test_send_time_faults_reject_without_a_command(tmp_path, core_change, state_change):
    pilot, _, transport, key = approved(tmp_path)
    state = current(**state_change)
    state = replace(state, core=replace(state.core, **core_change))
    assert pilot.dispatch(key, state) == "REJECTED"
    assert transport.calls == []


def test_human_recovery_description_does_not_certify_device_expiry(tmp_path):
    pilot, _, transport, key = approved(
        tmp_path,
        changed_envelope=replace(
            envelope(), independent_recovery="owner physically reachable"
        ),
    )
    state = current()
    assert (
        pilot.dispatch(
            key, replace(state, core=replace(state.core, device_expiry_verified=False))
        )
        == "REJECTED"
    )
    assert pilot.status(key)["human_recovery_is_device_expiry"] is False
    assert transport.calls == []


def test_lost_ack_never_retries_but_can_observe_partial_delivery(tmp_path):
    pilot, _, transport, key = approved(tmp_path, lost_ack=True)
    assert pilot.dispatch(key, current()) == "UNKNOWN_DELIVERY"
    with pytest.raises(ValueError):
        pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    assert transport.calls == [key]
    record = pilot.status(key)
    observed = record["evidence"][-1]["body"]
    assert observed["net_site_import_kw"] == 0.4
    assert observed["battery_power_ac_kw"] == 0.3


def test_partial_delivery_is_not_completion_and_return_requires_observation(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    assert (
        pilot.observe(
            key,
            feedback(
                at=T + timedelta(seconds=5),
                monotonic_seconds=5,
                device_at=T + timedelta(seconds=4),
                received_at=T + timedelta(seconds=4),
                energy_ac_kwh=0.0002,
                throughput_stored_kwh=0.0002,
            ),
        )
        == "RESTORE_FAILED"
    )
    assert pilot.status(key)["status_meaning"] == "RETURN_FAILED"
    assert (
        pilot.observe(
            key,
            feedback(
                at=T + timedelta(seconds=6),
                monotonic_seconds=6,
                device_at=T + timedelta(seconds=5),
                received_at=T + timedelta(seconds=5),
                energy_ac_kwh=0.0002,
                throughput_stored_kwh=0.0002,
                battery_power_ac_kw=0,
                ordinary_state_observed=True,
            ),
        )
        == "NEUTRAL_STATE_VERIFIED"
    )
    assert transport.calls == [key]  # No blind restore command, no retry.


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "discharge"},
        {"battery_power_ac_kw": 0.301},
        {"energy_ac_kwh": 0.006},
        {"throughput_stored_kwh": 0.006},
        {"energy_stored_kwh": 0.1},
        {"energy_stored_kwh": 0.901},
        {"import_cost_aud": 0.011},
        {"bms_healthy": False},
        {"grid_available": False},
        {"network_available": False},
        {"ha_available": False},
        {"app_available": False},
        {"database_available": False},
        {"mode": "unexpected forced mode"},
        {"net_site_import_kw": None},
        {"net_site_export_kw": 0.1},
        {"monotonic_seconds": 30},
        {"device_at": T - timedelta(seconds=20)},
        {
            "at": T + timedelta(seconds=13),
            "monotonic_seconds": 13,
            "device_at": T + timedelta(seconds=12),
            "received_at": T + timedelta(seconds=12),
        },
    ],
)
def test_feedback_faults_require_human_recovery_not_an_automatic_write(
    tmp_path, changes
):
    pilot, _, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback(**changes)) == "ABORTED"
    assert transport.calls == [key]


def test_newer_manual_state_wins_even_if_old_return_is_reported(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert (
        pilot.observe(
            key, feedback(ownership_generation=2, ordinary_state_observed=True)
        )
        == "ABORTED"
    )
    assert (
        pilot.observe(
            key,
            feedback(
                at=T + timedelta(seconds=4),
                monotonic_seconds=4,
                ordinary_state_observed=True,
            ),
        )
        == "ABORTED"
    )
    assert "manual_intervention" in pilot.status(key)["events"][-1]["reason"]
    assert transport.calls == [key]


def test_expiry_with_partial_delivery_needs_return_then_fresh_ordinary_state(tmp_path):
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    expired = feedback(
        at=T + timedelta(seconds=60),
        monotonic_seconds=60,
        device_at=T + timedelta(seconds=59),
        received_at=T + timedelta(seconds=59),
        energy_ac_kwh=0.0001,
        throughput_stored_kwh=0.0001,
    )
    assert pilot.observe(key, expired) == "RESTORE_FAILED"
    assert "EXPIRED" in [item["state"] for item in pilot.status(key)["events"]]
    assert (
        pilot.observe(
            key,
            replace(
                expired,
                at=T + timedelta(seconds=61),
                monotonic_seconds=61,
                ordinary_state_observed=True,
                battery_power_ac_kw=0,
                device_at=T + timedelta(seconds=60),
                received_at=T + timedelta(seconds=60),
            ),
        )
        == "NEUTRAL_STATE_VERIFIED"
    )


def test_restart_preserves_unknown_delivery_and_does_not_requeue(tmp_path):
    pilot, journal, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    journal.close()
    reopened = Journal(tmp_path / "pilot.db")
    resumed = SupervisedPilot(reopened, FakeTransport(), fake_rehearsal=True)
    assert resumed.status(key)["state"] == "ACKNOWLEDGED"
    with pytest.raises(ValueError, match="already_dispatched"):
        resumed.dispatch(key, current())
    assert resumed.observe(key, feedback()) == "EFFECT_OBSERVED"
    assert resumed.executor.transport.calls == []
    assert transport.calls == [key]


def test_restart_before_send_requires_new_intent(tmp_path):
    pilot, journal, transport, key = approved(tmp_path)
    resumed = SupervisedPilot(journal, transport, fake_rehearsal=True)
    assert resumed.dispatch(key, current()) == "REJECTED"
    assert transport.calls == []


def test_restart_in_sent_state_is_unknown_without_retry(tmp_path):
    pilot, journal, transport, key = approved(tmp_path)
    journal.connection.execute(
        "CREATE TRIGGER simulate_ack_database_outage BEFORE UPDATE ON intents "
        "WHEN NEW.state='ACKNOWLEDGED' BEGIN SELECT RAISE(ABORT,'fake outage'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        pilot.dispatch(key, current())
    resumed = SupervisedPilot(journal, transport, fake_rehearsal=True)
    assert resumed.observe(key, feedback(effect_observed=False)) == "UNKNOWN_DELIVERY"
    assert transport.calls == [key]


def test_closed_database_never_sends(tmp_path):
    pilot, journal, transport, key = approved(tmp_path)
    journal.close()
    with pytest.raises(sqlite3.ProgrammingError):
        pilot.dispatch(key, current())
    assert transport.calls == []


def test_export_and_economic_intents_are_not_implicitly_available(tmp_path):
    pilot = SupervisedPilot(
        Journal(tmp_path / "pilot.db"), FakeTransport(), fake_rehearsal=True
    )
    export = replace(
        proposal(), action="EXPORT_BATTERY_AC", permitted_actions=("EXPORT_BATTERY_AC",)
    )
    with pytest.raises(ValueError, match="export_disabled"):
        pilot.propose(export, envelope(), at=T, monotonic_seconds=0)


@pytest.mark.parametrize(
    "core_change",
    [
        {"device_expiry_verified": 1},
        {"neutral_verified": 1},
        {"effective_power_ac_kw": True},
        {"import_price_aud_per_kwh": float("nan")},
    ],
)
def test_malformed_safety_claims_cannot_authorise_dispatch(tmp_path, core_change):
    pilot, _, transport, key = approved(tmp_path)
    state = current()
    assert (
        pilot.dispatch(key, replace(state, core=replace(state.core, **core_change)))
        == "REJECTED"
    )
    assert transport.calls == []


def test_impossible_energy_feedback_does_not_count_as_physical_effect(tmp_path):
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback(energy_ac_kwh=0.00015)) == "ABORTED"


def test_post_approval_device_frame_must_advance_before_send(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    assert pilot.dispatch(key, current(device_at=T, received_at=T)) == "REJECTED"
    assert transport.calls == []


def test_repeated_cached_feedback_does_not_extend_frame_liveness(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    assert (
        pilot.observe(
            key,
            feedback(
                at=T + timedelta(seconds=4),
                monotonic_seconds=4,
                received_at=T + timedelta(seconds=4),
            ),
        )
        == "ABORTED"
    )
    assert transport.calls == [key]


@pytest.mark.parametrize(
    "field",
    [
        "battery_power_ac_kw",
        "energy_ac_kwh",
        "throughput_stored_kwh",
        "energy_stored_kwh",
        "import_cost_aud",
        "net_site_import_kw",
        "net_site_export_kw",
    ],
)
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -0.01])
def test_bad_feedback_numbers_never_count_as_effect(tmp_path, field, value):
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback(**{field: value})) == "ABORTED"


def test_feedback_site_import_limit_is_separate_from_battery_limit(tmp_path):
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback(net_site_import_kw=0.501)) == "ABORTED"


def test_ack_and_fresh_optimistic_state_without_physical_effect_times_out(tmp_path):
    pilot, _, transport, key = approved(tmp_path)
    assert pilot.dispatch(key, current()) == "ACKNOWLEDGED"
    assert (
        pilot.observe(
            key, feedback(effect_observed=False, ordinary_state_observed=True)
        )
        == "ACKNOWLEDGED"
    )
    between = feedback(
        at=T + timedelta(seconds=8),
        monotonic_seconds=8,
        device_at=T + timedelta(seconds=7),
        received_at=T + timedelta(seconds=7),
        effect_observed=False,
        ordinary_state_observed=True,
    )
    assert pilot.observe(key, between) == "ACKNOWLEDGED"
    late = feedback(
        at=T + timedelta(seconds=13),
        monotonic_seconds=13,
        device_at=T + timedelta(seconds=12),
        received_at=T + timedelta(seconds=12),
        effect_observed=False,
        ordinary_state_observed=True,
    )
    assert pilot.observe(key, late) == "ABORTED"
    assert "COMPLETED" not in [row["state"] for row in pilot.status(key)["events"]]
    assert transport.calls == [key]


def test_cli_propose_rehearse_feedback_status_and_rejection(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    from energy_optimizer.arbitrage.decision_types import canonical

    cli = Path(__file__).resolve().parents[1] / "tools/rehearse_supervised_pilot.py"
    journal = tmp_path / "operator.pilot.sqlite3"
    contract = tmp_path / "contract.json"
    contract.write_text(canonical({"intent": proposal(), "envelope": envelope()}))
    state_file = tmp_path / "state.json"
    state_file.write_text(canonical(current()))
    feedback_file = tmp_path / "feedback.json"
    feedback_file.write_text(canonical(feedback()))

    def command(*args):
        result = subprocess.run(
            [sys.executable, str(cli), "--journal", str(journal), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    record = command(
        "propose", "--fixture", str(contract), "--at", T.isoformat(), "--monotonic", "0"
    )
    key = record["intent_id"]
    assert record["proposal"]["purpose"] == "commissioning"
    result = command(
        "rehearse",
        "--key",
        key,
        "--binding",
        record["approval_binding"],
        "--operator",
        "synthetic-owner",
        "--at",
        T.isoformat(),
        "--monotonic",
        "0",
        "--state-fixture",
        str(state_file),
    )
    assert result["state"] == "ACKNOWLEDGED"
    assert result["live_dispatch"] is False
    assert (
        command("record-feedback", "--key", key, "--fixture", str(feedback_file))[
            "state"
        ]
        == "EFFECT_OBSERVED"
    )
    assert command("status", "--key", key)["state"] == "EFFECT_OBSERVED"
    other = tmp_path / "other.json"
    other.write_text(
        canonical(
            {
                "intent": replace(proposal(), proposal_sha256=digest("other proposal")),
                "envelope": envelope(),
            }
        )
    )
    second = command(
        "propose", "--fixture", str(other), "--at", T.isoformat(), "--monotonic", "0"
    )
    assert (
        command("reject", "--key", second["intent_id"], "--at", T.isoformat())["state"]
        == "REJECTED"
    )


def test_cli_refuses_unowned_existing_database_without_modifying_it(tmp_path):
    from energy_optimizer.arbitrage.supervised_pilot import open_rehearsal_journal

    database = tmp_path / "not-owned.pilot.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE untouched(data TEXT)")
    before = database.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        open_rehearsal_journal(database)
    assert database.read_bytes() == before


def test_payload_resource_bounds_are_explicit_and_do_not_silently_drop_evidence(
    tmp_path,
):
    from energy_optimizer.arbitrage.supervised_pilot import read_rehearsal_json

    oversized = tmp_path / "oversized.json"
    oversized.write_text("x" * 16385)
    with pytest.raises(ValueError, match="too_large"):
        read_rehearsal_json(oversized)
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert len(str(pilot.status(key)).encode()) < 16384


def test_missing_delivery_evidence_remains_unknown_without_zero_substitution(tmp_path):
    pilot, _, _, key = approved(tmp_path, lost_ack=True)
    pilot.dispatch(key, current())
    assert (
        pilot.observe(
            key,
            feedback(
                energy_ac_kwh=None, throughput_stored_kwh=None, effect_observed=False
            ),
        )
        == "UNKNOWN_DELIVERY"
    )
    observed = pilot.status(key)["evidence"][-1]["body"]
    assert observed["energy_ac_kwh"] is None
    assert observed["throughput_stored_kwh"] is None


def test_preservation_has_separate_commissioning_identity_and_witnessed_return(
    tmp_path,
):
    intent = replace(
        proposal(),
        action="PRESERVE_BATTERY",
        permitted_actions=("PRESERVE_BATTERY",),
        max_power_ac_kw=0,
    )
    pilot, _, _, key = approved(tmp_path, changed_intent=intent)
    state = current()
    assert (
        pilot.dispatch(
            key, replace(state, core=replace(state.core, expected_direction="inhibit"))
        )
        == "ACKNOWLEDGED"
    )
    preserved = feedback(
        direction="inhibit",
        battery_power_ac_kw=0,
        energy_ac_kwh=0,
        throughput_stored_kwh=0,
        energy_stored_kwh=0.5,
        import_cost_aud=0,
    )
    assert pilot.observe(key, preserved) == "EFFECT_OBSERVED"
    at_expiry = replace(
        preserved,
        at=T + timedelta(seconds=60),
        monotonic_seconds=60,
        device_at=T + timedelta(seconds=59),
        received_at=T + timedelta(seconds=59),
        ordinary_state_observed=True,
    )
    assert pilot.observe(key, at_expiry) == "NEUTRAL_STATE_VERIFIED"
    assert pilot.status(key)["purpose"] == "commissioning"


def test_claimed_charge_effect_with_zero_delivery_remains_acknowledged(tmp_path):
    pilot, _, _, key = approved(tmp_path)
    pilot.dispatch(key, current())
    zero = feedback(
        battery_power_ac_kw=0,
        energy_ac_kwh=0,
        throughput_stored_kwh=0,
        energy_stored_kwh=0.5,
        import_cost_aud=0,
    )
    assert pilot.observe(key, zero) == "ACKNOWLEDGED"


def test_offset_input_is_normalised_before_approval_identity_is_computed():
    import json

    from energy_optimizer.arbitrage.decision_types import canonical
    from energy_optimizer.arbitrage.supervised_pilot import (
        parse_contract,
        parse_feedback,
        parse_state,
    )

    offset = timezone(timedelta(hours=10))
    utc_contract = {"intent": proposal(), "envelope": envelope()}
    local_intent = replace(
        proposal(),
        approved_at=T.astimezone(offset),
        expires_at=proposal().expires_at.astimezone(offset),
    )
    parsed, _ = parse_contract(
        json.loads(canonical({"intent": local_intent, "envelope": envelope()}))
    )
    expected, _ = parse_contract(json.loads(canonical(utc_contract)))
    assert parsed.id == expected.id
    state = current()
    local_state = replace(
        state,
        core=replace(state.core, at=state.core.at.astimezone(offset)),
        device_at=state.device_at.astimezone(offset),
        received_at=state.received_at.astimezone(offset),
    )
    assert parse_state(json.loads(canonical(local_state))) == state
    observed = feedback()
    local_feedback = replace(
        observed,
        at=observed.at.astimezone(offset),
        device_at=observed.device_at.astimezone(offset),
        received_at=observed.received_at.astimezone(offset),
    )
    assert parse_feedback(json.loads(canonical(local_feedback))) == observed


def test_direct_non_utc_intent_fails_closed_before_journal_proposal(tmp_path):
    offset = timezone(timedelta(hours=10))
    intent = replace(
        proposal(),
        approved_at=T.astimezone(offset),
        expires_at=proposal().expires_at.astimezone(offset),
    )
    journal = Journal(tmp_path / "utc-check.db")
    pilot = SupervisedPilot(journal)
    with pytest.raises(ValueError, match="proposal_clock"):
        pilot.propose(intent, envelope(), at=T, monotonic_seconds=0)
    assert journal.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    journal.close()


@pytest.mark.parametrize(
    "field,lower",
    [
        ("energy_ac_kwh", 0.00004),
        ("throughput_stored_kwh", 0.00004),
        ("import_cost_aud", 0.000004),
    ],
)
@pytest.mark.parametrize("restart", [False, True])
def test_missing_sample_cannot_erase_known_cumulative_delivery(
    tmp_path: Path, field: str, lower: float, restart: bool
) -> None:
    pilot, journal, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    missing = feedback(
        at=T + timedelta(seconds=4),
        monotonic_seconds=4,
        device_at=T + timedelta(seconds=3),
        received_at=T + timedelta(seconds=3),
        effect_observed=False,
        **{field: None},
    )
    assert pilot.observe(key, missing) == "EFFECT_OBSERVED"
    assert pilot.status(key)["evidence"][-1]["body"][field] is None
    if restart:
        journal.close()
        journal = Journal(tmp_path / "pilot.db")
        pilot = SupervisedPilot(journal, FakeTransport(), fake_rehearsal=True)
    regressed = replace(
        missing,
        at=T + timedelta(seconds=5),
        monotonic_seconds=5,
        device_at=T + timedelta(seconds=4),
        received_at=T + timedelta(seconds=4),
        **{field: lower},
    )
    assert pilot.observe(key, regressed) == "ABORTED"
    assert pilot.status(key)["events"][-1]["reason"] == "cumulative_feedback_regressed"
    assert transport.calls == [key]
    if restart:
        assert pilot.executor.transport.calls == []
    journal.close()


def test_failed_return_restart_and_stale_witness_never_release_ownership(
    tmp_path: Path,
) -> None:
    pilot, journal, transport, key = approved(tmp_path)
    pilot.dispatch(key, current())
    assert pilot.observe(key, feedback()) == "EFFECT_OBSERVED"
    failed = feedback(
        at=T + timedelta(seconds=5),
        monotonic_seconds=5,
        device_at=T + timedelta(seconds=4),
        received_at=T + timedelta(seconds=4),
        energy_ac_kwh=0.0002,
        throughput_stored_kwh=0.0002,
    )
    assert pilot.observe(key, failed) == "RESTORE_FAILED"
    journal.close()
    reopened = Journal(tmp_path / "pilot.db")
    resumed_transport = FakeTransport()
    resumed = SupervisedPilot(reopened, resumed_transport, fake_rehearsal=True)
    assert resumed.status(key)["status_meaning"] == "RETURN_FAILED"
    with pytest.raises(ValueError, match="already_dispatched"):
        resumed.dispatch(key, current())
    stale_return = replace(
        failed,
        at=T + timedelta(seconds=6),
        monotonic_seconds=6,
        ordinary_state_observed=True,
        battery_power_ac_kw=0,
    )
    assert resumed.observe(key, stale_return) == "ABORTED"
    assert (
        resumed.observe(
            key,
            replace(
                stale_return,
                at=T + timedelta(seconds=7),
                monotonic_seconds=7,
                device_at=T + timedelta(seconds=6),
                received_at=T + timedelta(seconds=6),
            ),
        )
        == "ABORTED"
    )
    assert reopened.connection.execute(
        "SELECT active FROM intents WHERE id=?", (key,)
    ).fetchone() == (1,)
    assert transport.calls == [key]
    assert resumed_transport.calls == []
    reopened.close()


@pytest.mark.parametrize(
    "field",
    ["network_available", "ha_available", "app_available", "database_available"],
)
def test_feedback_requires_explicit_service_health(field: str) -> None:
    import json

    body = json.loads(canonical(feedback()))
    body.pop(field)
    with pytest.raises(TypeError, match=field):
        parse_feedback(body)


@pytest.mark.parametrize("cost", [None, 0.011])
@pytest.mark.parametrize("at_expiry", [False, True])
def test_preservation_unknown_or_exceeded_cost_cannot_verify_effect_or_return(
    tmp_path: Path, cost: float | None, at_expiry: bool
) -> None:
    intent = replace(
        proposal(),
        action="PRESERVE_BATTERY",
        permitted_actions=("PRESERVE_BATTERY",),
        max_power_ac_kw=0,
    )
    pilot, journal, transport, key = approved(tmp_path, changed_intent=intent)
    state = current()
    pilot.dispatch(
        key, replace(state, core=replace(state.core, expected_direction="inhibit"))
    )
    seconds = 60 if at_expiry else 3
    observed = feedback(
        at=T + timedelta(seconds=seconds),
        monotonic_seconds=seconds,
        device_at=T + timedelta(seconds=seconds - 1),
        received_at=T + timedelta(seconds=seconds - 1),
        direction="inhibit",
        battery_power_ac_kw=0,
        energy_ac_kwh=0,
        throughput_stored_kwh=0,
        energy_stored_kwh=0.5,
        import_cost_aud=cost,
        ordinary_state_observed=at_expiry,
    )
    assert pilot.observe(key, observed) == "ABORTED"
    assert transport.calls == [key]
    assert journal.connection.execute(
        "SELECT active FROM intents WHERE id=?", (key,)
    ).fetchone() == (1,)
    journal.close()


@pytest.mark.parametrize("cost", [0, 0.01])
@pytest.mark.parametrize("at_expiry", [False, True])
def test_preservation_within_cost_cap_keeps_witnessed_lifecycle(
    tmp_path: Path, cost: float, at_expiry: bool
) -> None:
    intent = replace(
        proposal(),
        action="PRESERVE_BATTERY",
        permitted_actions=("PRESERVE_BATTERY",),
        max_power_ac_kw=0,
    )
    pilot, journal, transport, key = approved(tmp_path, changed_intent=intent)
    state = current()
    pilot.dispatch(
        key, replace(state, core=replace(state.core, expected_direction="inhibit"))
    )
    seconds = 60 if at_expiry else 3
    result = pilot.observe(
        key,
        feedback(
            at=T + timedelta(seconds=seconds),
            monotonic_seconds=seconds,
            device_at=T + timedelta(seconds=seconds - 1),
            received_at=T + timedelta(seconds=seconds - 1),
            direction="inhibit",
            battery_power_ac_kw=0,
            energy_ac_kwh=0,
            throughput_stored_kwh=0,
            energy_stored_kwh=0.5,
            import_cost_aud=cost,
            ordinary_state_observed=at_expiry,
        ),
    )
    assert result == ("NEUTRAL_STATE_VERIFIED" if at_expiry else "EFFECT_OBSERVED")
    assert transport.calls == [key]
    journal.close()
