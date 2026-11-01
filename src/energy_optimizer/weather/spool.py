"""Private durable delivery buffer, never a database or quota-ledger fallback."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from energy_optimizer.weather.domain import utc
from energy_optimizer.weather.receipt import PayloadReceipt


@dataclass(frozen=True)
class PendingPage:
    claim: dict[str, Any]
    finished_at: datetime
    http_status: int | None
    receipt: PayloadReceipt | None
    navigation: dict[str, Any] | None
    error_code: str | None


class WeatherSpool:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, attempt_id: str) -> Path:
        return self.directory / f"{UUID(attempt_id)}.json"

    def _sync_directory(self) -> None:
        if os.name == "posix":
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def prepare(self) -> None:
        # Called only for ready/enabled collection, before reserving/fetching.
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("WEATHER_SPOOL_SYMLINK")
        with tempfile.TemporaryFile(dir=self.directory) as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            stream.write(b"ready")
            stream.flush()
            os.fsync(stream.fileno())
        self._sync_directory()

    def save(self, page: PendingPage) -> None:
        receipt = page.receipt
        body = {
            "claim": {
                k: v.isoformat() if isinstance(v, datetime) else v
                for k, v in page.claim.items()
            },
            "finished_at": utc(page.finished_at).isoformat(),
            "http_status": page.http_status,
            "receipt": (
                None
                if receipt is None
                else {
                    "body": base64.b64encode(receipt.body).decode("ascii"),
                    "stored_sha256": hashlib.sha256(receipt.body).hexdigest(),
                    "original_sha256": receipt.original_sha256,
                    "original_byte_count": receipt.original_byte_count,
                    "credential_redacted": receipt.credential_redacted,
                }
            ),
            "navigation": page.navigation,
            "error_code": page.error_code,
        }
        path = self._path(page.claim["id"])
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(body, sort_keys=True, allow_nan=False).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        self._sync_directory()

    def load(self) -> PendingPage | None:
        # At most one outstanding page in normal operation. Bound damaged/backlog scans.
        paths = sorted(self.directory.iterdir())
        if len(paths) > 20:
            raise ValueError("WEATHER_SPOOL_BACKLOG")
        for path in paths:
            # A crash during a write must halt new acquisition, never discard the bytes.
            if path.suffix == ".tmp":
                raise ValueError("WEATHER_SPOOL_INCOMPLETE_WRITE")
            if path.suffix != ".json":
                continue
            if path.is_symlink() or path.stat().st_size > 4_000_000:
                raise ValueError("WEATHER_SPOOL_INVALID_FILE")
            item = json.loads(path.read_bytes())
            claim = item["claim"]
            if self._path(claim["id"]) != path:
                raise ValueError("WEATHER_SPOOL_ID_MISMATCH")
            for key in ("requested_at", "window_start", "window_end"):
                claim[key] = utc(datetime.fromisoformat(claim[key]))
            raw = item["receipt"]
            receipt = None
            if raw is not None:
                data = base64.b64decode(raw["body"], validate=True)
                if hashlib.sha256(data).hexdigest() != raw["stored_sha256"]:
                    raise ValueError("WEATHER_SPOOL_HASH_MISMATCH")
                receipt = PayloadReceipt(
                    data,
                    raw["original_sha256"],
                    raw["original_byte_count"],
                    raw["credential_redacted"],
                )
            return PendingPage(
                claim,
                utc(datetime.fromisoformat(item["finished_at"])),
                item["http_status"],
                receipt,
                item["navigation"],
                item["error_code"],
            )
        return None

    def acknowledge(self, page: PendingPage) -> None:
        self._path(page.claim["id"]).unlink(missing_ok=True)
        self._sync_directory()
