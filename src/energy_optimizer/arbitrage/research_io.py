"""Portable pinned core and immutable local research receipts."""

import hashlib
from pathlib import Path

from energy_optimizer import offline_paired_synthetic as core
from energy_optimizer.arbitrage.core_bridge import CORE_SHA
from energy_optimizer.arbitrage.decision_types import canonical


def load_core(root=None, manifest=None):
    if hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest() != CORE_SHA:
        raise ValueError("reviewed_core_source_mismatch")
    return core


def append_receipt(directory, receipt):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (receipt.sha256 + ".json")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(receipt) + "\n")
    return path
