"""Subway network as an adjacency-list graph with heap-based Dijkstra shortest paths.

Nodes are (station, route) pairs rather than bare stations, so a path that changes trains pays a
transfer penalty: riding Green-D from Kenmore to Park Street is one leg, but switching to the Red
Line there adds TRANSFER_MINUTES. Each station's route nodes are linked by transfer edges.

Dijkstra uses a binary heap with lazy deletion: every edge is relaxed at most once and each heap
operation costs O(log V), giving O((V + E) log V), i.e. O(E log V) on this connected graph.
"""

import heapq
import math
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

from transit.config import ROUTE_CACHE_SIZE, TRANSFER_MINUTES
from transit.models import Network

RIDE, TRANSFER = 0, 1


class StationNotFoundError(KeyError):
    pass


class StationClosedError(ValueError):
    pass


@dataclass
class Leg:
    route: str           # route id ridden on this leg, e.g. "Green-D"
    line: str            # line group, e.g. "Green"
    stations: list[str]  # station ids from boarding to alighting, inclusive
    minutes: float


@dataclass
class Route:
    origin: str
    destination: str
    minutes: float       # riding time plus transfer penalties
    stations: list[str]  # every station passed through, origin to destination
    legs: list[Leg] = field(default_factory=list)

    @property
    def transfers(self) -> int:
        return max(len(self.legs) - 1, 0)


class TransitGraph:
    """Adjacency list: node index -> [(neighbor index, minutes, edge kind, segment key)]."""

    def __init__(self, network: Network, transfer_minutes: float = TRANSFER_MINUTES):
        self.network = network
        self.transfer_minutes = transfer_minutes
        self.line_of = {line.id: line.group for line in network.lines}
        self.nodes: list[tuple[str, str]] = []  # index -> (station id, route id)
        self.adjacency: list[list[tuple[int, float, int, frozenset | None]]] = []
        self.station_nodes: dict[str, list[int]] = defaultdict(list)
        self._index: dict[tuple[str, str], int] = {}

        for seg in network.segments:
            key = frozenset((seg.from_station, seg.to_station))
            for route in seg.routes:
                a = self._node(seg.from_station, route)
                b = self._node(seg.to_station, route)
                self.adjacency[a].append((b, seg.minutes, RIDE, key))
                self.adjacency[b].append((a, seg.minutes, RIDE, key))

        for nodes in self.station_nodes.values():
            for u in nodes:
                for v in nodes:
                    if u != v:
                        self.adjacency[u].append((v, transfer_minutes, TRANSFER, None))

        self.closed_stations: frozenset[str] = frozenset()
        self.closed_segments: frozenset[frozenset[str]] = frozenset()
        self.version = 0  # bumped on every closure change so caches know to drop stale routes

    def _node(self, station: str, route: str) -> int:
        key = (station, route)
        if key not in self._index:
            self._index[key] = len(self.nodes)
            self.nodes.append(key)
            self.adjacency.append([])
            self.station_nodes[station].append(self._index[key])
        return self._index[key]

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self.adjacency) // 2

    def set_closures(self, stations=(), segments=()) -> None:
        """Apply live service changes.

        A closed station is skipped by trains: it can't be boarded, left or used to transfer, but
        trains still run through it. A closed segment (pair of adjacent station ids) can't be
        ridden at all, e.g. a suspension replaced by shuttle buses.
        """
        stations = frozenset(stations)
        segments = frozenset(frozenset(pair) for pair in segments)
        if stations != self.closed_stations or segments != self.closed_segments:
            self.closed_stations, self.closed_segments = stations, segments
            self.version += 1

    def shortest_path(self, origin: str, destination: str) -> Route | None:
        """Fastest route between two stations, or None if closures disconnect them."""
        found = self.find_path(origin, destination)
        return self.build_route(origin, destination, *found) if found else None

    def find_path(self, origin: str, destination: str) -> tuple[float, tuple[int, ...]] | None:
        """Compact search result: (minutes, node indices along the path)."""
        for station in (origin, destination):
            if station not in self.station_nodes:
                raise StationNotFoundError(station)
            if station in self.closed_stations:
                raise StationClosedError(f"{station} is closed")
        if origin == destination:
            return 0.0, ()

        dist, prev, end = self._dijkstra(origin, set(self.station_nodes[destination]))
        if end is None:
            return None
        path = [end]
        while prev[path[-1]] != -1:
            path.append(prev[path[-1]])
        return dist[end], tuple(reversed(path))

    def shortest_minutes_from(self, origin: str) -> dict[str, float]:
        """Single-source Dijkstra: fastest minutes from `origin` to every reachable station."""
        dist, _, _ = self._dijkstra(origin, None)
        best: dict[str, float] = {}
        for node, d in enumerate(dist):
            station = self.nodes[node][0]
            if d < best.get(station, math.inf):
                best[station] = d
        return best

    def _dijkstra(self, origin: str, targets: set[int] | None):
        dist = [math.inf] * len(self.nodes)
        prev = [-1] * len(self.nodes)
        heap = []
        for node in self.station_nodes[origin]:  # board any line serving the origin at no cost
            dist[node] = 0.0
            heap.append((0.0, node))
        heapq.heapify(heap)

        closed_stations, closed_segments = self.closed_stations, self.closed_segments
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue  # stale heap entry
            if targets is not None and u in targets:
                return dist, prev, u
            station = self.nodes[u][0]
            for v, minutes, kind, key in self.adjacency[u]:
                if kind == TRANSFER and station in closed_stations:
                    continue
                if key is not None and key in closed_segments:
                    continue
                nd = d + minutes
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))
        return dist, prev, None

    def build_route(self, origin: str, destination: str, minutes: float, path: tuple[int, ...]) -> Route:
        """Expand a compact node path into stations and per-line legs."""
        legs: list[Leg] = []
        for a, b in zip(path, path[1:]):
            (sa, ra), (sb, rb) = self.nodes[a], self.nodes[b]
            if ra != rb:
                continue  # transfer edge: the next ride starts a new leg
            if not legs or legs[-1].route != ra or legs[-1].stations[-1] != sa:
                legs.append(Leg(ra, self.line_of[ra], [sa], 0.0))
            legs[-1].stations.append(sb)
            legs[-1].minutes += next(m for v, m, kind, _ in self.adjacency[a] if v == b and kind == RIDE)

        stations = [origin]
        for leg in legs:
            stations.extend(leg.stations[1:])
        for leg in legs:
            leg.minutes = round(leg.minutes, 2)
        return Route(origin, destination, round(minutes, 2), stations, legs)


class RouteCache:
    """Least-recently-used cache with hit/miss counters.

    Stores compact search results (minutes, node-index tuple) rather than Route objects, which
    keeps each entry to a few hundred bytes; routes are rebuilt from the path on a hit.
    """

    def __init__(self, maxsize: int = ROUTE_CACHE_SIZE):
        self.maxsize = maxsize
        self._data: OrderedDict[tuple[str, str], tuple | None] = OrderedDict()
        self.hits = self.misses = self.evictions = 0

    def get(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            self.hits += 1
            return True, self._data[key]
        self.misses += 1
        return False, None

    def put(self, key, value: tuple | None) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.maxsize:
            self._data.popitem(last=False)
            self.evictions += 1

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict:
        return {"size": len(self), "maxsize": self.maxsize, "hits": self.hits,
                "misses": self.misses, "evictions": self.evictions, "hit_rate": round(self.hit_rate, 4)}


class RoutePlanner:
    """Shortest-route queries over a TransitGraph, cached until the graph's closures change."""

    def __init__(self, graph: TransitGraph, cache_size: int = ROUTE_CACHE_SIZE):
        self.graph = graph
        self.cache = RouteCache(cache_size)
        self._cache_version = graph.version

    def route(self, origin: str, destination: str) -> Route | None:
        if self.graph.version != self._cache_version:
            self.cache.clear()
            self._cache_version = self.graph.version
        hit, found = self.cache.get((origin, destination))
        if not hit:
            found = self.graph.find_path(origin, destination)
            self.cache.put((origin, destination), found)
        return self.graph.build_route(origin, destination, *found) if found else None

    def all_pairs_minutes(self) -> dict[tuple[str, str], float]:
        """Fastest minutes for every unordered pair of open stations (one Dijkstra per origin)."""
        stations = sorted(s for s in self.graph.station_nodes if s not in self.graph.closed_stations)
        result = {}
        for i, origin in enumerate(stations):
            best = self.graph.shortest_minutes_from(origin)
            for destination in stations[i + 1:]:
                if destination in best:
                    result[(origin, destination)] = round(best[destination], 2)
        return result
