"""Run the drift-free, read-only five-minute collector."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from energy_optimizer.collector import Collector
from energy_optimizer.config import load_config
from energy_optimizer.db.engine import DatabaseConnectionError, DatabaseTransactionError
from energy_optimizer.home_assistant import HomeAssistantClient, HomeAssistantError
from energy_optimizer.logging_config import configure_logging
from energy_optimizer.persistence import ObservationStore

LOGGER = logging.getLogger(__name__)


def seconds_to_next_boundary(now_timestamp: float, interval: int) -> float:
    return interval - (now_timestamp % interval)


def save_with_retry(
    save: Callable[[], object],
    *,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Retry transient connection failures with bounded exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return save()
        except DatabaseConnectionError:
            if attempt == attempts:
                raise
            delay = 2 ** (attempt - 1)
            LOGGER.warning(
                "Database unavailable; retrying write in %s second(s) (%s/%s)",
                delay,
                attempt,
                attempts,
            )
            sleep(delay)
    raise AssertionError("unreachable")


def run(
    collect_once: Callable[[], object],
    *,
    interval: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    stop_event: threading.Event | None = None,
    on_success: Callable[[object], None] | None = None,
    on_failure: Callable[[str], None] | None = None,
) -> None:
    while stop_event is None or not stop_event.is_set():
        delay = seconds_to_next_boundary(clock(), interval)
        if stop_event is not None:
            if stop_event.wait(delay):
                break
        else:
            sleep(delay)
        try:
            result = collect_once()
            if on_success is not None:
                on_success(result)
        except HomeAssistantError as exc:
            LOGGER.error("Transient Home Assistant read failed: %s", exc)
            if on_failure is not None:
                on_failure("home_assistant")
        except DatabaseConnectionError as exc:
            LOGGER.error(
                "Database connection failed; next boundary will retry: %s", exc
            )
            if on_failure is not None:
                on_failure("database")
        except DatabaseTransactionError as exc:
            LOGGER.error("Database transaction failed; write was rolled back: %s", exc)
            if on_failure is not None:
                on_failure("database")


def main(
    *,
    stop_event: threading.Event | None = None,
    on_success: Callable[[object], None] | None = None,
    on_failure: Callable[[str], None] | None = None,
) -> int:
    configure_logging()
    config = load_config()
    store = ObservationStore()

    def collect_once() -> object:
        with HomeAssistantClient(
            config.ha_url,
            config.ha_token,
            timeout_seconds=config.request_timeout_seconds,
        ) as client:
            observation = Collector(client, config).collect(
                observed_at=datetime.now(UTC)
            )
        result = save_with_retry(lambda: store.save(observation))
        LOGGER.info(
            "Saved slot %s (telemetry %s, price %s, solar %s, weather %s, "
            "flow %s, overall %s, duplicate result %s). No command was issued.",
            observation.slot_utc.isoformat(),
            observation.data_health.telemetry.score,
            observation.data_health.price.score,
            observation.data_health.solar.score,
            observation.data_health.weather.score,
            observation.data_health.flow.score,
            observation.data_health.overall.score,
            result,
        )
        return observation

    LOGGER.info(
        "Starting strictly read-only collector. No hardware commands are available."
    )
    try:
        run(
            collect_once,
            interval=config.collection_interval_seconds,
            stop_event=stop_event,
            on_success=on_success,
            on_failure=on_failure,
        )
    except KeyboardInterrupt:
        LOGGER.info("Collector stopped cleanly. No command was issued.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
