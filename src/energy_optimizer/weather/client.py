"""One bounded HTTPS GET; no retries, redirects, pagination traversal or fallback."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

from energy_optimizer.weather.deadline import deadline_adapter

ENDPOINT = "https://api.openweathermap.org/data/4.0/onecall/timeline/15min"
MAX_PAYLOAD_BYTES = 2_000_000


@dataclass(frozen=True)
class PageResponse:
    status: int
    received_at: datetime
    raw: bytes = field(repr=False)


class WeatherFetchError(RuntimeError):
    """Only fixed safe error codes cross the transport boundary."""


class OneCallClient:
    def __init__(
        self,
        *,
        session_factory: Callable = requests.Session,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    def fetch(
        self, *, key: str, latitude: float, longitude: float, start_epoch: int
    ) -> PageResponse:
        response = None
        try:
            with self.session_factory() as session:
                session.trust_env = False
                started = time.monotonic()
                session.mount("https://", deadline_adapter(started + 20))
                response = session.get(
                    ENDPOINT,
                    params={
                        "appid": key,
                        "lat": latitude,
                        "lon": longitude,
                        "units": "metric",
                        "lang": "en",
                        "start": start_epoch,
                    },
                    timeout=(5, 10),
                    allow_redirects=False,
                    stream=True,
                )
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_PAYLOAD_BYTES or time.monotonic() - started > 20:
                        raise WeatherFetchError("RESPONSE_LIMIT")
                    chunks.append(chunk)
                return PageResponse(
                    response.status_code, self.clock(), b"".join(chunks)
                )
        except requests.RequestException:
            raise WeatherFetchError("TRANSPORT_OUTCOME_UNKNOWN") from None
        finally:
            if response is not None:
                response.close()
