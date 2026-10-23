import pytest

from transit import config
from transit.mbta_api import MbtaApiError, MbtaClient


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {"data": []}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("transit.mbta_api.time.sleep", lambda s: None)


def test_sends_api_key_header():
    session = FakeSession([])
    MbtaClient(api_key="abc", session=session)
    assert session.headers["x-api-key"] == "abc"


def test_retries_rate_limit_then_succeeds():
    session = FakeSession([FakeResponse(429), FakeResponse(200, {"data": [{"id": "Red"}]})])
    client = MbtaClient(api_key="k", session=session)
    assert client.subway_routes() == [{"id": "Red"}]
    assert len(session.calls) == 2
    assert session.calls[0][1] == {"filter[type]": "0,1"}


def test_client_error_is_not_retried():
    session = FakeSession([FakeResponse(403)])
    with pytest.raises(MbtaApiError, match="403"):
        MbtaClient(api_key="k", session=session).subway_routes()
    assert len(session.calls) == 1


def test_gives_up_after_max_retries():
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(MbtaApiError, match="503"):
        MbtaClient(api_key="k", session=session, max_retries=2).subway_routes()


def test_placeholder_key_is_ignored(monkeypatch):
    monkeypatch.setenv("MBTA_API_KEY", "your-key-here")
    assert config.mbta_api_key() is None
    monkeypatch.setenv("MBTA_API_KEY", " real-key ")
    assert config.mbta_api_key() == "real-key"
