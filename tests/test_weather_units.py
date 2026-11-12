"""Synthetic provider fixtures: canonical units without numeric conversion."""

import json
from datetime import UTC, datetime

import pytest

from energy_optimizer.forecast_context import convert_value
from energy_optimizer.weather.providers import parse_meteo, parse_onecall4

NOW = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "product", ["onecall4_current", "onecall4_15min", "onecall4_1h", "onecall4_1day"]
)
def test_onecall_celsius_units_preserve_values_and_wire_bytes(product):
    temperature = {"day": 24.5, "night": -2.0} if product == "onecall4_1day" else 24.5
    feels_like = {"day": 26.0} if product == "onecall4_1day" else 26.0
    raw = json.dumps(
        {
            "data": [
                {
                    "dt": int(NOW.timestamp()),
                    "temp": temperature,
                    "feels_like": feels_like,
                    "dew_point": -2.0,
                }
            ]
        }
    ).encode()
    capture = parse_onecall4(
        raw,
        product=product,
        requested_at=NOW,
        received_at=NOW,
        site_ref="synthetic",
        requested_units="metric",
    )
    temperatures = [
        p
        for p in capture.points
        if p.variable.startswith(("temperature", "feels_like", "dew_point"))
    ]
    assert temperatures
    assert capture.raw == raw and capture.parser_version == "weather-v2"
    expected = (
        [24.5, -2.0, 26.0, -2.0] if product == "onecall4_1day" else [24.5, 26.0, -2.0]
    )
    assert [p.value for p in temperatures if p.value is not None] == expected
    assert all(p.unit == "\u00b0C" for p in temperatures)
    for point in temperatures:
        if point.value is not None:
            value, unit, _, error = convert_value(
                point.value, "temperature", point.unit
            )
            assert (value, unit, error) == (point.value, "\u00b0C", None)


def test_missing_temperature_stays_missing_and_nonmetric_is_rejected():
    raw = json.dumps({"data": [{"dt": int(NOW.timestamp()), "temp": None}]}).encode()
    kwargs = dict(
        product="onecall4_15min",
        requested_at=NOW,
        received_at=NOW,
        site_ref="synthetic",
    )
    capture = parse_onecall4(raw, requested_units="metric", **kwargs)
    points = {p.variable: p for p in capture.points}
    assert points["temperature"].value is None
    assert points["temperature"].presence == "NULL"
    assert points["feels_like"].value is None
    assert points["feels_like"].presence == "MISSING"
    assert points["temperature"].unit == points["feels_like"].unit == "\u00b0C"
    with pytest.raises(ValueError, match="explicit metric"):
        parse_onecall4(raw, requested_units="imperial", **kwargs)


def test_open_meteo_accepts_canonical_celsius_and_rejects_malformed_provider_unit():
    body = {
        "utc_offset_seconds": 0,
        "hourly_units": {"time": "unixtime", "temperature_2m": "\u00b0C"},
        "hourly": {"time": [int(NOW.timestamp())], "temperature_2m": [24.5]},
    }
    raw = json.dumps(body).encode()
    capture = parse_meteo(
        raw,
        requested_at=NOW,
        received_at=NOW,
        site_ref="synthetic",
        requested_fields=("temperature_2m",),
    )
    assert capture.points[0].unit == "\u00b0C"
    assert capture.points[0].value == 24.5
    assert capture.raw == raw and capture.parser_version == "weather-v2"
    body["hourly_units"]["temperature_2m"] = "\u00c2\u00b0C"
    with pytest.raises(ValueError, match="unit mismatch"):
        parse_meteo(
            json.dumps(body).encode(),
            requested_at=NOW,
            received_at=NOW,
            site_ref="synthetic",
            requested_fields=("temperature_2m",),
        )
