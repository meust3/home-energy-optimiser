"""Lossless capture storage, legacy integrity and unchanged admission gates."""

import copy
import math
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_advisory_input_contract import context, rehash, shaped
from test_arbitrage_programme import T
from test_arbitrage_programme import capture_db as capture_db

from energy_optimizer.arbitrage.capture import (
    MAX_BYTES,
    STORAGE_VERSION,
    VERSION,
    CaptureRepository,
    decode_capture_body,
    encode_capture_body,
)
from energy_optimizer.arbitrage.decision_types import canonical, digest
from energy_optimizer.db.models import ArbitrageCapture, ArbitrageCommitWitness


@pytest.mark.parametrize("kind", ["source", "decision_inputs", "opportunity"])
def test_lossless_round_trip_hash_witness_and_duplicate(capture_db, kind):
    repo, _ = capture_db
    store = CaptureRepository(repo)
    body = {
        "version": VERSION,
        "kind": kind,
        "nested": [{"per_kwh": -0.0, "positive": 0.0, "integer": 0}],
        "values": [-1e-30, 1e-30, -0.0123, 1.0, 123456789012345678901234567890],
        "text": 'quote " and backslash \\ and Unicode \u2600; literal -0.0',
        "missing": None,
        "boolean": False,
    }
    original = canonical(body)
    key = store.save(origin=kind, kind=kind, at=T, body=body, clock=lambda: T)
    row = store.latest(kind)
    assert canonical(row["body"]) == original == canonical(body)
    assert row["body_sha256"] == digest(body) == digest(row["body"])
    assert math.copysign(1, row["body"]["nested"][0]["per_kwh"]) == -1
    assert math.copysign(1, row["body"]["nested"][0]["positive"]) == 1
    assert type(row["body"]["nested"][0]["integer"]) is int
    assert row["confirmed_at"] == T
    assert key == digest({"origin": kind, "kind": kind, "version": VERSION})
    with repo.transaction() as session:
        stored = session.get(ArbitrageCapture, key).body
        assert stored == {
            "storage_format": STORAGE_VERSION,
            "canonical_body_json": original,
        }
    assert store.save(origin=kind, kind=kind, at=T, body=body) == key
    assert store.latest(kind)["confirmed_at"] == T
    changed = copy.deepcopy(body)
    changed["nested"][0]["per_kwh"] = 0.0
    with pytest.raises(ValueError, match="immutable_capture_conflict"):
        store.save(origin=kind, kind=kind, at=T, body=changed)
    assert canonical(store.latest(kind)["body"]) == original


def test_new_signed_zero_source_admitted_with_exact_linked_floor(capture_db):
    repo, _ = capture_db
    inputs, source, profile, _ = shaped(floor=2, linked=True)
    source["body"]["sources"]["export_forecast"]["forecasts"][0]["per_kwh"] = -0.0
    store = CaptureRepository(repo)
    source_id = store.save(
        origin="signed-zero", kind="source", at=T, body=source["body"], clock=lambda: T
    )
    inputs["body"]["source_capture_id"] = source_id
    store.save(
        origin="input",
        kind="decision_inputs",
        at=T,
        body=inputs["body"],
        clock=lambda: T,
    )
    saved_source = store.latest("source")
    saved_inputs = store.latest("decision_inputs")
    c = context(saved_inputs, saved_source, profile)
    assert c.reserve.floor_kwh == 2 == c.assumptions.capacity_kwh
    assert saved_inputs["body"]["reserve"] == inputs["body"]["reserve"]
    assert math.copysign(1, c.export_price.points[0].value) == -1
    # New storage does not excuse an unavailable source or change reserve rules.
    saved_source["confirmed_at"] = T + timedelta(seconds=1)
    with pytest.raises(ValueError, match="capture_unavailable_or_corrupt"):
        context(saved_inputs, saved_source, profile)


def test_old_hash_invalid_capture_stays_blocked_and_unmodified(capture_db):
    repo, _ = capture_db
    inputs, source, profile, _ = shaped(floor=2, linked=True)
    source["body"]["sources"]["export_forecast"]["forecasts"][0]["per_kwh"] = -0.0
    rehash(inputs, source)
    original = copy.deepcopy(source["body"])
    retained = copy.deepcopy(original)
    retained["sources"]["export_forecast"]["forecasts"][0]["per_kwh"] = 0.0
    key = digest({"origin": "old", "kind": "source", "version": VERSION})
    with repo.transaction() as session:
        session.add(
            ArbitrageCapture(
                id=key,
                origin="old",
                kind="source",
                captured_at_utc=T,
                body_sha256=digest(original),
                body=retained,
            )
        )
        session.flush()
        session.add(ArbitrageCommitWitness(capture_id=key, confirmed_at_utc=T))
    store = CaptureRepository(repo)
    before = canonical(retained), digest(original), T
    old = store.latest("source")
    inputs["body"]["source_capture_id"] = key
    rehash(inputs, source)
    assert digest(old["body"]) != old["body_sha256"]
    with pytest.raises(ValueError, match="capture_unavailable_or_corrupt"):
        context(inputs, old, profile)
    with pytest.raises(ValueError, match="capture_persisted_hash_mismatch"):
        store.save(origin="old", kind="source", at=T, body=original)
    old = store.latest("source")
    assert (canonical(old["body"]), old["body_sha256"], old["confirmed_at"]) == before
    with repo.transaction() as session:
        assert session.get(ArbitrageCapture, key).body == retained


def test_old_valid_object_is_read_without_reencoding(capture_db):
    repo, _ = capture_db
    body = {"kind": "source", "value": 0.0, "unavailable": None}
    key = digest({"origin": "old-valid", "kind": "source", "version": VERSION})
    with repo.transaction() as session:
        session.add(
            ArbitrageCapture(
                id=key,
                origin="old-valid",
                kind="source",
                captured_at_utc=T,
                body_sha256=digest(body),
                body=body,
            )
        )
        session.flush()
        session.add(ArbitrageCommitWitness(capture_id=key, confirmed_at_utc=T))
    before = canonical(body)
    store = CaptureRepository(repo)
    assert store.latest("source")["body_sha256"] == digest(body)
    store.save(origin="old-valid", kind="source", at=T, body=body)
    with repo.transaction() as session:
        assert canonical(session.get(ArbitrageCapture, key).body) == before


@pytest.mark.parametrize("encoded", ['{"x":-0.0}', '{"x":0.0}', '{"x":0}'])
def test_exact_canonical_numeric_spelling(encoded):
    stored = {"storage_format": STORAGE_VERSION, "canonical_body_json": encoded}
    assert canonical(decode_capture_body(stored)) == encoded


@pytest.mark.parametrize("encoded", ['{"x": 0}', '{"x":1,"x":2}', "NaN", "[]", "{"])
def test_noncanonical_or_invalid_json_is_not_admitted(encoded):
    with pytest.raises(ValueError, match="capture_storage_invalid"):
        decode_capture_body(
            {"storage_format": STORAGE_VERSION, "canonical_body_json": encoded}
        )


@pytest.mark.parametrize(
    "stored",
    [
        None,
        [],
        {"storage_format": "future"},
        {"storage_format": STORAGE_VERSION, "canonical_body_json": 1},
        {"storage_format": STORAGE_VERSION, "canonical_body_json": "{}", "extra": 1},
    ],
)
def test_unknown_or_malformed_storage_is_rejected(stored):
    with pytest.raises(ValueError, match="capture_storage_invalid"):
        decode_capture_body(stored)


def test_storage_envelope_stays_within_existing_bound(capture_db):
    repo, _ = capture_db
    # Logical payload fits, but escaping expands its persisted representation.
    body = {"text": '"' * (MAX_BYTES // 3)}
    assert len(canonical(body).encode()) < MAX_BYTES
    with pytest.raises(ValueError, match="capture_byte_bound"):
        CaptureRepository(repo).save(origin="oversize", kind="source", at=T, body=body)
    with repo.transaction() as session:
        assert session.execute(select(ArbitrageCapture)).first() is None
        assert session.execute(select(ArbitrageCommitWitness)).first() is None


def test_legacy_numeric_storage_reproduces_postgresql_fault(capture_db):
    repo, _ = capture_db
    body = {"sources": {"export_forecast": {"forecasts": [{"per_kwh": -0.0}]}}}
    key = digest({"origin": "legacy-zero", "kind": "source", "version": VERSION})
    with repo.transaction() as session:
        session.add(
            ArbitrageCapture(
                id=key,
                origin="legacy-zero",
                kind="source",
                captured_at_utc=T,
                body_sha256=digest(body),
                body=body,
            )
        )
    with repo.transaction() as session:
        saved = session.get(ArbitrageCapture, key)
        assert (digest(saved.body) == saved.body_sha256) == (repo.backend == "sqlite")
    encoded = encode_capture_body(body)
    assert decode_capture_body(encoded) == body
    assert canonical(decode_capture_body(encoded)) == canonical(body)
