"""Validate and run the collector inside a Home Assistant App."""

import logging
import os
import signal
import threading

import run_collector

from energy_optimizer.config import load_config
from energy_optimizer.db.redaction import display_database_url
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
)
from energy_optimizer.home_assistant_app import (
    HEALTH_PORT,
    AppHealth,
    app_environment,
    load_app_options,
    redact_runtime_error,
    start_dashboard_server,
    validate_startup,
)
from energy_optimizer.logging_config import configure_logging
from energy_optimizer.persistence import open_bounded_forecast_repository

LOGGER = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    options = None
    try:
        options = load_app_options()
        return _run(options)
    except Exception as exc:
        database_password = (
            options.db_password.get_secret_value() if options is not None else None
        )
        LOGGER.error(
            "Home Assistant App startup failed: %s",
            redact_runtime_error(
                exc,
                database_password,
                os.getenv("SUPERVISOR_TOKEN"),
            ),
        )
        return 1


def _run(options) -> int:
    environment = app_environment(options)
    os.environ.update(environment)
    config = load_config(env_file=None)
    LOGGER.info(
        "Starting Home Assistant App with %s",
        display_database_url(environment["DATABASE_URL"]),
    )
    validate_startup(
        database_url=environment["DATABASE_URL"],
        ha_url=config.ha_url,
        ha_token=config.ha_token,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    LOGGER.info(
        "Startup validation passed: PostgreSQL revision, application readiness, "
        "and read-only Home Assistant entity access"
    )
    health = AppHealth(options.health_max_observation_age_seconds)
    server, thread = start_dashboard_server(
        health, database_url=environment["DATABASE_URL"], port=HEALTH_PORT
    )
    LOGGER.info(
        "Read-only dashboard server ready for Home Assistant Ingress on port %s",
        HEALTH_PORT,
    )
    stop_event = threading.Event()
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_bounded_forecast_repository(
            environment["DATABASE_URL"],
            max_runtime_seconds=options.forecast_max_runtime_seconds,
        ),
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=options.forecast_operations_enabled,
            interval_minutes=options.forecast_interval_minutes,
            horizon_hours=options.forecast_horizon_hours,
            alignment_minutes=options.forecast_alignment_minutes,
            scoring_delay_minutes=options.forecast_scoring_delay_minutes,
            max_runtime_seconds=options.forecast_max_runtime_seconds,
            reserve_snapshot_enabled=options.reserve_snapshot_enabled,
            timezone=options.timezone,
        ),
        health=health,
    )
    forecast_thread = threading.Thread(
        target=coordinator.run,
        args=(stop_event,),
        name="forecast-coordinator",
        daemon=True,
    )
    forecast_thread.start()

    def stop(_signum, _frame) -> None:
        LOGGER.info("Shutdown requested; stopping before the next collection attempt")
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return run_collector.main(
            stop_event=stop_event,
            on_success=health.record_success,
            on_failure=health.record_failure,
        )
    finally:
        stop_event.set()
        forecast_thread.join(timeout=options.forecast_max_runtime_seconds + 5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        LOGGER.info("Dashboard server stopped cleanly")


if __name__ == "__main__":
    raise SystemExit(main())
