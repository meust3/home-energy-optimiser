"""Durable fake-only execution rehearsal. No HA client, credentials or network code.

Gate A exposes no executor API. A real transport is deliberately unsupported;
Gate B must establish device semantics/expiry and a separately scoped permission.
"""

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from energy_optimizer.arbitrage.decision_types import canonical, digest

STATES = {
    "PROPOSED",
    "APPROVED",
    "PRECHECKED",
    "SENT",
    "ACKNOWLEDGED",
    "EFFECT_OBSERVED",
    "COMPLETED",
    "EXPIRED",
    "NEUTRAL_STATE_VERIFIED",
    "REJECTED",
    "ABORTED",
    "UNKNOWN_DELIVERY",
    "RESTORE_FAILED",
}
ACTIVE = {
    "ABORTED",
    "APPROVED",
    "PRECHECKED",
    "SENT",
    "ACKNOWLEDGED",
    "EFFECT_OBSERVED",
    "COMPLETED",
    "EXPIRED",
    "UNKNOWN_DELIVERY",
    "RESTORE_FAILED",
}
TRANSITIONS = {
    "PROPOSED": {"APPROVED", "REJECTED"},
    "APPROVED": {"PRECHECKED", "REJECTED", "ABORTED", "EXPIRED"},
    "PRECHECKED": {"SENT", "ABORTED", "EXPIRED"},
    "SENT": {"ACKNOWLEDGED", "UNKNOWN_DELIVERY"},
    "ACKNOWLEDGED": {"EFFECT_OBSERVED", "UNKNOWN_DELIVERY", "ABORTED", "EXPIRED"},
    "EFFECT_OBSERVED": {"COMPLETED", "EXPIRED", "ABORTED"},
    "COMPLETED": {"NEUTRAL_STATE_VERIFIED", "RESTORE_FAILED", "ABORTED"},
    "EXPIRED": {"NEUTRAL_STATE_VERIFIED", "RESTORE_FAILED", "ABORTED"},
    "UNKNOWN_DELIVERY": {"EFFECT_OBSERVED", "EXPIRED", "ABORTED"},
    "RESTORE_FAILED": {"NEUTRAL_STATE_VERIFIED", "ABORTED"},
    "ABORTED": {"NEUTRAL_STATE_VERIFIED"},
}


@dataclass(frozen=True)
class Intent:
    proposal_sha256: str
    actor: str
    action: str
    device_identity: str
    input_sha256: str
    owner: str
    ownership_generation: int
    approved_at: datetime
    expires_at: datetime
    max_duration_seconds: int
    max_power_ac_kw: float
    max_energy_ac_kwh: float
    max_import_cost_aud: float
    max_throughput_stored_kwh: float
    min_energy_stored_kwh: float
    expected_feedback: str
    neutral_contract: str
    permitted_actions: tuple[str, ...]

    def __post_init__(self):
        if (
            self.action
            not in {
                "PRESERVE_BATTERY",
                "CHARGE_BATTERY_FROM_GRID",
                "DISCHARGE_FOR_SELF_CONSUMPTION",
                "EXPORT_BATTERY_AC",
            }
            or self.action not in self.permitted_actions
        ):
            raise ValueError("action_not_explicitly_permitted")
        if not all(
            (
                self.actor,
                self.device_identity,
                self.owner,
                self.expected_feedback,
                self.neutral_contract,
            )
        ):
            raise ValueError("incomplete_intent_contract")
        if any(
            len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
            for v in (self.proposal_sha256, self.input_sha256)
        ):
            raise ValueError("invalid_intent_hash")
        if (
            any(
                t.tzinfo is None or t.utcoffset() is None
                for t in (self.approved_at, self.expires_at)
            )
            or self.approved_at >= self.expires_at
        ):
            raise ValueError("invalid_intent_time")
        if (
            self.max_duration_seconds <= 0
            or self.max_duration_seconds
            > (self.expires_at - self.approved_at).total_seconds()
        ):
            raise ValueError("invalid_duration_envelope")
        if any(
            not math.isfinite(v) or v < 0
            for v in (
                self.max_power_ac_kw,
                self.max_energy_ac_kwh,
                self.max_import_cost_aud,
                self.max_throughput_stored_kwh,
                self.min_energy_stored_kwh,
            )
        ):
            raise ValueError("invalid_intent_bounds")

    @property
    def id(self):
        return digest(self)


@dataclass(frozen=True)
class Precheck:
    at: datetime
    input_sha256: str
    device_identity: str
    owner: str
    ownership_generation: int
    fresh: bool
    healthy: bool
    bms_healthy: bool
    clock_continuous: bool
    energy_stored_kwh: float | None
    effective_power_ac_kw: float | None
    effective_import_kw: float | None
    effective_export_kw: float | None
    import_price_aud_per_kwh: float | None
    export_price_aud_per_kwh: float | None
    expected_direction: str
    device_expiry_verified: bool
    neutral_verified: bool


def precheck_reasons(intent, state):
    reasons = []
    if state.at < intent.approved_at or state.at >= intent.expires_at:
        reasons.append("approval_expired_or_clock_reversed")
    if state.input_sha256 != intent.input_sha256:
        reasons.append("material_input_change")
    if (state.device_identity, state.owner, state.ownership_generation) != (
        intent.device_identity,
        intent.owner,
        intent.ownership_generation,
    ):
        reasons.append("ownership_or_device_changed")
    if not all(
        v is True
        for v in (state.fresh, state.healthy, state.bms_healthy, state.clock_continuous)
    ):
        reasons.append("unhealthy_stale_or_clock_fault")
    if not state.device_expiry_verified or not state.neutral_verified:
        reasons.append("expiry_or_recovery_unverified")
    required = [
        state.energy_stored_kwh,
        state.effective_power_ac_kw,
        state.import_price_aud_per_kwh,
    ]
    required.append(
        state.effective_export_kw
        if intent.action == "EXPORT_BATTERY_AC"
        else state.effective_import_kw
    )
    if any(v is None or not math.isfinite(v) for v in required):
        return reasons + ["unknown_critical_capability"]
    if state.energy_stored_kwh < intent.min_energy_stored_kwh:
        reasons.append("reserve_shortfall")
    if state.effective_power_ac_kw < intent.max_power_ac_kw:
        reasons.append("power_cap_reduced")
    if intent.action == "CHARGE_BATTERY_FROM_GRID":
        if state.effective_import_kw < intent.max_power_ac_kw:
            reasons.append("import_cap_reduced")
        if (
            max(state.import_price_aud_per_kwh, 0) * intent.max_energy_ac_kwh
            > intent.max_import_cost_aud
        ):
            reasons.append("cost_cap_or_tariff_spike")
    if intent.action == "EXPORT_BATTERY_AC":
        if state.effective_export_kw < intent.max_power_ac_kw:
            reasons.append("export_cap_reduced")
        if (
            state.export_price_aud_per_kwh is None
            or not math.isfinite(state.export_price_aud_per_kwh)
            or state.export_price_aud_per_kwh < 0
        ):
            reasons.append("missing_or_negative_export_price")
    direction = {
        "PRESERVE_BATTERY": "inhibit",
        "CHARGE_BATTERY_FROM_GRID": "charge",
        "DISCHARGE_FOR_SELF_CONSUMPTION": "discharge",
        "EXPORT_BATTERY_AC": "discharge",
    }[intent.action]
    if state.expected_direction != direction:
        reasons.append("wrong_direction")
    return reasons


class Journal:
    """Owned local journal only, serialised durable ownership and no stale queue."""

    def __init__(self, path):
        self.connection = sqlite3.connect(Path(path), timeout=1, isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY, "
            "body TEXT NOT NULL,state TEXT NOT NULL,active INTEGER UNIQUE)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,"
            "intent_id TEXT REFERENCES intents(id),state TEXT NOT NULL,"
            "at TEXT NOT NULL,reason TEXT NOT NULL)"
        )

    def propose(self, intent):
        self.connection.execute(
            "INSERT OR IGNORE INTO intents VALUES (?,?,?,NULL)",
            (intent.id, canonical(intent), "PROPOSED"),
        )
        return intent.id

    def state(self, key):
        row = self.connection.execute(
            "SELECT state FROM intents WHERE id=?", (key,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown_intent")
        return row[0]

    def transition(self, key, state, *, at, reason=""):
        if state not in STATES:
            raise ValueError("unknown_execution_state")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            old = self.state(key)
            if state not in TRANSITIONS.get(old, set()):
                raise ValueError("illegal_execution_transition")
            self.connection.execute(
                "UPDATE intents SET state=?,active=? WHERE id=?",
                (state, 1 if state in ACTIVE else None, key),
            )
            self.connection.execute(
                "INSERT INTO events(intent_id,state,at,reason) VALUES (?,?,?,?)",
                (key, state, at.isoformat(), reason),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()


class FakeTransport:
    """In-memory command receipts for local tests; never calls another system."""

    def __init__(self, *, lost_ack=False):
        self.calls = []
        self.lost_ack = lost_ack

    def send(self, intent):
        self.calls.append(intent.id)
        if self.lost_ack:
            raise TimeoutError("fake_ack_loss")
        return "fake_ack"


class DisabledExecutor:
    def __init__(self, journal, transport=None, *, fake_rehearsal=False):
        self.journal = journal
        self.transport = transport
        self.fake_rehearsal = fake_rehearsal
        if transport is not None and type(transport) is not FakeTransport:
            raise ValueError("real_transport_not_supported")

    def dispatch(self, intent, state):
        if not self.fake_rehearsal or type(self.transport) is not FakeTransport:
            raise PermissionError("hardware_execution_disabled")
        if self.journal.state(intent.id) != "APPROVED":
            raise ValueError("not_approved_or_already_dispatched")
        reasons = precheck_reasons(intent, state)
        if reasons:
            self.journal.transition(
                intent.id, "REJECTED", at=state.at, reason=",".join(reasons)
            )
            return "REJECTED"
        self.journal.transition(intent.id, "PRECHECKED", at=state.at)
        self.journal.transition(intent.id, "SENT", at=state.at)
        try:
            self.transport.send(intent)
        except TimeoutError:
            self.journal.transition(
                intent.id, "UNKNOWN_DELIVERY", at=state.at, reason="no_automatic_retry"
            )
            return "UNKNOWN_DELIVERY"
        self.journal.transition(intent.id, "ACKNOWLEDGED", at=state.at)
        return "ACKNOWLEDGED"

    def observe(
        self,
        intent,
        *,
        at,
        direction,
        power_ac_kw,
        energy_ac_kwh,
        throughput_stored_kwh,
        energy_stored_kwh,
        ownership_generation,
        effect_observed,
        neutral_observed,
        import_cost_aud=None,
        feedback_fresh=None,
        bms_healthy=None,
    ):
        state = self.journal.state(intent.id)
        if state == "ABORTED":
            # A human abort never grants a fresh owner until neutral is witnessed.
            if neutral_observed is True:
                self.journal.transition(intent.id, "NEUTRAL_STATE_VERIFIED", at=at)
                return "NEUTRAL_STATE_VERIFIED"
            return state
        if state == "NEUTRAL_STATE_VERIFIED":
            return state
        if state == "SENT":
            self.journal.transition(
                intent.id,
                "UNKNOWN_DELIVERY",
                at=at,
                reason="restart_after_send_no_retry",
            )
            state = "UNKNOWN_DELIVERY"
        if ownership_generation != intent.ownership_generation:
            self.journal.transition(
                intent.id,
                "ABORTED",
                at=at,
                reason="manual_intervention_wins_no_restore",
            )
            return "ABORTED"
        if (
            at < intent.approved_at
            or feedback_fresh is not True
            or bms_healthy is not True
        ):
            self.journal.transition(
                intent.id,
                "ABORTED",
                at=at,
                reason="clock_or_feedback_or_bms_fault_human_fallback",
            )
            return "ABORTED"
        expired = (
            at >= intent.expires_at
            or (at - intent.approved_at).total_seconds() >= intent.max_duration_seconds
        )
        if expired and state in {"ACKNOWLEDGED", "UNKNOWN_DELIVERY", "EFFECT_OBSERVED"}:
            self.journal.transition(intent.id, "EXPIRED", at=at)
            state = "EXPIRED"

        def unresolved():
            if state == "EXPIRED":
                self.journal.transition(
                    intent.id,
                    "RESTORE_FAILED",
                    at=at,
                    reason="expired_without_complete_feedback",
                )
                return "RESTORE_FAILED"
            return state

        values = (power_ac_kw, energy_ac_kwh, throughput_stored_kwh, energy_stored_kwh)
        if intent.action == "CHARGE_BATTERY_FROM_GRID":
            # Missing cost feedback is not permission to declare success.
            if import_cost_aud is None or not math.isfinite(import_cost_aud):
                return unresolved()
            if import_cost_aud > intent.max_import_cost_aud:
                self.journal.transition(
                    intent.id,
                    "ABORTED",
                    at=at,
                    reason="observed_cost_cap_human_fallback",
                )
                return "ABORTED"
        if any(v is None or not math.isfinite(v) or v < 0 for v in values):
            return unresolved()  # Never zero delivery or claimed successful restore.
        expected = (
            "inhibit"
            if intent.action == "PRESERVE_BATTERY"
            else (
                "charge" if intent.action == "CHARGE_BATTERY_FROM_GRID" else "discharge"
            )
        )
        if (
            direction != expected
            or power_ac_kw > intent.max_power_ac_kw
            or energy_ac_kwh > intent.max_energy_ac_kwh
            or throughput_stored_kwh > intent.max_throughput_stored_kwh
            or energy_stored_kwh < intent.min_energy_stored_kwh
        ):
            self.journal.transition(
                intent.id,
                "ABORTED",
                at=at,
                reason="observed_safety_failure_human_fallback",
            )
            return "ABORTED"
        if (
            not expired
            and effect_observed is True
            and state in {"ACKNOWLEDGED", "UNKNOWN_DELIVERY"}
        ):
            self.journal.transition(intent.id, "EFFECT_OBSERVED", at=at)
            state = "EFFECT_OBSERVED"
        if state == "EFFECT_OBSERVED" and energy_ac_kwh >= intent.max_energy_ac_kwh:
            self.journal.transition(intent.id, "COMPLETED", at=at)
            state = "COMPLETED"
        if state in {"COMPLETED", "EXPIRED", "RESTORE_FAILED"}:
            if neutral_observed is True:
                self.journal.transition(intent.id, "NEUTRAL_STATE_VERIFIED", at=at)
                return "NEUTRAL_STATE_VERIFIED"
            if state != "RESTORE_FAILED":
                self.journal.transition(
                    intent.id,
                    "RESTORE_FAILED",
                    at=at,
                    reason="neutral_effect_not_verified",
                )
                return "RESTORE_FAILED"
        return state
