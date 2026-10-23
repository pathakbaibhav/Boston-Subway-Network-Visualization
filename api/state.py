"""Long-lived application state: network, live graph, route planners and current alerts."""

import difflib
import logging
from datetime import datetime, timezone

from transit.closures import Closures, closures_from_alerts, is_active
from transit.graph import RoutePlanner, TransitGraph
from transit.models import Alert, Network, Station

log = logging.getLogger("api.state")


class UnknownStationError(LookupError):
    def __init__(self, query: str, suggestions: list[str]):
        super().__init__(query)
        self.query = query
        self.suggestions = suggestions


class AppState:
    def __init__(self, network: Network, alerts: list[Alert] | None = None,
                 alerts_updated_at: str | None = None):
        self.network = network
        self.stations: dict[str, Station] = {s.id: s for s in network.stations}
        self._by_name = {s.name.lower(): s for s in network.stations}
        self.lines = {line.id: line for line in network.lines}
        self.line_colors = {line.group: line.color for line in network.lines}

        self.graph = TransitGraph(network)          # live: closures applied
        self.planner = RoutePlanner(self.graph)
        self.normal_planner = RoutePlanner(TransitGraph(network))  # never closed, for comparison

        self.alerts: list[Alert] = []
        self.closures = Closures()
        self.alerts_updated_at: str | None = None
        self.last_refresh_error: str | None = None
        self.apply_alerts(alerts or [], alerts_updated_at)

    def apply_alerts(self, alerts: list[Alert], updated_at: str | None, now: datetime | None = None) -> None:
        """Replace the current alerts and re-derive closures for the live graph."""
        self.alerts = alerts
        self.alerts_updated_at = updated_at
        self.refresh_closures(now)

    def refresh_closures(self, now: datetime | None = None) -> None:
        """Re-evaluate which alerts are active; alerts start and end without new data arriving."""
        self.closures = closures_from_alerts(self.alerts, self.network, now)
        before = self.graph.version
        self.graph.set_closures(self.closures.stations, self.closures.segments)
        if self.graph.version != before:
            log.info("closures changed (version %d): %d stations, %d segments",
                     self.graph.version, len(self.closures.stations), len(self.closures.segments))

    def closures_at(self, at: datetime) -> tuple[Closures, TransitGraph]:
        """Closures and a separate graph for a requested time (leaves the live graph untouched)."""
        closures = closures_from_alerts(self.alerts, self.network, at)
        graph = TransitGraph(self.network)
        graph.set_closures(closures.stations, closures.segments)
        return closures, graph

    def active_alerts(self, at: datetime | None = None) -> list[Alert]:
        at = at or datetime.now(timezone.utc)
        return [a for a in self.alerts if is_active(a, at)]

    def resolve_station(self, query: str) -> Station:
        """Accept a station id ("place-pktrm") or name, case-insensitive ("park street")."""
        if query in self.stations:
            return self.stations[query]
        if station := self._by_name.get(query.strip().lower()):
            return station
        names = difflib.get_close_matches(query.strip().lower(), self._by_name, n=3, cutoff=0.6)
        raise UnknownStationError(query, [self._by_name[n].name for n in names])
