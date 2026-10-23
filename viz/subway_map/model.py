"""Drawing model for the subway map: projection, view transform, geometry and hit-testing.

Pure Python (no py5), so it can be unit-tested without starting the JVM.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

PARALLEL_OFFSET = 3.5  # px between lines sharing the same track pair


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


class Projection:
    """Equirectangular lat/lon -> base pixel coordinates, fitted into a rectangle."""

    def __init__(self, points: list[tuple[float, float]], x: float, y: float, w: float, h: float,
                 margin: float = 30):
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        self.lat0 = (min(lats) + max(lats)) / 2
        self.kx = math.cos(math.radians(self.lat0))  # shrink longitude to keep shapes true
        span_x = (max(lons) - min(lons)) * self.kx or 1e-9
        span_y = (max(lats) - min(lats)) or 1e-9
        self.scale = min((w - 2 * margin) / span_x, (h - 2 * margin) / span_y)
        self.min_lon, self.max_lat = min(lons), max(lats)
        # Center the drawing in the rectangle.
        self.off_x = x + (w - span_x * self.scale) / 2
        self.off_y = y + (h - span_y * self.scale) / 2

    def to_base(self, lat: float, lon: float) -> tuple[float, float]:
        return (self.off_x + (lon - self.min_lon) * self.kx * self.scale,
                self.off_y + (self.max_lat - lat) * self.scale)


@dataclass
class View:
    """Zoom and pan applied on top of the base projection."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    min_zoom: float = 0.6
    max_zoom: float = 8.0

    def to_screen(self, bx: float, by: float) -> tuple[float, float]:
        return bx * self.zoom + self.pan_x, by * self.zoom + self.pan_y

    def to_base(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.pan_x) / self.zoom, (sy - self.pan_y) / self.zoom

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom keeping the point under the cursor fixed."""
        bx, by = self.to_base(sx, sy)
        self.zoom = min(max(self.zoom * factor, self.min_zoom), self.max_zoom)
        self.pan_x = sx - bx * self.zoom
        self.pan_y = sy - by * self.zoom

    def reset(self) -> None:
        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0

    def fitted(self, points: list[tuple[float, float]], x: float, y: float, w: float, h: float,
               padding: float = 80, max_zoom: float = 3.0) -> "View":
        """A view that fits base-coordinate `points` into the screen rectangle, never zooming out."""
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        span_x = max(max(xs) - min(xs), 1.0)
        span_y = max(max(ys) - min(ys), 1.0)
        zoom = min((w - 2 * padding) / span_x, (h - 2 * padding) / span_y, max_zoom)
        zoom = max(zoom, 1.0)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        return View(zoom, x + w / 2 - cx * zoom, y + h / 2 - cy * zoom, self.min_zoom, self.max_zoom)

    def ease_toward(self, target: "View", rate: float = 0.18) -> None:
        self.zoom += (target.zoom - self.zoom) * rate
        self.pan_x += (target.pan_x - self.pan_x) * rate
        self.pan_y += (target.pan_y - self.pan_y) * rate


@dataclass
class MapStation:
    id: str
    name: str
    lines: list[str]
    x: float  # base coordinates
    y: float
    degree: int = 0

    @property
    def is_transfer(self) -> bool:
        return len(self.lines) > 1

    @property
    def is_terminal(self) -> bool:
        return self.degree == 1


@dataclass
class MapSegment:
    a: str
    b: str
    line: str
    color: tuple[int, int, int]
    x1: float  # base coordinates of the endpoints
    y1: float
    x2: float
    y2: float
    ox: float = 0.0  # screen-pixel offset for lines sharing a track pair (constant at any zoom)
    oy: float = 0.0

    @property
    def key(self) -> tuple[str, frozenset[str]]:
        return self.line, frozenset((self.a, self.b))

    def screen_points(self, view: "View") -> tuple[float, float, float, float]:
        x1, y1 = view.to_screen(self.x1, self.y1)
        x2, y2 = view.to_screen(self.x2, self.y2)
        return x1 + self.ox, y1 + self.oy, x2 + self.ox, y2 + self.oy


@dataclass
class RouteView:
    data: dict
    stations: list[str]
    legs: list[tuple[tuple[int, int, int], list[str]]]  # (color, station ids)
    polyline: list[tuple[float, float]]                 # base coordinates
    length: float

    @property
    def transfer_stations(self) -> list[str]:
        return [stations[0] for _, stations in self.legs[1:]]


@dataclass
class MapModel:
    stations: dict[str, MapStation]
    segments: list[MapSegment]
    line_colors: dict[str, tuple[int, int, int]]
    version: int = -1
    closed_stations: set[str] = field(default_factory=set)
    closed_segments: set[tuple[str, frozenset[str]]] = field(default_factory=set)
    closure_alerts: list[str] = field(default_factory=list)

    @classmethod
    def from_network(cls, network: dict, x: float, y: float, w: float, h: float) -> "MapModel":
        projection = Projection([(s["latitude"], s["longitude"]) for s in network["stations"]], x, y, w, h)
        stations = {}
        for s in network["stations"]:
            bx, by = projection.to_base(s["latitude"], s["longitude"])
            stations[s["id"]] = MapStation(s["id"], s["name"], s["lines"], bx, by)

        line_colors = {}
        for line in network["lines"]:
            line_colors.setdefault(line["group"], hex_to_rgb(line["color"]))

        by_pair = defaultdict(list)
        for seg in network["segments"]:
            by_pair[frozenset((seg["from_station"], seg["to_station"]))].append(seg)
            stations[seg["from_station"]].degree += 1
            stations[seg["to_station"]].degree += 1

        segments = []
        for pair_segments in by_pair.values():
            n = len(pair_segments)
            for i, seg in enumerate(sorted(pair_segments, key=lambda s: s["line"])):
                a, b = stations[seg["from_station"]], stations[seg["to_station"]]
                ox, oy = _perpendicular_offset(a, b, (i - (n - 1) / 2) * PARALLEL_OFFSET)
                segments.append(MapSegment(a.id, b.id, seg["line"], line_colors[seg["line"]],
                                           a.x, a.y, b.x, b.y, ox, oy))
        model = cls(stations, segments, line_colors, network.get("version", -1))
        model.apply_network_closures(network)
        return model

    def apply_network_closures(self, network: dict) -> None:
        self.closed_stations = {s["id"] for s in network["stations"] if s.get("closed")}
        self.closed_segments = {(s["line"], frozenset((s["from_station"], s["to_station"])))
                                for s in network["segments"] if s.get("closed")}

    def apply_closures(self, closures: dict) -> None:
        """Use /closures output (works for live and ?at= views alike)."""
        self.closed_stations = {c["station"]["id"] for c in closures["stations"]}
        self.closed_segments = {(c["line"], frozenset(s["id"] for s in c["stations"]))
                                for c in closures["segments"]}
        ids = {a for c in closures["stations"] for a in c["alert_ids"]}
        ids |= {a for c in closures["segments"] for a in c["alert_ids"]}
        self.closure_alerts = sorted(ids)
        self.version = closures.get("version", self.version)

    def station_at(self, view: View, sx: float, sy: float, radius: float = 9) -> str | None:
        best, best_d = None, radius
        for s in self.stations.values():
            x, y = view.to_screen(s.x, s.y)
            d = math.hypot(x - sx, y - sy)
            if d <= best_d:
                best, best_d = s.id, d
        return best

    def route_view(self, route: dict) -> RouteView:
        legs = []
        for leg in route["legs"]:
            color = hex_to_rgb(leg["color"])
            legs.append((color, [s["id"] for s in leg["stations"]]))
        ids = [s["id"] for s in route["stations"]]
        polyline = [(self.stations[i].x, self.stations[i].y) for i in ids]
        length = sum(math.dist(p, q) for p, q in zip(polyline, polyline[1:]))
        return RouteView(route, ids, legs, polyline, length)


def point_along(polyline: list[tuple[float, float]], fraction: float) -> tuple[float, float]:
    """Point at `fraction` (0..1) of the polyline's total length."""
    if len(polyline) == 1:
        return polyline[0]
    total = sum(math.dist(p, q) for p, q in zip(polyline, polyline[1:]))
    target = max(0.0, min(1.0, fraction)) * total
    for p, q in zip(polyline, polyline[1:]):
        step = math.dist(p, q)
        if target <= step and step > 0:
            t = target / step
            return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        target -= step
    return polyline[-1]


def _perpendicular_offset(a: MapStation, b: MapStation, amount: float) -> tuple[float, float]:
    if amount == 0:
        return 0.0, 0.0
    # Order endpoints so both lines on a pair offset consistently.
    (p, q) = (a, b) if a.id < b.id else (b, a)
    dx, dy = q.x - p.x, q.y - p.y
    length = math.hypot(dx, dy) or 1.0
    return -dy / length * amount, dx / length * amount
