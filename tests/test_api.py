import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.state import AppState
from transit.models import Alert, Line, Network, Segment, Station

# A loop, so closing one side forces a detour:  Red A-B-C (2 + 2 min), Green-B A-D-C (3 + 3 min).
STATIONS = [
    Station("place-a", "Alpha", 42.36, -71.06, "Boston", ["Green", "Red"]),
    Station("place-b", "Bravo Street", 42.37, -71.07, "Boston", ["Red"]),
    Station("place-c", "Charlie Square", 42.38, -71.08, "Boston", ["Green", "Red"]),
    Station("place-d", "Delta", 42.35, -71.09, "Brookline", ["Green"]),
]
SEGMENTS = [
    Segment("place-a", "place-b", "Red", ["Red"], 2.0, "schedule", 10),
    Segment("place-b", "place-c", "Red", ["Red"], 2.0, "schedule", 10),
    Segment("place-a", "place-d", "Green", ["Green-B"], 3.0, "schedule", 10),
    Segment("place-d", "place-c", "Green", ["Green-B"], 3.0, "schedule", 10),
]
LINES = [Line("Red", "Red Line", "Red", "#DA291C", 1), Line("Green-B", "Green Line B", "Green", "#00843D", 0)]

RED_SUSPENSION = Alert("sus-1", "api", "SUSPENSION", "No Red Line trains Bravo-Charlie", severity=7,
                       routes=["Red"], stations=["place-b", "place-c"],
                       active_periods=[{"start": "2026-01-01T00:00:00-05:00", "end": None}])
FUTURE_CLOSURE = Alert("clo-1", "api", "STATION_CLOSURE", "Delta closed in December", severity=5,
                       routes=["Green-B"], stations=["place-d"],
                       active_periods=[{"start": "2099-12-01T00:00:00-05:00",
                                        "end": "2099-12-31T00:00:00-05:00"}])
ELEVATOR = Alert("elv-1", "web", "ELEVATOR_CLOSURE", "Alpha elevator out", lifecycle="ONGOING",
                 routes=["Red"], stations=["place-a"])


def make_client(alerts=()):
    network = Network("2026-10-26", "2026-10-24T00:00:00+00:00", LINES, STATIONS, SEGMENTS, {})
    state = AppState(network, list(alerts), "2026-10-24T00:00:00+00:00")
    return TestClient(create_app(state, refresh_seconds=0))


@pytest.fixture
def client():
    with make_client() as c:
        yield c


@pytest.fixture
def disrupted():
    with make_client([RED_SUSPENSION, FUTURE_CLOSURE, ELEVATOR]) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert (body["stations"], body["segments"], body["alerts"]) == (4, 4, 0)


def test_lines_and_station_filters(client):
    assert [line["id"] for line in client.get("/lines").json()] == ["Red", "Green-B"]
    assert [s["id"] for s in client.get("/stations", params={"line": "green"}).json()] == \
        ["place-a", "place-c", "place-d"]
    assert [s["id"] for s in client.get("/stations", params={"q": "street"}).json()] == ["place-b"]


def test_station_detail_by_name(disrupted):
    body = disrupted.get("/stations/alpha").json()
    assert body["id"] == "place-a"
    assert [n["id"] for n in body["neighbors"]] == ["place-b", "place-d"]
    assert [a["id"] for a in body["alerts"]] == ["elv-1"]


def test_unknown_station_suggests_names(client):
    resp = client.get("/route", params={"from": "Bravo St", "to": "Alpha"})
    assert resp.status_code == 404
    assert resp.json()["suggestions"] == ["Bravo Street"]


def test_route_normal_service(client):
    body = client.get("/route", params={"from": "place-a", "to": "Charlie Square"}).json()
    assert body["minutes"] == 4.0
    assert [s["name"] for s in body["stations"]] == ["Alpha", "Bravo Street", "Charlie Square"]
    assert body["legs"][0]["color"] == "#DA291C"
    assert body["disrupted"] is False and body["alert_ids"] == []


def test_route_detours_around_suspension(disrupted):
    body = disrupted.get("/route", params={"from": "place-a", "to": "place-c"}).json()
    assert body["minutes"] == 6.0
    assert [leg["route"] for leg in body["legs"]] == ["Green-B"]
    assert body["disrupted"] is True
    assert body["normal_minutes"] == 4.0
    assert body["alert_ids"] == ["sus-1"]


def test_route_at_future_time_applies_scheduled_closure(disrupted):
    resp = disrupted.get("/route", params={"from": "place-d", "to": "place-c", "at": "2099-12-15T09:00"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"message": "Delta is closed", "alert_ids": ["clo-1"]}

    # The live graph is untouched by the what-if query.
    assert disrupted.get("/route", params={"from": "place-d", "to": "place-c"}).status_code == 200


def test_no_route_reports_blocking_alerts():
    suspension_everywhere = Alert("sus-2", "api", "SUSPENSION", "All lines down",
                                  stations=["place-a", "place-b", "place-c", "place-d"],
                                  active_periods=[{"start": "2026-01-01T00:00:00-05:00", "end": None}])
    with make_client([suspension_everywhere]) as c:
        resp = c.get("/route", params={"from": "place-a", "to": "place-c"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["alert_ids"] == ["sus-2"]


def test_alert_filters(disrupted):
    ids = lambda **p: [a["id"] for a in disrupted.get("/alerts", params=p).json()]  # noqa: E731
    assert ids(active="true") == ["sus-1", "elv-1"]
    assert ids(active="false") == ["clo-1"]
    assert ids(effect="suspension") == ["sus-1"]
    assert ids(line="Green") == ["clo-1"]


def test_closures_now_and_at(disrupted):
    now = disrupted.get("/closures").json()
    assert now["stations"] == []
    assert now["segments"] == [{"line": "Red", "alert_ids": ["sus-1"],
                                "stations": [{"id": "place-b", "name": "Bravo Street"},
                                             {"id": "place-c", "name": "Charlie Square"}]}]
    later = disrupted.get("/closures", params={"at": "2099-12-15T09:00-05:00"}).json()
    assert [x["station"]["id"] for x in later["stations"]] == ["place-d"]


def test_network_marks_closed_segments(disrupted):
    body = disrupted.get("/network").json()
    closed = [(s["from_station"], s["to_station"]) for s in body["segments"] if s["closed"]]
    assert closed == [("place-b", "place-c")]
    assert body["version"] == 1


def test_refresh_applies_new_alerts(client, monkeypatch):
    monkeypatch.setattr("api.main.build_alerts", lambda client, network: [RED_SUSPENSION])
    monkeypatch.setattr("api.main.write_alerts", lambda alerts, generated_at: [])
    client.app.state.client = object()

    before = client.get("/route", params={"from": "place-a", "to": "place-c"}).json()
    body = client.post("/alerts/refresh").json()
    after = client.get("/route", params={"from": "place-a", "to": "place-c"}).json()

    assert body["alerts"] == 1 and body["last_refresh_error"] is None
    assert body["version"] == before["version"] + 1
    assert (before["minutes"], after["minutes"]) == (4.0, 6.0)  # cached route was invalidated


def test_failed_refresh_keeps_last_alerts(disrupted, monkeypatch):
    def broken(client, network):
        raise ConnectionError("MBTA unreachable")

    monkeypatch.setattr("api.main.build_alerts", broken)
    disrupted.app.state.client = object()
    body = disrupted.post("/alerts/refresh").json()
    assert body["alerts"] == 3
    assert body["last_refresh_error"] == "ConnectionError: MBTA unreachable"
