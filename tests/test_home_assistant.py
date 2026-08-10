import pytest
import requests

from energy_optimizer.home_assistant import (
    HomeAssistantClient,
    HomeAssistantConnectionError,
    ReadOnlyViolation,
    redact_secret,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.headers = {}
        self.payload = payload
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return Response(self.payload)


def test_bulk_retrieval_uses_one_get(healthy_states):
    session = Session(
        [state.model_dump(mode="json") for state in healthy_states.values()]
    )
    client = HomeAssistantClient("http://ha", "secret", session=session)
    result = client.get_states(healthy_states)
    assert set(result) == set(healthy_states)
    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("/api/states")


def test_client_rejects_non_allowlisted_path():
    client = HomeAssistantClient("http://ha", "secret", session=Session({}))
    with pytest.raises(ReadOnlyViolation):
        client._get_json("/api/services/light/turn_on")
    assert not hasattr(client, "post")


def test_token_redaction():
    assert (
        redact_secret("Bearer very-secret failed", "very-secret")
        == "Bearer [REDACTED] failed"
    )


def test_network_error_redacts_token():
    class Broken(Session):
        def get(self, url, timeout):
            raise requests.ConnectionError("very-secret leaked")

    client = HomeAssistantClient("http://ha", "very-secret", session=Broken({}))
    with pytest.raises(HomeAssistantConnectionError, match="REDACTED") as raised:
        client.check_api()
    assert "very-secret" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_authorization_header_is_redacted_without_exception_chain():
    token = "example-authorization-token"

    class Broken(Session):
        def get(self, url, timeout):
            raise requests.ConnectionError(f"Authorization: Bearer {token}")

    client = HomeAssistantClient("http://ha", token, session=Broken({}))
    with pytest.raises(HomeAssistantConnectionError) as raised:
        client.check_api()
    assert token not in str(raised.value)
    assert raised.value.__cause__ is None
