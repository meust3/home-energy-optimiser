from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from energy_optimizer.sems_probe import (
    AU_LOGIN_URL,
    READ_ONLY_ENDPOINTS,
    ProbeError,
    SemsCloudProbe,
    assert_endpoint_allowed,
    parse_chargers,
    parse_plants,
    redact_identifier,
    summarize_charger_evidence,
    validate_gateway_base,
)

GATEWAY = "https://eu-gateway.semsportal.com/web/sems"
MODULE_PATH = Path(__file__).parents[1] / "src" / "energy_optimizer" / "sems_probe.py"


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return FakeResponse(self.responses.pop(0))


def login_payload(token="secret-token"):
    return {
        "code": "00000",
        "data": {
            "uid": "cloud-user-id",
            "token": token,
            "api": GATEWAY,
            "client": "semsPlusWeb",
        },
    }


def station_payload():
    return {
        "code": "00000",
        "data": {
            "records": [
                {
                    "stationId": "private-plant-id",
                    "stationName": "Private home",
                    "address": "Private address",
                    "latitude": -27.0,
                    "longitude": 153.0,
                }
            ]
        },
    }


def charger_payload():
    return {
        "code": "00000",
        "data": {
            "dataList": [
                {
                    "stationId": "private-plant-id",
                    "children": [
                        {
                            "sn": "GW7KHCA20ABC1234",
                            "deviceType": "EV_CHARGER",
                            "productModel": "GW7K-HCA-20",
                        }
                    ],
                }
            ]
        },
    }


def detail_payload(last_update="2026-08-30T05:58:00Z"):
    return {
        "code": "00000",
        "data": {
            "productModel": "GW7K-HCA-20",
            "isOnline": True,
            "lastUpdate": last_update,
            "power": 7.1,
            "current": "10.3 A",
            "workstate": "available_gun_insered",
            "chargeMode": 2,
            "startStatus": False,
        },
    }


def last_charge_payload(work_status=6):
    return {
        "code": "00000",
        "data": {
            "chargeLog": {
                "workStu": work_status,
                "pevChar": "7.20",
                "chargeTimeLength": "01:30:00",
                "currentChargeQuantity": "10.8",
            }
        },
    }


def run_probe(*responses, now=None):
    transport = FakeTransport(responses)
    probe = SemsCloudProbe(
        "visitor@example.invalid",
        "do-not-log-this-password",
        transport=transport,
        now=now or datetime(2026, 8, 30, 6, 0, tzinfo=UTC),
    )
    return probe.run_once(), transport


def normal_responses():
    return [
        login_payload(),
        station_payload(),
        charger_payload(),
        detail_payload(),
        last_charge_payload(),
    ]


def test_exact_one_shot_sequence_no_redirects_and_no_private_output():
    summary, transport = run_probe(*normal_responses())
    assert [(method, urlparse(url).path) for method, url, _ in transport.calls] == [
        (spec.method, spec.path if name == "authenticate" else "/web/sems/" + spec.path)
        for name, spec in READ_ONLY_ENDPOINTS.items()
    ]
    assert summary["request_count"] == 5
    assert all(call[2]["allow_redirects"] is False for call in transport.calls)
    rendered = json.dumps(summary)
    for secret in (
        "visitor@example.invalid",
        "do-not-log-this-password",
        "secret-token",
        "cloud-user-id",
        "private-plant-id",
        "Private home",
        "Private address",
        "GW7KHCA20ABC1234",
        "-27.0",
        "153.0",
    ):
        assert secret not in rendered
    assert summary["charger_identifier"] == "***1234"


def test_login_supports_gateway_at_response_top_level_without_fallback():
    responses = normal_responses()
    responses[0]["api"] = responses[0]["data"].pop("api")
    summary, _ = run_probe(*responses)
    assert summary["request_count"] == 5


def test_reduced_budget_stops_before_next_request():
    transport = FakeTransport(normal_responses())
    probe = SemsCloudProbe("visitor", "password", transport=transport, request_budget=1)
    with pytest.raises(ProbeError, match="budget"):
        probe.run_once()
    assert len(transport.calls) == 1


def test_owner_designated_au_origin_and_bounded_discovery_without_plants():
    responses = normal_responses()
    del responses[1]
    transport = FakeTransport(responses)
    summary = SemsCloudProbe(
        "visitor@example.invalid",
        "password",
        transport=transport,
        login_url=AU_LOGIN_URL,
        discover_plants=False,
        request_budget=4,
    ).run_once()
    assert transport.calls[0][1] == AU_LOGIN_URL
    assert (
        transport.calls[0][2]["headers"]["Origin"] == "https://au-semsplus.goodwe.com"
    )
    assert len(transport.calls) == 4
    assert summary["plant_count"] is None
    assert transport.calls[-1][2]["params"]["pwId"] == "private-plant-id"


def test_requests_use_fixed_query_bodies_without_control_parameters():
    _, transport = run_probe(*normal_responses())
    assert set(transport.calls[0][2]["json"]) == {
        "account",
        "pwd",
        "agreement",
        "isLocal",
        "isChinese",
    }
    assert transport.calls[1][2]["json"] == {"current": 1, "size": 50}
    assert transport.calls[2][2]["json"] == {
        "deviceTypeList": ["EV_CHARGER"],
        "current": 1,
        "size": 50,
    }
    assert set(transport.calls[3][2]["json"]) == {"sn", "plantId", "productModel"}
    assert set(transport.calls[4][2]["params"]) == {"chargeSn", "pwId"}
    assert transport.calls[4][2]["json"] is None


def test_authentication_failure_does_not_expose_response_or_credentials():
    transport = FakeTransport([{"code": "failure-private", "msg": "private password"}])
    with pytest.raises(ProbeError) as error:
        SemsCloudProbe(
            "private user", "private password", transport=transport
        ).run_once()
    assert "private" not in str(error.value)
    assert "success_code=False" in str(error.value)
    assert len(transport.calls) == 1


def test_network_failure_suppresses_third_party_exception_details():
    import requests

    class FailedTransport(FakeTransport):
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError("private user, private password, token")

    with pytest.raises(ProbeError) as error:
        SemsCloudProbe(
            "private user", "private password", transport=FailedTransport([])
        ).run_once()
    assert str(error.value) == "authentication request failed"
    assert error.value.__suppress_context__


def test_cli_without_live_flag_never_creates_probe(monkeypatch):
    from tools.probe_sems_hca_cloud import main

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("live probe must not be created")

    monkeypatch.setattr("tools.probe_sems_hca_cloud.SemsCloudProbe", unexpected_probe)
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2


@pytest.mark.parametrize("work_status", [6, 8, 999, None])
def test_status_codes_do_not_rewrite_power_or_establish_ac_domain(work_status):
    responses = normal_responses()
    responses[-1] = last_charge_payload(work_status)
    summary, _ = run_probe(*responses)
    fields = summary["fields"]
    assert fields["last_charge.pevChar"]["raw_value"] == "7.20"
    assert fields["last_charge.workStu"]["raw_value"] == work_status
    assert fields["last_charge.currentChargeQuantity"]["raw_value"] == "10.8"
    assert fields["detail.current"]["raw_value"] == "10.3 A"
    assert summary["ac_power_w"] is None
    assert summary["charging_active"] is None
    assert summary["session_energy_kwh"] is None
    assert summary["plugged_in"] is None
    assert summary["eligible_for_baseline_subtraction"] is False
    assert all(f["normalized_value"] is None for f in fields.values())
    assert all(f["confidence"] == "unvalidated" for f in fields.values())
    assert summary["source_timing"]["detail"]["freshness"] == "fresh"
    assert summary["source_timing"]["last_charge"]["freshness"] == "unknown"


@pytest.mark.parametrize(
    "raw, freshness, age",
    [
        (None, "unknown", None),
        ("invalid", "unknown", None),
        ("2026-08-30T05:58:00", "unknown", None),
        (1750000000000, "unknown", None),
        ("2026-08-30T05:00:00Z", "stale", 3600),
        ("2026-08-30T06:01:00Z", "future", -60),
        ("2026-08-30T15:58:00+10:00", "fresh", 120),
    ],
)
def test_timestamp_evidence_is_per_endpoint_and_conservative(raw, freshness, age):
    summary = summarize_charger_evidence(
        detail={"lastUpdate": raw},
        charge_log={"endTime": "2026-08-30T06:00:00Z"},
        now=datetime(2026, 8, 30, 6, tzinfo=UTC),
    )
    timing = summary["source_timing"]["detail"]
    assert timing["timestamp_raw"] == raw
    assert timing["freshness"] == freshness
    assert timing["age_seconds"] == age
    if freshness == "fresh":
        assert timing["timestamp_utc"] == "2026-08-30T05:58:00+00:00"
    assert summary["source_timing"]["last_charge"]["freshness"] == "unknown"


def test_missing_fields_stay_missing_and_no_sensitive_attributes_are_copied():
    summary = summarize_charger_evidence(
        detail={"vin": "private-vin", "coordinates": [-27, 153], "control": {}},
        charge_log={},
        now=datetime.now(UTC),
    )
    assert all(not field["raw_available"] for field in summary["fields"].values())
    assert all(field["raw_value"] is None for field in summary["fields"].values())
    assert "private-vin" not in json.dumps(summary)
    assert "coordinates" not in json.dumps(summary)


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), {}, [], "x" * 129])
def test_unbounded_or_nonfinite_telemetry_is_rejected(raw):
    with pytest.raises(ProbeError, match="scalar"):
        summarize_charger_evidence(
            detail={"power": raw}, charge_log={}, now=datetime.now(UTC)
        )


def test_naive_evaluation_time_and_nonpositive_threshold_rejected():
    with pytest.raises(ValueError, match="aware"):
        summarize_charger_evidence(detail={}, charge_log={}, now=datetime(2026, 8, 30))
    with pytest.raises(ValueError, match="positive"):
        summarize_charger_evidence(
            detail={}, charge_log={}, now=datetime.now(UTC), stale_after_minutes=0
        )


def test_one_refresh_and_seven_request_bound():
    responses = normal_responses()
    responses[1:1] = [{"code": "C0602"}, login_payload("second-token")]
    summary, transport = run_probe(*responses)
    assert summary["request_count"] == len(transport.calls) == 7


def test_second_expiry_fails_without_another_refresh():
    transport = FakeTransport(
        [
            login_payload(),
            {"code": "C0602"},
            login_payload("second-token"),
            {"code": "C0602"},
        ]
    )
    with pytest.raises(ProbeError, match="expired again"):
        SemsCloudProbe("visitor", "password", transport=transport).run_once()
    assert len(transport.calls) == 4


def test_multiple_chargers_fail_before_detail():
    discovery = charger_payload()
    children = discovery["data"]["dataList"][0]["children"]
    children.append({"sn": "another-private-charger"})
    transport = FakeTransport([login_payload(), station_payload(), discovery])
    with pytest.raises(ProbeError, match="ambiguous"):
        SemsCloudProbe("visitor", "password", transport=transport).run_once()
    assert len(transport.calls) == 3


def test_probe_cannot_be_reused_for_polling():
    transport = FakeTransport(normal_responses())
    probe = SemsCloudProbe("visitor@example.invalid", "password", transport=transport)
    probe.run_once()
    with pytest.raises(ProbeError, match="only once"):
        probe.run_once()
    assert len(transport.calls) == 5


def test_live_opt_in_required_before_creating_network_session(monkeypatch):
    def unexpected_session():
        raise AssertionError("network session must not be created")

    monkeypatch.setattr(
        "energy_optimizer.sems_probe.requests.Session", unexpected_session
    )
    with pytest.raises(ProbeError, match="opt-in"):
        SemsCloudProbe("visitor", "password")


@pytest.mark.parametrize("status", [301, 302, 307, 400, 500])
def test_redirects_and_http_failures_never_follow_a_destination(status):
    class RedirectTransport(FakeTransport):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return FakeResponse({"location": "http://192.168.1.10"}, status)

    transport = RedirectTransport([])
    with pytest.raises(ProbeError, match="HTTP"):
        SemsCloudProbe("visitor", "password", transport=transport).run_once()
    assert len(transport.calls) == 1
    assert transport.calls[0][2]["allow_redirects"] is False


@pytest.mark.parametrize(
    "gateway",
    [
        "http://eu-gateway.semsportal.com/web/sems",
        "https://localhost/web/sems",
        "https://homeassistant.local/web/sems",
        "https://192.168.1.10/web/sems",
        "https://10.0.0.10/web/sems",
        "https://example.com/web/sems",
        "https://semsportal.com.evil.test/web/sems",
        "https://semsportal.com:abc/web/sems",
        "https://semsportal.com/web/sems?control=true",
        "https://semsportal.com/web/sems#x",
        "https://user:pass@semsportal.com/web/sems",
        "https://semsportal.com/elsewhere",
    ],
)
def test_local_or_unapproved_gateways_are_rejected(gateway):
    with pytest.raises(ProbeError):
        validate_gateway_base(gateway)


@pytest.mark.parametrize(
    "path",
    [
        "sems-remote/api/ev-charger/set-config",
        "sems-remote/api/ev-charger/set-mode",
        "sems-remote/api/ev-charger/startCharge",
        "sems-remote/api/ev-charger/stopCharge",
        "sems-remote/api/ev-charger/control-item-content-list",
        "sems-remote/api/v2/address/remote/get-work-mode",
    ],
)
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_control_and_control_metadata_paths_rejected(path, method):
    with pytest.raises(ProbeError, match="allowlist"):
        assert_endpoint_allowed(method, f"{GATEWAY}/{path}")


def test_recovered_discovery_shapes_and_identifier_redaction():
    assert len(parse_plants(station_payload())) == 1
    assert parse_chargers(charger_payload())[0]["stationId"] == "private-plant-id"
    assert redact_identifier("GW7KHCA20ABC1234") == "***1234"
    assert redact_identifier("12") == "***"


def test_no_collection_runtime_imports_or_polling():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf8"))
    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    root = MODULE_PATH.parent
    for source in root.rglob("*.py"):
        if source != MODULE_PATH:
            assert "sems_probe" not in source.read_text(encoding="utf8")
