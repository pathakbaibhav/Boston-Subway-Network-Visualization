"""Tests for the map's data, geometry and live-update logic (no py5/JVM needed)."""

import math

import pytest

from viz.subway_map.client import ApiClient, ApiUnavailableError
from viz.subway_map.feed import LiveFeed
from viz.subway_map.model import (PARALLEL_OFFSET, MapModel, Projection, View, hex_to_rgb,
                                  point_along)

NETWORK = {
    "version": 0,
    "lines": [{"id": "Orange", "group": "Orange", "color": "#ED8B00"},
              {"id": "Green-E", "group": "Green", "color": "#00843D"}],
    "stations": [
        {"id": "hay", "name": "Haymarket", "latitude": 42.363, "longitude": -71.058,
         "lines": ["Green", "Orange"], "closed": False},
        {"id": "nst", "name": "North Station", "latitude": 42.366, "longitude": -71.061,
         "lines": ["Green", "Orange"], "closed": True},
        {"id": "sci", "name": "Science Park", "latitude": 42.367, "longitude": -71.068,
         "lines": ["Green"], "closed": False},
    ],
    "segments": [
        {"from_station": "hay", "to_station": "nst", "line": "Orange", "closed": False},
        {"from_station": "hay", "to_station": "nst", "line": "Green", "closed": True},
        {"from_station": "nst", "to_station": "sci", "line": "Green", "closed": False},
    ],
}

ROUTE = {
    "minutes": 3.0, "transfers": 0,
    "stations": [{"id": "hay", "name": "Haymarket"}, {"id": "nst", "name": "North Station"},
                 {"id": "sci", "name": "Science Park"}],
    "legs": [{"route": "Green-E", "line": "Green", "color": "#00843D", "minutes": 3.0,
              "stations": [{"id": "hay", "name": "Haymarket"}, {"id": "nst", "name": "North Station"},
                           {"id": "sci", "name": "Science Park"}]}],
}


def model() -> MapModel:
    return MapModel.from_network(NETWORK, 0, 0, 800, 600)


def test_hex_to_rgb():
    assert hex_to_rgb("#DA291C") == (218, 41, 28)


def test_projection_preserves_aspect_and_fits_rectangle():
    proj = Projection([(42.0, -71.0), (42.1, -71.1)], 0, 0, 400, 400, margin=0)
    nw, se = proj.to_base(42.1, -71.1), proj.to_base(42.0, -71.0)
    assert nw[1] < se[1]                                  # north is up
    width, height = se[0] - nw[0], se[1] - nw[1]
    assert width / height == pytest.approx(math.cos(math.radians(42.05)), rel=1e-6)
    assert max(width, height) == pytest.approx(400)


def test_view_zoom_keeps_cursor_point_fixed():
    view = View()
    before = view.to_base(300, 200)
    view.zoom_at(300, 200, 2.0)
    assert view.zoom == 2.0
    assert view.to_base(300, 200) == pytest.approx(before)


def test_view_zoom_is_clamped():
    view = View()
    for _ in range(50):
        view.zoom_at(0, 0, 2.0)
    assert view.zoom == view.max_zoom


def test_fitted_view_centers_points_without_zooming_out():
    view = View().fitted([(100, 100), (110, 120)], 0, 0, 800, 600, max_zoom=3)
    cx, cy = view.to_screen(105, 110)
    assert (cx, cy) == pytest.approx((400, 300))
    assert view.zoom == 3
    assert View().fitted([(0, 0), (5000, 5000)], 0, 0, 800, 600).zoom == 1.0


def test_parallel_lines_are_offset_apart():
    segs = [s for s in model().segments if {s.a, s.b} == {"hay", "nst"}]
    assert len(segs) == 2
    (ox1, oy1), (ox2, oy2) = [(s.ox, s.oy) for s in segs]
    assert math.hypot(ox1 - ox2, oy1 - oy2) == pytest.approx(PARALLEL_OFFSET)


def test_network_and_closures_flags():
    m = model()
    assert m.closed_stations == {"nst"}
    assert m.closed_segments == {("Green", frozenset({"hay", "nst"}))}
    assert m.stations["sci"].is_terminal and m.stations["hay"].is_transfer

    m.apply_closures({"version": 4, "stations": [],
                      "segments": [{"line": "Orange", "alert_ids": ["9"],
                                    "stations": [{"id": "hay"}, {"id": "nst"}]}]})
    assert m.closed_stations == set()
    assert m.closed_segments == {("Orange", frozenset({"hay", "nst"}))}
    assert m.closure_alerts == ["9"] and m.version == 4


def test_station_hit_testing_follows_view():
    m, view = model(), View()
    s = m.stations["sci"]
    assert m.station_at(view, s.x + 3, s.y - 3) == "sci"
    assert m.station_at(view, s.x + 50, s.y + 50) is None
    view.zoom_at(0, 0, 2.0)
    assert m.station_at(view, *view.to_screen(s.x, s.y)) == "sci"


def test_route_view_and_point_along():
    rv = model().route_view(ROUTE)
    assert rv.stations == ["hay", "nst", "sci"]
    assert rv.legs[0][0] == (0, 132, 61)
    assert point_along(rv.polyline, 0) == pytest.approx(rv.polyline[0])
    assert point_along(rv.polyline, 1) == pytest.approx(rv.polyline[-1])
    assert point_along([(0, 0), (10, 0), (10, 10)], 0.75) == pytest.approx((10, 5))


class FakeClient:
    def __init__(self):
        self.version = 1
        self.calls = []
        self.down = False

    def _call(self, name, result):
        if self.down:
            raise ApiUnavailableError("down")
        self.calls.append(name)
        return result

    def health(self):
        return self._call("health", {"version": self.version, "alerts_updated_at": "t"})

    def network(self):
        return self._call("network", NETWORK)

    def closures(self, at=None):
        return self._call("closures", {"version": self.version, "stations": [], "segments": []})

    def alerts(self):
        return self._call("alerts", [{"id": "9", "header": "h"}])

    def route(self, a, b, at=None):
        return self._call("route", (ROUTE, None))


def test_live_feed_reloads_only_when_version_changes():
    client, posts = FakeClient(), []
    feed = LiveFeed(client, lambda **u: posts.append(u))
    feed.route_pair = ("hay", "sci")

    feed.poll_once()
    assert client.calls == ["health", "network", "closures", "alerts", "route"]
    assert posts[1]["changed"] is False  # first load is not announced as a change

    client.calls.clear()
    feed.poll_once()
    assert client.calls == ["health"]  # steady state: one small request

    client.version = 2
    client.calls.clear()
    feed.poll_once()
    assert client.calls == ["health", "closures", "alerts", "route"]
    assert any(p.get("changed") for p in posts)


def test_live_feed_reports_api_outage():
    client, posts = FakeClient(), []
    client.down = True
    LiveFeed(client, lambda **u: posts.append(u)).poll_once()
    assert posts == [{"api_ok": False, "status": "down"}]


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.response


def test_client_route_returns_api_message_on_conflict():
    session = FakeSession(FakeResponse(409, {"detail": {"message": "Delta is closed", "alert_ids": ["1"]}}))
    route, error = ApiClient("http://x/", session=session).route("a", "b", at="2026-11-08T12:00")
    assert (route, error) == (None, "Delta is closed")
    assert session.calls == [("http://x/route", {"from": "a", "to": "b", "at": "2026-11-08T12:00"})]


def test_client_raises_when_api_is_down():
    class DownSession:
        def get(self, *a, **k):
            import requests
            raise requests.ConnectionError("refused")

    with pytest.raises(ApiUnavailableError, match="not reachable"):
        ApiClient(session=DownSession()).health()
