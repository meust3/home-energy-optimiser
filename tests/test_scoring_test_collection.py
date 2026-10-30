"""The shared scoring fixture must survive combined test-module collection."""

import subprocess
import sys
from pathlib import Path


def test_inventory_fixture_is_parameterized_when_collected_with_scoring():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_bounded_forecast_scoring.py",
            "tests/test_pending_score_inventory.py",
            "-k",
            "raw_sql_updates_scores_types_and_retention",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for backend in ("sqlite", "postgresql"):
        assert (
            f"test_raw_sql_updates_scores_types_and_retention[{backend}]"
            in result.stdout
        )
