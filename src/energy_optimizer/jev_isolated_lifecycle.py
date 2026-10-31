"""Host-owned Docker lifecycle for an exclusively synthetic Panel rehearsal."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4

LABEL = "energy.jev.offline.owner"


def docker(*args: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError("Owned Docker operation failed")
    return result.stdout.strip()


def owned(container: str, owner: str, network: str) -> dict:
    value = json.loads(docker("inspect", container))[0]
    if (
        value["Config"]["Labels"].get(LABEL) != owner
        or value["HostConfig"]["NetworkMode"] != network
        or value["HostConfig"].get("PortBindings")
        or value["HostConfig"].get("Privileged")
    ):
        raise RuntimeError("Container ownership or isolation mismatch")
    return value


def run_isolated(
    image: str, registry: Path, experiment_id: str, *, fail_provider: bool = False
) -> dict:
    """Create only new labelled resources; remove only those exact owned IDs."""
    experiment_id = str(UUID(experiment_id))
    directory = registry.resolve() / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    owner = str(uuid4())
    containers = []
    report = {
        "owner": owner,
        "experiment_id": experiment_id,
        "mode": "offline_rehearsal",
        "provider_responses": "fixed_mock",
        "live_calls": 0,
        "production_activation": "NOT AUTHORISED",
        "status": "starting",
        "containers_removed": False,
    }
    receipt = directory / "lifecycle.json"

    def save():
        temporary = receipt.with_suffix(".partial")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(receipt)

    save()
    try:
        image_id = docker("image", "inspect", image, "--format", "{{.Id}}")
        pg_image = docker("image", "inspect", "postgres:17", "--format", "{{.Id}}")
        report.update(runtime_image=image_id, postgres_image=pg_image)
        # Persist unique owned names before create can fail or be interrupted.
        pg = "energy-jev-pg-" + UUID(owner).hex
        containers.append((pg, "none"))
        report["postgres_container"] = pg
        save()
        docker(
            "create",
            "--name",
            pg,
            "--network",
            "none",
            "--label",
            f"{LABEL}={owner}",
            "--tmpfs",
            "/var/lib/postgresql/data",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=ai_control_panel_test",
            "-e",
            "POSTGRES_USER=jev_" + UUID(owner).hex,
            pg_image,
        )
        pg_id = owned(pg, owner, "none")["Id"]
        docker("start", pg)
        for _ in range(40):
            try:
                docker(
                    "exec",
                    pg,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "jev_" + UUID(owner).hex,
                    "-d",
                    "ai_control_panel_test",
                )
                break
            except RuntimeError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Owned PostgreSQL did not become ready")
        source = Path(__file__).resolve().parent
        network = "container:" + pg_id
        command = [
            "python",
            "-m",
            "energy_optimizer.jev_isolated_lifecycle",
            "--inside",
            "--experiment-id",
            experiment_id,
        ]
        if fail_provider:
            command.append("--fail-provider")
        runtime = "energy-jev-runner-" + UUID(owner).hex
        containers.append((runtime, network))
        report["runtime_container"] = runtime
        save()
        docker(
            "create",
            "--name",
            runtime,
            "--network",
            network,
            "--label",
            f"{LABEL}={owner}",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-e",
            f"JEV_REHEARSAL_OWNER={owner}",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONPATH=/offline-src:/panel/apps:/panel",
            "--mount",
            f"type=bind,source={source},target=/offline-src/energy_optimizer,readonly",
            "--mount",
            f"type=bind,source={directory},target=/evidence",
            image_id,
            *command,
        )
        owned(runtime, owner, network)
        docker("start", runtime)
        code = docker("wait", runtime, timeout=180)
        report["runtime_exit_code"] = int(code)
        state = directory / "runs" / experiment_id / "state.json"
        if state.exists():
            report["runner"] = json.loads(state.read_bytes())
        report["status"] = "completed" if code == "0" else "failed"
    except (Exception, KeyboardInterrupt):
        report.update(status="failed", failure="isolated_lifecycle_incomplete_no_retry")
    finally:
        failures = []
        for container, network in reversed(containers):
            try:
                owned(container, owner, network)
                docker("rm", "-f", "-v", container)
            except (Exception, KeyboardInterrupt):
                failures.append(container)
        report["containers_removed"] = not failures
        if failures:
            report.update(status="cleanup_incomplete", cleanup_container_ids=failures)
        save()
    return report


def inside(experiment_id: str, fail_provider: bool) -> None:
    from energy_optimizer.jev_panel_rehearsal import PanelSession, isolated_environment
    from energy_optimizer.jev_runner import manifest_template, rehearse

    isolated_environment()
    manifest = json.dumps(
        manifest_template(
            experiment_id,
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
    Path("/evidence/manifest.json").write_bytes(manifest)
    Path("/evidence/offline-approval.json").write_bytes(approval)
    report = asyncio.run(
        rehearse(
            manifest,
            approval,
            Path("/evidence/runs"),
            panel_session=PanelSession(
                Path("/tmp/panel-session"), fail_provider=fail_provider
            ),
        )
    )
    expected = "partial" if fail_provider else "completed"
    if report["status"] != expected or not all(
        report.get(k)
        for k in (
            "panel_ledger_reconciled",
            "panel_grant_revoked",
            "panel_revocation_enforced",
            "child_stopped",
            "ledger_reconciled",
        )
    ):
        raise RuntimeError("Offline lifecycle verification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--fail-provider", action="store_true")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        inside(args.experiment_id, args.fail_provider)
    elif args.image and args.registry:
        result = run_isolated(
            args.image,
            args.registry,
            args.experiment_id,
            fail_provider=args.fail_provider,
        )
        print(json.dumps({k: result[k] for k in ("status", "containers_removed")}))
        raise SystemExit(0 if result["status"] == "completed" else 1)
    else:
        parser.error("--image and --registry required")


if __name__ == "__main__":
    main()
