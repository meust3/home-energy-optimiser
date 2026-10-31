"""One-shot, read-only SEMS+ cloud telemetry diagnostic for a GoodWe HCA G2.

This diagnostic is deliberately isolated from the collection runtime. It performs no
local discovery, has no polling loop, and can call only the exact cloud query
endpoints declared in ``READ_ONLY_ENDPOINTS``.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import requests

from energy_optimizer.timestamps import aware_datetime

LOGIN_URL = "https://semsplus.goodwe.com/web/sems/sems-user/api/v1/auth/cross-login"
AU_LOGIN_URL = (
    "https://au-semsplus.goodwe.com/web/sems/sems-user/api/v1/auth/cross-login"
)
ALLOWED_LOGIN_URLS = frozenset({LOGIN_URL, AU_LOGIN_URL})
REQUEST_TIMEOUT_SECONDS = 30
SESSION_EXPIRED_CODE = "C0602"
SUCCESS_CODES = {"0", "00000"}
ALLOWED_GATEWAY_SUFFIXES = ("goodwe.com", "semsportal.com")


@dataclass(frozen=True)
class EndpointSpec:
    method: str
    path: str
    semantic_operation: str


READ_ONLY_ENDPOINTS: dict[str, EndpointSpec] = {
    "authenticate": EndpointSpec(
        method="POST",
        path="/web/sems/sems-user/api/v1/auth/cross-login",
        semantic_operation="authentication",
    ),
    "discover_plants": EndpointSpec(
        method="POST",
        path="sems-plant/api/portal/stations/page",
        semantic_operation="power-station discovery",
    ),
    "discover_chargers": EndpointSpec(
        method="POST",
        path="sems-plant/api/web/device/centralized/page",
        semantic_operation="EV-charger discovery",
    ),
    "charger_detail": EndpointSpec(
        method="POST",
        path="sems-remote/api/ev-charger/detail",
        semantic_operation="charger detail query",
    ),
    "last_charge": EndpointSpec(
        method="GET",
        path="sems-plant/api/v1/chargePile/getLastCharge",
        semantic_operation="last-charge query",
    ),
}


class ProbeError(RuntimeError):
    """Safe diagnostic failure that never embeds response bodies or credentials."""


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int,
        allow_redirects: bool,
    ) -> ResponseLike: ...


def _hostname_is_approved_cloud(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in ALLOWED_GATEWAY_SUFFIXES
    )


def validate_gateway_base(value: str) -> str:
    """Accept only an HTTPS GoodWe/SEMS cloud gateway with no custom port."""
    parsed = urlparse(value.strip())
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ProbeError("SEMS returned an invalid regional gateway") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not _hostname_is_approved_cloud(parsed.hostname)
    ):
        raise ProbeError("SEMS returned a non-cloud or non-HTTPS regional gateway")
    path = parsed.path.rstrip("/")
    if path != "/web/sems":
        raise ProbeError("SEMS returned an unexpected regional gateway path")
    return f"https://{parsed.hostname.lower()}{path}"


def assert_endpoint_allowed(method: str, url: str) -> None:
    """Reject every request that is not one of the five read-only operations."""
    parsed = urlparse(url)
    normalized_method = method.upper()
    try:
        parsed_port = parsed.port
    except ValueError:
        raise ProbeError("Invalid cloud destination port") from None
    if url in ALLOWED_LOGIN_URLS and normalized_method == "POST":
        return
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not _hostname_is_approved_cloud(parsed.hostname)
    ):
        raise ProbeError("Request destination is not an approved SEMS cloud host")
    allowed = {
        (spec.method, f"/web/sems/{spec.path}")
        for name, spec in READ_ONLY_ENDPOINTS.items()
        if name != "authenticate"
    }
    if (normalized_method, parsed.path) not in allowed:
        raise ProbeError("Request is not in the read-only endpoint allowlist")


def redact_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return f"***{text[-4:]}" if len(text) > 4 else "***"


def _first(raw: dict[str, Any], *names: str) -> tuple[Any, str]:
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name], name
    return None, names[0]


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("dataList", "records", "list", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def parse_plants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plants = []
    for item in _records(payload):
        plant_id, _ = _first(item, "stationId", "id", "plantId", "powerStationId")
        if plant_id is not None:
            plants.append(item)
    return plants


def parse_chargers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    chargers: list[dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("dataList"), list):
        for station in data["dataList"]:
            if not isinstance(station, dict):
                continue
            for child in station.get("children") or []:
                if not isinstance(child, dict):
                    continue
                serial, _ = _first(child, "sn", "serialNumber", "deviceSn", "sno")
                if serial is None:
                    continue
                enriched = dict(child)
                enriched.setdefault("stationId", station.get("stationId"))
                chargers.append(enriched)
        if chargers:
            return chargers
    for item in _records(payload):
        serial, _ = _first(item, "sn", "serialNumber", "deviceSn", "sno")
        if serial is not None:
            chargers.append(item)
    return chargers


class SemsCloudProbe:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        transport: Transport | None = None,
        now: datetime | None = None,
        stale_after_minutes: int = 15,
        allow_live_requests: bool = False,
        request_budget: int = 7,
        login_url: str = LOGIN_URL,
        discover_plants: bool = True,
    ) -> None:
        if not username or not password:
            raise ProbeError("SEMS_USERNAME and SEMS_PASSWORD are required")
        if transport is None and not allow_live_requests:
            raise ProbeError("Live cloud requests require explicit opt-in")
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("probe timestamp must be timezone-aware")
        if stale_after_minutes <= 0:
            raise ValueError("freshness threshold must be positive")
        if not 1 <= request_budget <= 7:
            raise ValueError("request budget must be between one and seven")
        if login_url not in ALLOWED_LOGIN_URLS:
            raise ProbeError("Authentication origin is not explicitly allowlisted")
        self._login_url = login_url
        self._discover_plants = discover_plants
        self._request_count = 0
        self._request_budget = request_budget
        self._attempted = False
        self._owns_transport = transport is None
        self._username = username
        self._password = password
        self._transport = transport or requests.Session()
        self._now = (now or datetime.now(UTC)).astimezone(UTC)
        self._stale_after_minutes = stale_after_minutes
        self._token: dict[str, Any] | None = None
        self._gateway_base: str | None = None
        self._refresh_used = False

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        operation: str,
    ) -> dict[str, Any]:
        assert_endpoint_allowed(method, url)
        if self._request_count >= self._request_budget:
            raise ProbeError("One-shot request budget exhausted")
        self._request_count += 1
        try:
            response = self._transport.request(
                method,
                url,
                headers=headers,
                json=body,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise ProbeError(f"{operation} request failed") from None
        if not 200 <= response.status_code < 300:
            raise ProbeError(f"{operation} returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise ProbeError(f"{operation} returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ProbeError(f"{operation} returned an invalid response shape")
        return payload

    def authenticate(self, *, refresh: bool = False) -> None:
        empty_token = json.dumps(
            {
                "uid": "",
                "timestamp": 0,
                "token": "",
                "client": "semsPlusWeb",
                "version": "",
                "language": "en",
            },
            separators=(",", ":"),
        )
        timestamp_ms = str(int(time.time() * 1000))
        digest = hashlib.sha256(f"{timestamp_ms}@@".encode()).hexdigest()
        signature = base64.b64encode(f"{digest}@{timestamp_ms}".encode()).decode()
        password_digest = hashlib.md5(  # noqa: S324 - required by SEMS login
            self._password.encode(), usedforsecurity=False
        ).hexdigest()
        password_value = base64.b64encode(password_digest.encode()).decode()
        payload = self._request(
            "POST",
            self._login_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "token": empty_token,
                "client": "semsPlusWeb",
                "neutral": "0",
                "currentlang": "en",
                "x-signature": signature,
                "Origin": f"https://{urlparse(self._login_url).hostname}",
                "Referer": f"https://{urlparse(self._login_url).hostname}/",
            },
            body={
                "account": self._username,
                "pwd": password_value,
                "agreement": 1,
                "isLocal": False,
                "isChinese": False,
            },
            operation="authentication",
        )
        code = payload.get("code")
        data = payload.get("data") or {}
        gateway = payload.get("api") or (
            data.get("api") if isinstance(data, dict) else None
        )
        if (
            payload.get("hasError")
            or str(code) not in SUCCESS_CODES
            or not isinstance(data, dict)
            or not data.get("token")
            or not gateway
        ):
            raise ProbeError(
                "SEMS authentication failed "
                f"(success_code={str(code) in SUCCESS_CODES}, "
                f"token_present={isinstance(data, dict) and bool(data.get('token'))}, "
                f"gateway_present={bool(gateway)})"
            )
        self._gateway_base = validate_gateway_base(str(gateway))
        self._token = dict(data, api=self._gateway_base)
        if refresh:
            self._refresh_used = True

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            raise ProbeError("SEMS session is not authenticated")
        timestamp_ms = str(int(time.time() * 1000))
        uid = str(self._token.get("uid") or "")
        token = str(self._token.get("token") or "")
        digest = hashlib.sha256(f"{timestamp_ms}@{uid}@{token}".encode()).hexdigest()
        signature = base64.b64encode(f"{digest}@{timestamp_ms}".encode()).decode()
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "token": json.dumps(self._token, separators=(",", ":")),
            "client": "semsPlusWeb",
            "neutral": "0",
            "currentlang": "en",
            "x-signature": signature,
        }

    def _gateway_url(self, endpoint_name: str) -> str:
        if self._gateway_base is None:
            raise ProbeError("SEMS session has no regional gateway")
        spec = READ_ONLY_ENDPOINTS[endpoint_name]
        url = urljoin(f"{self._gateway_base.rstrip('/')}/", spec.path)
        assert_endpoint_allowed(spec.method, url)
        return url

    def _query(
        self,
        endpoint_name: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = READ_ONLY_ENDPOINTS[endpoint_name]
        payload = self._request(
            spec.method,
            self._gateway_url(endpoint_name),
            headers=self._headers(),
            body=body,
            params=params,
            operation=spec.semantic_operation,
        )
        if str(payload.get("code") or "") == SESSION_EXPIRED_CODE:
            if self._refresh_used:
                raise ProbeError(
                    "SEMS session expired again after the one allowed refresh"
                )
            self.authenticate(refresh=True)
            payload = self._request(
                spec.method,
                self._gateway_url(endpoint_name),
                headers=self._headers(),
                body=body,
                params=params,
                operation=spec.semantic_operation,
            )
            if str(payload.get("code") or "") == SESSION_EXPIRED_CODE:
                raise ProbeError(
                    "SEMS session expired again after the one allowed refresh"
                )
        if payload.get("hasError") or str(payload.get("code")) not in SUCCESS_CODES:
            raise ProbeError(f"{spec.semantic_operation} returned a non-success code")
        return payload

    def run_once(self) -> dict[str, Any]:
        if self._attempted:
            raise ProbeError("Probe instances may run only once")
        self._attempted = True
        try:
            return self._run_once()
        finally:
            if self._owns_transport:
                self._transport.close()

    def _run_once(self) -> dict[str, Any]:
        self.authenticate()
        plants = []
        if self._discover_plants:
            stations_payload = self._query(
                "discover_plants", body={"current": 1, "size": 50}
            )
            plants = parse_plants(stations_payload)
        chargers_payload = self._query(
            "discover_chargers",
            body={"deviceTypeList": ["EV_CHARGER"], "current": 1, "size": 50},
        )
        chargers = parse_chargers(chargers_payload)
        if not chargers:
            raise ProbeError("No EV charger was discovered in the SEMS account")
        if len(chargers) != 1:
            raise ProbeError("Charger selection is ambiguous; no detail requested")
        selected = chargers[0]
        serial, _ = _first(selected, "sn", "serialNumber", "deviceSn", "sno")
        plant_id, _ = _first(selected, "stationId", "plantId", "powerStationId")
        if plant_id is None and len(plants) == 1:
            plant_id, _ = _first(
                plants[0], "stationId", "id", "plantId", "powerStationId"
            )
        model, _ = _first(selected, "productModel", "model", "deviceModel", "type")
        detail_body: dict[str, Any] = {"sn": serial}
        if plant_id is not None:
            detail_body["plantId"] = plant_id
        if model is not None:
            detail_body["productModel"] = model
        detail_payload = self._query("charger_detail", body=detail_body)
        detail = detail_payload.get("data") or {}
        if not isinstance(detail, dict):
            raise ProbeError("charger detail returned an invalid response shape")
        if plant_id is None:
            raise ProbeError("No plant identifier was available for last-charge query")
        last_payload = self._query(
            "last_charge", params={"chargeSn": serial, "pwId": plant_id}
        )
        last_data = last_payload.get("data") or {}
        charge_log = last_data.get("chargeLog") if isinstance(last_data, dict) else None
        if not isinstance(charge_log, dict):
            charge_log = {}
        summary = summarize_charger_evidence(
            detail=detail,
            charge_log=charge_log,
            now=self._now,
            stale_after_minutes=self._stale_after_minutes,
        )
        summary.update(
            request_count=self._request_count,
            charger_count=len(chargers),
            plant_count=len(plants) if self._discover_plants else None,
            charger_identifier=redact_identifier(serial),
            charger_model=_raw_scalar(detail.get("productModel", model)),
        )
        self._assert_private_values_absent(summary, serial=serial, plant_id=plant_id)
        return summary

    def _assert_private_values_absent(
        self, summary: dict[str, Any], *, serial: Any, plant_id: Any
    ) -> None:
        rendered = json.dumps(summary, ensure_ascii=False)
        token = str((self._token or {}).get("token") or "")
        forbidden_values = (
            self._username,
            self._password,
            token,
            str((self._token or {}).get("uid") or ""),
            str(serial or ""),
            str(plant_id or ""),
        )
        if any(value and value in rendered for value in forbidden_values):
            raise ProbeError("Privacy guard rejected the normalized output")


def _raw_scalar(value: Any) -> str | float | bool | int | None:
    """Retain bounded scalar evidence, never full attributes or nested objects."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str) and len(value) <= 128:
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    raise ProbeError("Telemetry field is not a bounded finite scalar")


def _source_timing(
    raw: dict[str, Any], now: datetime, stale_after_minutes: int
) -> dict[str, Any]:
    value, field = _first(raw, "lastUpdate", "updateTime", "reportTime")
    try:
        stamp = aware_datetime(value).astimezone(UTC) if value is not None else None
    except (ValueError, TypeError, OverflowError):
        stamp = None
    age = (now - stamp).total_seconds() if stamp is not None else None
    return {
        "timestamp_field": field if value is not None else None,
        "timestamp_raw": _raw_scalar(value),
        "timestamp_utc": stamp.isoformat() if stamp is not None else None,
        "age_seconds": age,
        "freshness": (
            "unknown"
            if age is None
            else (
                "future"
                if age < 0
                else "stale" if age > stale_after_minutes * 60 else "fresh"
            )
        ),
        "confidence": "source_timestamp_semantics_unvalidated",
    }


def summarize_charger_evidence(
    *,
    detail: dict[str, Any],
    charge_log: dict[str, Any],
    now: datetime,
    stale_after_minutes: int = 15,
) -> dict[str, Any]:
    """Capture candidate fields without claiming their AC domain or live meaning.

    Last-session power may be an average or maximum, and status codes and units
    need natural-session evidence. Nothing here is eligible for baseline demand
    subtraction. Timestamp evidence never crosses an endpoint boundary.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evidence evaluation requires a timezone-aware timestamp")
    if stale_after_minutes <= 0:
        raise ValueError("freshness threshold must be positive")
    sources = {
        "detail": (
            detail,
            READ_ONLY_ENDPOINTS["charger_detail"].path,
            (
                "power",
                "chargePower",
                "activePower",
                "powerUnit",
                "current",
                "chargeCurrent",
                "currentUnit",
                "isOnline",
                "online",
                "onlineStatus",
                "status",
                "workstate",
                "workState",
                "carState",
                "lastUpdate",
                "updateTime",
                "reportTime",
            ),
        ),
        "last_charge": (
            charge_log,
            READ_ONLY_ENDPOINTS["last_charge"].path,
            (
                "workStu",
                "pevChar",
                "currentChargeQuantity",
                "chargeTimeLength",
                "lastUpdate",
                "updateTime",
                "reportTime",
                "startTime",
                "endTime",
            ),
        ),
    }
    fields: dict[str, Any] = {}
    timing = {}
    for source, (raw, endpoint, keys) in sources.items():
        timing[source] = _source_timing(raw, now.astimezone(UTC), stale_after_minutes)
        for key in keys:
            value = _raw_scalar(raw.get(key))
            fields[f"{source}.{key}"] = {
                "source_endpoint": endpoint,
                "source_field": key,
                "raw_value": value,
                "raw_available": value is not None,
                "normalized_value": None,
                "raw_unit": None,
                "measurement_domain": "unverified_charger_cloud",
                "confidence": "unvalidated",
            }
    return {
        "schema_version": 2,
        "probe_mode": "one_shot_read_only_evidence",
        "evaluated_at_utc": now.astimezone(UTC).isoformat(),
        "fields": fields,
        "source_timing": timing,
        "ac_power_w": None,
        "charging_active": None,
        "session_energy_kwh": None,
        "plugged_in": None,
        "eligible_for_baseline_subtraction": False,
        "validation_required": [
            "AC measurement domain and units",
            "live power versus last-session average or maximum",
            "status codes during natural charging and plugged idle",
            "per-source timestamps and update cadence",
        ],
    }
