"""Translate live alerts into graph closures at a point in time.

- STATION_CLOSURE / STOP_CLOSURE: trains skip the station (closed station).
- SUSPENSION / SHUTTLE / NO_SERVICE / SHUTDOWN: no trains on the affected stretch. A segment is
  closed when both of its stations are named by the alert and it carries one of the alert's routes.
  Closures are per line, so a Green Line suspension leaves a parallel Orange Line segment open.
  The stretch's end stations stay open, since riders can still board there.

Simplifications: direction-specific closures (e.g. "skipping Hawes St outbound") close the station
in both directions, and a station closure applies to every line at that station.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from transit.models import Alert, Network

STATION_EFFECTS = {"STATION_CLOSURE", "STOP_CLOSURE"}
SEGMENT_EFFECTS = {"SUSPENSION", "SHUTTLE", "NO_SERVICE", "SHUTDOWN"}


@dataclass
class Closures:
    stations: dict[str, list[str]] = field(default_factory=dict)  # station id -> alert ids
    # Segment key (line, frozenset(station pair)) -> alert ids
    segments: dict[tuple[str, frozenset[str]], list[str]] = field(default_factory=dict)

    def alert_ids(self) -> list[str]:
        ids = {a for ids in self.stations.values() for a in ids}
        ids |= {a for ids in self.segments.values() for a in ids}
        return sorted(ids)


def is_active(alert: Alert, at: datetime) -> bool:
    if alert.active_periods:
        for period in alert.active_periods:
            start = _parse(period.get("start"))
            end = _parse(period.get("end"))
            if (start is None or start <= at) and (end is None or at < end):
                return True
        return False
    # Scraped-only alerts carry no periods; the page's badge says whether they've started.
    return alert.lifecycle != "UPCOMING"


def closures_from_alerts(alerts: list[Alert], network: Network, at: datetime | None = None) -> Closures:
    at = at or datetime.now(timezone.utc)
    closures = Closures()
    for alert in alerts:
        if not is_active(alert, at):
            continue
        if alert.effect in STATION_EFFECTS:
            for station in alert.stations:
                closures.stations.setdefault(station, []).append(alert.id)
        elif alert.effect in SEGMENT_EFFECTS:
            named = set(alert.stations)
            routes = set(alert.routes)
            for seg in network.segments:
                if (seg.from_station in named and seg.to_station in named
                        and (not routes or routes & set(seg.routes))):
                    closures.segments.setdefault(seg.key, []).append(alert.id)
    return closures


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
