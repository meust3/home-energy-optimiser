"""Content identity must be checked before any later outcome is opened."""

import hashlib
from pathlib import Path

import pytest

from energy_optimizer import offline_paired_synthetic as core
from energy_optimizer.arbitrage import archive, research_io
from energy_optimizer.arbitrage.decision_types import canonical, digest
from energy_optimizer.arbitrage.selector import POLICY_SHA
from energy_optimizer.arbitrage.synthetic_cases import authored_case


def test_receipt_identity_is_actual_source_bytes(tmp_path):
    package = Path(research_io.__file__).parent
    expected = {
        "arbitrage/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.glob("*.py"))
    }
    expected["offline_paired_synthetic.py"] = hashlib.sha256(
        Path(core.__file__).read_bytes()
    ).hexdigest()
    identity = hashlib.sha256(canonical(expected).encode()).hexdigest()
    receipt = archive.freeze_context(authored_case(), tmp_path / "frozen")
    assert receipt.source_sha256 == identity == research_io.integration_source_sha()
    assert receipt.source_sha256 != digest(archive.INTEGRATION)
    assert receipt.policy_sha256 == POLICY_SHA


def test_changed_source_rejected_before_opening_outcome(tmp_path, monkeypatch):
    directory = tmp_path / "frozen"
    receipt = archive.freeze_context(authored_case(), directory)
    monkeypatch.setattr(archive, "integration_source_sha", lambda: digest("changed"))
    with pytest.raises(ValueError, match="^frozen_source_identity_mismatch$"):
        archive.evaluate_files(
            directory / "decision.json",
            directory / "receipts" / (receipt.sha256 + ".json"),
            tmp_path / "outcome-must-not-be-opened.json",
        )


def test_matching_source_advances_to_explicit_outcome_read(tmp_path):
    directory = tmp_path / "frozen"
    receipt = archive.freeze_context(authored_case(), directory)
    with pytest.raises(FileNotFoundError):
        archive.evaluate_files(
            directory / "decision.json",
            directory / "receipts" / (receipt.sha256 + ".json"),
            tmp_path / "absent-outcome.json",
        )
