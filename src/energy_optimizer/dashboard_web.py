"""Ingress-aware, GET-only standard-library web application."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

from energy_optimizer.dashboard_api import DashboardQueryError, DashboardService

LOGGER = logging.getLogger(__name__)
INGRESS_GATEWAY_ADDRESS = "172.30.32.2"
STATIC_DIRECTORY = Path(__file__).with_name("dashboard_static")
STATIC_FILES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}
SHELL_ROUTES = {
    "/",
    "/overview",
    "/history",
    "/forecasts",
    "/forecast-operations",
    "/reserve",
    "/data-quality",
}


class IngressAccessPolicy:
    """Authorize from the socket peer; forwarded identity headers are irrelevant."""

    def __init__(
        self,
        *,
        ingress_gateway: str = INGRESS_GATEWAY_ADDRESS,
        allow_loopback: bool = True,
    ) -> None:
        self.ingress_gateway = ip_address(ingress_gateway)
        self.allow_loopback = allow_loopback

    def allows(self, peer_address: str, path: str) -> bool:
        if path == "/health":
            return True
        try:
            peer = ip_address(peer_address.split("%", 1)[0])
        except ValueError:
            return False
        return peer == self.ingress_gateway or (
            self.allow_loopback and peer.is_loopback
        )


def normalize_ingress_path(value: str | None) -> str:
    """Return one safe trailing-slash prefix for relative browser navigation."""
    if not value:
        return "/"
    split = urlsplit(value)
    if split.scheme or split.netloc or split.query or split.fragment:
        raise DashboardQueryError("invalid_ingress_path", "Invalid Ingress path.")
    path = split.path
    if (
        not path.startswith("/")
        or "\\" in path
        or "//" in path
        or len(path) > 512
        or re.fullmatch(r"/[A-Za-z0-9._~/-]*", path) is None
    ):
        raise DashboardQueryError("invalid_ingress_path", "Invalid Ingress path.")
    parts = PurePosixPath(path).parts
    if ".." in parts:
        raise DashboardQueryError("invalid_ingress_path", "Invalid Ingress path.")
    normalized = "/" + "/".join(part for part in parts if part != "/")
    return normalized.rstrip("/") + "/" if normalized != "/" else "/"


def route_path(request_path: str, ingress_prefix: str) -> str:
    """Strip at most one trusted Ingress prefix without duplicating components."""
    path = urlsplit(request_path).path
    prefix_without_slash = ingress_prefix.rstrip("/")
    if ingress_prefix != "/":
        if path == prefix_without_slash:
            return "/"
        if path.startswith(ingress_prefix):
            path = "/" + path[len(ingress_prefix) :].lstrip("/")
    return path or "/"


def make_handler(
    *,
    health: Any,
    service: DashboardService,
    access_policy: IngressAccessPolicy,
    static_directory: Path = STATIC_DIRECTORY,
):
    """Build a dependency-injected handler class for production and tests."""

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "HomeEnergyDashboard"
        sys_version = ""

        def version_string(self) -> str:
            return "HomeEnergyDashboard"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            raw_path = urlsplit(self.path).path
            peer = self.client_address[0]
            if not access_policy.allows(peer, raw_path):
                self._json_error(
                    HTTPStatus.FORBIDDEN,
                    "ingress_required",
                    "This resource is available only through Home Assistant Ingress.",
                )
                return
            try:
                prefix = normalize_ingress_path(self.headers.get("X-Ingress-Path"))
                route = route_path(self.path, prefix)
                if route == "/health":
                    status, payload = health.response()
                    self._json(status, payload, cache="no-store")
                elif route in SHELL_ROUTES:
                    self._shell(prefix)
                elif route.startswith("/static/"):
                    self._static(route.removeprefix("/static/"), static_directory)
                elif route.startswith("/api/v1/"):
                    self._api(route)
                else:
                    self._json_error(
                        HTTPStatus.NOT_FOUND,
                        "not_found",
                        "The requested dashboard resource was not found.",
                    )
            except DashboardQueryError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, exc.code, exc.message)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                LOGGER.error("Dashboard request failed; details withheld")
                self._json_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "dashboard_unavailable",
                    "Dashboard data is temporarily unavailable.",
                )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            self._method_not_allowed()

        def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
            self._method_not_allowed()

        def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
            self._method_not_allowed()

        def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
            self._method_not_allowed()

        def _method_not_allowed(self) -> None:
            self._json_error(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "read_only",
                "Only GET requests are supported.",
                extra_headers={"Allow": "GET"},
            )

        def _shell(self, prefix: str) -> None:
            template = (static_directory / "index.html").read_text(encoding="utf-8")
            base = escape(prefix, quote=True)
            body = template.replace("__INGRESS_BASE_PATH__", base).encode("utf-8")
            self._send(
                HTTPStatus.OK,
                body,
                "text/html; charset=utf-8",
                cache="no-store",
            )

        def _static(self, name: str, directory: Path) -> None:
            content_type = STATIC_FILES.get(name)
            if content_type is None:
                self._json_error(
                    HTTPStatus.NOT_FOUND,
                    "not_found",
                    "The requested dashboard resource was not found.",
                )
                return
            body = (directory / name).read_bytes()
            self._send(
                HTTPStatus.OK,
                body,
                content_type,
                cache="public, max-age=3600",
            )

        def _api(self, route: str) -> None:
            params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if route == "/api/v1/status":
                self._require_params(params, set())
                response = service.status()
            elif route == "/api/v1/live":
                self._require_params(params, set())
                response = service.live()
            elif route == "/api/v1/timeseries":
                self._require_params(params, {"range", "start", "end", "resolution"})
                response = service.timeseries(
                    range_name=self._single(params, "range") or "24h",
                    start=self._timestamp(params, "start"),
                    end=self._timestamp(params, "end"),
                    resolution=self._single(params, "resolution") or "auto",
                )
            elif route == "/api/v1/forecast-runs":
                self._require_params(
                    params, {"forecast_type", "after", "before", "limit"}
                )
                response = service.forecast_runs(
                    forecast_type=self._single(params, "forecast_type"),
                    after=self._timestamp(params, "after"),
                    before=self._timestamp(params, "before"),
                    limit=self._integer(
                        params, "limit", default=25, minimum=1, maximum=100
                    ),
                )
            elif route == "/api/v1/forecast-comparison":
                self._require_params(
                    params,
                    {"forecast_run_id", "forecast_type", "start", "end", "limit"},
                )
                response = service.forecast_comparison(
                    forecast_run_id=self._optional_integer(
                        params, "forecast_run_id", minimum=1, maximum=2_147_483_647
                    ),
                    forecast_type=self._single(params, "forecast_type"),
                    start=self._timestamp(params, "start"),
                    end=self._timestamp(params, "end"),
                    limit=self._integer(
                        params, "limit", default=2500, minimum=1, maximum=2500
                    ),
                )
            elif route == "/api/v1/reserve/latest":
                self._require_params(params, set())
                response = service.reserve_latest()
            elif route == "/api/v1/forecast-operations/status":
                self._require_params(params, set())
                response = service.forecast_operations_status()
            elif route == "/api/v1/forecast-accuracy":
                self._require_params(params, {"range", "forecast_run_id"})
                response = service.forecast_accuracy(
                    range_name=self._single(params, "range") or "7d",
                    forecast_run_id=self._optional_integer(
                        params,
                        "forecast_run_id",
                        minimum=1,
                        maximum=2_147_483_647,
                    ),
                )
            elif route == "/api/v1/reserve-history":
                self._require_params(params, {"range"})
                response = service.reserve_history(
                    range_name=self._single(params, "range") or "30d"
                )
            elif route == "/api/v1/data-quality":
                self._require_params(params, {"range", "start", "end"})
                response = service.data_quality(
                    range_name=self._single(params, "range") or "30d",
                    start=self._timestamp(params, "start"),
                    end=self._timestamp(params, "end"),
                )
            else:
                self._json_error(
                    HTTPStatus.NOT_FOUND,
                    "not_found",
                    "The requested API resource was not found.",
                )
                return
            body = response.model_dump_json().encode("utf-8")
            self._send(
                HTTPStatus.OK,
                body,
                "application/json; charset=utf-8",
                cache="no-store",
            )

        def _require_params(
            self, params: dict[str, list[str]], allowed: set[str]
        ) -> None:
            unknown = set(params) - allowed
            if unknown:
                raise DashboardQueryError(
                    "unknown_parameter", "Unsupported dashboard query parameter."
                )
            if any(len(values) != 1 for values in params.values()):
                raise DashboardQueryError(
                    "duplicate_parameter", "Query parameters may be supplied once."
                )

        def _single(self, params: dict[str, list[str]], name: str) -> str | None:
            values = params.get(name)
            if not values:
                return None
            value = values[0].strip()
            return value or None

        def _timestamp(
            self, params: dict[str, list[str]], name: str
        ) -> datetime | None:
            value = self._single(params, name)
            if value is None:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise DashboardQueryError(
                    "invalid_timestamp", "Timestamp must be valid ISO 8601."
                ) from None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise DashboardQueryError(
                    "timezone_required", "Dashboard timestamps must include a timezone."
                )
            return parsed

        def _optional_integer(
            self,
            params: dict[str, list[str]],
            name: str,
            *,
            minimum: int,
            maximum: int,
        ) -> int | None:
            value = self._single(params, name)
            if value is None:
                return None
            return self._validated_integer(value, minimum=minimum, maximum=maximum)

        def _integer(
            self,
            params: dict[str, list[str]],
            name: str,
            *,
            default: int,
            minimum: int,
            maximum: int,
        ) -> int:
            value = self._single(params, name)
            return (
                default
                if value is None
                else self._validated_integer(value, minimum=minimum, maximum=maximum)
            )

        @staticmethod
        def _validated_integer(value: str, *, minimum: int, maximum: int) -> int:
            try:
                parsed = int(value)
            except ValueError:
                raise DashboardQueryError(
                    "invalid_integer", "Query value must be an integer."
                ) from None
            if not minimum <= parsed <= maximum:
                raise DashboardQueryError(
                    "invalid_integer", "Query value is outside the allowed range."
                )
            return parsed

        def _json(self, status: int, payload: dict[str, Any], *, cache: str) -> None:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
            self._send(status, body, "application/json; charset=utf-8", cache=cache)

        def _json_error(
            self,
            status: int,
            code: str,
            message: str,
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(
                {"error": {"code": code, "message": message}}, separators=(",", ":")
            ).encode()
            self._send(
                status,
                body,
                "application/json; charset=utf-8",
                cache="no-store",
                extra_headers=extra_headers,
            )

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            *,
            cache: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'none'; "
                "object-src 'none'; base-uri 'self'; form-action 'none'; "
                "frame-ancestors 'self'",
            )
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return DashboardHandler


def create_dashboard_server(
    *,
    health: Any,
    database_url: str,
    port: int,
    access_policy: IngressAccessPolicy | None = None,
    repository_factory=None,
) -> ThreadingHTTPServer:
    """Create the one internal Ingress/watchdog server without starting a worker."""
    service = (
        DashboardService(database_url, health)
        if repository_factory is None
        else DashboardService(
            database_url, health, repository_factory=repository_factory
        )
    )
    handler = make_handler(
        health=health,
        service=service,
        access_policy=access_policy or IngressAccessPolicy(),
    )
    return ThreadingHTTPServer(("0.0.0.0", port), handler)
