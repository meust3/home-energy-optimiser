"""Admission, economics, topology and fake-control failure witnesses."""

import json
import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url

from energy_optimizer import offline_paired_synthetic as core
from energy_optimizer.arbitrage.archive import (
    context_from_capture,
)
from energy_optimizer.arbitrage.capture import CaptureRepository, snapshot_states
from energy_optimizer.arbitrage.core_bridge import make_inputs, reconcile
from energy_optimizer.arbitrage.decision_types import canonical, digest, primitive
from energy_optimizer.arbitrage.economics import (
    BusinessScenario,
    operational_choice,
    replay,
    terminal_bounds,
)
from energy_optimizer.arbitrage.executor import (
    DisabledExecutor,
    FakeTransport,
    Intent,
    Journal,
    Precheck,
)
from energy_optimizer.arbitrage.export_model import SharedEnvelope, compare, simulate
from energy_optimizer.arbitrage.opportunity import (
    board,
    declared_context,
    save_opportunity,
)
from energy_optimizer.arbitrage.selector import POLICY_SHA
from energy_optimizer.arbitrage.selector import select as research_select
from energy_optimizer.arbitrage.synthetic_cases import authored_case
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.persistence import open_repository

T = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgresql"])
def capture_db(request, tmp_path):
    admin = schema = None
    if request.param == "sqlite":
        url = f"sqlite:///{(tmp_path/'capture.db').as_posix()}"
    else:
        configured = os.getenv("TEST_POSTGRES_URL")
        if not configured:
            pytest.skip("owned disposable TEST_POSTGRES_URL required")
        parsed = make_url(configured)
        assert (
            parsed.host == "127.0.0.1"
            and parsed.database == os.environ["F1_F3_OWNED_TEST_DATABASE"]
        )
        admin = create_database_engine(configured)
        schema = "arbitrage_" + uuid.uuid4().hex
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.set(query={"options": f"-csearch_path={schema}"}).render_as_string(
            hide_password=False
        )
    command.upgrade(alembic_config(url), "head")
    repo = open_repository(url)
    try:
        yield repo, url
    finally:
        repo.close()
        if admin is not None:
            with admin.begin() as c:
                c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_capture_post_commit_witness_immutability_and_rollback(capture_db):
    repo, url = capture_db
    store = CaptureRepository(repo)
    key = store.save(
        origin="one",
        kind="source",
        at=T,
        body={"value": 1},
        clock=lambda: T + timedelta(seconds=1),
    )
    row = store.latest("source")
    assert row["id"] == key and row["confirmed_at"] == T + timedelta(seconds=1)
    assert store.latest("source", before=T) is None
    assert (
        store.save(
            origin="one",
            kind="source",
            at=T,
            body={"value": 1},
            clock=lambda: T + timedelta(days=1),
        )
        == key
    )
    assert store.latest("source")["confirmed_at"] == row["confirmed_at"]
    with pytest.raises(ValueError, match="immutable_capture_conflict"):
        store.save(origin="one", kind="source", at=T, body={"value": 2})
    assert store.latest("source")["body"] == {"value": 1}
    assert current_revision(repo.engine) == "20261008_01"


def test_capture_crash_between_transactions_not_ready(capture_db):
    repo, _ = capture_db
    store = CaptureRepository(repo)

    def crash():
        raise RuntimeError("crash_after_commit")

    with pytest.raises(RuntimeError):
        store.save(
            origin="crashed", kind="source", at=T, body={"value": 1}, clock=crash
        )
    assert store.latest("source")["confirmed_at"] is None
    assert store.latest("source", before=T + timedelta(days=1)) is None
    store.save(
        origin="crashed",
        kind="source",
        at=T,
        body={"value": 1},
        clock=lambda: T + timedelta(hours=1),
    )
    assert store.latest("source")["confirmed_at"] == T + timedelta(hours=1)
    assert store.latest("source", before=T + timedelta(minutes=5)) is None


def test_capture_whitelist_no_extra_fetch_or_secrets(healthy_states, now):
    for state in healthy_states.values():
        state.attributes.update(
            token="secret", latitude=99, serial="private", friendly_name="household"
        )
    result = snapshot_states(healthy_states, slot=now, received_at=now)
    encoded = canonical(result)
    assert all(
        term not in encoded
        for term in ("secret", "latitude", "serial", "friendly_name")
    )
    assert result["sources"]["import_forecast"]["forecasts"][0]["per_kwh"] == 0.22


def bundle():
    c = authored_case("charging")
    raw = {
        "soc": {
            "state": "25",
            "reported_at": T.isoformat(),
            "attributes": {"unit_of_measurement": "%"},
        },
        "import_forecast": {
            "reported_at": T.isoformat(),
            "attributes": {"unit_of_measurement": "AUD/kWh"},
            "forecasts": [
                {
                    "start_time": p.start.isoformat(),
                    "end_time": p.end.isoformat(),
                    "per_kwh": p.value,
                }
                for p in c.import_price.points
            ],
        },
        "export_forecast": {
            "reported_at": T.isoformat(),
            "attributes": {"unit_of_measurement": "AUD/kWh"},
            "forecasts": [
                {
                    "start_time": p.start.isoformat(),
                    "end_time": p.end.isoformat(),
                    "per_kwh": p.value,
                }
                for p in c.export_price.points
            ],
        },
        "pv_today": {
            "reported_at": T.isoformat(),
            "attributes": {},
            "detailedForecast": [
                {"period_start": p.start.isoformat(), "pv_estimate": p.value}
                for p in c.pv.points
            ],
        },
        "pv_tomorrow": {
            "reported_at": T.isoformat(),
            "attributes": {},
            "detailedForecast": [],
        },
    }
    src_body = {"sources": raw, "received_at": T.isoformat()}
    src = {
        "id": "source-id",
        "body": src_body,
        "body_sha256": digest(src_body),
        "confirmed_at": T,
        "captured_at": T,
    }
    points = [
        {
            "start": p.start.isoformat(),
            "end": p.end.isoformat(),
            "value": p.value * 1000,
            "unit": "W",
        }
        for p in c.demand.points
    ]
    body = {
        "source_capture_id": src["id"],
        "demand_points": points,
        "ready_at": T.isoformat(),
        "created_at": T.isoformat(),
    }
    inputs = {
        "id": "input-id",
        "body": body,
        "body_sha256": digest(body),
        "confirmed_at": T,
        "captured_at": T,
    }
    a = primitive(c.assumptions)
    a.pop("evidence")
    profile = {
        "assumptions": a,
        "evidence": primitive(c.assumptions.evidence),
        "floor_kwh": 0,
        "state_bridge": "constant_soc_capacity_proxy_until_branch",
        "soc_report_age_seconds": 600,
        "forecast_report_age_seconds": {
            "demand": 3600,
            "pv": 21600,
            "import_price": 3600,
            "export_price": 3600,
        },
        "uncontrolled_load_kw": 0,
        "uncontrolled_load_basis": "explicit authored zero-EV conditional scenario, not measured absence",  # noqa: E501
    }
    return inputs, src, profile


def test_producer_shaped_capture_admission_and_parity():
    inputs, src, profile = bundle()
    c = context_from_capture(
        inputs, src, primitive(declared_context(inputs, src, profile))
    )
    receipt = research_select(core, c, digest("integration"))
    assert receipt.selected == "G" and receipt.policy_sha256 == POLICY_SHA
    assert json.loads(receipt.estimates_json)["costs_aud"] == pytest.approx(
        {"R": 1.2, "P": 1.05, "G": 0.15}
    )


def test_complete_24h_opportunity_fits_byte_bound_without_duplicate_ledgers(
    capture_db, monkeypatch
):
    inputs, source, profile = bundle()
    raw = source["body"]["sources"]
    for alias in ("import_forecast", "export_forecast"):
        raw[alias]["forecasts"] = [
            {
                "start_time": (T + timedelta(minutes=30 * i)).isoformat(),
                "end_time": (T + timedelta(minutes=30 * (i + 1))).isoformat(),
                "per_kwh": (
                    (0.1 if i == 0 else 0.4) if alias == "import_forecast" else 0
                ),
            }
            for i in range(48)
        ]
    raw["pv_today"]["detailedForecast"] = [
        {
            "period_start": (T + timedelta(minutes=30 * i)).isoformat(),
            "pv_estimate": 0,
        }
        for i in range(48)
    ]
    raw["pv_tomorrow"]["detailedForecast"] = []
    inputs["body"]["demand_points"] = [
        {
            "start": (T + timedelta(minutes=5 * i)).isoformat(),
            "end": (T + timedelta(minutes=5 * (i + 1))).isoformat(),
            "value": 1000,
            "unit": "W",
        }
        for i in range(288)
    ]
    inputs["body"].update(
        forecast_id=1,
        reserve_id=None,
        model="authored-24h",
        load_basis="authored baseline + explicit zero-EV scenario",
    )
    original = CaptureRepository.save

    def at_fixture_time(self, **kwargs):
        kwargs.setdefault("clock", lambda: T)
        return original(self, **kwargs)

    monkeypatch.setattr(CaptureRepository, "save", at_fixture_time)
    store = CaptureRepository(capture_db[0])
    source_id = store.save(origin="source", kind="source", at=T, body=source["body"])
    inputs["body"]["source_capture_id"] = source_id
    store.save(origin="inputs", kind="decision_inputs", at=T, body=inputs["body"])
    save_opportunity(capture_db[0], profile_json=canonical(profile))
    body = store.latest("opportunity")["body"]
    assert len(canonical(body).encode()) < 2097152
    assert "original_ledgers" not in body["expected_candidate_value"]
    assert "original_ledgers" in json.loads(body["receipt"]["estimates_json"])
    # Independent decimal arithmetic, no simulator/helper call:
    expected = {
        "R": Fraction("23.5") * Fraction("0.4"),
        "P": Fraction("0.5") * Fraction("0.1") + 23 * Fraction("0.4"),
        "G": Fraction("1.5") * Fraction("0.1") + 22 * Fraction("0.4"),
    }
    assert body["expected_candidate_value"]["costs_aud"] == pytest.approx(
        {k: float(v) for k, v in expected.items()}
    )
    assert (
        body["expires_at"] == T.isoformat().replace("+00:00", "Z")
        or body["expires_at"] == T.isoformat()
    )
    public = board(capture_db[0], now=T)["items"][0]
    assert public["status"] == "expired"
    assert public["observed_accounting"] is None
    assert public["simulated_comparative_value"] is None
    assert "receipt" not in public


@pytest.mark.parametrize(
    "defect",
    ["witness", "hash", "link", "unit", "EV", "overlap", "unknown_physics", "SOC_age"],
)
def test_capture_admission_rejects_unavailable_or_undeclared(defect):
    inputs, src, profile = bundle()
    if defect == "witness":
        inputs["confirmed_at"] = None
    elif defect == "hash":
        src["body_sha256"] = "0" * 64
    elif defect == "link":
        inputs["body"]["source_capture_id"] = "wrong"
        inputs["body_sha256"] = digest(inputs["body"])
    elif defect == "unit":
        src["body"]["sources"]["import_forecast"]["attributes"][
            "unit_of_measurement"
        ] = "c/kWh"
        src["body_sha256"] = digest(src["body"])
    elif defect == "EV":
        profile["uncontrolled_load_kw"] = None
    elif defect == "overlap":
        src["body"]["sources"]["pv_tomorrow"]["detailedForecast"] = [
            {"period_start": T.isoformat(), "pv_estimate": 99}
        ]
        src["body_sha256"] = digest(src["body"])
    elif defect == "unknown_physics":
        del profile["assumptions"]["import_limit_kw"]
    else:
        src["body"]["sources"]["soc"]["reported_at"] = (
            T - timedelta(days=1)
        ).isoformat()
        src["body_sha256"] = digest(src["body"])
    with pytest.raises((ValueError, TypeError)):
        context_from_capture(
            inputs, src, primitive(declared_context(inputs, src, profile))
        )


def test_board_is_read_only_and_unconfirmed_is_truthful(capture_db):
    repo, _ = capture_db
    assert board(repo, now=T)["status"] == "awaiting_capture"
    store = CaptureRepository(repo)
    store.save(
        origin="advice",
        kind="opportunity",
        at=T,
        body={
            "status": "research_only",
            "expires_at": T.isoformat(),
            "selected": "G",
            "context": {"private": "hidden"},
            "receipt": {},
        },
        clock=lambda: T,
    )
    before = store.latest("opportunity")
    response = board(repo, now=T + timedelta(seconds=1))
    assert response["status"] == "expired" and response["execution"] == "disabled"
    assert (
        "context" not in response["items"][0] and store.latest("opportunity") == before
    )


def scenario(**kw):
    return BusinessScenario(
        **(
            {
                "scenario_id": "authored-business",
                "material_benefit_aud": 0.05,
                "uncertainty_budget_aud": 0.02,
                "wear_aud_per_discharged_dc_kwh": 0.08,
                "minimum_dwell_minutes": 30,
                "expiry_minutes": 30,
            }
            | kw
        )
    )


def test_operational_materiality_signed_wear_and_expiry():
    c = authored_case("charging_without_preservation_benefit")
    r = research_select(core, c, digest("test"))
    result = operational_choice(r, scenario(), now=T, discharge_efficiency=1)
    assert result["selected"] == "G" and result["status"] == "research_only"
    assert (
        operational_choice(
            r, scenario(material_benefit_aud=10), now=T, discharge_efficiency=1
        )["selected"]
        == "HOLD"
    )
    assert (
        operational_choice(
            r, scenario(), now=T + timedelta(minutes=31), discharge_efficiency=1
        )["selected"]
        == "HOLD"
    )
    assert (
        operational_choice(r, scenario(), now=T, discharge_efficiency=1, last_change=T)[
            "selected"
        ]
        == "HOLD"
    )


def test_terminal_bounds_do_not_change_frozen_comparator():
    r = terminal_bounds(
        cash_benefit_aud=0.3,
        stored_delta_kwh=-1,
        lower_aud_per_dc_kwh=0.1,
        upper_aud_per_dc_kwh=0.5,
        assumptions_id="predeclared",
        feasible=True,
    )
    assert (
        r["conditional_value_bounds_aud"] == pytest.approx([-0.2, 0.2])
        and r["primary_v1_value"] is None
    )
    assert (
        terminal_bounds(
            cash_benefit_aud=0.3,
            stored_delta_kwh=1,
            lower_aud_per_dc_kwh=0.1,
            upper_aud_per_dc_kwh=0.5,
            assumptions_id="predeclared",
            feasible=False,
        )["conditional_value_bounds_aud"]
        is None
    )


def export_case(*, eta=1, load=0, pv=(0, 0, 4), price=0.5, capacity=2, energy=0.5):
    c = authored_case("charging")
    c = replace(
        c,
        assumptions=replace(
            c.assumptions, discharge_efficiency=eta, capacity_kwh=capacity
        ),
        branch=replace(c.branch, energy_kwh=energy),
        demand=replace(
            c.demand, points=tuple(replace(p, value=load) for p in c.demand.points)
        ),
        pv=replace(
            c.pv,
            points=tuple(
                replace(p, value=v) for p, v in zip(c.pv.points, pv, strict=True)
            ),
        ),
        export_price=replace(
            c.export_price,
            points=tuple(
                replace(p, value=price if i == 0 else 0)
                for i, p in enumerate(c.export_price.points)
            ),
        ),
    )
    return make_inputs(core, c, T + timedelta(minutes=90), "CHARGE_BATTERY_FROM_GRID")


def envelope(case, cap=8, output=100):
    return SharedEnvelope(
        output,
        100,
        (core.Interval(T, T + timedelta(minutes=90), cap),),
        "authored-shared-model",
    )


@pytest.mark.parametrize(
    "eta,price,expected", [(1, 0.5, 0.25), (0.9, 0.5, 0.225), (1, -0.5, -0.25)]
)
def test_export_incremental_cash_independent_terminal_match(eta, price, expected):
    case = export_case(eta=eta, price=price)
    report = compare(case, envelope(case))
    assert report["primary_conditional_value_aud"] == pytest.approx(expected)
    assert report["terminal_delta_stored_kwh"] == pytest.approx(0, abs=1e-6)
    rows = report["alternative"].steps
    assert any(r.end_utc < T + timedelta(minutes=30) for r in rows)  # floor event
    independently = sum(
        Fraction(str(r.export_kwh)) * Fraction(str(r.export_price))
        - Fraction(str(r.import_kwh)) * Fraction(str(r.import_price))
        for r in rows
    )
    assert float(independently) == pytest.approx(-report["audits"][1]["cost_aud"])
    assert all(r.energy_end_kwh >= -1e-9 and r.unserved_load_kwh == 0 for r in rows)


@pytest.mark.parametrize(
    "kind",
    [
        "load_consumes",
        "pv_cap",
        "no_cap",
        "shared",
        "dynamic",
        "terminal_mismatch",
        "reserve",
        "missing_price",
    ],
)
def test_export_constraints_and_unavailable(kind):
    case = export_case()
    e = envelope(case)
    if kind == "load_consumes":
        case = export_case(load=3, pv=(0, 0, 10))
    if kind == "pv_cap":
        case = export_case(pv=(4, 0, 4), capacity=0.5, energy=0.5)
        e = envelope(case, cap=1)
    if kind == "no_cap":
        e = envelope(case, cap=0)
    if kind == "shared":
        e = envelope(case, output=0.2)
    if kind == "dynamic":
        e = replace(
            e,
            site_export_caps_kw=(
                core.Interval(T, T + timedelta(minutes=10), 1),
                core.Interval(T + timedelta(minutes=10), T + timedelta(minutes=90), 0),
            ),
        )
    if kind == "terminal_mismatch":
        case = export_case(pv=(0, 0, 0))
    if kind == "reserve":
        case = replace(
            case,
            parameters=replace(
                case.parameters, policy_floor_kwh=0.4, terminal_reserve_kwh=0.4
            ),
        )
    if kind == "missing_price":
        case = replace(
            case,
            export_price_aud_per_kwh=tuple(
                replace(p, value=None) for p in case.export_price_aud_per_kwh
            ),
        )
        with pytest.raises(core.AdmissionError):
            compare(case, e)
        return
    report = compare(case, e)
    if kind in {"load_consumes", "pv_cap", "no_cap"}:
        assert (
            sum(r.export_kwh for r in report["alternative"].steps[:1])
            == pytest.approx(0)
            if kind != "pv_cap"
            else report["diagnostic_cash_difference_aud"] == pytest.approx(0)
        )
    if kind == "terminal_mismatch":
        assert report["primary_conditional_value_aud"] is None
    if kind == "dynamic":
        assert all(
            r.export_kwh == 0
            for r in report["alternative"].steps
            if T + timedelta(minutes=10) <= r.start_utc < T + timedelta(minutes=30)
        )
    if kind == "reserve":
        assert min(r.energy_end_kwh for r in report["alternative"].steps) >= 0.4 - 1e-9


@pytest.mark.parametrize(
    "action",
    [
        "HOLD",
        "PRESERVE_BATTERY",
        "CHARGE_BATTERY_FROM_GRID",
        "DISCHARGE_FOR_SELF_CONSUMPTION",
    ],
)
def test_new_model_frozen_kernel_parity_without_shared_binding(action):
    case = export_case(load=1, pv=(0, 0, 4))
    baseline = replace(
        case,
        schedule=replace(
            case.schedule,
            action=action,
            power_limit_kw=0 if action in {"HOLD", "PRESERVE_BATTERY"} else 2,
            energy_limit_ac_kwh=0 if action in {"HOLD", "PRESERVE_BATTERY"} else 1,
        ),
    )
    retained = core._simulate_pair(baseline)[1]
    new = simulate(baseline, envelope=envelope(case), action=action)
    assert reconcile(retained, case.parameters)["cost_aud"] == pytest.approx(
        reconcile(new, case.parameters)["cost_aud"], abs=1e-9
    )
    assert retained.steps[-1].energy_end_kwh == pytest.approx(
        new.steps[-1].energy_end_kwh, abs=1e-9
    )


def intent(**kw):
    return Intent(
        **(
            {
                "proposal_sha256": digest("proposal"),
                "actor": "synthetic-operator",
                "action": "CHARGE_BATTERY_FROM_GRID",
                "device_identity": "fake-only",
                "input_sha256": digest("inputs"),
                "owner": "fake-owner",
                "ownership_generation": 1,
                "approved_at": T,
                "expires_at": T + timedelta(minutes=30),
                "max_duration_seconds": 1800,
                "max_power_ac_kw": 2,
                "max_energy_ac_kwh": 1,
                "max_import_cost_aud": 0.25,
                "max_throughput_stored_kwh": 1,
                "min_energy_stored_kwh": 0.1,
                "expected_feedback": "AC direction power energy neutral",
                "neutral_contract": "finite device expiry plus operator-verified neutral",  # noqa: E501
                "permitted_actions": ("CHARGE_BATTERY_FROM_GRID",),
            }
            | kw
        )
    )


def state(**kw):
    return Precheck(
        **(
            {
                "at": T,
                "input_sha256": digest("inputs"),
                "device_identity": "fake-only",
                "owner": "fake-owner",
                "ownership_generation": 1,
                "fresh": True,
                "healthy": True,
                "bms_healthy": True,
                "clock_continuous": True,
                "energy_stored_kwh": 0.5,
                "effective_power_ac_kw": 2,
                "effective_import_kw": 3,
                "effective_export_kw": None,
                "import_price_aud_per_kwh": 0.1,
                "export_price_aud_per_kwh": None,
                "expected_direction": "charge",
                "device_expiry_verified": True,
                "neutral_verified": True,
            }
            | kw
        )
    )


@pytest.mark.parametrize(
    "kw",
    [
        {"fresh": False},
        {"healthy": False},
        {"bms_healthy": False},
        {"clock_continuous": False},
        {"energy_stored_kwh": None},
        {"energy_stored_kwh": 0},
        {"effective_power_ac_kw": 1},
        {"effective_import_kw": 1},
        {"import_price_aud_per_kwh": 10},
        {"expected_direction": "discharge"},
        {"device_expiry_verified": False},
        {"neutral_verified": False},
        {"ownership_generation": 2},
        {"owner": "other"},
        {"input_sha256": digest("changed")},
        {"at": T + timedelta(minutes=31)},
        {"at": T - timedelta(seconds=1)},
    ],
)
def test_executor_precheck_faults_never_send(tmp_path, kw):
    j = Journal(tmp_path / "fake.db")
    i = intent()
    f = FakeTransport()
    j.propose(i)
    j.transition(i.id, "APPROVED", at=T)
    assert (
        DisabledExecutor(j, f, fake_rehearsal=True).dispatch(i, state(**kw))
        == "REJECTED"
    )
    assert f.calls == []
    j.close()


def test_disabled_no_custom_or_arbitrary_transport(tmp_path):
    j = Journal(tmp_path / "fake.db")
    i = intent()
    j.propose(i)
    with pytest.raises(PermissionError):
        DisabledExecutor(j).dispatch(i, state())
    with pytest.raises(ValueError):
        DisabledExecutor(j, object(), fake_rehearsal=True)
    with pytest.raises(ValueError, match="not_explicitly"):
        intent(action="EXPORT_BATTERY_AC")
    j.close()


def test_executor_lost_ack_durable_no_retry_and_competing_owner(tmp_path):
    path = tmp_path / "fake.db"
    j = Journal(path)
    i = intent()
    j.propose(i)
    j.transition(i.id, "APPROVED", at=T)
    f = FakeTransport(lost_ack=True)
    e = DisabledExecutor(j, f, fake_rehearsal=True)
    assert e.dispatch(i, state()) == "UNKNOWN_DELIVERY"
    with pytest.raises(ValueError):
        e.dispatch(i, state())
    second = intent(actor="other")
    j.propose(second)
    with pytest.raises(sqlite3.IntegrityError):
        j.transition(second.id, "APPROVED", at=T)
    j.close()
    resumed = Journal(path)
    assert resumed.state(i.id) == "UNKNOWN_DELIVERY" and len(f.calls) == 1
    resumed.close()


@pytest.mark.parametrize(
    "fault",
    [
        "normal",
        "restore",
        "manual",
        "wrong_direction",
        "over_power",
        "over_energy",
        "reserve",
        "partial_expiry",
        "missing_feedback",
        "restart_after_send",
    ],
)
def test_effect_not_ack_and_expiry_restore_faults(tmp_path, fault):
    j = Journal(tmp_path / "fake.db")
    i = intent()
    j.propose(i)
    j.transition(i.id, "APPROVED", at=T)
    e = DisabledExecutor(j, FakeTransport(), fake_rehearsal=True)
    e.dispatch(i, state())
    values = {
        "at": T + timedelta(minutes=1),
        "direction": "charge",
        "power_ac_kw": 2,
        "energy_ac_kwh": 0.5,
        "throughput_stored_kwh": 0.5,
        "energy_stored_kwh": 1,
        "ownership_generation": 1,
        "effect_observed": True,
        "neutral_observed": False,
        "import_cost_aud": 0.05,
        "feedback_fresh": True,
        "bms_healthy": True,
    }
    if fault == "manual":
        values["ownership_generation"] = 2
    if fault == "wrong_direction":
        values["direction"] = "discharge"
    if fault == "over_power":
        values["power_ac_kw"] = 3
    if fault == "over_energy":
        values["energy_ac_kwh"] = 2
    if fault == "reserve":
        values["energy_stored_kwh"] = 0
    if fault == "missing_feedback":
        values["energy_ac_kwh"] = None
    if fault in {"restore", "partial_expiry"}:
        values["at"] = i.expires_at
    if fault == "partial_expiry":
        values["neutral_observed"] = True
    result = e.observe(i, **values)
    if fault in {"manual", "wrong_direction", "over_power", "over_energy", "reserve"}:
        assert result == "ABORTED"
    elif fault == "missing_feedback":
        assert result == "ACKNOWLEDGED"
    elif fault == "restore":
        assert result == "RESTORE_FAILED"
    elif fault == "partial_expiry":
        assert result == "NEUTRAL_STATE_VERIFIED"
    else:
        assert result == "EFFECT_OBSERVED"
    j.close()


def sequential_contexts():
    c = authored_case("charging")
    return [
        replace(
            c,
            context_id=f"chronological-{i}",
            cutoff=T + timedelta(minutes=30 * i),
            decision_at=T + timedelta(minutes=30 * i),
            evaluated_at=T + timedelta(minutes=30 * i),
            ready_at=T + timedelta(minutes=30 * i),
            action_start=T + timedelta(minutes=30 * i),
            action_end=T + timedelta(minutes=30 * (i + 1)),
            branch=replace(c.branch, at=T + timedelta(minutes=30 * i), energy_kwh=0.5),
            reserve=replace(c.reserve, at=T + timedelta(minutes=30 * i)),
        )
        for i in range(3)
    ]


def test_sequential_own_states_common_realised_path_and_independent_cash():
    seen = []
    reserves = []

    def actual(inputs, c, label):
        seen.append((label, c.context_id, inputs.initial_energy_kwh))
        return inputs

    def floor(c, energy):
        reserves.append((c.context_id, energy))
        return c.reserve

    report = replay(
        core,
        sequential_contexts(),
        initial_energy_kwh=0.5,
        scenario=scenario(minimum_dwell_minutes=0),
        realised_case_factory=actual,
        reserve_equation=floor,
    )
    assert report["origins"] == 3
    assert report["terminal_energy_kwh"] == pytest.approx({"R": 0, "candidate": 0})
    assert report["net_variable_cost_aud"]["R"] == pytest.approx(1.2)
    assert report["primary_comparative_claim"] is None
    assert ("R", "chronological-1", 0) in seen
    assert ("candidate", "chronological-1", 1.5) in seen
    assert ("chronological-1", 1.5) in reserves
    assert report["energy_metrics"]["candidate"]["charged_ac_kwh"] == pytest.approx(1)
    assert report["energy_metrics"]["candidate"]["unserved_load_kwh"] == 0
    for label, rows in report["ledgers"].items():
        independent = sum(
            Fraction(str(r.import_kwh)) * Fraction(str(r.import_price))
            - Fraction(str(r.export_kwh)) * Fraction(str(r.export_price))
            for r in rows
        )
        assert report["net_variable_cost_aud"][label] == pytest.approx(
            float(independent)
        )
        for previous, following in zip(rows, rows[1:], strict=False):
            assert following.energy_start_kwh == pytest.approx(previous.energy_end_kwh)


@pytest.mark.parametrize(
    "fault",
    [
        "gap",
        "reset",
        "different_actual",
        "missing_actual",
        "schedule",
        "physical_change",
    ],
)
def test_sequential_aborts_unsupported_comparisons(fault):
    contexts = sequential_contexts()
    if fault == "gap":
        contexts = [contexts[0], contexts[2]]
    if fault == "physical_change":
        contexts[1] = replace(
            contexts[1], assumptions=replace(contexts[1].assumptions, charge_limit_kw=2)
        )

    def actual(inputs, c, label):
        if fault == "reset" and c.context_id == "chronological-1":
            return replace(inputs, initial_energy_kwh=0.5)
        if fault == "different_actual" and label == "candidate":
            return replace(
                inputs,
                available_pv_kw=tuple(
                    replace(p, value=1) for p in inputs.available_pv_kw
                ),
            )
        if fault == "missing_actual":
            return replace(inputs, import_price_aud_per_kwh=())
        if fault == "schedule":
            return replace(
                inputs, schedule=replace(inputs.schedule, energy_limit_ac_kwh=999)
            )
        return inputs

    with pytest.raises(ValueError):
        replay(
            core,
            contexts,
            initial_energy_kwh=0.5,
            scenario=scenario(),
            realised_case_factory=actual,
            reserve_equation=lambda c, e: c.reserve,
        )


def test_restart_sent_and_abort_keeps_owner_until_neutral(tmp_path):
    path = tmp_path / "restart.db"
    i = intent()
    j = Journal(path)
    j.propose(i)
    for status in ("APPROVED", "PRECHECKED", "SENT"):
        j.transition(i.id, status, at=T)
    j.close()  # Actual process-boundary witness, not an alias of normal dispatch.
    resumed = Journal(path)
    transport = FakeTransport()
    e = DisabledExecutor(resumed, transport, fake_rehearsal=True)
    with pytest.raises(ValueError):
        e.dispatch(i, state())
    values = dict(
        at=T + timedelta(minutes=1),
        direction="charge",
        power_ac_kw=2,
        energy_ac_kwh=0.1,
        throughput_stored_kwh=0.1,
        energy_stored_kwh=0.6,
        ownership_generation=1,
        effect_observed=False,
        neutral_observed=False,
        import_cost_aud=0.01,
        feedback_fresh=True,
        bms_healthy=True,
    )
    assert e.observe(i, **values) == "UNKNOWN_DELIVERY"
    assert transport.calls == []
    assert e.observe(i, **(values | {"import_cost_aud": 1})) == "ABORTED"
    other = intent(actor="other")
    resumed.propose(other)
    with pytest.raises(sqlite3.IntegrityError):
        resumed.transition(other.id, "APPROVED", at=T)
    assert (
        e.observe(i, **(values | {"neutral_observed": True}))
        == "NEUTRAL_STATE_VERIFIED"
    )
    resumed.transition(other.id, "APPROVED", at=T)
    resumed.close()


def test_flat_export_price_later_pv_opportunity_cost_is_not_free():
    case = export_case(eta=0.9)
    case = replace(
        case,
        export_price_aud_per_kwh=tuple(
            replace(p, value=0.5) for p in case.export_price_aud_per_kwh
        ),
    )
    result = compare(case, envelope(case))
    assert result["primary_conditional_value_aud"] == pytest.approx(-0.025)


@pytest.mark.parametrize(
    "fault", ["HA_loss", "stale", "BMS", "clock", "cost_missing_at_expiry"]
)
def test_feedback_failure_preserves_durable_lock(tmp_path, fault):
    j = Journal(tmp_path / "feedback.db")
    i = intent()
    j.propose(i)
    j.transition(i.id, "APPROVED", at=T)
    e = DisabledExecutor(j, FakeTransport(), fake_rehearsal=True)
    e.dispatch(i, state())
    values = dict(
        at=T + timedelta(minutes=1),
        direction="charge",
        power_ac_kw=2,
        energy_ac_kwh=0.1,
        throughput_stored_kwh=0.1,
        energy_stored_kwh=0.6,
        ownership_generation=1,
        effect_observed=False,
        neutral_observed=False,
        import_cost_aud=0.01,
        feedback_fresh=True,
        bms_healthy=True,
    )
    if fault in {"HA_loss", "stale"}:
        values["feedback_fresh"] = False
    if fault == "BMS":
        values["bms_healthy"] = False
    if fault == "clock":
        values["at"] = T - timedelta(seconds=1)
    if fault == "cost_missing_at_expiry":
        values.update(at=i.expires_at, import_cost_aud=None)
    assert e.observe(i, **values) == (
        "RESTORE_FAILED" if fault == "cost_missing_at_expiry" else "ABORTED"
    )
    other = intent(actor="second")
    j.propose(other)
    with pytest.raises(sqlite3.IntegrityError):
        j.transition(other.id, "APPROVED", at=T)
    j.close()


@pytest.mark.parametrize(
    "action,direction",
    [
        ("PRESERVE_BATTERY", "inhibit"),
        ("DISCHARGE_FOR_SELF_CONSUMPTION", "discharge"),
        ("EXPORT_BATTERY_AC", "discharge"),
    ],
)
def test_fake_action_families_require_individual_approval_and_export_caps(
    tmp_path, action, direction
):
    j = Journal(tmp_path / "families.db")
    i = intent(action=action, permitted_actions=(action,))
    j.propose(i)
    j.transition(i.id, "APPROVED", at=T)
    transport = FakeTransport()
    e = DisabledExecutor(j, transport, fake_rehearsal=True)
    assert (
        e.dispatch(
            i,
            state(
                expected_direction=direction,
                effective_export_kw=2,
                export_price_aud_per_kwh=0.1,
            ),
        )
        == "ACKNOWLEDGED"
    )
    assert len(transport.calls) == 1
    j.close()
    if action == "EXPORT_BATTERY_AC":
        for bad in (
            {"export_price_aud_per_kwh": -0.1},
            {"effective_export_kw": 1},
            {"effective_export_kw": None},
        ):
            from energy_optimizer.arbitrage.executor import precheck_reasons

            assert precheck_reasons(
                i,
                state(
                    **(
                        {
                            "expected_direction": direction,
                            "effective_export_kw": 2,
                            "export_price_aud_per_kwh": 0.1,
                        }
                        | bad
                    )
                ),
            )
