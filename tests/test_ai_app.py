import json

import pytest

from energy_optimizer.ai_app import app_ai_environment
from energy_optimizer.ai_integration import AISettings, local_status


def bundle(tmp_path, **updates):
    values = {"enabled": True, "base_url": "https://panel.example.invalid:8789"}
    values.update(updates)
    (tmp_path / "connection.json").write_text(json.dumps(values))
    for name in ("runtime-production.key", "ca.crt", "client.crt", "client.key"):
        (tmp_path / name).touch()
    return tmp_path


def test_absent_optional_bundle_does_not_block_app(tmp_path):
    env = app_ai_environment(tmp_path)
    assert local_status(env)["enabled"] is False
    assert local_status(env)["configuration"] == "valid"


def test_production_bundle_uses_only_fixed_scoped_files(tmp_path):
    env = app_ai_environment(bundle(tmp_path), tmp_path / "status.json")
    settings = AISettings.from_environment(env)
    assert settings.environment == "production"
    assert settings.key_file == tmp_path / "runtime-production.key"
    assert settings.ca_file == tmp_path / "ca.crt"
    assert settings.cert_key_file == tmp_path / "client.key"
    assert settings.status_file == tmp_path / "status.json"
    assert settings.enabled


@pytest.mark.parametrize(
    "updates",
    [
        {"enabled": "true"},
        {"base_url": "http://127.0.0.1:8787"},
        {"base_url": "https://secret:password@panel.example.invalid"},
        {"base_url": 123},
        {"key_file": "build-development.key"},
        {"environment": "development"},
        {"SUPERVISOR_TOKEN": "must-not-escape"},
    ],
)
def test_bad_optional_configuration_is_visible_not_fatal(tmp_path, updates):
    env = app_ai_environment(bundle(tmp_path, **updates))
    assert env == {"ENERGY_AI_ENABLED": "invalid"}
    assert local_status(env)["configuration"] == "invalid"
    assert not local_status(env)["enabled"]


@pytest.mark.parametrize("content", ["bad", "[]", "x" * 4097, '{"enabled":'])
def test_unreadable_configuration_never_exposes_content(tmp_path, content):
    (tmp_path / "connection.json").write_text(content)
    assert app_ai_environment(tmp_path) == {"ENERGY_AI_ENABLED": "invalid"}


def test_disabled_bundle_does_not_require_credentials(tmp_path):
    bundle(tmp_path, enabled=False)
    (tmp_path / "runtime-production.key").unlink()
    assert app_ai_environment(tmp_path) == {"ENERGY_AI_ENABLED": "false"}


def test_build_key_cannot_replace_missing_runtime_key(tmp_path):
    bundle(tmp_path)
    (tmp_path / "runtime-production.key").rename(tmp_path / "build-development.key")
    assert app_ai_environment(tmp_path) == {"ENERGY_AI_ENABLED": "invalid"}
