"""Run the drift-free, read-only five-minute collector."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from energy_optimizer.collector import Collector
from energy_optimizer.config import load_config
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient, HomeAssistantError
from energy_optimizer.logging_config import configure_logging

LOGGER = logging.getLogger(__name__)


def seconds_to_next_boundary(now_timestamp: float, interval: int) -> float:
    return interval - (now_timestamp % interval)


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


def main() -> int:
    configure_logging()
    config = load_config()
    historian = Historian(config.database_path)

    def collect_once() -> None:
        with HomeAssistantClient(
            config.ha_url,
            config.ha_token,
            timeout_seconds=config.request_timeout_seconds,
        ) as client:
            observation = Collector(client, config).collect(
                observed_at=datetime.now(UTC)
            )
        historian.save(observation)
        LOGGER.info(
            "Saved slot %s (telemetry %s, price %s, solar %s, weather %s, "
            "overall %s). No command was issued.",
            observation.slot_utc.isoformat(),
            observation.data_health.telemetry.score,
            observation.data_health.price.score,
            observation.data_health.solar.score,
            observation.data_health.weather.score,
            observation.data_health.overall.score,
        )

    LOGGER.info(
        "Starting strictly read-only collector. No hardware commands are available."
    )
    try:
        run(collect_once, interval=config.collection_interval_seconds)
    except KeyboardInterrupt:
        LOGGER.info("Collector stopped cleanly. No command was issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
