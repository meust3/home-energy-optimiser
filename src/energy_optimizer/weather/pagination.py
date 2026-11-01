"""Validate navigation hints; never follow provider URLs or trust their units."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any
from urllib.parse import parse_qs, urlsplit


def page_metadata(
    raw: bytes,
    *,
    endpoint: str,
    page_start: int,
    horizon_end: int,
    latitude: float,
    longitude: float,
    key: str,
) -> dict[str, Any]:
    body = json.loads(raw)
    records = body["data"]
    times = [r["dt"] for r in records]
    if any(t % 900 for t in times) or times[0] < page_start:
        raise ValueError("PAGE_ALIGNMENT_OR_START_INVALID")
    record_hashes = {
        str(row["dt"]): hashlib.sha256(
            json.dumps(row, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        for row in records
    }
    result = {
        "target_epochs": times,
        "record_hashes": record_hashes,
        "next_start_epoch": None,
    }
    if times[-1] >= horizon_end - 900 or not body.get("next"):
        return result
    value = body["next"]
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("INVALID_PAGINATION_HINT")
    split, expected = urlsplit(value), urlsplit(endpoint)
    if (
        split.scheme not in {"https", "http"}
        or split.hostname != expected.hostname
        or split.port not in (None, 443)
        or split.username
        or split.password
        or split.path != expected.path
        or split.fragment
    ):
        raise ValueError("PAGINATION_DESTINATION_REJECTED")
    params = parse_qs(
        split.query, keep_blank_values=True, strict_parsing=True, max_num_fields=10
    )
    if set(params) - {"start", "lat", "lon", "appid", "units", "lang", "cnt"}:
        raise ValueError("UNKNOWN_PAGINATION_PARAMETER")
    if any(len(v) != 1 for v in params.values()):
        raise ValueError("DUPLICATE_PAGINATION_PARAMETER")
    for field, configured in (("lat", latitude), ("lon", longitude)):
        if field in params:
            returned = float(params[field][0])
            if not math.isfinite(returned) or abs(returned - configured) > 0.00011:
                raise ValueError("PAGINATION_LOCATION_MISMATCH")
    if "appid" in params and params["appid"][0] != key:
        raise ValueError("PAGINATION_CREDENTIAL_MISMATCH")
    # An HTTP link is only a cursor hint. It is NEVER used as a request URL:
    # capture_once always reconstructs a fixed HTTPS endpoint and metric units.
    if "units" in params and params["units"][0] != "metric":
        raise ValueError("PAGINATION_UNIT_CHANGE")
    next_start = int(params["start"][0])
    if not times[-1] <= next_start < horizon_end:
        raise ValueError("PAGINATION_CURSOR_NOT_FORWARD_OR_OUTSIDE_WINDOW")
    # A navigation cursor is a timeline position, not a forecast sampling time.
    # Providers may use an inclusive last timestamp or last+1 second. We already
    # retained that target, so rebuild the next request at the next full slot.
    result["provider_next_cursor_epoch"] = next_start
    result["next_start_epoch"] = max(times[-1] + 900, (next_start + 899) // 900 * 900)
    return result
