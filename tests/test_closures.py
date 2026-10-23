from datetime import datetime, timezone

from transit.closures import closures_from_alerts, is_active
from transit.graph import TransitGraph
from transit.models import Alert, Segment

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _alert(effect, stations, routes=(), start="2026-10-01T00:00:00-04:00", end=None, **kw):
    periods = [{"start": start, "end": end}] if start or end else []
    return Alert("a1", "api", effect, "header", stations=list(stations), routes=list(routes),
                 active_periods=periods, **kw)


def test_is_active_respects_periods():
    assert is_active(_alert("DELAY", []), NOW)
    assert not is_active(_alert("DELAY", [], start="2026-11-01T00:00:00-04:00"), NOW)
    assert not is_active(_alert("DELAY", [], end="2026-10-20T00:00:00-04:00"), NOW)


def test_scraped_alert_without_periods_uses_lifecycle():
    assert is_active(_alert("DELAY", [], start=None, lifecycle="ONGOING"), NOW)
    assert not is_active(_alert("DELAY", [], start=None, lifecycle="UPCOMING"), NOW)


def test_station_closure_closes_named_stations(tiny_network):
    closures = closures_from_alerts([_alert("STATION_CLOSURE", ["place-b"])], tiny_network, NOW)
    assert closures.stations == {"place-b": ["a1"]}
    assert closures.segments == {}


def test_suspension_closes_segments_between_named_stations_only(tiny_network):
    alert = _alert("SUSPENSION", ["place-a", "place-b", "place-d"], routes=["Red"])
    closures = closures_from_alerts([alert], tiny_network, NOW)
    # A-B is Red and fully named; B-D is named but Green, so it stays open.
    assert closures.segments == {("Red", frozenset({"place-a", "place-b"})): ["a1"]}
    assert closures.stations == {}


def test_suspension_on_one_line_leaves_parallel_line_open(tiny_network):
    tiny_network.segments.append(Segment("place-a", "place-b", "Green", ["Green-B"], 5.0, "schedule"))
    alert = _alert("SUSPENSION", ["place-a", "place-b"], routes=["Red"])
    closures = closures_from_alerts([alert], tiny_network, NOW)

    graph = TransitGraph(tiny_network)
    graph.set_closures(closures.stations, closures.segments)
    route = graph.shortest_path("place-a", "place-b")
    assert route.minutes == 5.0 and route.legs[0].route == "Green-B"


def test_inactive_and_facility_alerts_close_nothing(tiny_network):
    alerts = [
        _alert("STATION_CLOSURE", ["place-b"], start="2026-12-01T00:00:00-05:00"),
        _alert("ELEVATOR_CLOSURE", ["place-c"]),
        _alert("DELAY", ["place-a", "place-b"]),
    ]
    closures = closures_from_alerts(alerts, tiny_network, NOW)
    assert closures.stations == {} and closures.segments == {}
