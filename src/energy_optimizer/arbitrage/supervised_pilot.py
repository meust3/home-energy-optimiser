"""Finite commissioning rehearsals over the existing fake-only executor.

No live transport, polling, scheduler, settings, economic selector or HA client.
All limits are explicit proposal inputs, never installation defaults.
"""

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from energy_optimizer.arbitrage.decision_types import canonical, digest
from energy_optimizer.arbitrage.executor import (
    DisabledExecutor,
    FakeTransport,
    Intent,
    Journal,
    Precheck,
)

VERSION = "supervised-commissioning-fake-v1"
ACTIONS = {"PRESERVE_BATTERY", "CHARGE_BATTERY_FROM_GRID"}
MAX_RECORD_BYTES = 16384
MAX_EVENTS_PER_INTENT = 256


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _aware(at: object) -> bool:
    return (
        isinstance(at, datetime)
        and at.tzinfo is not None
        and at.utcoffset() is not None
        and at.utcoffset().total_seconds() == 0
    )


@dataclass(frozen=True)
class Envelope:
    source_scope: str
    start_interface: str
    return_interface: str
    ordinary_mode: str
    allowed_modes: tuple[str, ...]
    capacity_kwh: float
    min_soc_percent: float
    max_soc_percent: float
    send_freshness_seconds: float
    feedback_timeout_seconds: float
    approval_max_age_seconds: float
    independent_recovery: str
    approved_import_price_aud_per_kwh: float
    site_import_limit_kw: float
    site_export_limit_kw: float

    def __post_init__(self) -> None:
        strings = (
            self.source_scope,
            self.start_interface,
            self.return_interface,
            self.ordinary_mode,
            self.independent_recovery,
            *self.allowed_modes,
        )
        if not self.allowed_modes or any(
            not isinstance(s, str) or not s or len(s) > 256 for s in strings
        ):
            raise ValueError("incomplete_pilot_interface_contract")
        if not all(
            _finite(v)
            for v in (
                self.capacity_kwh,
                self.min_soc_percent,
                self.max_soc_percent,
                self.send_freshness_seconds,
                self.feedback_timeout_seconds,
                self.approval_max_age_seconds,
                self.approved_import_price_aud_per_kwh,
                self.site_import_limit_kw,
                self.site_export_limit_kw,
            )
        ):
            raise ValueError("invalid_pilot_numeric_bound")
        if not (
            self.capacity_kwh > 0
            and 0 <= self.min_soc_percent < self.max_soc_percent <= 100
            and 0 < self.send_freshness_seconds <= 60
            and 0 < self.feedback_timeout_seconds <= 60
            and 0 < self.approval_max_age_seconds <= 60
            and self.site_import_limit_kw >= 0
            and self.site_export_limit_kw >= 0
        ):
            raise ValueError("invalid_pilot_bound")


@dataclass(frozen=True)
class PilotState:
    core: Precheck
    device_at: datetime
    received_at: datetime
    monotonic_seconds: float
    source_scope: str
    mode: str
    grid_available: bool
    control_owners: tuple[str, ...]
    capacity_kwh: float
    soc_percent: float
    net_site_import_kw: float
    net_site_export_kw: float
    network_available: bool
    ha_available: bool
    app_available: bool
    database_available: bool


@dataclass(frozen=True)
class Feedback:
    at: datetime
    device_at: datetime
    received_at: datetime
    monotonic_seconds: float
    device_identity: str
    owner: str
    ownership_generation: int
    mode: str
    grid_available: bool
    direction: str
    battery_power_ac_kw: float | None
    net_site_import_kw: float | None
    net_site_export_kw: float | None
    energy_ac_kwh: float | None
    throughput_stored_kwh: float | None
    energy_stored_kwh: float | None
    import_cost_aud: float | None
    effect_observed: bool
    ordinary_state_observed: bool
    bms_healthy: bool
    network_available: bool = True
    ha_available: bool = True
    app_available: bool = True
    database_available: bool = True


class SupervisedPilot:
    """Operator seam; live dispatch remains structurally unavailable.

    Extra evidence shares the owned Journal connection. This is a bounded local
    rehearsal artifact, not a migration or an additional controller.
    """

    def __init__(
        self,
        journal: Journal,
        transport: FakeTransport | None = None,
        *,
        fake_rehearsal: bool = False,
    ) -> None:
        if type(journal) is not Journal:
            raise ValueError("owned_journal_required")
        if transport is not None and type(transport) is not FakeTransport:
            raise ValueError("real_transport_not_supported")
        self.journal = journal
        self.executor = DisabledExecutor(
            journal, transport, fake_rehearsal=fake_rehearsal
        )
        self.session = uuid4().hex
        journal.connection.execute(
            "CREATE INDEX IF NOT EXISTS pilot_events_intent ON events(intent_id,id)"
        )
        journal.connection.execute(
            "CREATE TABLE IF NOT EXISTS pilot_contracts("
            "intent_id TEXT PRIMARY KEY REFERENCES intents(id), envelope TEXT NOT NULL,"
            "binding TEXT UNIQUE NOT NULL, session TEXT NOT NULL,"
            "last_at TEXT NOT NULL,last_mono REAL NOT NULL)"
        )
        journal.connection.execute(
            "CREATE TABLE IF NOT EXISTS pilot_approvals("
            "intent_id TEXT PRIMARY KEY REFERENCES intents(id), "
            "binding TEXT UNIQUE NOT NULL,"
            "operator TEXT NOT NULL,at TEXT NOT NULL)"
        )
        journal.connection.execute(
            "CREATE TABLE IF NOT EXISTS pilot_evidence("
            "id INTEGER PRIMARY KEY,intent_id TEXT REFERENCES intents(id),"
            "kind TEXT NOT NULL,body TEXT NOT NULL)"
        )

        journal.connection.execute(
            "CREATE INDEX IF NOT EXISTS pilot_evidence_intent "
            "ON pilot_evidence(intent_id,kind,id)"
        )

    def _record(self, key: str, kind: str, body: dict) -> None:
        text = canonical(body)
        if len(text.encode()) > MAX_RECORD_BYTES:
            raise ValueError("pilot_record_too_large")
        count = self.journal.connection.execute(
            "SELECT COUNT(*) FROM pilot_evidence WHERE intent_id=?", (key,)
        ).fetchone()[0]
        if count >= MAX_EVENTS_PER_INTENT:
            raise ValueError("pilot_evidence_bound_reached_human_recovery")
        self.journal.connection.execute(
            "INSERT INTO pilot_evidence(intent_id,kind,body) VALUES (?,?,?)",
            (key, kind, text),
        )

    def _load(self, key: str) -> tuple[Intent, Envelope, tuple]:
        row = self.journal.connection.execute(
            "SELECT i.body,p.envelope,p.binding,p.session,p.last_at,p.last_mono "
            "FROM intents i JOIN pilot_contracts p ON p.intent_id=i.id WHERE i.id=?",
            (key,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown_pilot_intent")
        body = json.loads(row[0])
        for name in ("approved_at", "expires_at"):
            body[name] = datetime.fromisoformat(body[name])
        body["permitted_actions"] = tuple(body["permitted_actions"])
        intent = Intent(**body)
        envelope = json.loads(row[1])
        envelope["allowed_modes"] = tuple(envelope["allowed_modes"])
        envelope = Envelope(**envelope)
        if (
            intent.id != key
            or digest({"intent": intent, "envelope": envelope, "version": VERSION})
            != row[2]
        ):
            raise ValueError("pilot_contract_identity_mismatch")
        return intent, envelope, row

    def _clock(self, key: str, at: datetime, mono: float) -> bool:
        _, _, row = self._load(key)
        if not _aware(at) or not _finite(mono):
            return False
        wall_delta = (at - datetime.fromisoformat(row[4])).total_seconds()
        mono_delta = mono - row[5]
        if wall_delta < 0 or mono_delta < 0 or abs(wall_delta - mono_delta) > 2:
            return False
        self.journal.connection.execute(
            "UPDATE pilot_contracts SET last_at=?,last_mono=? WHERE intent_id=?",
            (at.isoformat(), mono, key),
        )
        return True

    def propose(
        self,
        intent: Intent,
        envelope: Envelope,
        *,
        at: datetime,
        monotonic_seconds: float,
    ) -> dict:
        if type(intent) is not Intent or type(envelope) is not Envelope:
            raise ValueError("exact_pilot_contract_types_required")
        if (
            type(intent.max_duration_seconds) is not int
            or type(intent.ownership_generation) is not int
            or intent.ownership_generation < 0
            or any(
                not _finite(v)
                for v in (
                    intent.max_power_ac_kw,
                    intent.max_energy_ac_kwh,
                    intent.max_import_cost_aud,
                    intent.max_throughput_stored_kwh,
                    intent.min_energy_stored_kwh,
                )
            )
        ):
            raise ValueError("invalid_explicit_intent_bounds")
        if intent.permitted_actions != (intent.action,):
            raise ValueError("one_explicit_commissioning_action_required")
        if intent.action not in ACTIONS:
            raise ValueError("action_not_prepared_export_disabled")
        if (
            not all(_aware(t) for t in (at, intent.approved_at, intent.expires_at))
            or not _finite(monotonic_seconds)
            or at >= intent.expires_at
        ):
            raise ValueError("invalid_proposal_clock_or_expiry")
        if (
            intent.min_energy_stored_kwh
            < envelope.capacity_kwh * envelope.min_soc_percent / 100
        ):
            raise ValueError("pilot_floor_below_explicit_soc_bound")
        if intent.max_throughput_stored_kwh < intent.max_energy_ac_kwh:
            raise ValueError("charge_throughput_bound_not_conservative")
        if any(
            len(s) > 256
            for s in (
                intent.actor,
                intent.owner,
                intent.device_identity,
                intent.expected_feedback,
                intent.neutral_contract,
            )
        ):
            raise ValueError("pilot_identifier_too_long")
        binding = digest({"intent": intent, "envelope": envelope, "version": VERSION})
        if self.journal.connection.execute(
            "SELECT 1 FROM pilot_contracts WHERE intent_id=?", (intent.id,)
        ).fetchone():
            raise ValueError("duplicate_pilot_proposal")
        self.journal.propose(intent)
        self.journal.connection.execute(
            "INSERT INTO pilot_contracts VALUES (?,?,?,?,?,?)",
            (
                intent.id,
                canonical(envelope),
                binding,
                self.session,
                at.isoformat(),
                monotonic_seconds,
            ),
        )
        self._record(
            intent.id,
            "PROPOSED",
            {"at": at, "purpose": "commissioning", "binding": binding},
        )
        return {
            "intent_id": intent.id,
            "approval_binding": binding,
            "live_dispatch": False,
        }

    def approve(
        self,
        key: str,
        *,
        binding: str,
        operator: str,
        at: datetime,
        monotonic_seconds: float,
    ) -> str:
        intent, envelope, row = self._load(key)
        if self.journal.state(key) != "PROPOSED":
            raise ValueError("not_proposed_or_replayed_approval")
        if binding != row[2] or operator != intent.actor:
            raise ValueError("original_approval_binding_required")
        if not self._clock(key, at, monotonic_seconds) or not (
            intent.approved_at <= at < intent.expires_at
            and (at - intent.approved_at).total_seconds()
            <= envelope.approval_max_age_seconds
        ):
            raise ValueError("stale_approval_or_clock_fault")
        self.journal.connection.execute(
            "INSERT INTO pilot_approvals VALUES (?,?,?,?)",
            (key, binding, operator, at.isoformat()),
        )
        self.journal.connection.execute(
            "UPDATE pilot_contracts SET session=? WHERE intent_id=?",
            (self.session, key),
        )
        self.journal.transition(
            key, "APPROVED", at=at, reason="exact_commissioning_approval_fake_only"
        )
        self._record(
            key, "APPROVED", {"at": at, "operator": operator, "binding": binding}
        )
        return "APPROVED"

    def reject(self, key: str, *, at: datetime) -> str:
        self._load(key)
        if not _aware(at):
            raise ValueError("aware_rejection_time_required")
        self.journal.transition(key, "REJECTED", at=at, reason="owner_rejected_no_send")
        return "REJECTED"

    def _fresh(
        self,
        envelope: Envelope,
        at: datetime,
        device_at: datetime,
        received_at: datetime,
    ) -> bool:
        return all(_aware(t) for t in (at, device_at, received_at)) and (
            device_at <= received_at <= at
            and 0 <= (at - device_at).total_seconds() <= envelope.send_freshness_seconds
            and 0
            <= (at - received_at).total_seconds()
            <= envelope.send_freshness_seconds
        )

    def dispatch(self, key: str, state: PilotState) -> str:
        if type(state) is not PilotState or type(state.core) is not Precheck:
            raise ValueError("exact_pilot_state_required")
        if (
            not self.executor.fake_rehearsal
            or type(self.executor.transport) is not FakeTransport
        ):
            raise PermissionError("hardware_execution_disabled")
        intent, envelope, row = self._load(key)
        if self.journal.state(key) != "APPROVED":
            raise ValueError("not_approved_or_already_dispatched")
        approval = self.journal.connection.execute(
            "SELECT binding,at FROM pilot_approvals WHERE intent_id=?", (key,)
        ).fetchone()
        reasons = []
        if (
            state.core.device_expiry_verified is not True
            or state.core.neutral_verified is not True
        ):
            reasons.append("device_expiry_or_return_not_explicitly_verified")
        required_numbers = (
            state.core.effective_power_ac_kw,
            state.core.effective_import_kw,
            state.core.import_price_aud_per_kwh,
        )
        if any(not _finite(v) for v in required_numbers):
            reasons.append("invalid_critical_capability_type")
        if approval is None or approval[0] != row[2]:
            reasons.append("original_approval_missing")
        elif (
            state.core.at - datetime.fromisoformat(approval[1])
        ).total_seconds() > envelope.approval_max_age_seconds:
            reasons.append("approval_too_old")
        if row[3] != self.session:
            reasons.append("restart_requires_new_intent_no_send")
        if not self._clock(key, state.core.at, state.monotonic_seconds):
            reasons.append("clock_discontinuity")
        if approval and (
            not _aware(state.device_at)
            or state.device_at <= datetime.fromisoformat(approval[1])
        ):
            reasons.append("no_advancing_post_approval_device_frame")
        if not self._fresh(envelope, state.core.at, state.device_at, state.received_at):
            reasons.append("send_time_evidence_stale_or_future")
        if not all(
            v is True
            for v in (
                state.network_available,
                state.ha_available,
                state.app_available,
                state.database_available,
                state.grid_available,
            )
        ):
            reasons.append("service_or_grid_unavailable")
        site_flows = (state.net_site_import_kw, state.net_site_export_kw)
        if any(not _finite(v) or v < 0 for v in site_flows):
            reasons.append("unknown_site_flow")
        elif (
            all(v > 0 for v in site_flows)
            or state.net_site_import_kw
            + (
                intent.max_power_ac_kw
                if intent.action == "CHARGE_BATTERY_FROM_GRID"
                else 0
            )
            > envelope.site_import_limit_kw
            or state.net_site_export_kw > envelope.site_export_limit_kw
        ):
            reasons.append("site_flow_or_import_headroom_bound")
        if (
            state.core.import_price_aud_per_kwh
            != envelope.approved_import_price_aud_per_kwh
        ):
            reasons.append("approved_price_changed")
        if (
            state.source_scope != envelope.source_scope
            or state.mode not in envelope.allowed_modes
        ):
            reasons.append("source_or_mode_changed")
        if state.control_owners != (intent.owner,):
            reasons.append("exclusive_control_owner_unconfirmed")
        if not all(
            _finite(v)
            for v in (
                state.capacity_kwh,
                state.soc_percent,
                state.core.energy_stored_kwh,
            )
        ):
            reasons.append("capacity_or_soc_unknown")
        elif (
            state.capacity_kwh != envelope.capacity_kwh
            or not envelope.min_soc_percent
            <= state.soc_percent
            <= envelope.max_soc_percent
            or abs(
                state.core.energy_stored_kwh
                - state.capacity_kwh * state.soc_percent / 100
            )
            > 0.001
            or state.core.energy_stored_kwh + intent.max_throughput_stored_kwh
            > envelope.capacity_kwh * envelope.max_soc_percent / 100
        ):
            reasons.append("capacity_soc_or_headroom_bound")
        if reasons:
            self.journal.transition(
                key, "REJECTED", at=state.core.at, reason=",".join(reasons)
            )
            return "REJECTED"
        self._record(
            key,
            "SEND_PRECHECK",
            {
                "at": state.core.at,
                "input_sha256": state.core.input_sha256,
                "device_expiry_verified": state.core.device_expiry_verified,
                "energy_stored_kwh": state.core.energy_stored_kwh,
                "device_at": state.device_at,
                "received_at": state.received_at,
            },
        )
        return self.executor.dispatch(intent, state.core)

    def observe(self, key: str, feedback: Feedback) -> str:
        if type(feedback) is not Feedback:
            raise ValueError("exact_pilot_feedback_required")
        intent, envelope, _ = self._load(key)
        state = self.journal.state(key)
        if state in {"PROPOSED", "APPROVED", "PRECHECKED", "REJECTED"}:
            raise ValueError("no_dispatch_to_observe")
        if state == "NEUTRAL_STATE_VERIFIED":
            return state
        if state == "SENT":
            self.journal.transition(
                key,
                "UNKNOWN_DELIVERY",
                at=feedback.at,
                reason="restart_after_send_no_retry",
            )
            state = "UNKNOWN_DELIVERY"
        if not _aware(feedback.at):
            raise ValueError("aware_feedback_time_required")
        if (
            feedback.ownership_generation != intent.ownership_generation
            or feedback.owner != intent.owner
            or feedback.device_identity != intent.device_identity
        ):
            if state != "ABORTED":
                self.journal.transition(
                    key,
                    "ABORTED",
                    at=feedback.at,
                    reason="manual_intervention_wins_no_restore",
                )
            return "ABORTED"
        if state == "ABORTED":
            return (
                "ABORTED"  # Explicit recovery review; never overwrite a newer operator.
            )
        fresh = self._fresh(
            envelope, feedback.at, feedback.device_at, feedback.received_at
        )
        clock_ok = self._clock(key, feedback.at, feedback.monotonic_seconds)
        services_ok = all(
            v is True
            for v in (
                feedback.network_available,
                feedback.ha_available,
                feedback.app_available,
                feedback.database_available,
                feedback.grid_available,
                feedback.bms_healthy,
            )
        )
        if not (fresh and clock_ok and services_ok):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="feedback_or_clock_or_service_failure_human_recovery",
            )
            return "ABORTED"
        if (
            feedback.mode != envelope.ordinary_mode
            and feedback.mode not in envelope.allowed_modes
        ):
            self.journal.transition(
                key, "ABORTED", at=feedback.at, reason="unexpected_mode_human_recovery"
            )
            return "ABORTED"
        events = self.journal.connection.execute(
            "SELECT at FROM events WHERE intent_id=? AND state='SENT' "
            "ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
        prior = self.journal.connection.execute(
            "SELECT body FROM pilot_evidence WHERE intent_id=? AND kind='FEEDBACK' "
            "ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        last_at = (
            datetime.fromisoformat(json.loads(prior[0])["at"])
            if prior
            else datetime.fromisoformat(events[0])
        )
        if state in {"ACKNOWLEDGED", "UNKNOWN_DELIVERY"}:
            last_at = datetime.fromisoformat(events[0])
        expired = (
            feedback.at >= intent.expires_at
            or (feedback.at - intent.approved_at).total_seconds()
            >= intent.max_duration_seconds
        )
        if (
            not expired
            and (feedback.at - last_at).total_seconds()
            > envelope.feedback_timeout_seconds
        ):
            self.journal.transition(
                key, "ABORTED", at=feedback.at, reason="feedback_timeout_human_recovery"
            )
            return "ABORTED"
        baseline = self.journal.connection.execute(
            "SELECT body FROM pilot_evidence WHERE intent_id=? "
            "AND kind='SEND_PRECHECK' ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        previous_device_at = (
            json.loads(prior[0])["device_at"]
            if prior
            else json.loads(baseline[0])["device_at"] if baseline else None
        )
        if previous_device_at is None or feedback.device_at <= datetime.fromisoformat(
            previous_device_at
        ):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="device_frame_did_not_advance_human_recovery",
            )
            return "ABORTED"
        all_numbers = (
            feedback.battery_power_ac_kw,
            feedback.energy_ac_kwh,
            feedback.throughput_stored_kwh,
            feedback.energy_stored_kwh,
            feedback.import_cost_aud,
            feedback.net_site_import_kw,
            feedback.net_site_export_kw,
        )
        if any(v is not None and (not _finite(v) or v < 0) for v in all_numbers):
            self.journal.transition(
                key, "ABORTED", at=feedback.at, reason="invalid_feedback_numeric_value"
            )
            return "ABORTED"
        if (
            type(feedback.effect_observed) is not bool
            or type(feedback.ordinary_state_observed) is not bool
        ):
            self.journal.transition(
                key, "ABORTED", at=feedback.at, reason="invalid_feedback_boolean_claim"
            )
            return "ABORTED"
        numeric = (feedback.net_site_import_kw, feedback.net_site_export_kw)
        if any(not _finite(v) or v < 0 for v in numeric) or all(v > 0 for v in numeric):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="invalid_or_ambiguous_net_site_feedback",
            )
            return "ABORTED"
        if (
            feedback.net_site_import_kw > envelope.site_import_limit_kw
            or feedback.net_site_export_kw > envelope.site_export_limit_kw
        ):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="observed_site_import_or_export_cap",
            )
            return "ABORTED"
        if (
            _finite(feedback.energy_stored_kwh)
            and feedback.energy_stored_kwh
            > envelope.capacity_kwh * envelope.max_soc_percent / 100
        ):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="observed_soc_or_capacity_ceiling",
            )
            return "ABORTED"
        if prior:
            old = json.loads(prior[0])
            for name in ("energy_ac_kwh", "throughput_stored_kwh", "import_cost_aud"):
                before, after = old[name], getattr(feedback, name)
                if _finite(before) and _finite(after) and after < before:
                    self.journal.transition(
                        key,
                        "ABORTED",
                        at=feedback.at,
                        reason="cumulative_feedback_regressed",
                    )
                    return "ABORTED"
        if _finite(feedback.energy_ac_kwh) and feedback.energy_ac_kwh > (
            intent.max_power_ac_kw
            * max(0, (feedback.at - datetime.fromisoformat(events[0])).total_seconds())
            / 3600
            + 1e-9
        ):
            self.journal.transition(
                key,
                "ABORTED",
                at=feedback.at,
                reason="energy_feedback_exceeds_power_time_envelope",
            )
            return "ABORTED"
        measured_effect = feedback.effect_observed
        if intent.action == "CHARGE_BATTERY_FROM_GRID":
            initial_energy = json.loads(baseline[0])["energy_stored_kwh"]
            measured_effect = feedback.effect_observed and (
                (
                    _finite(feedback.battery_power_ac_kw)
                    and feedback.battery_power_ac_kw > 0
                )
                or (
                    all(
                        _finite(v)
                        for v in (
                            feedback.energy_ac_kwh,
                            feedback.throughput_stored_kwh,
                            feedback.energy_stored_kwh,
                        )
                    )
                    and feedback.energy_ac_kwh > 0
                    and feedback.throughput_stored_kwh > 0
                    and feedback.energy_stored_kwh > initial_energy
                )
            )
        self._record(key, "FEEDBACK", asdict(feedback))
        return self.executor.observe(
            intent,
            at=feedback.at,
            direction=feedback.direction,
            power_ac_kw=feedback.battery_power_ac_kw,
            energy_ac_kwh=feedback.energy_ac_kwh,
            throughput_stored_kwh=feedback.throughput_stored_kwh,
            energy_stored_kwh=feedback.energy_stored_kwh,
            ownership_generation=feedback.ownership_generation,
            effect_observed=measured_effect,
            neutral_observed=feedback.ordinary_state_observed
            and feedback.mode == envelope.ordinary_mode,
            import_cost_aud=feedback.import_cost_aud,
            feedback_fresh=fresh,
            bms_healthy=feedback.bms_healthy,
        )

    def status(self, key: str) -> dict:
        intent, envelope, row = self._load(key)
        state = self.journal.state(key)
        events = self.journal.connection.execute(
            "SELECT state,at,reason FROM events WHERE intent_id=? ORDER BY id LIMIT ?",
            (key, MAX_EVENTS_PER_INTENT),
        ).fetchall()
        evidence = self.journal.connection.execute(
            "SELECT kind,body FROM pilot_evidence WHERE intent_id=? "
            "ORDER BY id LIMIT ?",
            (key, MAX_EVENTS_PER_INTENT),
        ).fetchall()
        return {
            "version": VERSION,
            "intent_id": key,
            "purpose": "commissioning",
            "approval_binding": row[2],
            "intent": json.loads(canonical(intent)),
            "envelope": json.loads(canonical(envelope)),
            "state": state,
            "status_meaning": "RETURN_FAILED" if state == "RESTORE_FAILED" else state,
            "live_dispatch": False,
            "independent_device_expiry_required": True,
            "human_recovery_is_device_expiry": False,
            "events": [
                dict(zip(("state", "at", "reason"), item, strict=True))
                for item in events
            ],
            "evidence": [
                {"kind": kind, "body": json.loads(body)} for kind, body in evidence
            ],
        }


def read_rehearsal_json(path: str | Path) -> dict:
    """Read one explicit bounded synthetic fixture, never an environment store."""
    fixture = Path(path)
    if fixture.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("fixture_too_large")
    body = json.loads(fixture.read_text(encoding="utf-8-sig"))
    if type(body) is not dict:
        raise ValueError("fixture_object_required")
    return body


def parse_contract(body: dict) -> tuple[Intent, Envelope]:
    """Strict constructor decoding; missing/extra fields are never defaulted."""
    if set(body) != {"intent", "envelope"}:
        raise ValueError("intent_and_envelope_required")
    intent = dict(body["intent"])
    for field in ("approved_at", "expires_at"):
        intent[field] = parse_utc_time(intent[field])
    intent["permitted_actions"] = tuple(intent["permitted_actions"])
    envelope = dict(body["envelope"])
    envelope["allowed_modes"] = tuple(envelope["allowed_modes"])
    return Intent(**intent), Envelope(**envelope)


def parse_state(body: dict) -> PilotState:
    state = dict(body)
    core = dict(state.pop("core"))
    core["at"] = parse_utc_time(core["at"])
    for name in ("device_at", "received_at"):
        state[name] = parse_utc_time(state[name])
    state["control_owners"] = tuple(state["control_owners"])
    return PilotState(core=Precheck(**core), **state)


def parse_feedback(body: dict) -> Feedback:
    values = dict(body)
    for name in ("at", "device_at", "received_at"):
        values[name] = parse_utc_time(values[name])
    return Feedback(**values)


def open_rehearsal_journal(path: str | Path) -> Journal:
    """Refuse an existing database unless this CLI explicitly owns its marker."""
    target = Path(path)
    if not target.name.endswith(".pilot.sqlite3"):
        raise ValueError("owned_pilot_journal_suffix_required")
    if target.exists():
        with sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True) as check:
            row = check.execute("SELECT version FROM pilot_cli_owner").fetchall()
            if row != [(VERSION,)]:
                raise ValueError("existing_journal_not_owned_by_fake_pilot")
    journal = Journal(target)
    journal.connection.execute(
        "CREATE TABLE IF NOT EXISTS pilot_cli_owner(version TEXT PRIMARY KEY)"
    )
    journal.connection.execute(
        "INSERT OR IGNORE INTO pilot_cli_owner VALUES (?)", (VERSION,)
    )
    return journal


def parse_utc_time(value: str) -> datetime:
    at = datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware_time_required")
    return at.astimezone(UTC)
