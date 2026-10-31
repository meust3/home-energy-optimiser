"""Offline host ownership and session refusal contracts; no Docker invocation."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from energy_optimizer import jev_isolated_lifecycle as lifecycle
from energy_optimizer import jev_panel_rehearsal as panel
from energy_optimizer import jev_runner as runner
from energy_optimizer.jev_offline_adapter import SDK_SOURCE_SHA256


def test_no_session_refuses_before_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "energy_optimizer.jev_offline_adapter.checked_sdk_digest",
        lambda: SDK_SOURCE_SHA256,
    )
    manifest = json.dumps(
        runner.manifest_template(
            str(uuid4()),
            transport="offline_panel_postgres",
        )
    ).encode()
    approval = json.dumps(
        {
            "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "max_cost_usd": "0.13",
        }
    ).encode()
    with pytest.raises(runner.RunnerRefused, match="session required"):
        asyncio.run(runner.rehearse(manifest, approval, tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_network_interface_refuses_before_database(monkeypatch):
    monkeypatch.setenv("JEV_REHEARSAL_OWNER", str(uuid4()))
    monkeypatch.setattr(panel.sys, "platform", "linux")
    monkeypatch.setattr(Path, "iterdir", lambda _: iter([Path("lo"), Path("eth0")]))
    with pytest.raises(ValueError, match="namespace"):
        panel.isolated_environment()


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_URL",
        "HA_TOKEN",
        "SUPERVISOR_TOKEN",
        "ENERGY_JEV_APPROVAL_FILE",
        "ENERGY_JEV_MANIFEST_FILE",
    ],
)
def test_inherited_live_configuration_refused(monkeypatch, name):
    monkeypatch.setenv("JEV_REHEARSAL_OWNER", str(uuid4()))
    monkeypatch.setenv(name, "inert-fixture")
    monkeypatch.setattr(panel.sys, "platform", "linux")
    monkeypatch.setattr(Path, "iterdir", lambda _: iter([Path("lo")]))
    with pytest.raises(ValueError, match="namespace"):
        panel.isolated_environment()


def test_source_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "PANEL_ROOT", tmp_path)
    (tmp_path / "changed.py").write_text("pass")
    with pytest.raises(ValueError, match="source"):
        panel.checked_panel_source()


@pytest.mark.parametrize(
    "change",
    [
        {"Labels": {}},
        {"NetworkMode": "host"},
        {"PortBindings": {"5432/tcp": [{}]}},
        {"Privileged": True},
    ],
)
def test_container_mismatch_never_authorizes_cleanup(monkeypatch, change):
    value = {
        "Config": {"Labels": {lifecycle.LABEL: "owner"}},
        "HostConfig": {"NetworkMode": "none", "PortBindings": {}, "Privileged": False},
    }
    if "Labels" in change:
        value["Config"].update(change)
    else:
        value["HostConfig"].update(change)
    monkeypatch.setattr(lifecycle, "docker", lambda *args: json.dumps([value]))
    with pytest.raises(RuntimeError, match="mismatch"):
        lifecycle.owned("container-id", "owner", "none")


def test_registry_claim_is_exclusive_before_docker(tmp_path, monkeypatch):
    identifier = str(uuid4())
    (tmp_path / identifier).mkdir()
    monkeypatch.setattr(lifecycle, "docker", lambda *args: pytest.fail("Docker called"))
    with pytest.raises(FileExistsError):
        lifecycle.run_isolated("image", tmp_path, identifier)


@pytest.mark.parametrize("interruption", [RuntimeError, KeyboardInterrupt])
def test_create_interruption_keeps_owned_name_for_cleanup(
    tmp_path, monkeypatch, interruption
):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "image":
            return "sha256:fixture"
        if args[0] == "create":
            raise interruption()
        if args[0] == "inspect":
            receipt = next(tmp_path.glob("*/lifecycle.json"))
            owner = json.loads(receipt.read_text())["owner"]
            return json.dumps(
                [
                    {
                        "Config": {"Labels": {lifecycle.LABEL: owner}},
                        "HostConfig": {"NetworkMode": "none"},
                    }
                ]
            )
        if args[:3] == ("rm", "-f", "-v"):
            return "removed"
        pytest.fail(str(args))

    monkeypatch.setattr(lifecycle, "docker", docker)
    result = lifecycle.run_isolated("image", tmp_path, str(uuid4()))
    assert result["status"] == "failed"
    assert result["containers_removed"]
    assert any(c[:3] == ("rm", "-f", "-v") for c in calls)


def test_cleanup_mismatch_is_reported_without_removal(tmp_path, monkeypatch):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "image":
            return "sha256:fixture"
        if args[0] == "create":
            return "fixture-id"
        if args[0] == "inspect":
            return json.dumps(
                [{"Config": {"Labels": {}}, "HostConfig": {"NetworkMode": "none"}}]
            )
        pytest.fail(str(args))

    monkeypatch.setattr(lifecycle, "docker", docker)
    result = lifecycle.run_isolated("image", tmp_path, str(uuid4()))
    assert result["status"] == "cleanup_incomplete"
    assert not result["containers_removed"]
    assert result["cleanup_container_ids"]
    assert not any(c[0] == "rm" for c in calls)


@pytest.mark.parametrize("failure", ["startup", "submission", "cleanup", "cancel"])
def test_panel_failure_always_stops_owned_child(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(
        "energy_optimizer.jev_offline_adapter.checked_sdk_digest",
        lambda: SDK_SOURCE_SHA256,
    )
    manifest = json.dumps(
        runner.manifest_template(
            str(uuid4()),
            "0.003",
            transport="offline_panel_postgres",
        )
    ).encode()
    approval = json.dumps(
        {
            "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "max_cost_usd": "0.003",
        }
    ).encode()

    class Session:
        finished = False

        def validate(self, *args):
            pass

        async def start(self, owner):
            self.process = await runner._start_child(
                "fixture",
                Path(runner.__file__).with_name("jev_rehearsal_worker.py"),
                owner,
            )
            if failure == "startup":
                raise ValueError("safe fixture failure")
            return self.process

        async def exchange(self, request):
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure == "submission":
                raise TimeoutError()
            return await runner._exchange(self.process, "fixture", request)

        async def finish(self, report):
            self.finished = True
            if failure == "cleanup":
                raise ValueError("safe fixture cleanup failure")

    session = Session()
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                runner.rehearse(manifest, approval, tmp_path, panel_session=session)
            )
    else:
        asyncio.run(
            runner.rehearse(manifest, approval, tmp_path, panel_session=session)
        )
    report = json.loads(next(tmp_path.glob("*/state.json")).read_bytes())
    assert session.finished and session.process.returncode is not None
    assert report["child_stopped"] and report["grant_revoked"]
    assert report["status"] != "completed"
    if failure in {"cancel", "submission"}:
        assert len(report["results"]) == 1
        assert report["results"][0]["status"] == "unknown"
        assert report["reserved_usd"] == "0.002688"


def test_http_cleanup_failure_still_revokes_and_closes(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    commands = []

    class Connection:
        closed = False

        def execute(self, sql, args=()):
            commands.append(sql)
            return self

        def fetchone(self):
            return {"revoked": True, "n": 0}

        def fetchall(self):
            return []

        def close(self):
            self.closed = True

    class BrokenHTTP:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            raise TimeoutError()

    monkeypatch.setattr(httpx, "AsyncClient", BrokenHTTP)
    session = panel.PanelSession(tmp_path)
    session.connection = Connection()
    control = tmp_path / "control.json"
    control.write_text("synthetic-only")
    report = {
        "results": [
            {
                "case_id": "h01",
                "operation_id": str(uuid4()),
                "experiment_id": str(uuid4()),
                "manifest_sha256": "0" * 64,
            }
        ]
    }
    with pytest.raises(TimeoutError):
        asyncio.run(session.finish(report))
    assert any(sql.startswith("UPDATE api_keys SET revoked=true") for sql in commands)
    assert report["panel_grant_revoked"]
    assert session.connection.closed
    assert not control.exists()


def test_nonempty_database_is_closed_without_cleanup_writes(tmp_path, monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("cryptography")
    commands = []

    class Connection:
        closed = False

        def execute(self, sql):
            commands.append(sql)
            return self

        def fetchone(self):
            return {"n": 1}

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connection)
    session = panel.PanelSession(tmp_path / "uncreated")
    session.owner = str(uuid4())
    with pytest.raises(ValueError, match="Fresh empty database"):
        asyncio.run(session.start(runner.ChildOwner()))
    asyncio.run(session.finish({}))
    assert connection.closed and session.connection is None
    assert len(commands) == 1 and commands[0].startswith("SELECT")
    assert not session.directory.exists()
