"""Portable pinned core and immutable local research receipts."""

import hashlib
from pathlib import Path

from energy_optimizer import offline_paired_synthetic as core
from energy_optimizer.arbitrage.core_bridge import CORE_SHA
from energy_optimizer.arbitrage.decision_types import canonical


def integration_source_sha():
    """Content identity of this installed wrapper bundle plus the pinned kernel.

    Works identically from canonical-LF source or the installed package; no Git,
    network, environment/private paths or mutable external manifest are consulted.
    """
    package = Path(__file__).parent
    files = {
        "arbitrage/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(package.glob("*.py"))
    }
    files["offline_paired_synthetic.py"] = hashlib.sha256(
        Path(core.__file__).read_bytes()
    ).hexdigest()
    return hashlib.sha256(canonical(files).encode()).hexdigest()


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
