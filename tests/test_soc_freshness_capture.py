"""New capture provenance admits unchanged SOC without weakening freshness."""

import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_advisory_input_contract import context, rehash, shaped
from test_arbitrage_programme import T
from test_arbitrage_programme import capture_db as capture_db

from energy_optimizer import entity_ids as ids
from energy_optimizer.arbitrage.capture import (
    SOURCES,
    CaptureRepository,
    decode_capture_body,
    encode_capture_body,
    snapshot_states,
)
from energy_optimizer.arbitrage.decision_types import canonical, digest
from energy_optimizer.arbitrage.opportunity import (
    board,
    declared_context,
    save_opportunity,
)


def runtime_case():
    inputs, source, profile, _ = shaped(linked=True, floor=1.5)
    raw = source["body"]["sources"]
    raw["soc"]["reported_at"] = (T - timedelta(minutes=15)).isoformat()
    states = {}
    for alias, value in raw.items():
        attrs = dict(value["attributes"])
        attrs.update(
            {k: value[k] for k in ("forecasts", "detailedForecast") if k in value}
        )
        states[SOURCES[alias]] = SimpleNamespace(
            state=value.get("state", "0"),
            last_updated=T.fromisoformat(value["reported_at"]),
            attributes=attrs,
        )
    states[ids.GOODWE_TIMESTAMP] = SimpleNamespace(
        state=(T - timedelta(seconds=5)).isoformat(),
        last_updated=T - timedelta(seconds=3),
        attributes={},
    )
    source["body"] = snapshot_states(
        states, slot=T, received_at=T, soc_runtime_timezone="UTC"
    )
    rehash(inputs, source)
    return inputs, source, profile, states


def test_unchanged_soc_uses_captured_runtime_frame_and_preserves_floor():
    inputs, source, profile, _ = runtime_case()
    result = context(inputs, source, profile)
    assert result.reserve.floor_kwh == 1.5
    assert profile["soc_report_age_seconds"] == 600
    assert (
        source["body"]["sources"]["soc"]["reported_at"]
        == (T - timedelta(minutes=15)).isoformat()
    )
    assert (
        source["body"]["soc_freshness"]["version"] == "goodwe-runtime-soc-freshness-v1"
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("stale_device", "soc_runtime_stale_or_future"),
        ("stale_receipt", "soc_runtime_stale_or_future"),
        ("future_device", "soc_runtime_stale_or_future"),
        ("future_receipt", "soc_runtime_stale_or_future"),
        ("missing_runtime", "soc_runtime_evidence_missing"),
        ("wrong_entity", "soc_freshness_binding_mismatch"),
        ("wrong_soc", "soc_freshness_binding_mismatch"),
        ("wrong_slot", "soc_freshness_binding_mismatch"),
        ("wrong_reserve_slot", "soc_freshness_binding_mismatch"),
        ("wrong_source", "soc_freshness_binding_mismatch"),
        ("future_witness", "soc_freshness_binding_mismatch"),
        ("invalid_clock", "soc_freshness_invalid"),
        ("invalid_zone", "soc_freshness_invalid"),
        ("unknown_version", "soc_freshness_version_unsupported"),
        ("null_block", "soc_freshness_invalid"),
        ("missing_field", "soc_freshness_invalid"),
        ("nan_soc", "soc_domain_missing"),
        ("high_soc", "soc_domain_missing"),
        ("negative_soc", "soc_domain_missing"),
        ("future_soc_change", "soc_runtime_stale_or_future"),
    ],
)
def test_versioned_evidence_fails_closed(mutation, reason):
    i, s, p, _ = runtime_case()
    b = s["body"]["soc_freshness"]
    r = b["runtime"]
    if mutation == "stale_device":
        r["state"] = (T - timedelta(seconds=601)).isoformat()
    elif mutation == "stale_receipt":
        r["reported_at"] = (T - timedelta(seconds=601)).isoformat()
    elif mutation == "future_device":
        r["state"] = (T + timedelta(seconds=1)).isoformat()
    elif mutation == "future_receipt":
        r["reported_at"] = (T + timedelta(seconds=1)).isoformat()
    elif mutation == "missing_runtime":
        b["runtime"] = None
    elif mutation == "wrong_entity":
        r["entity_id"] = ids.GOODWE_BATTERY_POWER
    elif mutation == "wrong_soc":
        s["body"]["sources"]["soc"]["state"] = "22"
    elif mutation == "wrong_slot":
        b["slot"] = (T - timedelta(minutes=5)).isoformat()
    elif mutation == "wrong_reserve_slot":
        s["body"]["slot"] = b["slot"] = (T - timedelta(minutes=5)).isoformat()
    elif mutation == "wrong_source":
        s["id"] = "other-source"
    elif mutation == "future_witness":
        s["confirmed_at"] = T + timedelta(seconds=1)
    elif mutation == "invalid_clock":
        r["state"] = "unavailable"
    elif mutation == "invalid_zone":
        b["timezone"] = "not/a/zone"
    elif mutation == "unknown_version":
        b["version"] = "future-v99"
    elif mutation == "null_block":
        s["body"]["soc_freshness"] = None
    elif mutation == "missing_field":
        del b["slot"]
    elif mutation in ("nan_soc", "high_soc", "negative_soc", "future_soc_change"):
        soc = s["body"]["sources"]["soc"]
        if mutation == "future_soc_change":
            soc["reported_at"] = (T + timedelta(seconds=1)).isoformat()
        else:
            soc["state"] = {"nan_soc": "nan", "high_soc": "101", "negative_soc": "-1"}[
                mutation
            ]
        b["soc_sha256"] = digest(soc)
    rehash(i, s)
    before = canonical([i, s, p])
    with pytest.raises(ValueError, match=reason):
        declared_context(i, s, p)
    assert canonical([i, s, p]) == before


@pytest.mark.parametrize("age,passes", [(600, True), (600.000001, False)])
def test_exact_600_second_boundary(age, passes):
    i, s, p, _ = runtime_case()
    s["body"]["soc_freshness"]["runtime"].update(
        state=(T - timedelta(seconds=age)).isoformat(),
        reported_at=(T - timedelta(seconds=age)).isoformat(),
    )
    rehash(i, s)
    if passes:
        assert declared_context(i, s, p).reserve.floor_kwh == 1.5
    else:
        with pytest.raises(ValueError, match="soc_runtime_stale_or_future"):
            declared_context(i, s, p)


def test_legacy_capture_bytes_and_hashes_keep_original_interpretation():
    i, s, p, states = runtime_case()
    old = snapshot_states(states, slot=T, received_at=T)
    assert "soc_freshness" not in old
    s["body"] = old
    rehash(i, s)
    before = canonical([i, s, p])
    with pytest.raises(ValueError, match="soc_report_stale_or_future"):
        declared_context(i, s, p)
    assert canonical([i, s, p]) == before
    assert decode_capture_body(encode_capture_body(old)) == old
    assert digest(decode_capture_body(old)) == s["body_sha256"]


@pytest.mark.parametrize("clock", ["2026-04-05T02:30:00", "2026-10-04T02:30:00"])
def test_ambiguous_and_nonexistent_local_clock_block(clock):
    i, s, p, _ = runtime_case()
    s["body"]["soc_freshness"]["runtime"]["state"] = clock
    s["body"]["soc_freshness"]["timezone"] = "Australia/Sydney"
    rehash(i, s)
    with pytest.raises(ValueError, match="soc_runtime_clock_invalid"):
        declared_context(i, s, p)


def test_capture_roundtrip_and_missing_runtime_keep_fail_closed_marker():
    i, s, p, states = runtime_case()
    body = s["body"]
    encoded = encode_capture_body(body)
    assert digest(decode_capture_body(encoded)) == s["body_sha256"]
    del states[ids.GOODWE_TIMESTAMP]
    s["body"] = snapshot_states(
        states, slot=T, received_at=T, soc_runtime_timezone="UTC"
    )
    rehash(i, s)
    with pytest.raises(ValueError, match="soc_runtime_evidence_missing"):
        declared_context(i, s, p)


def test_profile_and_exact_linked_floor_unchanged_for_fixed_and_linked_modes():
    for linked in (True, False):
        i, s, p, _ = runtime_case()
        if not linked:
            p["reserve_binding"] = {"mode": "fixed_research_floor_v1", "floor_kwh": 1.5}
        before = copy.deepcopy(p)
        c = declared_context(i, s, p)
        assert p == before and c.reserve.floor_kwh == 1.5
        assert c.branch.evidence.version == "goodwe-runtime-soc-freshness-v1"
        assert c.branch.evidence.available_at == s["confirmed_at"]


def test_corrupt_capture_hash_blocks_new_contract():
    i, s, p, _ = runtime_case()
    s["body_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="soc_freshness_binding_mismatch"):
        declared_context(i, s, p)


def test_new_provenance_persists_and_dashboard_stays_non_executing(capture_db):
    repo, _ = capture_db
    i, s, p, _ = runtime_case()
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
    result = store.latest("opportunity")["body"]
    assert "soc_report_stale_or_future" not in result["reasons"]
    assert (
        result["context"]["branch"]["evidence"]["version"]
        == "goodwe-runtime-soc-freshness-v1"
    )
    assert result["context"]["reserve"]["floor_kwh"] == 1.5
    assert result["execution"] == "disabled" and result["no_command_issued"]
    assert result["research_only"] and result["observed_accounting"] is None
    assert result["input_semantics"]["profile_sha256"] == digest(p)
    assert board(repo, now=T)["items"][0]["execution"] == "disabled"


def test_capture_byte_bound_still_applies(healthy_states, now, monkeypatch):
    import energy_optimizer.arbitrage.capture as capture

    states = copy.deepcopy(healthy_states)
    states[ids.GOODWE_TIMESTAMP] = SimpleNamespace(
        state=now.isoformat(), last_updated=now, attributes={}
    )
    old = capture.snapshot_states(states, slot=now, received_at=now)
    monkeypatch.setattr(capture, "MAX_BYTES", len(canonical(old).encode()) + 1)
    with pytest.raises(ValueError, match="capture_byte_bound"):
        capture.snapshot_states(
            states, slot=now, received_at=now, soc_runtime_timezone="UTC"
        )


def test_new_contract_does_not_accept_longer_profile_limit():
    i, s, p, _ = runtime_case()
    p["soc_report_age_seconds"] = 601
    with pytest.raises(ValueError, match="soc_freshness_limit_invalid"):
        declared_context(i, s, p)


@pytest.mark.parametrize("enabled", [False, True])
def test_collector_wires_existing_option_without_extra_fetch(
    capture_db, healthy_states, now, monkeypatch, enabled
):
    from test_run_collector import load_tool

    from energy_optimizer.models import CollectorConfig
    from energy_optimizer.persistence import open_repository

    module = load_tool()
    repo, url = capture_db
    states = copy.deepcopy(healthy_states)
    states[ids.GOODWE_TIMESTAMP] = SimpleNamespace(
        state=now.isoformat(), last_updated=now, attributes={}
    )
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_states(self, entities):
            calls.append(tuple(entities))
            return states

    class Store:
        def save(self, observation):
            return "inserted"

        def close(self):
            pass

    monkeypatch.setattr(module, "HomeAssistantClient", Client)
    monkeypatch.setattr(module, "ObservationStore", Store)
    monkeypatch.setattr(module, "load_database_url", lambda: url)
    # Route into the disposable fixture schema; production bounded connection
    # options intentionally replace URL options, including this test search_path.
    monkeypatch.setattr(module, "open_bounded_context_repository", open_repository)
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: CollectorConfig(
            ha_url="http://fixture.invalid",
            ha_token="synthetic-only",
            arbitrage_capture_enabled=True,
            goodwe_soc_timestamp_enabled=enabled,
        ),
    )
    monkeypatch.setattr(module, "run", lambda collect_once, **kwargs: collect_once())
    assert module.main() == 0
    assert len(calls) == 1
    stored = CaptureRepository(repo).latest("source")["body"]
    assert ("soc_freshness" in stored) == enabled
    if enabled:
        assert stored["soc_freshness"]["runtime"]["entity_id"] == ids.GOODWE_TIMESTAMP


def test_reserve_observation_subsecond_timestamp_is_same_capture_slot():
    from energy_optimizer.arbitrage.soc_freshness import validate_soc_evidence

    i, s, p, _ = runtime_case()
    received = T + timedelta(seconds=1)
    s["body"]["received_at"] = received.isoformat()
    s["captured_at"] = s["confirmed_at"] = received
    i["captured_at"] = i["confirmed_at"] = received
    i["body"]["reserve"]["observation_timestamp_utc"] = (
        T + timedelta(microseconds=442)
    ).isoformat()
    rehash(i, s)
    assert validate_soc_evidence(i, s, ready=received, limit=600) is not None
