"""Credential-safe receipt bytes and original wire provenance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


def sanitized_payload(raw: bytes, key: str) -> tuple[bytes, bool]:
    # API keys are ASCII hex. Also redact JSON-unicode escaped echoes when a
    # malformed/deep response cannot safely be traversed as a Python object.
    pattern = b"".join(
        b"(?:"
        + re.escape(char.encode())
        + b"|\\\\u"
        + f"{ord(char.lower()):04x}".encode()
        + b"|\\\\u"
        + f"{ord(char.upper()):04x}".encode()
        + b")"
        for char in key
    )
    safe = re.sub(pattern, b"[REDACTED]", raw, flags=re.IGNORECASE) if key else raw
    changed = safe != raw

    def clean(item: Any) -> Any:
        nonlocal changed
        if isinstance(item, dict):
            result = {}
            for name, value in item.items():
                if (
                    name.lower()
                    in {
                        "next",
                        "prev",
                        "appid",
                        "api_key",
                        "apikey",
                        "authorization",
                        "token",
                        "access_token",
                    }
                    and value is not None
                ):
                    changed = True
                    result[name] = "[REDACTED]"
                else:
                    result[name] = clean(value)
            return result
        if isinstance(item, str) and key:
            result = re.sub(re.escape(key), "[REDACTED]", item, flags=re.IGNORECASE)
            changed = changed or result != item
            return result
        if isinstance(item, list):
            return [clean(value) for value in item]
        return item

    try:
        body = clean(json.loads(safe))
        stored = (
            json.dumps(
                body,
                sort_keys=True,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            if changed
            else safe
        )
    except (ValueError, UnicodeError, RecursionError):
        stored = safe
    return stored, changed


@dataclass(frozen=True)
class PayloadReceipt:
    body: bytes = field(repr=False)
    original_sha256: str
    original_byte_count: int
    credential_redacted: bool

    @classmethod
    def from_wire(cls, raw: bytes, key: str) -> PayloadReceipt:
        body, redacted = sanitized_payload(raw, key)
        return cls(body, hashlib.sha256(raw).hexdigest(), len(raw), redacted)
