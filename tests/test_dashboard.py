import http.client
import json
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from energy_optimizer.collector import build_observation
from energy_optimizer.dashboard_api import (
    DashboardQueryError,
    DashboardService,
    aggregate_timeseries,
    resolve_resolution,
    resolve_window,
)
from energy_optimizer.dashboard_web import (
    IngressAccessPolicy,
    make_handler,
    normalize_ingress_path,
    route_path,
)
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.models import ForecastPoint, ForecastRun
from energy_optimizer.persistence import open_repository


def _repository_url(config):
    return f"sqlite:///{config.database_path}"


@pytest.fixture
def dashboard_database(healthy_states, config, now):
    url = _repository_url(config)
    repository = open_repository(url)
    repository.create_schema_for_tests()
    first = build_observation(healthy_states, config, observed_at=now)
    repository.save_observation(first)
    second = build_observation(
        healthy_states, config, observed_at=now + timedelta(minutes=10)
    )
    repository.save_observation(second)
    run_id = repository.save_forecast_run(
        ForecastRun(
            created_at_utc=now - timedelta(hours=1),
            forecast_type="household_load",
            source="unit-test",
            horizon_start_utc=first.slot_utc,
            horizon_end_utc=first.slot_utc + timedelta(minutes=5),
            model_version="test-v1",
            metadata={},
            points=[
                ForecastPoint(
                    period_start_utc=first.slot_utc,
                    period_end_utc=first.slot_utc + timedelta(minutes=5),
                    expected_value=1700,
                    lower_value=1500,
                    upper_value=1900,
                    unit="W",
                )
            ],
        )
    )
    repository.close()
    return url, first, run_id


def test_ingress_policy_uses_actual_peer_and_preserves_health():
    policy = IngressAccessPolicy()
    assert policy.allows("172.30.32.2", "/api/v1/live")
    assert policy.allows("127.0.0.1", "/")
    assert policy.allows("192.0.2.10", "/health")
    assert not policy.allows("192.0.2.10", "/api/v1/live")
    assert not policy.allows("192.0.2.10", "/")


def test_ingress_path_normalization_and_routing():
    prefix = normalize_ingress_path("/api/hassio_ingress/example-token/")
    assert prefix == "/api/hassio_ingress/example-token/"
    assert route_path("/", prefix) == "/"
    assert route_path(prefix, prefix) == "/"
    assert route_path(prefix + "static/app.css", prefix) == "/static/app.css"
    assert route_path(prefix + "history", prefix) == "/history"
    assert route_path("/api/v1/live", "/") == "/api/v1/live"
    with pytest.raises(DashboardQueryError):
        normalize_ingress_path("https://attacker.invalid/path")
    with pytest.raises(DashboardQueryError):
        normalize_ingress_path("/safe/../unsafe")
    with pytest.raises(DashboardQueryError):
        normalize_ingress_path("/safe/%2e%2e/unsafe")
    with pytest.raises(DashboardQueryError):
        normalize_ingress_path('/safe/"><script>/')


def test_window_and_resolution_limits(now):
    start, end = resolve_window(range_name="30d", start=None, end=None, now=now)
    assert end - start == timedelta(days=30)
    assert resolve_resolution(start, end, "auto") == "30m"
    with pytest.raises(DashboardQueryError, match="2500-point"):
        resolve_resolution(start, end, "5m")
    with pytest.raises(DashboardQueryError, match="31 days"):
        resolve_window(
            range_name="24h",
            start=now - timedelta(days=32),
            end=now,
        )
    with pytest.raises(DashboardQueryError, match="timezone"):
        resolve_window(
            range_name="24h",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 2),
        )


def test_aggregation_uses_average_last_soc_and_preserves_gap(now):
    start = now.replace(minute=0, second=0, microsecond=0)
    rows = [
        {
            "slot_utc": start,
            "is_healthy": True,
            "house_consumption_w": 1000,
            "baseline_house_consumption_w": None,
            "pv_power_w": 500,
            "battery_soc_percent": 50,
            "battery_charge_power_w": None,
            "battery_discharge_power_w": 100,
            "grid_import_power_w": 500,
            "grid_export_power_w": None,
            "amber_import_price_per_kwh": 0.2,
            "amber_export_price_per_kwh": 0.1,
        },
        {
            "slot_utc": start + timedelta(minutes=5),
            "is_healthy": False,
            "house_consumption_w": 2000,
            "baseline_house_consumption_w": 1800,
            "pv_power_w": 1000,
            "battery_soc_percent": 49,
            "battery_charge_power_w": 200,
            "battery_discharge_power_w": None,
            "grid_import_power_w": None,
            "grid_export_power_w": 100,
            "amber_import_price_per_kwh": 0.4,
            "amber_export_price_per_kwh": 0.2,
        },
    ]
    points = aggregate_timeseries(
        rows,
        start=start,
        end=start + timedelta(minutes=30),
        resolution="15m",
    )
    assert points[0].house_consumption_w == 1500
    assert points[0].battery_soc_percent == 49
    assert points[0].healthy is False
    assert points[1].has_observation is False
    assert points[1].house_consumption_w is None


def test_live_timeseries_and_forecast_comparison_are_read_only(dashboard_database, now):
    url, first, run_id = dashboard_database
    health = AppHealth(900)
    health.record_success(first)
    service = DashboardService(url, health)
    repository = open_repository(url)
    before_counts = repository.table_counts()
    before_point = repository.forecast_run(run_id)["points"][0]
    repository.close()

    live = service.live()
    assert live.available
    assert live.sign_convention_status == "unconfirmed"
    assert live.slot_utc.tzinfo is not None
    assert live.amber_buy_price_aud_per_kwh == pytest.approx(0.21)
    assert live.ev_power_w is None
    assert live.ev_contamination_warning
    series = service.timeseries(
        start=first.slot_utc - timedelta(minutes=5),
        end=first.slot_utc + timedelta(minutes=15),
        resolution="5m",
    )
    assert series.missing_slot_count == 3
    assert series.normalized_flow_unavailable_due_to_unconfigured_signs
    assert any(not point.has_observation for point in series.points)
    comparison = service.forecast_comparison(forecast_run_id=run_id)
    assert comparison.available
    assert comparison.sample_count == 1
    assert comparison.mae == pytest.approx(100)
    assert comparison.points[0].lower_value == 1500

    repository = open_repository(url)
    assert repository.table_counts() == before_counts
    after_point = repository.forecast_run(run_id)["points"][0]
    assert before_point["actual_value"] is None
    assert after_point["actual_value"] is None
    repository.close()


def test_reserve_empty_state_and_data_quality(dashboard_database):
    url, first, _ = dashboard_database
    service = DashboardService(url, AppHealth(900))
    reserve = service.reserve_latest()
    assert not reserve.available
    assert reserve.potentially_tradable_energy_kwh is None
    quality = service.data_quality(
        start=first.slot_utc - timedelta(minutes=5),
        end=first.slot_utc + timedelta(minutes=15),
    )
    assert quality.total_observations == 2
    assert quality.missing_slots == 3
    assert quality.ev_contamination_warning
    assert quality.configured_grid_power_sign == "unknown"
    assert quality.configured_battery_power_sign == "unknown"
    assert quality.configured_sign_confidence == "unconfirmed"


def test_data_quality_reports_runtime_sign_configuration(dashboard_database):
    url, first, _ = dashboard_database
    health = AppHealth(
        900,
        grid_power_sign="positive_export",
        battery_power_sign="positive_discharge",
        sign_convention_confidence="high",
        sign_convention_supporting_samples=175,
        balance_tolerance_w=250,
    )
    quality = DashboardService(url, health).data_quality(
        start=first.slot_utc - timedelta(minutes=5),
        end=first.slot_utc + timedelta(minutes=15),
    )
    assert quality.configured_grid_power_sign == "positive_export"
    assert quality.configured_battery_power_sign == "positive_discharge"
    assert quality.configured_sign_confidence == "high"
    assert quality.configured_sign_supporting_samples == 175
    assert quality.configured_balance_tolerance_w == 250


def test_vehicle_dashboard_api_uses_nullable_privacy_minimized_fields(
    healthy_states, config, now
):
    entity_ids = {
        "charging": "binary_sensor.test_vehicle_charging",
        "plugged": "binary_sensor.test_vehicle_plugged",
        "online": "binary_sensor.test_vehicle_online",
        "soc": "sensor.test_vehicle_soc",
        "power": "sensor.test_vehicle_battery_power",
        "updated": "sensor.test_vehicle_updated",
        "location": "device_tracker.test_vehicle_location",
    }
    config.ev_vehicle_enabled = True
    config.ev_vehicle_charging_entity_id = entity_ids["charging"]
    config.ev_vehicle_plugged_entity_id = entity_ids["plugged"]
    config.ev_vehicle_online_entity_id = entity_ids["online"]
    config.ev_vehicle_soc_entity_id = entity_ids["soc"]
    config.ev_vehicle_battery_power_entity_id = entity_ids["power"]
    config.ev_vehicle_telemetry_updated_entity_id = entity_ids["updated"]
    config.ev_vehicle_location_entity_id = entity_ids["location"]
    template = next(iter(healthy_states.values()))
    values = {
        "charging": "on",
        "plugged": "on",
        "online": "on",
        "soc": "72",
        "power": "-12",
        "updated": now.isoformat(),
        "location": "home",
    }
    for role, value in values.items():
        healthy_states[entity_ids[role]] = template.model_copy(
            deep=True,
            update={
                "entity_id": entity_ids[role],
                "state": value,
                "attributes": {
                    "vin": "PRIVATE-SENTINEL-NOT-STORED",
                    "latitude": "PRIVATE-SENTINEL-NOT-STORED",
                },
            },
        )
    url = _repository_url(config)
    repository = open_repository(url)
    repository.create_schema_for_tests()
    observation = build_observation(healthy_states, config, observed_at=now)
    repository.save_observation(observation)
    repository.close()
    service = DashboardService(url, AppHealth(900))

    live = service.live()
    assert live.ev_vehicle_configured
    assert live.ev_vehicle_available
    assert live.ev_vehicle_soc_percent == 72
    assert live.ev_vehicle_battery_power_w_raw == -12
    assert live.ev_charging_active is True
    assert live.ev_plugged_in is True
    assert live.ev_at_home is True
    assert live.ev_power_w is None
    assert "PRIVATE" not in live.model_dump_json()
    assert "latitude" not in live.model_dump_json().lower()

    series = service.timeseries(
        start=observation.slot_utc,
        end=observation.slot_utc + timedelta(minutes=5),
        resolution="5m",
    )
    assert series.points[0].ev_vehicle_soc_percent == 72
    assert series.points[0].ev_charging_active is True
    quality = service.data_quality(
        start=observation.slot_utc,
        end=observation.slot_utc + timedelta(minutes=5),
    )
    assert quality.ev_integration_configured
    assert quality.ev_telemetry_fresh is True
    assert not quality.independent_ac_charger_power_available
    assert quality.known_charging_rows_excluded == 1


def test_latest_persisted_reserve_returns_supported_subset(dashboard_database):
    url, first, _ = dashboard_database
    repository = open_repository(url)
    run_id = repository.save_forecast_run(
        ForecastRun(
            created_at_utc=first.slot_utc,
            forecast_type="baseline_household_load",
            source="reserve_estimator",
            horizon_start_utc=first.slot_utc,
            horizon_end_utc=first.slot_utc + timedelta(hours=1),
            model_version="hierarchical-demand-v1",
            metadata={
                "current_state_source": "history",
                "gross_reserve_requirement_kwh": 12.5,
                "capacity_capped_reserve_kwh": 12.5,
                "overall_reserve_confidence": {"level": "medium"},
            },
            points=[
                ForecastPoint(
                    period_start_utc=first.slot_utc,
                    period_end_utc=first.slot_utc + timedelta(hours=1),
                    expected_value=2000,
                    unit="W",
                    metadata={"tier": "tier1_exact"},
                )
            ],
        )
    )
    repository.close()
    service = DashboardService(url, AppHealth(900))
    reserve = service.reserve_latest()
    assert reserve.available
    assert reserve.forecast_run_id == run_id
    assert reserve.expected_household_demand_kwh == pytest.approx(2.0)
    assert reserve.gross_reserve_requirement_kwh == pytest.approx(12.5)
    assert reserve.potentially_tradable_energy_kwh is None
    assert reserve.command_issued is False
    quality = service.data_quality(
        start=first.slot_utc - timedelta(minutes=5),
        end=first.slot_utc + timedelta(minutes=15),
    )
    assert quality.forecast_tier_usage == {"tier1_exact": 1}
    assert quality.forecast_tier_share["exact"] == 1.0


class _FakeService:
    def live(self):
        from energy_optimizer.dashboard_api import LiveResponse

        return LiveResponse(available=False)

    def status(self):
        from energy_optimizer.dashboard_api import StatusResponse

        return StatusResponse(
            app_version="0.4.1",
            overall_status="healthy",
            collector_status="healthy",
            database_status="healthy",
            home_assistant_status="healthy",
            latest_successful_collection_utc=None,
            latest_observation_slot_utc=None,
            observation_age_seconds=None,
            database_schema_revision="test",
            expected_schema_revision="test",
        )


def _serve(policy):
    health = AppHealth(900)
    handler = make_handler(
        health=health,
        service=_FakeService(),
        access_policy=policy,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _request(server, method, path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def test_web_shell_static_nested_ingress_api_and_security_headers():
    server, thread = _serve(IngressAccessPolicy())
    prefix = "/api/hassio_ingress/test-token/"
    try:
        status, headers, body = _request(
            server, "GET", prefix, {"X-Ingress-Path": prefix}
        )
        assert status == 200
        html = body.decode()
        assert f'<base href="{prefix}">' in html
        assert 'href="static/app.css?v=0.4.1"' in html
        assert "Advisory only. No command was issued." in html
        assert "Content-Security-Policy" in headers
        assert "X-Frame-Options" not in headers
        status, _, css = _request(
            server,
            "GET",
            prefix + "static/app.css?v=0.4.1",
            {"X-Ingress-Path": prefix},
        )
        assert status == 200
        assert b"prefers-color-scheme" in css
        status, _, body = _request(
            server, "GET", prefix + "api/v1/live", {"X-Ingress-Path": prefix}
        )
        assert status == 200
        assert json.loads(body)["available"] is False
        status, _, _ = _request(
            server, "GET", prefix + "history", {"X-Ingress-Path": prefix}
        )
        assert status == 200
        status, headers, body = _request(server, "POST", "/api/v1/live")
        assert status == 405
        assert headers["Allow"] == "GET"
        assert json.loads(body)["error"]["code"] == "read_only"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_direct_request_and_spoofed_forwarded_for_are_denied_but_health_works():
    server, thread = _serve(IngressAccessPolicy(allow_loopback=False))
    try:
        status, _, body = _request(
            server,
            "GET",
            "/api/v1/live",
            {
                "X-Forwarded-For": "172.30.32.2",
                "X-Ingress-Path": "/api/hassio_ingress/spoof/",
            },
        )
        assert status == 403
        assert json.loads(body)["error"]["code"] == "ingress_required"
        status, _, _ = _request(server, "GET", "/health")
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_frontend_has_no_external_assets_or_control_actions():
    directory = Path("src/energy_optimizer/dashboard_static")
    html = (directory / "index.html").read_text(encoding="utf-8")
    javascript = (directory / "app.js").read_text(encoding="utf-8")
    combined = html + javascript + (directory / "app.css").read_text(encoding="utf-8")
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "url(http" not in combined
    assert "Google Fonts" not in combined
    assert "<button" not in html
    for forbidden in (
        "run-estimator",
        "control endpoint",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ):
        assert forbidden not in javascript
    for section in ("Overview", "History", "Forecasts", "Reserve", "Data Quality"):
        assert section in html
    assert "prefers-reduced-motion" in combined
    assert "Accessible data table" in javascript
    assert 'id="overview-ev"' in html
    assert "Vehicle battery power (raw)" in javascript
    assert "not treated as charger AC demand" in javascript
    assert "ev_vehicle_soc_percent" in javascript
    assert "EV connection history" in javascript
    assert "EV contamination warning" in javascript
    for private_field in ("vin", "latitude", "longitude"):
        assert private_field not in javascript.lower()


def test_forecast_metadata_uses_stable_readable_key_value_layout():
    directory = Path("src/energy_optimizer/dashboard_static")
    html = (directory / "index.html").read_text(encoding="utf-8")
    javascript = (directory / "app.js").read_text(encoding="utf-8")
    css = (directory / "app.css").read_text(encoding="utf-8")
    assert '<div id="forecast-run-meta" class="forecast-meta"></div>' in html
    assert '<div id="forecast-run-meta" class="definition-grid">' not in html
    assert ".forecast-meta .definition-grid" in css
    assert "overflow-wrap: break-word" in css
    assert "word-break: normal" in css
    assert "overflow-wrap: anywhere" not in css
    assert '["Created", localTime(data.created_at_utc)]' in javascript
    assert '["Model", data.model_version]' in javascript


def test_fully_missing_and_mixed_chart_series_have_intentional_rendering():
    javascript = Path("src/energy_optimizer/dashboard_static/app.js").read_text(
        encoding="utf-8"
    )
    assert "No grid import/export data is available for this period." in javascript
    assert (
        "No battery charge/discharge data is available for this period." in javascript
    )
    assert "if (!chartableSeries.length)" in javascript
    assert 'class="empty-state chart-empty" role="status"' in javascript
    assert "chartableSeries.forEach" in javascript
    assert "chartableSeries.map" in javascript
    assert "segment.length === 1" in javascript
    assert 'createElementNS(svgNS, "circle")' in javascript
    assert "Historical collection gaps" in javascript
    assert (
        "Power sign conventions are not configured, so normalized import/export "
        "and charge/discharge values are unavailable." in javascript
    )
    assert "normalized_flow_unavailable_due_to_unconfigured_signs" in javascript
    assert javascript.count("article.append(details)") == 2


def test_reserve_states_are_explicit_and_advisory_remains_visible():
    directory = Path("src/energy_optimizer/dashboard_static")
    html = (directory / "index.html").read_text(encoding="utf-8")
    javascript = (directory / "app.js").read_text(encoding="utf-8")
    assert "Advisory only. No command was issued." in html
    assert '"not-stored": "Not stored"' in javascript
    assert 'unavailable: "Unavailable in this run"' in javascript
    assert '"not-calculated": "Not calculated"' in javascript
    assert "This dashboard shows only fields persisted" in javascript
    assert 'notStoredRow("Opportunity details")' in javascript
    assert 'reserveRow("Overall", confidence)' in javascript


def test_missing_directional_flows_use_one_concise_fallback():
    javascript = Path("src/energy_optimizer/dashboard_static/app.js").read_text(
        encoding="utf-8"
    )
    fallback = "Detailed directional flow breakdown is unavailable for this slot."
    assert javascript.count(fallback) == 1
    assert 'data.sign_convention_status === "unconfirmed"' in javascript
    assert "availableFlows.map" in javascript
    assert "flows.map" not in javascript
    assert "directionalState(data.grid_import_power_w" in javascript
    assert "data.energy_balance_residual_w == null" in javascript
