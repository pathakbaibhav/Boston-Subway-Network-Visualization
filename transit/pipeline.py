"""Build the normalized subway network and live alerts from the MBTA API and mbta.com.

Usage:
    python -m transit.pipeline network [--date YYYY-MM-DD]
    python -m transit.pipeline alerts
    python -m transit.pipeline all
"""

import argparse
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from transit.config import MIN_SEGMENT_MINUTES, SCHEDULE_WINDOW
from transit.mbta_api import MbtaClient, related_id
from transit.models import Alert, Line, Network, Segment, Station, validate_network
from transit.scraper import fetch_alerts_page, parse_alerts_html
from transit.storage import load_network, save_raw, write_alerts, write_network

log = logging.getLogger("transit.pipeline")

# Weekdays tried (after the service date) to fill segments that had no scheduled trips,
# e.g. during a planned shutdown.
FALLBACK_SERVICE_DAYS = 5
FALLBACK_SPEED_KM_PER_MIN = 0.4  # ~24 km/h, used only if a line has no scheduled data at all
STOP_BATCH_SIZE = 50


# --------------------------------------------------------------------------- network

def build_network(client: MbtaClient, service_date: date) -> Network:
    routes = client.subway_routes()
    save_raw("routes", routes)
    lines = [_to_line(r) for r in routes]
    group_of = {line.id: line.group for line in lines}

    platforms = client.subway_platforms()
    save_raw("platforms", platforms)
    platform_to_station = {p["id"]: related_id(p, "parent_station") or p["id"] for p in platforms}

    segments = _topology(client, list(group_of), group_of, platform_to_station)
    log.info("topology: %d segments across %d routes", len(segments), len(group_of))

    stations = _stations(client, segments)
    samples = _sample_travel_times(client, group_of, platform_to_station, segments, service_date)
    _assign_minutes(segments, samples, stations)

    for s in stations.values():
        s.lines = sorted({seg.line for seg in segments.values()
                          if s.id in (seg.from_station, seg.to_station)})

    network = Network(
        service_date=service_date.isoformat(),
        generated_at=_now(),
        lines=lines,
        stations=sorted(stations.values(), key=lambda s: s.name),
        segments=list(segments.values()),
        platform_to_station=platform_to_station,
    )
    validate_network(network)
    return network


def _to_line(route: dict) -> Line:
    attrs = route["attributes"]
    return Line(
        id=route["id"],
        name=attrs["long_name"],
        group="Green" if route["id"].startswith("Green-") else route["id"],
        color=f"#{attrs['color']}",
        route_type=attrs["type"],
    )


def _topology(client, route_ids, group_of, platform_to_station) -> dict:
    """Adjacent-station segments from each route's canonical (direction 0) stop sequence."""
    patterns = [p for p in client.canonical_patterns(route_ids) if p["attributes"]["direction_id"] == 0]
    save_raw("canonical_patterns", patterns)

    segments: dict[tuple[str, frozenset], Segment] = {}
    for pattern in patterns:
        route_id = related_id(pattern, "route")
        trip_id = related_id(pattern, "representative_trip")
        stops = client.trip_stops(trip_id)
        sequence = []
        for stop in stops:
            station = platform_to_station.get(stop["id"]) or related_id(stop, "parent_station") or stop["id"]
            if not sequence or sequence[-1] != station:
                sequence.append(station)

        for a, b in zip(sequence, sequence[1:]):
            key = (group_of[route_id], frozenset((a, b)))
            if key in segments:
                if route_id not in segments[key].routes:
                    segments[key].routes.append(route_id)
            else:
                segments[key] = Segment(a, b, group_of[route_id], [route_id], minutes=0.0,
                                        minutes_source="estimated")
    return segments


def _stations(client, segments) -> dict[str, Station]:
    ids = sorted({s for seg in segments.values() for s in (seg.from_station, seg.to_station)})
    raw = []
    for i in range(0, len(ids), STOP_BATCH_SIZE):
        raw.extend(client.stops_by_id(ids[i:i + STOP_BATCH_SIZE]))
    save_raw("stations", raw)
    stations = {}
    for stop in raw:
        attrs = stop["attributes"]
        stations[stop["id"]] = Station(
            id=stop["id"],
            name=attrs["name"],
            latitude=attrs["latitude"],
            longitude=attrs["longitude"],
            municipality=attrs.get("municipality"),
        )
    return stations


def _sample_travel_times(client, group_of, platform_to_station, segments, service_date):
    """Collect scheduled minutes between adjacent stations, per segment key."""
    samples: dict[tuple[str, frozenset], list[float]] = defaultdict(list)
    routes_needed = set(group_of)

    for day in _service_days(service_date, FALLBACK_SERVICE_DAYS):
        for route_id in sorted(routes_needed):
            for direction in (0, 1):
                rows = client.schedules(route_id, direction, day.isoformat(), *SCHEDULE_WINDOW)
                if day == service_date:
                    save_raw(f"schedules_{route_id}_{direction}", rows)
                for key, minutes in _hops(rows, group_of[route_id], platform_to_station):
                    if key in segments:
                        samples[key].append(minutes)

        missing = [k for k in segments if not samples.get(k)]
        if not missing:
            break
        routes_needed = {r for k in missing for r in segments[k].routes}
        log.info("%d segments without scheduled trips on %s; trying next service day", len(missing), day)
    return samples


def _hops(rows, group, platform_to_station):
    """Yield (segment key, minutes) for consecutive stops of each scheduled trip."""
    trips = defaultdict(list)
    for row in rows:
        trips[related_id(row, "trip")].append(row)
    for stops in trips.values():
        stops.sort(key=lambda r: r["attributes"]["stop_sequence"])
        for a, b in zip(stops, stops[1:]):
            leave = a["attributes"]["departure_time"] or a["attributes"]["arrival_time"]
            arrive = b["attributes"]["arrival_time"] or b["attributes"]["departure_time"]
            if not leave or not arrive:
                continue
            sa = platform_to_station.get(related_id(a, "stop"))
            sb = platform_to_station.get(related_id(b, "stop"))
            if sa and sb and sa != sb:
                minutes = (datetime.fromisoformat(arrive) - datetime.fromisoformat(leave)).total_seconds() / 60
                if minutes >= 0:
                    yield (group, frozenset((sa, sb))), minutes


def _assign_minutes(segments, samples, stations):
    for key, seg in segments.items():
        if values := samples.get(key):
            seg.minutes = round(max(sum(values) / len(values), MIN_SEGMENT_MINUTES), 2)
            seg.minutes_source = "schedule"
            seg.samples = len(values)

    # Segments that never appeared in a schedule: estimate from distance at the line's average speed.
    speed = {}
    for group in {seg.line for seg in segments.values()}:
        timed = [s for s in segments.values() if s.line == group and s.minutes_source == "schedule"]
        km = sum(_distance_km(stations, s) for s in timed)
        mins = sum(s.minutes for s in timed)
        speed[group] = km / mins if mins else FALLBACK_SPEED_KM_PER_MIN

    for seg in segments.values():
        if seg.minutes_source == "estimated":
            seg.minutes = round(max(_distance_km(stations, seg) / speed[seg.line], MIN_SEGMENT_MINUTES), 2)
            log.warning("estimated %s-%s (%s): %.1f min", seg.from_station, seg.to_station, seg.line, seg.minutes)


def _distance_km(stations, seg) -> float:
    a, b = stations[seg.from_station], stations[seg.to_station]
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _service_days(start: date, extra: int):
    yield start
    day, found = start, 0
    while found < extra:
        day += timedelta(days=1)
        if day.weekday() < 5:
            found += 1
            yield day


def next_weekday(today: date) -> date:
    while today.weekday() >= 5:
        today += timedelta(days=1)
    return today


# --------------------------------------------------------------------------- alerts

def build_alerts(client: MbtaClient | None, network: Network, html: str | None = None) -> list[Alert]:
    """Merge structured API alerts with alerts scraped from mbta.com (matched by alert id)."""
    api_alerts, web_alerts = [], []
    api_error = web_error = None

    if client is not None:
        try:
            raw = client.subway_alerts()
            save_raw("alerts_api", raw)
            api_alerts = [_api_alert(a, network) for a in raw]
        except Exception as exc:  # one source failing should not lose the other
            api_error = exc
            log.warning("MBTA API alerts unavailable: %s", exc)

    try:
        html = html if html is not None else fetch_alerts_page()
        save_raw("alerts_page.html", html)
        line_routes = defaultdict(list)
        for line in network.lines:
            line_routes[line.name].append(line.id)
        web_alerts = parse_alerts_html(html, network.stations, line_routes)
    except Exception as exc:
        web_error = exc
        log.warning("mbta.com alerts page unavailable: %s", exc)

    if api_error and web_error:
        raise RuntimeError(f"no alert source available (api: {api_error}; web: {web_error})")
    return merge_alerts(api_alerts, web_alerts)


def merge_alerts(api_alerts: list[Alert], web_alerts: list[Alert]) -> list[Alert]:
    merged = {a.id: a for a in api_alerts}
    for web in web_alerts:
        api = merged.get(web.id)
        if api is None:
            merged[web.id] = web
            continue
        api.source = "api+web"
        api.stations = api.stations or web.stations
        api.routes = api.routes or web.routes
        api.url = api.url or web.url
    return sorted(merged.values(), key=lambda a: (-(a.severity or 0), a.id))


def _api_alert(raw: dict, network: Network) -> Alert:
    attrs = raw["attributes"]
    station_ids = {s.id for s in network.stations}
    routes, stations = [], []
    for entity in attrs.get("informed_entity", []):
        if (route := entity.get("route")) and route not in routes:
            routes.append(route)
        stop = entity.get("stop")
        station = network.platform_to_station.get(stop, stop) if stop else None
        if station in station_ids and station not in stations:
            stations.append(station)
    return Alert(
        id=raw["id"],
        source="api",
        effect=attrs["effect"],
        header=attrs["header"],
        description=attrs.get("description") or "",
        severity=attrs.get("severity"),
        lifecycle=attrs.get("lifecycle"),
        routes=routes,
        stations=stations,
        active_periods=[{"start": p.get("start"), "end": p.get("end")} for p in attrs.get("active_period", [])],
        updated_at=attrs.get("updated_at"),
        url=attrs.get("url"),
    )


# --------------------------------------------------------------------------- CLI

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=["network", "alerts", "all"])
    parser.add_argument("--date", type=date.fromisoformat,
                        help="service date for sampling schedules (default: next weekday)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = MbtaClient()
    if args.target in ("network", "all"):
        network = build_network(client, args.date or next_weekday(date.today()))
        for path in write_network(network):
            log.info("wrote %s", path)
        log.info("network: %d stations, %d segments, %d lines",
                 len(network.stations), len(network.segments), len(network.lines))
    else:
        network = load_network()

    if args.target in ("alerts", "all"):
        alerts = build_alerts(client, network)
        for path in write_alerts(alerts, _now()):
            log.info("wrote %s", path)
        by_source = defaultdict(int)
        for a in alerts:
            by_source[a.source] += 1
        log.info("alerts: %d total %s", len(alerts), dict(by_source))


if __name__ == "__main__":
    main()
