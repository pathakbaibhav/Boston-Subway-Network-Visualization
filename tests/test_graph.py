import random

import pytest

from scripts.baseline_matrix import MatrixGraph
from transit.graph import (RouteCache, RoutePlanner, StationClosedError, StationNotFoundError,
                           TransitGraph)
from transit.storage import load_network

# tiny_network (conftest): Red A-B (2 min), B-C (3 min); Green-B B-D (4 min).


def test_route_with_transfer_pays_penalty(tiny_network):
    route = TransitGraph(tiny_network, transfer_minutes=4).shortest_path("place-a", "place-d")
    assert route.minutes == 10.0  # 2 ride + 4 transfer + 4 ride
    assert route.stations == ["place-a", "place-b", "place-d"]
    assert [(leg.route, leg.line, leg.stations, leg.minutes) for leg in route.legs] == [
        ("Red", "Red", ["place-a", "place-b"], 2.0),
        ("Green-B", "Green", ["place-b", "place-d"], 4.0),
    ]
    assert route.transfers == 1


def test_route_on_one_line_has_no_transfer(tiny_network):
    route = TransitGraph(tiny_network).shortest_path("place-c", "place-a")
    assert route.minutes == 5.0
    assert route.stations == ["place-c", "place-b", "place-a"]
    assert route.transfers == 0


def test_same_origin_and_destination(tiny_network):
    route = TransitGraph(tiny_network).shortest_path("place-b", "place-b")
    assert (route.minutes, route.stations, route.legs) == (0.0, ["place-b"], [])


def test_unknown_station_raises(tiny_network):
    with pytest.raises(StationNotFoundError):
        TransitGraph(tiny_network).shortest_path("place-a", "place-nope")


def test_closed_segment_disconnects(tiny_network):
    graph = TransitGraph(tiny_network)
    graph.set_closures(segments=[("place-b", "place-a")])
    assert graph.shortest_path("place-a", "place-c") is None
    assert graph.shortest_path("place-b", "place-c").minutes == 3.0


def test_closed_station_is_passed_through_but_not_used(tiny_network):
    graph = TransitGraph(tiny_network)
    graph.set_closures(stations=["place-b"])
    assert graph.shortest_path("place-a", "place-c").stations == ["place-a", "place-b", "place-c"]
    assert graph.shortest_path("place-a", "place-d") is None  # would need a transfer at B
    with pytest.raises(StationClosedError):
        graph.shortest_path("place-b", "place-c")


def test_set_closures_bumps_version_only_on_change(tiny_network):
    graph = TransitGraph(tiny_network)
    graph.set_closures(stations=["place-b"])
    assert graph.version == 1
    graph.set_closures(stations=["place-b"])
    assert graph.version == 1
    graph.set_closures()
    assert graph.version == 2


def test_planner_caches_and_invalidates_on_closure(tiny_network):
    graph = TransitGraph(tiny_network)
    planner = RoutePlanner(graph)
    first = planner.route("place-a", "place-c")
    assert planner.route("place-a", "place-c") == first
    assert (planner.cache.hits, planner.cache.misses) == (1, 1)

    graph.set_closures(segments=[("place-a", "place-b")])
    assert planner.route("place-a", "place-c") is None  # stale cached route not served
    assert planner.cache.misses == 2


def test_cache_evicts_least_recently_used():
    cache = RouteCache(maxsize=2)
    cache.put("a", (1.0, ()))
    cache.put("b", (2.0, ()))
    cache.get("a")
    cache.put("c", (3.0, ()))
    assert cache.get("b") == (False, None)
    assert cache.get("a") == (True, (1.0, ()))
    assert cache.evictions == 1


def test_all_pairs_covers_every_unordered_pair(tiny_network):
    planner = RoutePlanner(TransitGraph(tiny_network))
    table = planner.all_pairs_minutes()
    assert len(table) == 6
    assert table[("place-a", "place-d")] == planner.route("place-a", "place-d").minutes


@pytest.fixture(scope="module")
def real_network():
    return load_network()


def test_matches_original_matrix_dijkstra_on_real_network(real_network):
    matrix = MatrixGraph(real_network)
    graph = TransitGraph(real_network, transfer_minutes=0)
    ids = sorted(s.id for s in real_network.stations)
    rng = random.Random(7)
    for _ in range(300):
        a, b = rng.sample(ids, 2)
        assert graph.shortest_path(a, b).minutes == pytest.approx(matrix.shortest_path(a, b)[0], abs=0.011)


def test_real_network_routes_are_sensible(real_network):
    planner = RoutePlanner(TransitGraph(real_network))
    assert len(planner.all_pairs_minutes()) == 125 * 124 // 2  # every station reachable

    red_only = planner.route("place-alfcl", "place-pktrm")  # Alewife -> Park Street
    assert red_only.transfers == 0 and red_only.legs[0].route == "Red"

    cross_town = planner.route("place-wondl", "place-river")  # Wonderland -> Riverside
    assert [leg.line for leg in cross_town.legs] == ["Blue", "Green"]
