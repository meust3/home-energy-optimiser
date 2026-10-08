import ast
import json
import runpy
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path

import pytest

from energy_optimizer.arbitrage.core_bridge import align, make_inputs
from energy_optimizer.arbitrage.decision_types import (
    Point,
    canonical,
    decision_from_dict,
    digest,
    primitive,
)
from energy_optimizer.arbitrage.outcomes import (
    OutcomeContext,
    QuoteHealth,
    evaluate_outcome,
    summarize,
)
from energy_optimizer.arbitrage.research_io import append_receipt, load_core
from energy_optimizer.arbitrage.selector import POLICY_SHA, admission, choose, select
from energy_optimizer.arbitrage.synthetic_cases import authored_case

HERE = Path(__file__).resolve().parents[1] / "src/energy_optimizer/arbitrage"
CONFIG = {"core_root": HERE.parents[2], "core_manifest": None}


@pytest.fixture(scope="session")
def core():
    return load_core(CONFIG["core_root"], CONFIG["core_manifest"])


def run(core, c):
    return select(core, c, digest("test-source-identity"))


def estimates(receipt):
    return json.loads(receipt.estimates_json)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("hold", "HOLD"),
        ("preservation", "P"),
        ("charging", "G"),
        ("charging_without_preservation_benefit", "G"),
        ("zero_delivery_preservation", "P"),
        ("negative_price", "G"),
    ],
)
def test_authored_choices(core, kind, expected):
    r = run(core, authored_case(kind))
    assert r.selected == expected, r.reasons
    e = estimates(r)
    assert abs(e["cash_decomposition_residual_aud"]) < 1e-9
    assert abs(e["energy_decomposition_residual_kwh"]) < 1e-9
    if kind == "charging_without_preservation_benefit":
        assert e["costs_aud"] == pytest.approx({"R": 1.05, "P": 1.15, "G": 0.45})
    if kind == "zero_delivery_preservation":
        assert e["paths"]["G"]["delivered_action_ac_kwh"] == 0
        assert e["pg_physically_equivalent"]
        assert (
            e["comparisons"]["preservation"]["primary_comparative_gross_value_aud"] > 0
        )


@pytest.mark.parametrize("field", ["demand", "pv", "import_price", "export_price"])
def test_missing_forecast(core, field):
    r = run(core, replace(authored_case(), **{field: None}))
    assert r.selected == "HOLD" and estimates(r) is None
    assert field + ":missing" in r.reasons


@pytest.mark.parametrize(
    "variation",
    [
        "future_issue",
        "future_available",
        "stale",
        "unhealthy",
        "no_basis",
        "bad_hash",
        "bad_kind",
    ],
)
def test_evidence_gates(core, variation):
    c = authored_case()
    changes = {
        "future_issue": {"issued_at": c.cutoff + timedelta(seconds=1)},
        "future_available": {"available_at": c.cutoff + timedelta(seconds=1)},
        "stale": {"fresh_until": c.cutoff - timedelta(seconds=1)},
        "unhealthy": {"healthy": False},
        "no_basis": {"availability_basis": ""},
        "bad_hash": {"source_sha256": "x"},
        "bad_kind": {"availability_kind": "valid_time"},
    }[variation]
    c = replace(c, pv=replace(c.pv, evidence=replace(c.pv.evidence, **changes)))
    assert run(core, c).selected == "HOLD"
    assert estimates(run(core, c)) is None


def test_future_valid_time_allowed_when_already_available(core):
    c = authored_case()
    assert c.pv.points[-1].start > c.cutoff
    assert run(core, c).selected == "G"
    c = replace(
        c,
        pv=replace(
            c.pv,
            evidence=replace(c.pv.evidence, availability_kind="documented_upper_bound"),
        ),
    )
    assert run(core, c).selected == "G"


@pytest.mark.parametrize(
    "target", ["baseline_household_load", "household_load", "unknown"]
)
def test_unsupported_total_target(core, target):
    c = authored_case()
    assert (
        run(core, replace(c, demand=replace(c.demand, target=target))).selected
        == "HOLD"
    )


def test_named_baseline_plus_ev_is_counted_once(core):
    c = authored_case()
    d = replace(
        c.demand,
        target="baseline_household_load",
        points=tuple(replace(p, value=p.value - 0.5) for p in c.demand.points),
    )
    ev = replace(
        c.demand,
        target="named_uncontrolled_load_scenario",
        basis="explicit fixed EV scenario",
        points=tuple(replace(p, value=0.5) for p in c.demand.points),
    )
    modified = replace(c, demand=d, uncontrolled_load=ev)
    assert (
        estimates(run(core, modified))["costs_aud"]
        == estimates(run(core, c))["costs_aud"]
    )
    assert run(core, replace(c, uncontrolled_load=ev)).selected == "HOLD"


@pytest.mark.parametrize("minutes", [0, 5, 25, 29])
def test_short_coverage(core, minutes):
    c = authored_case()
    points = (
        ()
        if minutes == 0
        else (Point(c.action_start, c.action_start + timedelta(minutes=minutes), 0),)
    )
    r = run(core, replace(c, pv=replace(c.pv, points=points)))
    assert r.selected == "HOLD" and estimates(r) is None


def test_gap_truncation_and_horizon_value_independence(core):
    c = authored_case()
    points = (
        c.pv.points[0],
        replace(c.pv.points[1], start=c.action_start + timedelta(minutes=35)),
        c.pv.points[2],
    )
    c = replace(c, pv=replace(c.pv, points=points))
    r = run(core, c)
    assert r.horizon_end == c.action_end
    changed = replace(
        c,
        import_price=replace(
            c.import_price,
            points=tuple(replace(p, value=-100) for p in c.import_price.points),
        ),
    )
    assert run(core, changed).horizon_end == r.horizon_end


def test_cap_and_round_down(core):
    c = authored_case()

    def expand(name, hours):
        s = getattr(c, name)
        return replace(
            s,
            points=(
                Point(
                    c.action_start,
                    c.action_start + timedelta(hours=hours),
                    s.points[0].value,
                ),
            ),
        )

    c = replace(
        c,
        **{k: expand(k, 25) for k in ("demand", "pv", "import_price", "export_price")},
    )
    assert admission(core, c)[1] == c.action_start + timedelta(hours=24)
    c = replace(
        c,
        pv=replace(
            c.pv,
            points=(
                replace(c.pv.points[0], end=c.action_start + timedelta(minutes=43)),
            ),
        ),
    )
    assert admission(core, c)[1] == c.action_start + timedelta(minutes=40)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1, True])
def test_bad_power(core, value):
    c = authored_case()
    c = replace(
        c,
        pv=replace(
            c.pv, points=(replace(c.pv.points[0], value=value),) + c.pv.points[1:]
        ),
    )
    assert run(core, c).selected == "HOLD"


def test_losses_and_clipping(core):
    c = authored_case("negative_price")
    c = replace(
        c,
        assumptions=replace(
            c.assumptions,
            charge_efficiency=0.9,
            discharge_efficiency=0.9,
            import_limit_kw=2,
        ),
    )
    e = estimates(run(core, c))
    assert e["paths"]["G"]["delivered_action_ac_kwh"] == pytest.approx(0.5)
    assert e["paths"]["G"]["requested_action_ac_kwh"] == pytest.approx(1)
    assert e["paths"]["G"]["loss_kwh"] > 0
    assert all(
        r["maximum_balance_residual_kwh"] < 1e-9
        for r in e["independent_reconciliation"].values()
    )


def test_timing_and_no_catchup(core):
    c = authored_case()
    r = run(
        core,
        replace(
            c,
            ready_at=c.ready_at + timedelta(seconds=1),
            cutoff=c.cutoff + timedelta(seconds=1),
        ),
    )
    assert r.selected == "HOLD"
    shifted = decision_from_dict(primitive(c))
    shift = timedelta(minutes=5)
    changes = {}
    for key in ("demand", "pv", "import_price", "export_price"):
        s = getattr(c, key)
        changes[key] = replace(
            s,
            points=tuple(
                replace(p, start=p.start + shift, end=p.end + shift) for p in s.points
            ),
        )
    shifted = replace(
        shifted,
        ready_at=c.ready_at + timedelta(seconds=1),
        cutoff=c.cutoff + timedelta(seconds=1),
        action_start=c.action_start + shift,
        action_end=c.action_end + shift,
        branch=replace(c.branch, at=c.branch.at + shift),
        reserve=replace(c.reserve, at=c.reserve.at + shift),
        **changes,
    )
    e = estimates(run(core, shifted))
    assert e["paths"]["G"]["requested_action_ac_kwh"] == pytest.approx(1)
    for s in e["original_ledgers"]["G"]["steps"]:
        if s["start_utc"] >= shifted.action_end.isoformat():
            assert s["requested_action_ac_kwh"] == 0
    assert (
        run(core, replace(shifted, action_end=shifted.action_end + shift)).selected
        == "HOLD"
    )


def test_initial_deficit_and_terminal_reserve(core):
    c = authored_case("hold")
    c = replace(c, reserve=replace(c.reserve, floor_kwh=1))
    e = estimates(run(core, c))
    assert e["paths"]["R"]["initial_policy_shortfall_kwh"] == pytest.approx(0.5)
    assert (
        e["comparisons"]["preservation"]["primary_comparative_gross_value_aud"] is None
    )
    assert any(
        "terminal_reserve" in r
        for r in e["comparisons"]["preservation"]["primary_unavailable_reasons"]
    )


def test_unmatched_terminal_does_not_get_free_value(core):
    r = run(core, authored_case("hold"))
    e = estimates(r)
    assert e["comparisons"]["combined"]["primary_comparative_gross_value_aud"] is None
    assert (
        "terminal_energy_unmatched"
        in e["comparisons"]["combined"]["primary_unavailable_reasons"]
    )
    assert r.selected == "HOLD"


def outcome_for(c, r):
    return OutcomeContext(
        "authored-outcome",
        r.sha256,
        "authored_synthetic",
        digest("authored-outcome"),
        "authored total AC load and fixed PV proxies",
        c.action_start,
        r.horizon_end,
        c.demand.points,
        c.pv.points,
        c.import_price.points,
        c.export_price.points,
        (QuoteHealth(c.action_start, r.horizon_end, True, "authored healthy quotes"),),
        False,
        False,
    )


def test_outcome_perturbation_and_receipt_immutability(core):
    c = authored_case()
    r = run(core, c)
    frozen = canonical(r)
    o = outcome_for(c, r)
    first = evaluate_outcome(core, c, r, o)
    second = evaluate_outcome(
        core,
        c,
        r,
        replace(o, import_quotes=tuple(replace(p, value=-10) for p in o.import_quotes)),
    )
    assert first["realised_proxy"]["costs_aud"] != second["realised_proxy"]["costs_aud"]
    assert canonical(r) == frozen and run(core, c) == r
    with pytest.raises(FrozenInstanceError):
        r.selected = "P"
    with pytest.raises(TypeError):
        select(core, o, digest("x"))
    raw = primitive(c)
    raw["outcomes"] = {}
    with pytest.raises(ValueError, match="contract_fields"):
        decision_from_dict(raw)


def test_invalid_and_unmatched_outcomes_retained(core):
    c = authored_case()
    r = run(core, c)
    o = outcome_for(c, r)
    bad = replace(o, import_quotes=())
    result = evaluate_outcome(core, c, r, bad)
    assert (
        result["realised_proxy"] is None
        and result["raw_outcome"]["import_quotes"] == []
    )
    unmatched = replace(
        o, total_household_kw=tuple(replace(p, value=0) for p in o.total_household_kw)
    )
    result = evaluate_outcome(core, c, r, unmatched)
    assert result["realised_proxy"] is not None
    assert result["selected_vs_R_aud"] is None
    assert any("terminal_energy_unmatched" in x for x in result["unavailable_reasons"])


def test_unhealthy_quote_components_include_later_effects(core):
    c = authored_case()
    r = run(core, c)
    o = outcome_for(c, r)
    o = replace(
        o,
        quote_health=(
            QuoteHealth(c.action_start, c.action_end, False, "authored health failure"),
            QuoteHealth(c.action_end, r.horizon_end, True, "authored healthy"),
        ),
    )
    result = evaluate_outcome(core, c, r, o)
    q = result["quote_dependence"]
    assert q["charging_increment"]["unhealthy_quote_contribution_aud"] == pytest.approx(
        -0.3
    )
    assert q["charging_increment"][
        "later_healthy_interval_contribution_aud"
    ] == pytest.approx(1)
    assert result["eligibility_counts"] == {
        "numerical": 1,
        "quote_qualified": 0,
        "strict": 0,
    }
    assert result["false_positive"] is None
    assert summarize([result])["eligibility"]["strict"] == 0


def test_hashes_roundtrip_deterministic_exclusive_receipts(core, tmp_path):
    c = authored_case()
    r = run(core, c)
    assert run(core, decision_from_dict(primitive(c))) == r
    assert r.policy_sha256 == POLICY_SHA and r.input_sha256 == digest(c)
    append_receipt(tmp_path, r)
    with pytest.raises(FileExistsError):
        append_receipt(tmp_path, r)
    assert run(core, replace(c, context_id="changed")).input_sha256 != r.input_sha256


def test_original_cli_rejects_arbitrary_file(monkeypatch):
    path = Path(CONFIG["core_root"]) / "tools/evaluate_paired_synthetic.py"
    monkeypatch.setattr(sys, "argv", [str(path), "--fixture", "private-household.json"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(path), run_name="__main__")
    assert error.value.code == 2


def test_no_runtime_or_outcome_imports_in_selector():
    for name in ("selector.py", "decision_types.py", "core_bridge.py"):
        tree = ast.parse((HERE / name).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not any(
            i
            and (
                (
                    i.startswith("energy_optimizer")
                    and i
                    not in {
                        "energy_optimizer.arbitrage.core_bridge",
                        "energy_optimizer.arbitrage.decision_types",
                    }
                )
                or i
                in (
                    "os",
                    "socket",
                    "requests",
                    "sqlite3",
                    "psycopg",
                    "outcomes",
                    "openai",
                    "dotenv",
                )
            )
            for i in imports
        )
    assert "OutcomeContext" not in (HERE / "decision_types.py").read_text()


def test_infeasible_paths_cannot_win(core):
    c = authored_case()
    c = replace(c, assumptions=replace(c.assumptions, import_limit_kw=0))
    r = run(core, c)
    assert r.selected == "HOLD"
    assert estimates(r)["paths"]["G"]["unserved_load_kwh"] > 0


def test_comparator_tolerances_unchanged(core):
    assert core.TERMINAL_TOLERANCE_KWH == 1e-6
    assert core.NUMERICAL_EPSILON == 1e-9


def test_observed_future_state_rejected(core):
    c = authored_case()
    c = replace(
        c,
        branch=replace(
            c.branch,
            kind="observed_soc_capacity_proxy",
            at=c.branch.at + timedelta(minutes=5),
        ),
    )
    assert run(core, c).selected == "HOLD"


@pytest.mark.parametrize("seed", range(20))
def test_fractional_event_partition_reconciliation(core, seed):
    import random

    randomizer = random.Random(seed)
    c = authored_case("charging")
    c = replace(
        c,
        assumptions=replace(
            c.assumptions,
            charge_efficiency=randomizer.uniform(0.8, 1),
            discharge_efficiency=randomizer.uniform(0.8, 1),
            import_limit_kw=randomizer.uniform(1, 5),
            charge_limit_kw=randomizer.uniform(0.3, 3),
        ),
        branch=replace(c.branch, energy_kwh=randomizer.uniform(0.05, 1.9)),
    )
    c = replace(
        c,
        demand=replace(
            c.demand,
            points=tuple(
                replace(p, value=randomizer.uniform(0.1, 4)) for p in c.demand.points
            ),
        ),
        pv=replace(
            c.pv,
            points=tuple(
                replace(p, value=randomizer.uniform(0, 3)) for p in c.pv.points
            ),
        ),
    )
    e = estimates(run(core, c))
    assert e is not None
    assert abs(e["cash_decomposition_residual_aud"]) < 1e-9
    assert all(
        v["maximum_balance_residual_kwh"] < 1e-9
        for v in e["independent_reconciliation"].values()
    )


def test_cash_tolerance_and_unavailable_do_not_qualify():
    base = {
        "costs_aud": {"R": 1, "P": 1 - 5e-9, "G": 0.1},
        "comparisons": {
            "preservation": {"primary_comparative_gross_value_aud": 5e-9},
            "combined": {"primary_comparative_gross_value_aud": 0.9},
            "charging_increment": {"primary_comparative_gross_value_aud": None},
        },
        "pg_physically_equivalent": False,
        "paths": {"G": {"delivered_action_ac_kwh": 1}},
    }
    assert choose(base)[0] == "HOLD"
    base["costs_aud"]["P"] = 0.1
    base["comparisons"]["preservation"]["primary_comparative_gross_value_aud"] = 0.9
    base["comparisons"]["charging_increment"]["primary_comparative_gross_value_aud"] = 0
    assert choose(base)[0] == "P"


def test_corrupted_partition_not_repaired(core):
    c = authored_case()
    case = make_inputs(core, c, c.demand.points[-1].end, "PRESERVE_BATTERY")
    reference, _ = core._simulate_pair(case)
    corrupt = replace(
        reference,
        steps=(replace(reference.steps[0], load_kwh=9),) + reference.steps[1:],
    )
    boundaries = sorted({t for s in reference.steps for t in (s.start_utc, s.end_utc)})
    with pytest.raises(ValueError, match="source_energy_mismatch"):
        align(core, corrupt, boundaries, case)


@pytest.mark.parametrize(
    "event,args",
    [
        ("socket.connect", ()),
        ("sqlite3.connect", ()),
        ("subprocess.Popen", ()),
        ("open", ("example.env", "r")),
        ("import", ("openai",)),
        ("import", ("psycopg",)),
    ],
)
def test_offline_audit_guards(event, args):
    from energy_optimizer.arbitrage.offline_guard import guard

    with pytest.raises(RuntimeError, match="offline_guard"):
        guard(event, args)


def test_incomplete_or_mismatched_outcome_not_selected(core):
    c = authored_case()
    r = run(core, c)
    o = outcome_for(c, r)
    for changed in (
        replace(o, receipt_sha256="0" * 64),
        replace(o, end=o.end + timedelta(minutes=5)),
        replace(o, quote_health=()),
    ):
        result = evaluate_outcome(core, c, r, changed)
        assert result["realised_proxy"] is None and result["selected"] == r.selected


@pytest.mark.parametrize(
    "field,value",
    [
        ("capacity_kwh", None),
        ("charge_efficiency", 0),
        ("discharge_efficiency", 1.1),
        ("topology", "shared_inverter"),
        ("curtailment_permitted", None),
    ],
)
def test_invalid_assumptions_hold(core, field, value):
    c = authored_case()
    r = run(core, replace(c, assumptions=replace(c.assumptions, **{field: value})))
    assert r.selected == "HOLD" and estimates(r) is None


def test_later_false_positive_metrics_have_denominators(core):
    c = authored_case()
    r = run(core, c)
    o = outcome_for(c, r)
    changed = replace(
        o,
        import_quotes=tuple(
            replace(p, value=10 if i == 0 else 0.1)
            for i, p in enumerate(o.import_quotes)
        ),
    )
    result = evaluate_outcome(core, c, r, changed)
    assert result["false_positive"] is True
    assert result["charging_increment_false_positive"] is True
    assert result["prediction_errors_aud"]["combined"]["both_primary_available"]
    counts = summarize([result])
    assert counts["false_positive_evaluable"] == 1
    assert counts["charging_increment_evaluable"] == 1
    assert counts["missed_opportunity_evaluable"] == 1


def test_forced_hold_not_counted_as_success(core):
    c = replace(authored_case(), demand=None)
    r = run(core, c)
    good = authored_case()
    o = outcome_for(good, run(core, good))
    o = replace(o, receipt_sha256=r.sha256)
    result = evaluate_outcome(core, c, r, o)
    assert result["false_positive"] is None
    assert result["missed_opportunity"] is None
    assert summarize([result])["false_positive_evaluable"] == 0
