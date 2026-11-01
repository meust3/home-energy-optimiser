"""One weather page per existing coordinator step; no worker or startup request."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.weather.client import ENDPOINT, OneCallClient, WeatherFetchError
from energy_optimizer.weather.config import WeatherCollectionConfig
from energy_optimizer.weather.pagination import page_metadata
from energy_optimizer.weather.providers import parse_onecall4
from energy_optimizer.weather.receipt import PayloadReceipt
from energy_optimizer.weather.repository import WeatherRepository
from energy_optimizer.weather.spool import PendingPage, WeatherSpool

LOGGER = logging.getLogger(__name__)


class WeatherCollector:
    def __init__(
        self,
        *,
        config: WeatherCollectionConfig,
        repository_factory: Callable[[], DatabaseRepository],
        on_status: Callable[[dict[str, Any]], None],
        client: OneCallClient | None = None,
        spool: WeatherSpool | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.repository_factory = repository_factory
        self.on_status = on_status
        self.client = client or OneCallClient()
        self.clock = clock
        self.active = False
        self.spool = spool
        self._pending: PendingPage | None = None
        self.on_status({"status": "disabled" if not config.enabled else "pending"})

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def step(self, now: datetime, *, collector_idle: bool) -> dict[str, Any]:
        if not self.enabled:
            return self._report({"status": "disabled"})
        if not self.config.ready:
            return self._report({"status": "not_configured"})
        if not collector_idle:
            return self._report({"status": "deferred_to_collector"})
        repository = None
        try:
            if self.spool is None:
                return self._report({"status": "spool_not_configured"})
            self.spool.prepare()
            self._pending = self._pending or self.spool.load()
            repository = self.repository_factory()
            archive = WeatherRepository(repository)
            if self._pending is None:
                claim = archive.claim_page(self.config, now)
                if claim["status"] != "RESERVED":
                    self.active = claim["status"] == "PAGE_IN_FLIGHT"
                    return self._report(claim)
                self._pending = self._fetch(claim)
            page = self._pending
            # Fsync sanitized receipt before normalization or canonical DB delivery.
            # Do not acquire another page until this receipt is acknowledged.
            self.spool.save(page)
            capture = None
            error = page.error_code
            if page.receipt is not None and page.http_status == 200:
                try:
                    capture = parse_onecall4(
                        page.receipt.body,
                        product="onecall4_15min",
                        site_ref="home",
                        requested_at=page.claim["requested_at"],
                        received_at=page.finished_at,
                        requested_units="metric",
                    )
                except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
                    error = "INVALID_PAGE_OR_PAGINATION"
            result = archive.finish_page(
                page.claim,
                now=page.finished_at,
                config=self.config,
                raw=page.receipt.body if page.receipt else None,
                http_status=page.http_status,
                capture=capture,
                navigation=page.navigation,
                error_code=error,
                receipt=page.receipt,
            )
            self.spool.acknowledge(page)
            self._pending = None
            self.active = result["status"] == "COLLECTING"
            return self._report(result)
        except Exception:
            # Network exceptions are already safe codes. Database errors may contain
            # private payload parameters; never log the exception or its traceback.
            LOGGER.error("Optional weather collection failed; details withheld")
            self.active = self._pending is not None
            return self._report({"status": "archive_unavailable"})
        finally:
            if repository is not None:
                repository.close()

    def _fetch(self, claim: dict[str, Any]) -> PendingPage:
        try:
            response = self.client.fetch(
                key=self.config.api_key,
                latitude=self.config.latitude,
                longitude=self.config.longitude,
                start_epoch=claim["request_start_epoch"],
            )
        except WeatherFetchError:
            return PendingPage(
                claim, self.clock(), None, None, None, "TRANSPORT_OUTCOME_UNKNOWN"
            )
        page = PendingPage(
            claim,
            response.received_at,
            response.status,
            PayloadReceipt.from_wire(response.raw, self.config.api_key),
            None,
            (
                "PAGINATION_NOT_PERSISTED"
                if response.status == 200
                else f"HTTP_{response.status}"
            ),
        )
        # Keep the received bytes recoverable even if navigation/normalization crashes.
        self._pending = page
        self.spool.save(page)
        if response.status != 200:
            return page
        try:
            navigation = page_metadata(
                response.raw,
                endpoint=ENDPOINT,
                page_start=claim["request_start_epoch"],
                horizon_end=int(claim["window_end"].timestamp()),
                latitude=self.config.latitude,
                longitude=self.config.longitude,
                key=self.config.api_key,
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
            RecursionError,
        ):
            return replace(page, error_code="INVALID_PAGE_OR_PAGINATION")
        return replace(page, navigation=navigation, error_code=None)

    def _report(self, result: dict[str, Any]) -> dict[str, Any]:
        self.on_status(result)
        return result
