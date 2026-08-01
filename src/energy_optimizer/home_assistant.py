"""A deliberately GET-only Home Assistant HTTP client."""

from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import requests

from energy_optimizer.models import HomeAssistantState


def redact_secret(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


class HomeAssistantError(RuntimeError):
    """Base error for safe Home Assistant reads."""


class HomeAssistantConnectionError(HomeAssistantError):
    """Network or timeout failure."""


class HomeAssistantResponseError(HomeAssistantError):
    """Unexpected HTTP response or payload."""


class ReadOnlyViolation(HomeAssistantError):
    """Attempted access outside the explicitly allowed GET surface."""


class HomeAssistantClient:
    """Read Home Assistant states; this class has no mutation method."""

    _ALLOWED_EXACT_PATHS = frozenset({"/api/", "/api/states"})

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def __enter__(self) -> "HomeAssistantClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _get_json(self, path: str) -> Any:
        allowed = path in self._ALLOWED_EXACT_PATHS or path.startswith("/api/states/")
        if not allowed or path.startswith("/api/services"):
            raise ReadOnlyViolation(f"Path is not allowed by read-only client: {path}")
        try:
            response = self._session.get(
                f"{self._base_url}{path}", timeout=self._timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            message = redact_secret(str(exc), self._token)
            raise HomeAssistantConnectionError(message) from exc
        except ValueError as exc:
            raise HomeAssistantResponseError(
                "Home Assistant returned invalid JSON"
            ) from exc

    def check_api(self) -> dict[str, Any]:
        payload = self._get_json("/api/")
        if not isinstance(payload, dict):
            raise HomeAssistantResponseError("Expected an object from /api/")
        return payload

    def get_state(self, entity_id: str) -> HomeAssistantState:
        payload = self._get_json(f"/api/states/{quote(entity_id, safe='._')}")
        try:
            return HomeAssistantState.model_validate(payload)
        except ValueError as exc:
            raise HomeAssistantResponseError(
                f"Invalid state payload for {entity_id}"
            ) from exc

    def get_states(
        self, entity_ids: Iterable[str] | None = None
    ) -> dict[str, HomeAssistantState]:
        """Fetch all states once, then filter locally for efficient bulk collection."""
        payload = self._get_json("/api/states")
        if not isinstance(payload, list):
            raise HomeAssistantResponseError("Expected a list from /api/states")
        wanted = set(entity_ids) if entity_ids is not None else None
        result: dict[str, HomeAssistantState] = {}
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("entity_id"), str):
                continue
            if wanted is None or item["entity_id"] in wanted:
                try:
                    state = HomeAssistantState.model_validate(item)
                except ValueError as exc:
                    raise HomeAssistantResponseError(
                        f"Invalid state payload for {item['entity_id']}"
                    ) from exc
                result[state.entity_id] = state
        return result
