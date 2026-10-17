"""Versioned, immutable SOC freshness evidence; never fetch or infer new data."""

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from energy_optimizer import entity_ids as ids
from energy_optimizer.arbitrage.advisory_inputs import AdvisoryInputError
from energy_optimizer.arbitrage.decision_types import Evidence, digest, timestamp
from energy_optimizer.models import HomeAssistantState

VERSION = "goodwe-runtime-soc-freshness-v1"


def captured_soc_evidence(
    sources: dict,
    states: dict[str, HomeAssistantState],
    *,
    slot: datetime,
    timezone: str,
) -> dict:
    """Freeze the already fetched same-runtime source, including missing evidence."""
    runtime = states.get(ids.GOODWE_TIMESTAMP)
    return {
        "version": VERSION,
        "slot": slot,
        "soc_sha256": digest(sources.get("soc")),
        "timezone": timezone,
        "runtime": (
            None
            if runtime is None
            else {
                "entity_id": ids.GOODWE_TIMESTAMP,
                "state": (
                    runtime.state
                    if isinstance(runtime.state, str) and len(runtime.state) <= 128
                    else None
                ),
                "reported_at": runtime.last_updated,
            }
        ),
    }


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise AdvisoryInputError(code)


def validate_soc_evidence(
    inputs: dict, source: dict, *, ready: datetime, limit: float
) -> Evidence | None:
    """Return pinned evidence for v1 only; absent blocks retain legacy semantics.

    A fresh REST response, sibling power, HA last_reported or unchanged grace is
    never a substitute. Device clock and HA receipt must both be fresh at cutoff.
    """
    body = source["body"]
    if "soc_freshness" not in body:
        return None
    try:
        block = body["soc_freshness"]
        _require(
            isinstance(block, dict)
            and set(block) == {"version", "slot", "soc_sha256", "timezone", "runtime"},
            "soc_freshness_invalid",
        )
        _require(block["version"] == VERSION, "soc_freshness_version_unsupported")
        soc = body["sources"]["soc"]
        _require(
            isinstance(soc, dict) and block["soc_sha256"] == digest(soc),
            "soc_freshness_binding_mismatch",
        )
        value = float(soc["state"])
        _require(
            math.isfinite(value)
            and 0 <= value <= 100
            and soc["attributes"]["unit_of_measurement"] == "%",
            "soc_domain_missing",
        )
        _require(
            source["id"] == inputs["body"]["source_capture_id"]
            and digest(body) == source["body_sha256"],
            "soc_freshness_binding_mismatch",
        )
        slot, received = timestamp(body["slot"]), timestamp(body["received_at"])
        captured = source["captured_at"]
        witness = source["confirmed_at"]
        captured = timestamp(captured) if isinstance(captured, str) else captured
        witness = timestamp(witness) if isinstance(witness, str) else witness
        input_at = inputs["captured_at"]
        input_at = timestamp(input_at) if isinstance(input_at, str) else input_at
        _require(
            timestamp(block["slot"]) == slot
            and slot <= received == captured <= witness <= input_at <= ready,
            "soc_freshness_binding_mismatch",
        )
        # The decision must use the same source observation, not an older/newer SOC.
        reserve = inputs["body"].get("reserve")
        if reserve is not None:
            observation_at = timestamp(reserve["observation_timestamp_utc"])
            _require(
                slot <= observation_at <= received
                and observation_at < slot + timedelta(minutes=5),
                "soc_freshness_binding_mismatch",
            )
        runtime = block["runtime"]
        _require(
            isinstance(runtime, dict)
            and set(runtime) == {"entity_id", "state", "reported_at"},
            "soc_runtime_evidence_missing",
        )
        _require(
            runtime["entity_id"] == ids.GOODWE_TIMESTAMP,
            "soc_freshness_binding_mismatch",
        )
        _require(
            isinstance(block["timezone"], str) and len(block["timezone"]) <= 128,
            "soc_runtime_clock_invalid",
        )
        zone = ZoneInfo(block["timezone"])
        device = datetime.fromisoformat(runtime["state"])
        if device.tzinfo is None:
            local = device.replace(tzinfo=zone)
            _require(
                local.utcoffset() == local.replace(fold=1).utcoffset(),
                "soc_runtime_clock_invalid",
            )
            _require(
                local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == device,
                "soc_runtime_clock_invalid",
            )
            device = local
        device = device.astimezone(UTC)
        receipt = timestamp(runtime["reported_at"])
        changed = timestamp(soc["reported_at"])
        _require(
            changed <= received and device <= received and receipt <= received,
            "soc_runtime_stale_or_future",
        )
        _require(
            not isinstance(limit, bool) and math.isfinite(limit) and 0 < limit <= 600,
            "soc_freshness_limit_invalid",
        )
        _require(
            all(0 <= (ready - t).total_seconds() <= limit for t in (device, receipt)),
            "soc_runtime_stale_or_future",
        )
        return Evidence(
            source["id"],
            VERSION,
            digest(block),
            device,
            witness,
            "documented_upper_bound",
            (
                "post-commit witness of exact SOC/runtime capture; "
                "physical applicability remains conditional"
            ),
            min(device, receipt) + timedelta(seconds=limit),
            (
                "captured GoodWe runtime clock and HA receipt, each within unchanged "
                "SOC age limit at decision; not HA value-change age"
            ),
            True,
            (),
        )
    except AdvisoryInputError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        raise AdvisoryInputError("soc_freshness_invalid") from None
