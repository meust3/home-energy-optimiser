"""Validate and run the collector inside a Home Assistant App."""

import logging
import os
import signal
import threading

import run_collector

from energy_optimizer.config import load_config
from energy_optimizer.db.redaction import display_database_url
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
    LOGGER.info(
        "Power-flow configuration grid_sign=%s battery_sign=%s "
        "sign_confidence=%s supporting_samples=%s balance_tolerance_w=%s",
        options.grid_power_sign,
        options.battery_power_sign,
        options.sign_convention_confidence,
        options.sign_convention_supporting_samples,
        options.balance_tolerance_w,
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
    health = AppHealth(
        options.health_max_observation_age_seconds,
        grid_power_sign=options.grid_power_sign,
        battery_power_sign=options.battery_power_sign,
        sign_convention_confidence=options.sign_convention_confidence,
        sign_convention_supporting_samples=options.sign_convention_supporting_samples,
        balance_tolerance_w=options.balance_tolerance_w,
    )
    server, thread = start_dashboard_server(
        health, database_url=environment["DATABASE_URL"], port=HEALTH_PORT
    )
    LOGGER.info(
        "Read-only dashboard server ready for Home Assistant Ingress on port %s",
        HEALTH_PORT,
    )
    stop_event = threading.Event()

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
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        LOGGER.info("Dashboard server stopped cleanly")


if __name__ == "__main__":
    raise SystemExit(main())
