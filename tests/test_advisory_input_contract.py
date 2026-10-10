"""Authored source-shaped v2 contracts; no household identifiers or later data."""

import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_arbitrage_programme import T, bundle
from test_arbitrage_programme import capture_db as capture_db

from energy_optimizer.arbitrage.advisory_inputs import (
    FIXED_RESERVE,
    LINKED_RESERVE,
    PRICE_BOUNDARY,
    PRICE_RAW,
    PRICE_SOURCE,
    PROFILE_VERSION,
    RESERVE_FIELD,
    interpret_prices,
    profile_modes,
    validate_price_times,
)
from energy_optimizer.arbitrage.archive import context_from_capture
from energy_optimizer.arbitrage.capture import (
    SOURCES,
    CaptureRepository,
    capture_forecast,
    snapshot_states,
)
from energy_optimizer.arbitrage.decision_types import canonical, digest, primitive
from energy_optimizer.arbitrage.opportunity import (
    board,
    declared_context,
    save_opportunity,
)
from energy_optimizer.arbitrage.research_io import integration_source_sha, load_core
from energy_optimizer.arbitrage.selector import POLICY_SHA, select
from energy_optimizer.models import ForecastPoint, ForecastRun


def shaped(*, floor=0.0, linked=False, offset=1, minutes=30):
    inputs, source, old = bundle()
    source["body"].update(version="arbitrage-capture-v1", kind="source")
    for alias in ("import_forecast", "export_forecast"):
        original = source["body"]["sources"][alias]["forecasts"]
        if minutes == 5:
            original = [
                {
                    **p,
                    "start_time": (T + timedelta(minutes=5 * i)).isoformat(),
                    "end_time": (T + timedelta(minutes=5 * (i + 1))).isoformat(),
                }
                for i in range(18)
                for p in [original[i // 6]]
            ]
        source["body"]["sources"][alias]["forecasts"] = [
            {
                **p,
                "start_time": (
                    T.fromisoformat(p["start_time"]) + timedelta(seconds=offset)
                ).isoformat(),
                "duration": minutes,
            }
            for p in original
        ]
    inputs["body"].update(
        version="arbitrage-capture-v1",
        kind="decision_inputs",
        forecast_id=1,
        reserve_id=10,
        operation_id=1,
        model="household-demand-hierarchy-v1-cohort-v1",
        forecast_type="baseline_household_load",
        no_command_issued=True,
        load_basis="authored baseline plus explicit zero-EV scenario",
    )
    estimate = {
        RESERVE_FIELD: floor,
        "recommended_reserve_kwh": floor,
        "forecast_run_id": None,
        "usable_battery_capacity_kwh": 2.0,
        "command_issued": False,
        "horizon_is_valid": True,
    }
    inputs["body"]["reserve"] = {
        "id": 10,
        "forecast_run_id": 1,
        "model_version": "reserve-estimator-v1",
        RESERVE_FIELD: floor,
        "recommended_reserve_kwh": floor,
        "usable_battery_capacity_kwh": 2.0,
        "evaluation_timestamp_utc": T.isoformat(),
        "observation_timestamp_utc": T.isoformat(),
        "observation_is_stale": False,
        "observation_age_seconds": 0,
        "command_issued": False,
        "forecast_start_utc": T.isoformat(),
        "forecast_end_utc": (T + timedelta(hours=24)).isoformat(),
        "estimate_json": estimate,
        "health_json": {"telemetry": {"is_healthy": True}},
    }
    profile = copy.deepcopy(old)
    profile.pop("floor_kwh")
    profile.update(
        schema_version=PROFILE_VERSION,
        price_interpretation={"mode": PRICE_BOUNDARY, "source": PRICE_SOURCE},
        reserve_binding=(
            {"mode": LINKED_RESERVE, "quantity": RESERVE_FIELD, "unit": "stored_kWh"}
            if linked
            else {"mode": FIXED_RESERVE, "floor_kwh": floor}
        ),
    )
    rehash(inputs, source)
    return inputs, source, profile, old


def rehash(inputs, source):
    source["body_sha256"] = digest(source["body"])
    inputs["body_sha256"] = digest(inputs["body"])


def context(inputs, source, profile):
    validate_price_times(source, profile_modes(profile)[0])
    c = context_from_capture(
        inputs, source, primitive(declared_context(inputs, source, profile))
    )
    return interpret_prices(c, source, profile_modes(profile)[0])


@pytest.mark.parametrize("minutes", [5, 30])
@pytest.mark.parametrize("offset", [0, 1])
def test_explicit_periods_quotes_provenance_and_raw_preservation(minutes, offset):
    i, s, p, old = shaped(minutes=minutes, offset=offset)
    before = canonical([i, s])
    c = context(i, s, p)
    r = select(load_core(), c, integration_source_sha())
    assert json.loads(r.estimates_json) is not None and r.policy_sha256 == POLICY_SHA
    info = json.loads(c.import_price.basis)
    assert info["raw_duration_seconds"] == len(info["segments"]) * (
        minutes * 60 - offset
    )
    assert info["interpreted_duration_seconds"] == len(info["segments"]) * minutes * 60
    assert info["interpreted_start_count"] == len(info["segments"]) * offset
    assert all(
        x[4] == minutes * 60 - offset and x[5] == minutes * 60 for x in info["segments"]
    )
    assert all(
        x[2] == point.start.isoformat()
        for x, point in zip(info["segments"], c.import_price.points, strict=True)
    )
    assert [x.value for x in c.import_price.points] == [
        x["per_kwh"] for x in s["body"]["sources"]["import_forecast"]["forecasts"]
    ]
    assert canonical([i, s]) == before and info["capture_sha256"] == s["body_sha256"]
    assert (
        c.import_price.evidence.issued_at == T
        and c.import_price.evidence.available_at == T
    )
    raw = context(i, s, old)
    raw_receipt = select(load_core(), raw, integration_source_sha())
    if offset:
        assert (
            raw_receipt.estimates_json == "null"
            and "coverage_does_not_include_complete_action" in raw_receipt.reasons
        )
        assert digest(raw) != digest(c)


@pytest.mark.parametrize(
    "fault",
    [
        "two_seconds",
        "fractional",
        "missing_period",
        "duration",
        "missing_duration",
        "overlap",
        "duplicate",
        "reverse",
        "timestamp",
        "source",
        "channel",
        "unit",
        "wrong_envelope",
    ],
)
def test_bad_interval_and_attribution_rejected(fault):
    i, s, p, _ = shaped()
    raw = s["body"]["sources"]["import_forecast"]
    rows = raw["forecasts"]
    if fault in ("two_seconds", "fractional"):
        rows[0]["start_time"] = (
            T + timedelta(seconds=2 if fault == "two_seconds" else 0.5)
        ).isoformat()
    elif fault == "missing_period":
        rows.pop(1)
    elif fault == "duration":
        rows[0]["duration"] = 5
    elif fault == "missing_duration":
        rows[0].pop("duration")
    elif fault == "overlap":
        rows[1] = copy.deepcopy(rows[0])
    elif fault == "duplicate":
        rows.insert(1, copy.deepcopy(rows[0]))
    elif fault == "reverse":
        rows[0]["end_time"] = T.isoformat()
    elif fault == "timestamp":
        rows[0]["start_time"] = "unavailable"
    elif fault == "source":
        raw["entity_id"] = "sensor.other_price"
    elif fault == "channel":
        raw["channel_type"] = "controlledLoad"
    elif fault == "unit":
        raw["attributes"]["unit_of_measurement"] = "c/kWh"
    else:
        s["body"]["version"] = "unknown-capture"
    rehash(i, s)
    with pytest.raises((ValueError, TypeError, KeyError)):
        context(i, s, p)


@pytest.mark.parametrize("quote", [None, float("nan"), float("inf"), True])
def test_bad_quotes_never_become_zero(quote):
    i, s, p, _ = shaped()
    s["body"]["sources"]["import_forecast"]["forecasts"][0]["per_kwh"] = quote
    rehash(i, s)
    with pytest.raises(ValueError, match="amber_price_missing_or_nonfinite"):
        context(i, s, p)


@pytest.mark.parametrize("quote", [0, -0.25])
def test_zero_and_negative_quote_preserved(quote):
    i, s, p, _ = shaped()
    s["body"]["sources"]["import_forecast"]["forecasts"][0]["per_kwh"] = quote
    rehash(i, s)
    assert context(i, s, p).import_price.points[0].value == quote


def test_fixed_and_two_linked_floors_frozen_each_comparison():
    results = []
    for floor in (0.25, 1.0):
        i, s, p, _ = shaped(floor=floor, linked=True)
        c = context(i, s, p)
        r = select(load_core(), c, integration_source_sha())
        assert c.reserve.floor_kwh == floor and c.branch.energy_kwh == 0.5
        binding = json.loads(c.reserve.basis)
        assert (
            binding["snapshot_sha256"] == digest(i["body"]["reserve"])
            and binding["source_field"] == RESERVE_FIELD
        )
        e = json.loads(r.estimates_json)
        assert all(
            x["initial_policy_shortfall_kwh"] == max(0, floor - 0.5)
            for x in e["paths"].values()
        )
        results.append(c)
    assert digest(results[0]) != digest(results[1])
    i, s, p, _ = shaped(floor=0.25, linked=True)
    p["reserve_binding"] = {"mode": FIXED_RESERVE, "floor_kwh": 0.75}
    assert context(i, s, p).reserve.floor_kwh == 0.75


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "id",
        "forecast",
        "future",
        "stale",
        "quantity",
        "capacity",
        "unit",
        "model",
        "target",
        "health",
        "horizon",
        "estimate",
        "observation_future",
        "hash",
    ],
)
def test_linked_reserve_invalid_never_falls_back(fault):
    i, s, p, _ = shaped(floor=1.0, linked=True)
    r = i["body"]["reserve"]
    if fault == "missing":
        i["body"]["reserve"] = None
    elif fault == "id":
        r["id"] = 99
    elif fault == "forecast":
        r["forecast_run_id"] = 99
    elif fault == "future":
        r["evaluation_timestamp_utc"] = (T + timedelta(seconds=1)).isoformat()
    elif fault == "stale":
        r["observation_is_stale"] = True
    elif fault == "quantity":
        r[RESERVE_FIELD] = None
    elif fault == "capacity":
        r["usable_battery_capacity_kwh"] = 2000
    elif fault == "unit":
        r["unit"] = "Wh"
    elif fault == "model":
        r["model_version"] = "other"
    elif fault == "target":
        i["body"]["forecast_type"] = "total_house_load"
    elif fault == "health":
        r["health_json"]["telemetry"]["is_healthy"] = False
    elif fault == "horizon":
        r["estimate_json"]["horizon_is_valid"] = False
    elif fault == "estimate":
        r["estimate_json"][RESERVE_FIELD] = 0
    elif fault == "observation_future":
        r["observation_timestamp_utc"] = (T + timedelta(seconds=1)).isoformat()
    rehash(i, s)
    if fault == "hash":
        i["body_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="linked_reserve"):
        context(i, s, p)


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "unknown_price",
        "unknown_reserve",
        "extra",
        "linked_floor",
        "quantity",
    ],
)
def test_profile_version_and_modes_exact(fault):
    i, s, p, _ = shaped(linked=True)
    if fault == "version":
        p["schema_version"] = "v3"
    elif fault == "unknown_price":
        p["price_interpretation"]["mode"] = "automatic"
    elif fault == "unknown_reserve":
        p["reserve_binding"]["mode"] = "latest"
    elif fault == "extra":
        p["extra"] = 0
    elif fault == "linked_floor":
        p["reserve_binding"]["floor_kwh"] = 0
    else:
        p["reserve_binding"]["quantity"] = "technical_reserve_kwh"
    with pytest.raises(ValueError):
        context(i, s, p)


def test_explicit_raw_mode_stays_strict_and_late_profile_is_rejected():
    i, s, p, _ = shaped()
    p["price_interpretation"] = {"mode": PRICE_RAW}
    assert (
        select(load_core(), context(i, s, p), integration_source_sha()).estimates_json
        == "null"
    )
    p["price_interpretation"] = {"mode": PRICE_BOUNDARY, "source": PRICE_SOURCE}
    p["evidence"]["available_at"] = (T + timedelta(seconds=1)).isoformat()
    r = select(load_core(), context(i, s, p), integration_source_sha())
    assert r.estimates_json == "null" and any(
        "unavailable_at_cutoff" in x for x in r.reasons
    )


def test_full_capacity_floor_no_discharge_and_identity():
    i, s, p, _ = shaped(floor=2, linked=True)
    c = context(i, s, p)
    r = select(load_core(), c, integration_source_sha())
    e = json.loads(r.estimates_json)
    assert c.branch.energy_kwh == 0.5 and c.reserve.floor_kwh == 2
    assert e["costs_aud"]["R"] == e["costs_aud"]["P"]
    assert all(x["discharged_dc_kwh"] == 0 for x in e["paths"].values())


def test_new_modes_persist_privately_and_get_does_not_write(capture_db):
    repo, _ = capture_db
    i, s, p, _ = shaped(linked=True)
    store = CaptureRepository(repo)
    source_id = store.save(
        origin="authored-source", kind="source", at=T, body=s["body"], clock=lambda: T
    )
    i["body"]["source_capture_id"] = source_id
    store.save(
        origin="authored-input",
        kind="decision_inputs",
        at=T,
        body=i["body"],
        clock=lambda: T,
    )
    save_opportunity(repo, profile_json=canonical(p))
    row = store.latest("opportunity")
    assert row["body"]["input_semantics"]["reserve_binding"]["reserve_id"] == 10
    assert row["body"]["execution"] == "disabled" and row["body"]["research_only"]
    before = digest(row)
    response = board(repo, now=T - timedelta(seconds=1))
    assert (
        "context" not in response["items"][0]
        and digest(store.latest("opportunity")) == before
    )


def test_actual_capture_producers_bind_exact_audit_id(capture_db, monkeypatch):
    repo, _ = capture_db
    i, s, p, _ = shaped(floor=1, linked=True)
    original = CaptureRepository.save

    def saved_at_fixture_time(self, **kwargs):
        kwargs.setdefault("clock", lambda: T)
        return original(self, **kwargs)

    monkeypatch.setattr(CaptureRepository, "save", saved_at_fixture_time)
    states = {}
    for alias, raw in s["body"]["sources"].items():
        if raw:
            attrs = {**raw["attributes"]}
            for field in ("forecasts", "detailedForecast"):
                if field in raw:
                    attrs[field] = raw[field]
            states[SOURCES[alias]] = SimpleNamespace(
                state=raw.get("state", "0"), last_updated=T, attributes=attrs
            )
    store = CaptureRepository(repo)
    raw_body = snapshot_states(states, slot=T, received_at=T)
    store.save(origin="producer", kind="source", at=T, body=raw_body)
    lookup_ids = []

    def exact_audit(reserve_id):
        lookup_ids.append(reserve_id)
        return copy.deepcopy(i["body"]["reserve"])

    monkeypatch.setattr(repo, "reserve_audit_read_only", exact_audit)
    forecast = ForecastRun(
        created_at_utc=T,
        forecast_type="baseline_household_load",
        source="authored",
        horizon_start_utc=T,
        horizon_end_utc=T + timedelta(minutes=90),
        model_version="household-demand-hierarchy-v1-cohort-v1",
        points=[
            ForecastPoint(
                period_start_utc=T.fromisoformat(x["start"]),
                period_end_utc=T.fromisoformat(x["end"]),
                expected_value=x["value"],
                unit="W",
            )
            for x in i["body"]["demand_points"]
        ],
    )
    capture_forecast(
        repo,
        forecast=forecast,
        forecast_id=1,
        reserve_id=10,
        operation_id=1,
        ready_at=T,
    )
    assert lookup_ids == [10]
    save_opportunity(repo, profile_json=canonical(p))
    body = store.latest("opportunity")["body"]
    assert body["status"] == "research_only"
    assert body["input_semantics"]["reserve_binding"]["resolved_floor_kwh"] == 1
    assert body["expected_candidate_value"] is not None
    assert body["execution"] == "disabled"


def test_new_interpretation_bounds_work_and_keeps_future_witness_rejected():
    i, s, p, _ = shaped(minutes=5)
    s["body"]["sources"]["import_forecast"]["forecasts"] *= 228
    rehash(i, s)
    with pytest.raises(ValueError, match="amber_original_series_mismatch"):
        context(i, s, p)
    i, s, p, _ = shaped()
    s["confirmed_at"] = T + timedelta(seconds=1)
    with pytest.raises(ValueError, match="capture_unavailable_or_corrupt"):
        context(i, s, p)


def test_v2_mode_changes_identity_without_changing_legacy_context():
    i, s, p, old = shaped(offset=0)
    legacy = context(i, s, old)
    old_bytes = canonical(legacy)
    new = context(i, s, p)
    assert digest(new) != digest(legacy)
    p["reserve_binding"] = {
        "mode": LINKED_RESERVE,
        "quantity": RESERVE_FIELD,
        "unit": "stored_kWh",
    }
    assert digest(context(i, s, p)) != digest(new)
    assert canonical(context(i, s, old)) == old_bytes


def test_link_identity_changes_hash_even_when_resolved_floor_is_equal():
    i, s, p, _ = shaped(floor=1, linked=True)
    before = context(i, s, p)
    i["body"]["reserve_id"] = i["body"]["reserve"]["id"] = 11
    rehash(i, s)
    after = context(i, s, p)
    assert after.reserve.floor_kwh == before.reserve.floor_kwh
    assert digest(after) != digest(before)
    i["body"]["reserve"]["estimate_json"]["forecast_run_id"] = 99
    rehash(i, s)
    with pytest.raises(ValueError, match="linked_reserve_quantity"):
        context(i, s, p)


def test_fragmented_24h_opportunity_still_fits_unchanged_bound(capture_db, monkeypatch):
    repo, _ = capture_db
    i, s, p, _ = shaped(floor=2, linked=True, minutes=5)
    for alias in ("import_forecast", "export_forecast"):
        template = s["body"]["sources"][alias]["forecasts"][0]
        s["body"]["sources"][alias]["forecasts"] = [
            {
                **template,
                "start_time": (T + timedelta(minutes=5 * n, seconds=1)).isoformat(),
                "end_time": (T + timedelta(minutes=5 * (n + 1))).isoformat(),
            }
            for n in range(288)
        ]
    s["body"]["sources"]["pv_today"]["detailedForecast"] = [
        {"period_start": (T + timedelta(minutes=30 * n)).isoformat(), "pv_estimate": 0}
        for n in range(48)
    ]
    template = i["body"]["demand_points"][0]
    i["body"]["demand_points"] = [
        {
            **template,
            "start": (T + timedelta(minutes=5 * n)).isoformat(),
            "end": (T + timedelta(minutes=5 * (n + 1))).isoformat(),
        }
        for n in range(288)
    ]
    original = CaptureRepository.save

    def save_with_fixture_clock(self, **kwargs):
        kwargs.setdefault("clock", lambda: T)
        return original(self, **kwargs)

    monkeypatch.setattr(CaptureRepository, "save", save_with_fixture_clock)
    store = CaptureRepository(repo)
    source_id = store.save(origin="fragmented", kind="source", at=T, body=s["body"])
    i["body"]["source_capture_id"] = source_id
    store.save(origin="fragmented", kind="decision_inputs", at=T, body=i["body"])
    save_opportunity(repo, profile_json=canonical(p))
    body = store.latest("opportunity")["body"]
    assert body["status"] == "research_only"
    assert len(canonical(body).encode()) < 2097152
    assert body["input_semantics"]["prices"]["import_price"]["periods"] == 288
