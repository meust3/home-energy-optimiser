"""CLI exit codes use the actual report contract; no SDK or network required."""

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    "completed,correct,expected", [(8, 8, 0), (8, 7, 2), (0, 0, 2)]
)
def test_manual_replay_exit_code_uses_report_case_count(
    monkeypatch, capsys, completed, correct, expected
):
    path = Path(__file__).resolve().parents[1] / "tools/ai_review_replay.py"
    spec = importlib.util.spec_from_file_location("review_cli_test", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    async def fake_replay(*_args, **_kwargs):
        return {"cases": 8, "model_completed": completed, "model_correct": correct}

    monkeypatch.setattr(cli, "run_replay", fake_replay)
    monkeypatch.setattr(
        sys, "argv", [str(path), "--run", "--operation-id", str(uuid4())]
    )
    monkeypatch.setenv("ENERGY_AI_ENABLED", "false")
    assert cli.main() == expected
    assert '"cases": 8' in capsys.readouterr().out
