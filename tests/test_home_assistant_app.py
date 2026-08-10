import importlib.util
import json
import logging
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import energy_optimizer.home_assistant_app as app_module
from energy_optimizer.config import ConfigurationError, load_config
from energy_optimizer.db.engine import DatabaseConnectionError
from energy_optimizer.db.redaction import redact_database_urls
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.home_assistant_app import (
    APP_VERSION,
    SUPERVISOR_CORE_API_URL,
    AppHealth,
    HomeAssistantAppOptions,
    app_environment,
    load_app_options,
    postgresql_url,
    redact_runtime_error,
    validate_startup,
)


def _options(**updates):
    values = {
        "db_host": "db.example.invalid",
        "db_port": 55432,
        "db_name": "home_energy",
        "db_user": "test_user",
        "db_password": "test-password@:/",
    }
    values.update(updates)
    return HomeAssistantAppOptions.model_validate(values)


def _load_app_tool():
    tools_path = Path(__file__).parents[1] / "tools"
    sys.path.insert(0, str(tools_path))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_home_assistant_app_security_test",
            tools_path / "run_home_assistant_app.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(tools_path))


def test_app_configuration_parsing(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(_options().model_dump(mode="json")), encoding="utf-8")
    loaded = load_app_options(path)
    assert loaded.db_host == "db.example.invalid"
    assert loaded.db_port == 55432


def test_missing_database_password_rejects_startup(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"db_host": "nas.local"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="schema validation"):
        load_app_options(path)


def test_empty_database_password_rejects_startup(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(
        json.dumps({"db_host": "nas.local", "db_password": ""}), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="non-empty database password"):
        load_app_options(path)


def test_options_permission_denied_has_secret_safe_diagnostic(monkeypatch, tmp_path):
    path = tmp_path / "options.json"
    password = "permission-test-password"

    def deny_read(_self, **_kwargs):
        raise PermissionError("denied while reading " + password)

    monkeypatch.setattr(Path, "read_text", deny_read)
    with pytest.raises(ConfigurationError, match="permission denied") as raised:
        load_app_options(path)
    assert password not in str(raised.value)


def test_missing_options_file_has_specific_diagnostic(tmp_path):
    with pytest.raises(ConfigurationError, match="file not found"):
        load_app_options(tmp_path / "missing.json")


def test_malformed_options_json_has_specific_secret_safe_diagnostic(tmp_path):
    path = tmp_path / "options.json"
    secret_fragment = "malformed-secret"
    path.write_text('{"db_password":"' + secret_fragment, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="malformed JSON") as raised:
        load_app_options(path)
    assert secret_fragment not in str(raised.value)


def test_options_path_environment_override(monkeypatch, tmp_path):
    path = tmp_path / "overridden-options.json"
    path.write_text(json.dumps(_options().model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setenv("HOME_ENERGY_APP_OPTIONS_PATH", str(path))
    loaded = load_app_options()
    assert loaded.db_host == "db.example.invalid"
    assert path.exists()


def test_ephemeral_options_copy_is_deleted_after_parsing(monkeypatch, tmp_path):
    path = tmp_path / "runtime" / "options.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_options().model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(app_module, "EPHEMERAL_OPTIONS_PATH", path)
    monkeypatch.setenv("HOME_ENERGY_APP_OPTIONS_PATH", str(path))
    loaded = load_app_options()
    assert loaded.db_user == "test_user"
    assert not path.exists()


def test_supervisor_options_file_is_never_deleted(monkeypatch, tmp_path):
    path = tmp_path / "data" / "options.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_options().model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(app_module, "SUPERVISOR_OPTIONS_PATH", path)
    monkeypatch.delenv("HOME_ENERGY_APP_OPTIONS_PATH", raising=False)
    load_app_options()
    assert path.exists()


def test_invalid_database_port_rejects_startup():
    with pytest.raises(ValueError):
        _options(db_port=70000)


def test_postgresql_url_encodes_credentials():
    url = postgresql_url(_options())
    assert "test_user:test-password%40%3A%2F@db.example.invalid:55432" in url


def test_app_environment_uses_supervisor_proxy_and_never_sqlite():
    environment = app_environment(_options(), supervisor_token="example-token")
    assert environment["HA_URL"] == SUPERVISOR_CORE_API_URL
    assert environment["HA_TOKEN"] == "example-token"
    assert environment["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "sqlite" not in environment["DATABASE_URL"]


def test_app_requires_supervisor_token(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match="SUPERVISOR_TOKEN"):
        app_environment(_options())


def test_supervisor_proxy_url_does_not_duplicate_api_path():
    session = SimpleNamespace(headers={}, calls=[])

    def get(url, timeout):
        session.calls.append((url, timeout))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: [],
        )

    session.get = get
    client = HomeAssistantClient(SUPERVISOR_CORE_API_URL, "token", session=session)
    client.get_states([])
    assert session.calls[0][0] == "http://supervisor/core/api/states"


def test_app_startup_rejects_sqlite_before_connecting():
    with pytest.raises(ConfigurationError, match="SQLite fallback is disabled"):
        validate_startup(
            database_url="sqlite:///data/energy_history.db",
            ha_url=SUPERVISOR_CORE_API_URL,
            ha_token="token",
            repository_factory=lambda _url: pytest.fail("must not connect"),
        )


def test_postgresql_connection_failure_rejects_startup():
    def fail(_url):
        raise DatabaseConnectionError("unreachable")

    with pytest.raises(DatabaseConnectionError, match="unreachable"):
        validate_startup(
            database_url="postgresql+psycopg://user:secret@nas/db",
            ha_url=SUPERVISOR_CORE_API_URL,
            ha_token="token",
            repository_factory=fail,
        )


def test_wrong_alembic_revision_rejects_startup(monkeypatch):
    repository = SimpleNamespace(
        engine=object(),
        ping=lambda: True,
        close=lambda: None,
    )
    monkeypatch.setattr(
        "energy_optimizer.home_assistant_app.current_revision", lambda _engine: "old"
    )
    monkeypatch.setattr(
        "energy_optimizer.home_assistant_app.expected_revision",
        lambda: "20260810_01",
    )
    with pytest.raises(ConfigurationError, match="20260810_01 expected; found old"):
        validate_startup(
            database_url="postgresql+psycopg://user:secret@nas/db",
            ha_url=SUPERVISOR_CORE_API_URL,
            ha_token="token",
            repository_factory=lambda _url: repository,
        )


def test_startup_home_assistant_check_is_get_only(monkeypatch):
    class Repository:
        engine = object()

        def ping(self):
            return True

        def table_counts(self):
            return SimpleNamespace(
                observations=1,
                forecast_runs=0,
                forecast_points=0,
                observation_derivations=0,
                ev_session_annotations=0,
                ev_session_annotation_rows=0,
            )

        def close(self):
            return None

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def check_api(self):
            self.calls.append("GET /api/")
            return {}

        def get_states(self, ids):
            self.calls.append("GET /api/states")
            return dict.fromkeys(ids, object())

    monkeypatch.setattr(
        "energy_optimizer.home_assistant_app.current_revision",
        lambda _engine: "20260810_01",
    )
    monkeypatch.setattr(
        "energy_optimizer.home_assistant_app.expected_revision",
        lambda: "20260810_01",
    )
    validate_startup(
        database_url="postgresql+psycopg://user:secret@nas/db",
        ha_url=SUPERVISOR_CORE_API_URL,
        ha_token="token",
        repository_factory=lambda _url: Repository(),
        client_factory=Client,
    )
    assert not hasattr(Client, "post")


def test_database_url_and_supervisor_token_are_not_logged(caplog):
    secret_url = (
        "postgresql+psycopg://test_user:test-password@db.example.invalid/test_db"
    )
    token = "example-supervisor-token"
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("%s %s", redact_database_urls(secret_url), "ok")
    assert "test-password" not in caplog.text
    assert token not in caplog.text


def test_runtime_error_redacts_database_password_token_and_authorization_header():
    password = "example-database-password"
    token = "example-supervisor-token"
    error = (
        "authentication failed for postgresql+psycopg://test_user:"
        f"{password}@db.example.invalid/test_db; Authorization: Bearer {token}"
    )
    redacted = redact_runtime_error(error, password, token)
    assert password not in redacted
    assert token not in redacted
    assert "***" in redacted


@pytest.mark.parametrize("failure_kind", ["startup", "database_authentication"])
def test_app_failure_logs_never_contain_runtime_secrets(
    monkeypatch, caplog, failure_kind
):
    module = _load_app_tool()
    options = _options(db_password="example-database-password")
    token = "example-supervisor-token"
    monkeypatch.setenv("SUPERVISOR_TOKEN", token)
    monkeypatch.setattr(module, "load_app_options", lambda: options)

    def fail(_options):
        raise DatabaseConnectionError(
            f"{failure_kind}: postgresql+psycopg://test_user:"
            "example-database-password@db.example.invalid/test_db "
            f"Authorization: Bearer {token}"
        )

    monkeypatch.setattr(module, "_run", fail)
    with caplog.at_level(logging.ERROR):
        assert module.main() == 1
    assert "example-database-password" not in caplog.text
    assert token not in caplog.text
    assert "Authorization: Bearer [REDACTED]" in caplog.text


def test_invalid_options_error_never_dumps_options_json(tmp_path):
    password = "example-database-password"
    path = tmp_path / "options.json"
    path.write_text(
        json.dumps({"db_host": "", "db_password": password}), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError) as raised:
        load_app_options(path)
    assert password not in str(raised.value)
    assert "db_password" not in str(raised.value)


def test_health_response_contains_no_secrets_and_uses_age_threshold():
    health = AppHealth(max_observation_age_seconds=900)
    success = datetime(2026, 8, 10, 1, tzinfo=UTC)
    health.last_successful_collection_utc = success
    health.last_slot_utc = success
    health.collector = "healthy"
    status, payload = health.response(now=success + timedelta(seconds=901))
    assert status == 503
    assert payload["collector"] == "unhealthy"
    serialized = json.dumps(payload)
    assert "password" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "database_url" not in serialized.lower()


def test_health_tolerates_one_transient_failure():
    health = AppHealth(max_observation_age_seconds=900)
    now = datetime.now(UTC)
    health.record_failure("home_assistant")
    status, payload = health.response(now=now)
    assert status == 200
    assert payload["home_assistant"] == "healthy"
    health.record_failure("home_assistant")
    health.record_failure("home_assistant")
    status, payload = health.response(now=now)
    assert status == 503
    assert payload["home_assistant"] == "unhealthy"


def test_windows_environment_configuration_remains_unchanged(monkeypatch):
    monkeypatch.setenv("HA_URL", "http://homeassistant.local:8123")
    monkeypatch.setenv("HA_TOKEN", "windows-token")
    config = load_config(env_file=None)
    assert config.ha_url == "http://homeassistant.local:8123"
    assert config.ha_token == "windows-token"


def test_app_client_has_no_home_assistant_write_methods():
    source = Path("src/energy_optimizer/home_assistant.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for method in (".post(", ".put(", ".patch(", ".delete("):
        assert method not in lowered


def test_app_manifest_uses_least_privilege_and_watchdog():
    manifest = Path("home_energy_optimiser/config.yaml").read_text(encoding="utf-8")
    assert "homeassistant_api: true" in manifest
    assert "watchdog: http://[HOST]:[PORT:8099]/health" in manifest
    assert "boot: auto" in manifest
    assert "ingress: true" in manifest
    assert "ingress_port: 8099" in manifest
    assert "panel_admin: true" in manifest
    assert "panel_icon: mdi:home-lightning-bolt" in manifest
    assert "panel_title: Energy Optimiser" in manifest
    assert "stage: experimental" in manifest
    assert "ports:" not in manifest
    for forbidden in (
        "hassio_api: true",
        "host_network",
        "privileged",
        "docker_api",
        "map:",
        "devices:",
        "SYS_ADMIN",
        "NET_ADMIN",
    ):
        assert forbidden not in manifest


def test_app_patch_versions_are_consistent():
    manifest = Path("home_energy_optimiser/config.yaml").read_text(encoding="utf-8")
    dockerfile = Path("home_energy_optimiser/Dockerfile").read_text(encoding="utf-8")
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert APP_VERSION == "0.3.1"
    assert 'version: "0.3.1"' in manifest
    assert "ARG BUILD_VERSION=0.3.1" in dockerfile
    assert "ARG APP_SOURCE_REF=v0.3.1" in dockerfile
    assert 'version = "0.3.1"' in project


def test_app_launcher_execs_existing_collector_without_restart_loop():
    launcher = Path("home_energy_optimiser/run.sh").read_text(encoding="utf-8")
    assert "exec gosu app:app python tools/run_home_assistant_app.py" in launcher
    assert 'export HOME_ENERGY_APP_OPTIONS_PATH="${runtime_options}"' in launcher
    assert "while" not in launcher


def test_app_bootstrap_copies_options_without_modifying_supervisor_file():
    launcher = Path("home_energy_optimiser/run.sh").read_text(encoding="utf-8")
    assert 'source_options="/data/options.json"' in launcher
    assert 'runtime_options="${runtime_dir}/options.json"' in launcher
    assert 'install -o app -g app -m 0600 "${source_options}"' in launcher
    assert "chmod" not in launcher
    assert "chown" not in launcher
    assert 'rm -f -- "${source_options}"' not in launcher


def test_privilege_drop_preserves_environment_and_exec_signal_delivery():
    launcher = Path("home_energy_optimiser/run.sh").read_text(encoding="utf-8")
    assert "env -i" not in launcher
    assert "exec su " not in launcher
    assert 'exec gosu app:app "$@"' in launcher
    assert "exec gosu app:app python" in launcher


def test_container_validation_avoids_shell_quoted_probe_commands():
    validator = Path("tools/test_home_assistant_app_container.py").read_text(
        encoding="utf-8"
    )
    assert '"sh",' not in validator
    assert '"python", "-c"' not in validator
    assert 'probe = """' not in validator
    assert "container_app_probe.py" in validator


def test_dockerignore_excludes_sensitive_artifacts():
    ignored = Path("home_energy_optimiser/.dockerignore").read_text(encoding="utf-8")
    for pattern in (
        ".env",
        "*.db",
        "*.sqlite*",
        "*.dump",
        "*.sql",
        "*.pem",
        "*.key",
        "data",
        "logs",
        "captures",
        "exports",
        ".git",
    ):
        assert pattern in ignored.splitlines()


def test_root_gitignore_excludes_local_secrets_and_backups():
    ignored = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in (
        ".env",
        ".env.*",
        "data/*.db",
        "data/*.sqlite*",
        "data/backups/",
        "data/exports/",
        "logs/",
        "captures/",
        "*.dump",
        "*.sql",
        "*.pem",
        "*.key",
    ):
        assert pattern in ignored
    assert "!.env.example" in ignored


def test_docker_image_uses_root_only_for_bootstrap_then_drops_privileges():
    dockerfile = Path("home_energy_optimiser/Dockerfile").read_text(encoding="utf-8")
    assert "gosu" in dockerfile
    assert "groupadd --gid 10001 app" in dockerfile
    assert "useradd --uid 10001 --gid 10001" in dockerfile
    assert "USER 0:0" in dockerfile
    assert "SUPERVISOR_TOKEN" not in dockerfile
    assert "DATABASE_URL" not in dockerfile


def test_app_page_documentation_and_changelog_are_packaged():
    app_directory = Path("home_energy_optimiser")
    changelog = app_directory / "CHANGELOG.md"
    documentation = app_directory / "DOCS.md"
    assert changelog.is_file()
    assert documentation.is_file()
    changelog_text = changelog.read_text(encoding="utf-8")
    assert "## 0.3.1" in changelog_text
    assert "## 0.3.0" in changelog_text


def test_app_documentation_contains_only_placeholder_connection_details():
    documentation = Path("home_energy_optimiser/DOCS.md").read_text(encoding="utf-8")
    private_ipv4 = re.compile(
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
    )
    credential_url = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@", re.I)
    secret_assignment = re.compile(
        r"(?:db_password|ha_token)\s*[:=]\s*['\"]?[^\s<'\"]+", re.I
    )
    assert "YOUR_NAS_HOST" in documentation
    assert not private_ipv4.search(documentation)
    assert not credential_url.search(documentation)
    assert not secret_assignment.search(documentation)
    assert "-----BEGIN PRIVATE KEY-----" not in documentation


def test_home_assistant_image_label_uses_app_type():
    dockerfile = Path("home_energy_optimiser/Dockerfile").read_text(encoding="utf-8")
    assert 'io.hass.type="app"' in dockerfile
    assert 'io.hass.type="addon"' not in dockerfile


def test_app_package_contains_no_sensitive_artifacts():
    app_directory = Path("home_energy_optimiser")
    forbidden_names = {
        ".env",
        "backups",
        "captures",
        "credentials",
        "data",
        "exports",
        "logs",
        "secrets",
    }
    forbidden_suffixes = {
        ".backup",
        ".bak",
        ".db",
        ".dump",
        ".jsonl",
        ".key",
        ".p12",
        ".pem",
        ".pfx",
        ".sql",
        ".sqlite",
        ".sqlite3",
    }
    offenders = [
        path
        for path in app_directory.rglob("*")
        if path.name.lower() in forbidden_names
        or path.name.lower().startswith(".env.")
        or (path.is_file() and path.suffix.lower() in forbidden_suffixes)
    ]
    assert offenders == []

    sensitive_content = re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b|"
        r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@|"
        r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bAKIA[A-Z0-9]{16}\b",
        re.I,
    )
    content_offenders = [
        path
        for path in app_directory.rglob("*")
        if path.is_file() and sensitive_content.search(path.read_text(encoding="utf-8"))
    ]
    assert content_offenders == []
