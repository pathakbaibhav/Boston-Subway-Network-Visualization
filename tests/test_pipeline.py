from datetime import date

import pytest

from transit.models import Alert
from transit.pipeline import build_alerts, build_network, merge_alerts, next_weekday


def _stop(stop_id, parent):
    return {"id": stop_id, "type": "stop",
            "relationships": {"parent_station": {"data": {"id": parent, "type": "stop"}}}}


def _sched(trip, stop, seq, arrive, depart):
    day = "2026-10-26T"
    return {"attributes": {"stop_sequence": seq,
                           "arrival_time": f"{day}{arrive}:00-04:00" if arrive else None,
                           "departure_time": f"{day}{depart}:00-04:00" if depart else None},
            "relationships": {"trip": {"data": {"id": trip}}, "stop": {"data": {"id": stop}}}}


class FakeClient:
    """Red: A - B - C.  Green-B: B - D, with no scheduled trips (forces the distance estimate)."""

    def __init__(self):
        self.schedule_calls = []

    def subway_routes(self):
        return [{"id": "Red", "attributes": {"long_name": "Red Line", "color": "DA291C", "type": 1}},
                {"id": "Green-B", "attributes": {"long_name": "Green Line B", "color": "00843D", "type": 0}}]

    def subway_platforms(self):
        return [_stop("a1", "place-a"), _stop("b1", "place-b"), _stop("b2", "place-b"),
                _stop("c1", "place-c"), _stop("d1", "place-d")]

    def canonical_patterns(self, route_ids):
        def pattern(route, trip, direction):
            return {"attributes": {"direction_id": direction},
                    "relationships": {"route": {"data": {"id": route}},
                                      "representative_trip": {"data": {"id": trip}}}}
        return [pattern("Red", "red-0", 0), pattern("Red", "red-1", 1), pattern("Green-B", "grn-0", 0)]

    def trip_stops(self, trip_id):
        return {"red-0": [_stop("a1", "place-a"), _stop("b1", "place-b"), _stop("c1", "place-c")],
                "grn-0": [_stop("b2", "place-b"), _stop("d1", "place-d")]}[trip_id]

    def stops_by_id(self, ids):
        coords = {"place-a": (42.36, -71.06), "place-b": (42.37, -71.07),
                  "place-c": (42.38, -71.08), "place-d": (42.35, -71.09)}
        return [{"id": i, "attributes": {"name": i.title(), "latitude": coords[i][0],
                                         "longitude": coords[i][1], "municipality": "Boston"}}
                for i in ids]

    def schedules(self, route_id, direction, day, min_time, max_time):
        self.schedule_calls.append((route_id, direction, day))
        if route_id != "Red" or direction != 0:
            return []
        return [
            _sched("t1", "a1", 1, None, "10:00"), _sched("t1", "b1", 2, "10:02", "10:02"),
            _sched("t1", "c1", 3, "10:05", None),
            _sched("t2", "a1", 1, None, "10:10"), _sched("t2", "b1", 2, "10:13", "10:13"),
            _sched("t2", "c1", 3, "10:13", None),  # same-minute hop: floored to MIN_SEGMENT_MINUTES
        ]


def test_build_network_topology_and_travel_times():
    network = build_network(FakeClient(), date(2026, 10, 26))
    segs = {frozenset((s.from_station, s.to_station)): s for s in network.segments}

    ab = segs[frozenset(("place-a", "place-b"))]
    assert (ab.minutes, ab.minutes_source, ab.samples) == (2.5, "schedule", 2)

    bc = segs[frozenset(("place-b", "place-c"))]
    assert bc.minutes == 1.5  # mean of 3.0 and 0.0

    bd = segs[frozenset(("place-b", "place-d"))]
    assert bd.minutes_source == "estimated" and bd.minutes > 0
    assert bd.line == "Green"

    stations = {s.id: s for s in network.stations}
    assert stations["place-b"].lines == ["Green", "Red"]
    assert network.platform_to_station["b2"] == "place-b"


def test_missing_segments_retry_later_service_days_for_their_routes_only():
    client = FakeClient()
    build_network(client, date(2026, 10, 26))
    later_days = {(route, day) for route, _, day in client.schedule_calls if day != "2026-10-26"}
    assert later_days and all(route == "Green-B" for route, _ in later_days)


def test_next_weekday_skips_weekend():
    assert next_weekday(date(2026, 10, 24)) == date(2026, 10, 26)  # Saturday -> Monday
    assert next_weekday(date(2026, 10, 27)) == date(2026, 10, 27)


def test_merge_prefers_api_structure_and_fills_gaps_from_web():
    api = Alert("1", "api", "SUSPENSION", "API header", severity=7, routes=["Red"])
    web_dup = Alert("1", "web", "SHUTTLE", "Web header", stations=["place-a"], url="http://x")
    web_only = Alert("2", "web", "ELEVATOR_CLOSURE", "Elevator out")

    merged = {a.id: a for a in merge_alerts([api], [web_dup, web_only])}
    assert merged["1"].source == "api+web"
    assert merged["1"].effect == "SUSPENSION"
    assert merged["1"].stations == ["place-a"]
    assert merged["1"].url == "http://x"
    assert merged["2"].source == "web"


def test_api_alert_maps_platforms_to_stations(tiny_network):
    class AlertClient:
        def subway_alerts(self):
            return [{"id": "9", "attributes": {
                "effect": "STATION_CLOSURE", "header": "Closed", "severity": 7, "lifecycle": "NEW",
                "informed_entity": [{"route": "Red", "stop": "70002"}, {"route": "Red", "stop": "place-b"},
                                    {"route": "Red", "stop": "bus-stop-not-in-network"}],
                "active_period": [{"start": "2026-10-24T05:00:00-04:00", "end": None}]}}]

    alerts = build_alerts(AlertClient(), tiny_network, html="<html></html>")
    assert alerts[0].stations == ["place-b"]
    assert alerts[0].routes == ["Red"]
    assert alerts[0].active_periods == [{"start": "2026-10-24T05:00:00-04:00", "end": None}]


def test_alerts_fail_only_when_both_sources_fail(tiny_network, monkeypatch):
    class BrokenClient:
        def subway_alerts(self):
            raise ConnectionError("api down")

    def broken_fetch():
        raise ConnectionError("site down")

    monkeypatch.setattr("transit.pipeline.fetch_alerts_page", broken_fetch)
    with pytest.raises(RuntimeError, match="no alert source"):
        build_alerts(BrokenClient(), tiny_network)
