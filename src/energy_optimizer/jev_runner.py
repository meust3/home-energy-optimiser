"""Offline-only Jev lifecycle rehearsal, optionally through the shared adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from energy_optimizer.jev_evaluation import reference

RESERVATION = Decimal("0.002688")  # Published historical 64k-context policy.
BATCH_SECONDS = 120
CASE_SECONDS = 8
CLEANUP_SECONDS = 5
SOURCE_FILES = (
    "jev_runner.py",
    "jev_rehearsal_worker.py",
    "jev_reference.json",
    "jev_evaluation.py",
    "jev_offline_adapter.py",
    "ai_panel.py",
    "ai_integration.py",
    "ai_review.py",
)


class RunnerRefused(ValueError):
    """Safe local policy refusal, without input content or exception details."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Manifest(Strict):
    mode: Literal["offline_rehearsal"]
    transport: Literal["offline_pipe", "offline_shared_adapter"] = "offline_pipe"
    sdk_source_sha256: str | None = None
    experiment_id: str
    source_sha256: str
    provider_commit: Literal["3d194368db297e33049b414c4cae345e632e5dbb"]
    fixture_sha256: str
    question_sha256: str
    model: Literal["jev-1.13.0"]
    provider: Literal["typesafe"]
    billing_evidence: Literal["synthetic_only_not_live_verified"]
    max_cost_usd: str
    max_attempts: Literal[48]
    batch_seconds: Literal[120]
    concurrency: Literal[1]
    retries: Literal[0]
    fallback: Literal[False]


class Approval(Strict):
    approval: Literal["APPROVE_OFFLINE_JEV_REHEARSAL"]
    manifest_sha256: str
    max_cost_usd: str


def source_digest() -> str:
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        # Match canonical Git text across Windows checkouts and Linux packages.
        data = (
            files("energy_optimizer")
            .joinpath(name)
            .read_bytes()
            .replace(b"\r\n", b"\n")
        )
        digest.update(name.encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def manifest_template(
    experiment_id: str,
    max_cost_usd: str = "0.13",
    *,
    transport: Literal["offline_pipe", "offline_shared_adapter"] = "offline_pipe",
) -> dict:
    frozen = reference()
    sdk_digest = None
    if transport == "offline_shared_adapter":
        from energy_optimizer.jev_offline_adapter import checked_sdk_digest

        sdk_digest = checked_sdk_digest()
    return Manifest(
        mode="offline_rehearsal",
        transport=transport,
        sdk_source_sha256=sdk_digest,
        experiment_id=str(UUID(experiment_id)),
        source_sha256=source_digest(),
        provider_commit="3d194368db297e33049b414c4cae345e632e5dbb",
        fixture_sha256=frozen["dataset_sha256"],
        question_sha256=frozen["question_sha256"],
        model="jev-1.13.0",
        provider="typesafe",
        billing_evidence="synthetic_only_not_live_verified",
        max_cost_usd=max_cost_usd,
        max_attempts=48,
        batch_seconds=120,
        concurrency=1,
        retries=0,
        fallback=False,
    ).model_dump()


def preflight(
    manifest_bytes: bytes, approval_bytes: bytes
) -> tuple[Manifest, str, Decimal]:
    try:
        if max(len(manifest_bytes), len(approval_bytes)) > 16384:
            raise ValueError()
        manifest = Manifest.model_validate_json(manifest_bytes)
        raw = json.loads(manifest_bytes)
        if (
            any(
                type(raw[key]) is not int
                for key in ("max_attempts", "batch_seconds", "concurrency", "retries")
            )
            or type(raw["fallback"]) is not bool
        ):
            raise ValueError()
        approval = Approval.model_validate_json(approval_bytes)
        if manifest.transport == "offline_shared_adapter":
            from energy_optimizer.jev_offline_adapter import checked_sdk_digest

            if manifest.sdk_source_sha256 != checked_sdk_digest():
                raise ValueError()
        elif manifest.sdk_source_sha256 is not None:
            raise ValueError()
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        frozen = reference()
        cap = Decimal(manifest.max_cost_usd)
        if (
            str(UUID(manifest.experiment_id)) != manifest.experiment_id
            or manifest.source_sha256 != source_digest()
            or manifest.fixture_sha256 != frozen["dataset_sha256"]
            or manifest.question_sha256 != frozen["question_sha256"]
            or approval.manifest_sha256 != digest
            or approval.max_cost_usd != manifest.max_cost_usd
            or not cap.is_finite()
            or not 0 < cap <= 1
        ):
            raise ValueError()
        return manifest, digest, cap
    except (ValueError, TypeError, ArithmeticError):
        raise RunnerRefused("Matching offline manifest and approval required") from None


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".partial")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@dataclass
class ChildOwner:
    process: asyncio.subprocess.Process | None = None


async def _start_child(
    nonce: str, worker: Path, owner: ChildOwner
) -> asyncio.subprocess.Process:
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(worker),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
            limit=65536,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    )
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        # A timed-out spawn still has to yield its owned handle before cleanup.
        process = await spawn
        owner.process = process
        await _stop_child(process)
        raise
    owner.process = process
    try:
        process.stdin.write((json.dumps({"nonce": nonce}) + "\n").encode())
        await process.stdin.drain()
    except BaseException:
        await _stop_child(process)
        raise
    return process


async def _exchange(
    process: asyncio.subprocess.Process, nonce: str, request: dict
) -> dict:
    process.stdin.write((json.dumps({**request, "nonce": nonce}) + "\n").encode())
    await process.stdin.drain()
    line = await process.stdout.readline()
    if not line or len(line) > 65536:
        raise ValueError("Invalid child response")
    return json.loads(line)


async def _stop_child(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), CLEANUP_SECONDS)
    except TimeoutError:
        process.kill()
        await asyncio.wait_for(process.wait(), CLEANUP_SECONDS)


def _checked_receipt(value: dict, request: dict) -> dict:
    allowed = set(request) | {
        "status",
        "execution",
        "event_id",
        "request_id",
        "raw_typed_answer",
        "reported_usage",
    }
    if set(value) != allowed or any(value[k] != v for k, v in request.items()):
        raise ValueError("Receipt correlation mismatch")
    if value["status"] != "completed" or value["execution"] != "offline_simulation":
        raise ValueError("Only synthetic receipts accepted")
    UUID(value["event_id"])
    UUID(value["request_id"])
    answer = value["raw_typed_answer"]
    labels = {"supported", "needs_review", "insufficient_evidence"}
    if (
        set(answer) != {"type", "choice", "probabilities"}
        or answer["type"] != "choice"
        or answer["choice"] not in labels
    ):
        raise ValueError("Invalid typed answer")
    probabilities = answer["probabilities"]
    if set(probabilities) != labels or any(
        type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1
        for v in probabilities.values()
    ):
        raise ValueError("Invalid probabilities")
    if abs(sum(probabilities.values()) - 1) > 0.02 or probabilities[
        answer["choice"]
    ] + 0.001 < max(probabilities.values()):
        raise ValueError("Invalid distribution")
    if value["reported_usage"] is not None:
        raise ValueError("Offline worker cannot report provider usage")
    return value


def _reconcile(db: sqlite3.Connection, results: list[dict]) -> bool:
    rows = db.execute("SELECT payload FROM attempts ORDER BY ordinal").fetchall()
    return [json.loads(row[0]) for row in rows] == results


async def _cleanup(
    db: sqlite3.Connection, process: asyncio.subprocess.Process | None, report: dict
) -> None:
    try:
        db.execute("UPDATE grant_record SET revoked=1")
        db.commit()
        report["grant_revoked"] = True
        report["ledger_reconciled"] = _reconcile(db, report["results"])
    except Exception:
        # Explicit safe failure evidence; cleanup must still terminate the child.
        report["cleanup_failure"] = "ledger_cleanup_failed"
    finally:
        try:
            db.close()
        except Exception:
            report["cleanup_failure"] = "ledger_close_failed"
        try:
            if process is not None:
                await _stop_child(process)
            report["child_stopped"] = True
        except Exception:
            report["cleanup_failure"] = "child_cleanup_failed"
    if "cleanup_failure" in report or not all(
        report[k] for k in ("grant_revoked", "ledger_reconciled", "child_stopped")
    ):
        report["status"] = "cleanup_incomplete"


async def rehearse(
    manifest_bytes: bytes, approval_bytes: bytes, registry: Path
) -> dict[str, Any]:
    """Run only the bundled offline child; registry is durable and never pruned."""
    manifest, digest, cap = preflight(manifest_bytes, approval_bytes)
    run_dir = registry / manifest.experiment_id
    registry.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir()  # Atomic exclusive claim; interrupted runs cannot restart.
    except FileExistsError:
        raise RunnerRefused(
            "Experiment already claimed; restart and resume refused"
        ) from None
    report: dict[str, Any] = {
        "experiment_id": manifest.experiment_id,
        "manifest_sha256": digest,
        "source_sha256": manifest.source_sha256,
        "mode": "offline_rehearsal",
        "transport": manifest.transport,
        "sdk_source_sha256": manifest.sdk_source_sha256,
        "status": "starting",
        "results": [],
        "reserved_usd": "0",
        "actual_cost_usd": None,
        "live_calls": 0,
        "ledger_reconciled": False,
        "grant_revoked": False,
        "child_stopped": False,
        "production_activation": "NOT AUTHORISED",
    }
    state_path = run_dir / "state.json"
    _save(state_path, report)
    db = sqlite3.connect(run_dir / "synthetic-ledger.sqlite3")
    process = None
    owner = ChildOwner()
    interrupted = False
    reserved = Decimal(0)
    nonce = secrets.token_hex(32)
    try:
        db.executescript(
            "CREATE TABLE grant_record (digest TEXT, revoked INTEGER); "
            "CREATE TABLE attempts "
            "(ordinal INTEGER PRIMARY KEY, payload TEXT NOT NULL);"
        )
        db.execute(
            "INSERT INTO grant_record VALUES (?,0)",
            (hashlib.sha256(nonce.encode()).hexdigest(),),
        )
        db.commit()
        started = time.monotonic()
        if source_digest() != manifest.source_sha256:
            raise RunnerRefused("Source changed after preflight")
        worker = run_dir / "worker.py"
        with worker.open("xb") as handle:
            handle.write(
                files("energy_optimizer")
                .joinpath("jev_rehearsal_worker.py")
                .read_bytes()
            )
        task = asyncio.create_task(
            asyncio.wait_for(_start_child(nonce, worker, owner), CASE_SECONDS)
        )
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        process = await task
        if interrupted:
            raise asyncio.CancelledError
        report["child_pid"] = process.pid
        report["status"] = "running"
        for ordinal, case_id in enumerate(reference()["cases"]):
            remaining = BATCH_SECONDS - (time.monotonic() - started)
            if remaining <= 0 or reserved + RESERVATION > cap:
                report["status"] = "partial"
                report["failure"] = "deadline_or_budget_exhausted"
                break
            operation = str(
                uuid5(
                    UUID(manifest.experiment_id), f"{manifest.fixture_sha256}:{case_id}"
                )
            )
            request = {
                "case_id": case_id,
                "operation_id": operation,
                "experiment_id": manifest.experiment_id,
                "manifest_sha256": digest,
            }
            row = {**request, "status": "unknown", "reservation_usd": str(RESERVATION)}
            report["results"].append(row)
            reserved += RESERVATION
            report["reserved_usd"] = str(reserved)
            db.execute("INSERT INTO attempts VALUES (?,?)", (ordinal, json.dumps(row)))
            db.commit()  # Durable unknown before any submission; never release it.
            _save(state_path, report)
            if manifest.transport == "offline_shared_adapter":
                from energy_optimizer.jev_offline_adapter import (
                    exchange_via_shared_adapter,
                )

                submission = exchange_via_shared_adapter(
                    lambda body: _exchange(process, nonce, body), request
                )
            else:
                submission = _exchange(process, nonce, request)
            receipt = await asyncio.wait_for(submission, min(CASE_SECONDS, remaining))
            receipt = _checked_receipt(receipt, request)
            if any(
                receipt[key] == prior.get(key)
                for prior in report["results"][:-1]
                for key in ("event_id", "request_id")
            ):
                raise ValueError("Duplicate ledger identity")
            row.update(receipt)
            db.execute(
                "UPDATE attempts SET payload=? WHERE ordinal=?",
                (json.dumps(row), ordinal),
            )
            db.commit()
            _save(state_path, report)
        else:
            report["status"] = "completed"
    except asyncio.CancelledError:
        interrupted = True
        report.update(status="interrupted", failure="interrupted_no_retry")
    except Exception:
        # Persist a safe uncertain-outcome category, including unexpected failures.
        report.update(status="partial", failure="uncertain_outcome_no_retry")
    finally:
        # Shield cleanup even from repeated interruption; it has bounded waits.
        if owner.process is not None:
            report["child_pid"] = owner.process.pid
        cleanup = asyncio.create_task(_cleanup(db, owner.process, report))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                interrupted = True
                report.update(status="interrupted", failure="interrupted_no_retry")
        await cleanup
        _save(state_path, report)
    if interrupted:
        raise asyncio.CancelledError
    return report
