"""Normalized data schema shared by the pipeline, the graph engine and the API."""

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field


@dataclass
class Line:
    id: str          # MBTA route id, e.g. "Red", "Green-B"
    name: str        # e.g. "Green Line B"
    group: str       # line a rider sees on the map, e.g. "Green" for all Green branches
    color: str       # hex, e.g. "#DA291C"
    route_type: int  # 0 = light rail, 1 = heavy rail


@dataclass
class Station:
    id: str          # MBTA parent station id, e.g. "place-pktrm"
    name: str
    latitude: float
    longitude: float
    municipality: str | None = None
    lines: list[str] = field(default_factory=list)  # line groups serving the station


@dataclass
class Segment:
    """Undirected track segment between two adjacent stations on one line."""

    from_station: str
    to_station: str
    line: str                # line group
    routes: list[str]        # route ids running over this segment
    minutes: float
    minutes_source: str      # "schedule" or "estimated"
    samples: int = 0         # scheduled trips the travel time was averaged over

    @property
    def key(self) -> tuple[str, frozenset[str]]:
        return self.line, frozenset((self.from_station, self.to_station))


@dataclass
class Alert:
    id: str
    source: str                       # "api", "web" or "api+web"
    effect: str                       # e.g. SUSPENSION, SHUTTLE, STATION_CLOSURE, DELAY
    header: str
    description: str = ""
    severity: int | None = None       # MBTA 0-10 scale (API only)
    lifecycle: str | None = None      # e.g. NEW, ONGOING, UPCOMING
    routes: list[str] = field(default_factory=list)
    stations: list[str] = field(default_factory=list)  # parent station ids
    active_periods: list[dict] = field(default_factory=list)  # [{"start": iso, "end": iso | None}]
    updated_at: str | None = None
    url: str | None = None


@dataclass
class Network:
    service_date: str
    generated_at: str
    lines: list[Line]
    stations: list[Station]
    segments: list[Segment]
    platform_to_station: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Network":
        return cls(
            service_date=data["service_date"],
            generated_at=data["generated_at"],
            lines=[Line(**x) for x in data["lines"]],
            stations=[Station(**x) for x in data["stations"]],
            segments=[Segment(**x) for x in data["segments"]],
            platform_to_station=data.get("platform_to_station", {}),
        )


class ValidationError(ValueError):
    pass


def validate_network(network: Network) -> None:
    """Raise ValidationError if the network is inconsistent or not fully connected."""
    errors = []
    station_ids = {s.id for s in network.stations}
    line_groups = {line.group for line in network.lines}

    if len(station_ids) != len(network.stations):
        errors.append("duplicate station ids")

    seen = set()
    for seg in network.segments:
        label = f"{seg.from_station}-{seg.to_station} ({seg.line})"
        for end in (seg.from_station, seg.to_station):
            if end not in station_ids:
                errors.append(f"segment {label} references unknown station {end}")
        if seg.from_station == seg.to_station:
            errors.append(f"segment {label} is a self-loop")
        if seg.minutes <= 0:
            errors.append(f"segment {label} has non-positive minutes {seg.minutes}")
        if seg.line not in line_groups:
            errors.append(f"segment {label} has unknown line {seg.line}")
        if seg.key in seen:
            errors.append(f"duplicate segment {label}")
        seen.add(seg.key)

    for s in network.stations:
        if not (42.0 < s.latitude < 42.6 and -71.4 < s.longitude < -70.8):
            errors.append(f"station {s.id} has coordinates outside Greater Boston")

    if not errors and station_ids:
        adjacency = defaultdict(set)
        for seg in network.segments:
            adjacency[seg.from_station].add(seg.to_station)
            adjacency[seg.to_station].add(seg.from_station)
        start = next(iter(station_ids))
        reached, queue = {start}, deque([start])
        while queue:
            for nxt in adjacency[queue.popleft()] - reached:
                reached.add(nxt)
                queue.append(nxt)
        if missing := station_ids - reached:
            errors.append(f"network is disconnected; unreachable: {sorted(missing)[:5]}...")

    if errors:
        raise ValidationError("; ".join(errors[:10]))
