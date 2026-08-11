import subprocess
import sys
from pathlib import Path


def test_validate_power_signs_supports_days():
    tool = Path(__file__).parents[1] / "tools" / "validate_power_signs.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--days" in result.stdout


def test_reprocessing_apply_requires_explicit_backup_acknowledgement():
    tool = Path(__file__).parents[1] / "tools" / "reprocess_observations.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--apply"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--apply requires --backup-verified" in result.stderr
