"""Run the drift-free, read-only five-minute collector."""

import logging
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
    collect_once: Callable[[], None],
    *,
    interval: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> None:
    while True:
        delay = seconds_to_next_boundary(clock(), interval)
        sleep(delay)
        try:
            collect_once()
        except HomeAssistantError as exc:
            LOGGER.error("Transient Home Assistant read failed: %s", exc)
        except DatabaseConnectionError as exc:
            LOGGER.error(
                "Database connection failed; next boundary will retry: %s", exc
            )
        except DatabaseTransactionError as exc:
            LOGGER.error("Database transaction failed; write was rolled back: %s", exc)


def main() -> int:
    configure_logging()
    config = load_config()
    store = ObservationStore()

    def collect_once() -> None:
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

    LOGGER.info(
        "Starting strictly read-only collector. No hardware commands are available."
    )
    try:
        run(collect_once, interval=config.collection_interval_seconds)
    except KeyboardInterrupt:
        LOGGER.info("Collector stopped cleanly. No command was issued.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
