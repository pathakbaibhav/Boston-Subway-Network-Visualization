"""FastAPI service: stations, network, shortest routes and live alerts for the MBTA subway.

Run:  uvicorn api.main:app --reload      (docs at http://127.0.0.1:8000/docs)

Alerts are refreshed in the background every ALERTS_REFRESH_SECONDS (default 120; 0 disables).
Endpoints are `async` so all graph reads and closure updates happen on the event loop thread;
only the network fetch for alerts runs in a worker thread.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.schemas import (AlertOut, ClosedSegmentOut, ClosedStationOut, ClosuresOut, HealthOut,
                         LegOut, LineOut, NetworkOut, RouteOut, SegmentOut, StationDetail,
                         StationOut, StationRef)
from api.state import AppState, UnknownStationError
from transit.closures import Closures, is_active
from transit.config import PROCESSED_DIR
from transit.graph import Route, StationClosedError
from transit.mbta_api import MbtaClient
from transit.pipeline import build_alerts
from transit.storage import ALERTS_JSON, load_alerts, load_network, write_alerts

log = logging.getLogger("api")
# uvicorn configures only its own loggers; this makes the app's refresh/closure logs visible too.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
BOSTON = ZoneInfo("America/New_York")
DEFAULT_REFRESH_SECONDS = 120


def load_state() -> AppState:
    network = load_network()
    alerts, updated_at = [], None
    alerts_path = PROCESSED_DIR / ALERTS_JSON
    if alerts_path.exists():  # start with the last saved alerts; the refresher replaces them
        alerts = load_alerts(alerts_path)
        updated_at = json.loads(alerts_path.read_text()).get("generated_at")
    return AppState(network, alerts, updated_at)


async def refresh_alerts(state: AppState, client: MbtaClient) -> None:
    try:
        alerts = await asyncio.to_thread(build_alerts, client, state.network)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        await asyncio.to_thread(write_alerts, alerts, now)
        state.apply_alerts(alerts, now)
        state.last_refresh_error = None
        log.info("alerts refreshed: %d alerts, %d closed stations, %d closed segments",
                 len(alerts), len(state.closures.stations), len(state.closures.segments))
    except Exception as exc:  # keep serving the last known alerts
        state.last_refresh_error = f"{type(exc).__name__}: {exc}"
        log.warning("alert refresh failed: %s", state.last_refresh_error)


async def _refresh_loop(app: FastAPI, interval: float) -> None:
    while True:
        await refresh_alerts(app.state.transit, app.state.client)
        await asyncio.sleep(interval)


def create_app(state: AppState | None = None, refresh_seconds: float | None = None,
               client: MbtaClient | None = None) -> FastAPI:
    if refresh_seconds is None:
        refresh_seconds = float(os.getenv("ALERTS_REFRESH_SECONDS", DEFAULT_REFRESH_SECONDS))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.transit is None:
            app.state.transit = load_state()
        task = None
        if refresh_seconds > 0:
            app.state.client = app.state.client or MbtaClient()
            task = asyncio.create_task(_refresh_loop(app, refresh_seconds))
        yield
        if task:
            task.cancel()

    app = FastAPI(
        title="Boston Subway Network API",
        description="Shortest routes across the MBTA subway with live service alerts.",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.transit = state
    app.state.client = client
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"])

    @app.exception_handler(UnknownStationError)
    async def unknown_station(request: Request, exc: UnknownStationError):
        return JSONResponse(status_code=404, content={
            "detail": f"Unknown station: {exc.query!r}", "suggestions": exc.suggestions})

    def st(request: Request) -> AppState:
        return request.app.state.transit

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": app.title, "docs": "/docs",
                "endpoints": ["/health", "/lines", "/stations", "/stations/{station}", "/network",
                              "/route?from=&to=", "/alerts", "/closures", "POST /alerts/refresh"]}

    @app.get("/health", response_model=HealthOut)
    async def health(request: Request):
        s = st(request)
        return HealthOut(status="ok", service_date=s.network.service_date,
                         stations=len(s.network.stations), segments=len(s.network.segments),
                         alerts=len(s.alerts), alerts_updated_at=s.alerts_updated_at,
                         last_refresh_error=s.last_refresh_error, version=s.graph.version,
                         route_cache=s.planner.cache.stats())

    @app.get("/lines", response_model=list[LineOut])
    async def lines(request: Request):
        return [LineOut(**vars(line)) for line in st(request).network.lines]

    @app.get("/stations", response_model=list[StationOut])
    async def stations(request: Request,
                       line: str | None = Query(None, description="Line group, e.g. Red or Green"),
                       q: str | None = Query(None, description="Case-insensitive name search")):
        s = st(request)
        result = s.network.stations
        if line:
            result = [x for x in result if line.lower() in (g.lower() for g in x.lines)]
        if q:
            result = [x for x in result if q.lower() in x.name.lower()]
        return [_station_out(s, x) for x in result]

    @app.get("/stations/{station}", response_model=StationDetail)
    async def station_detail(request: Request, station: str):
        s = st(request)
        found = s.resolve_station(station)
        neighbors = set()
        for seg in s.network.segments:
            if found.id in (seg.from_station, seg.to_station):
                neighbors.add(seg.to_station if seg.from_station == found.id else seg.from_station)
        alerts = [a for a in s.active_alerts() if found.id in a.stations]
        return StationDetail(**_station_out(s, found).model_dump(),
                             neighbors=[_ref(s, n) for n in sorted(neighbors)],
                             alerts=[_alert_out(s, a) for a in alerts])

    @app.get("/network", response_model=NetworkOut)
    async def network(request: Request):
        s = st(request)
        return NetworkOut(
            service_date=s.network.service_date, generated_at=s.network.generated_at,
            version=s.graph.version,
            lines=[LineOut(**vars(line)) for line in s.network.lines],
            stations=[_station_out(s, x) for x in s.network.stations],
            segments=[SegmentOut(from_station=seg.from_station, to_station=seg.to_station,
                                 line=seg.line, routes=seg.routes, minutes=seg.minutes,
                                 minutes_source=seg.minutes_source,
                                 closed=seg.key in s.closures.segments,
                                 alert_ids=s.closures.segments.get(seg.key, []))
                      for seg in s.network.segments],
        )

    @app.get("/route", response_model=RouteOut)
    async def route(request: Request,
                    origin: str = Query(..., alias="from", description="Station id or name"),
                    destination: str = Query(..., alias="to", description="Station id or name"),
                    at: datetime | None = Query(None, description="Plan for this time instead of now "
                                                "(ISO 8601; Boston time if no offset)")):
        s = st(request)
        a, b = s.resolve_station(origin), s.resolve_station(destination)
        if at is not None:
            at = at if at.tzinfo else at.replace(tzinfo=BOSTON)
            closures, graph = s.closures_at(at)
            plan = graph.shortest_path
        else:
            s.refresh_closures()  # alerts may have started or ended since the last refresh
            closures, plan = s.closures, s.planner.route

        try:
            live = plan(a.id, b.id)
        except StationClosedError as exc:
            raise HTTPException(409, detail={
                "message": f"{s.stations[exc.station].name} is closed",
                "alert_ids": closures.stations.get(exc.station, [])})
        normal = s.normal_planner.route(a.id, b.id)
        blocking = _blocking_alerts(normal, closures)
        if live is None:
            raise HTTPException(409, detail={
                "message": f"No train route from {a.name} to {b.name} while service is disrupted",
                "alert_ids": blocking})
        disrupted = normal is not None and (live.stations != normal.stations or live.minutes != normal.minutes)
        return RouteOut(
            origin=_ref(s, a.id), destination=_ref(s, b.id), minutes=live.minutes,
            transfers=live.transfers, stations=[_ref(s, x) for x in live.stations],
            legs=[LegOut(route=leg.route, line=leg.line, color=s.line_colors[leg.line],
                         stations=[_ref(s, x) for x in leg.stations], minutes=leg.minutes)
                  for leg in live.legs],
            disrupted=disrupted, normal_minutes=normal.minutes if normal else None,
            alert_ids=blocking if disrupted else [],
            version=s.graph.version, at=at.isoformat() if at else None,
        )

    @app.get("/alerts", response_model=list[AlertOut])
    async def alerts(request: Request,
                     active: bool | None = Query(None, description="Only alerts in effect now (true) "
                                                 "or not yet/no longer in effect (false)"),
                     effect: str | None = Query(None, description="e.g. SUSPENSION, STATION_CLOSURE"),
                     line: str | None = Query(None, description="Route id or line group, e.g. Green")):
        s = st(request)
        now = datetime.now(timezone.utc)
        result = []
        for a in s.alerts:
            if active is not None and is_active(a, now) != active:
                continue
            if effect and a.effect != effect.upper():
                continue
            if line and not any(r == line or s.lines.get(r) and s.lines[r].group == line for r in a.routes):
                continue
            result.append(_alert_out(s, a, now))
        return result

    @app.get("/closures", response_model=ClosuresOut)
    async def closures(request: Request,
                       at: datetime | None = Query(None, description="ISO 8601; Boston time if no offset")):
        s = st(request)
        if at is not None:
            at = at if at.tzinfo else at.replace(tzinfo=BOSTON)
            result, _ = s.closures_at(at)
        else:
            s.refresh_closures()
            result, at = s.closures, datetime.now(timezone.utc)
        return ClosuresOut(
            version=s.graph.version, at=at.isoformat(),
            stations=[ClosedStationOut(station=_ref(s, sid), alert_ids=ids)
                      for sid, ids in sorted(result.stations.items())],
            segments=[ClosedSegmentOut(line=line, stations=[_ref(s, x) for x in sorted(pair)], alert_ids=ids)
                      for (line, pair), ids in sorted(result.segments.items(), key=lambda kv: (kv[0][0], sorted(kv[0][1])))],
        )

    @app.post("/alerts/refresh", response_model=HealthOut)
    async def refresh(request: Request):
        """Fetch alerts from the MBTA API and mbta.com now instead of waiting for the next cycle."""
        request.app.state.client = request.app.state.client or MbtaClient()
        await refresh_alerts(st(request), request.app.state.client)
        return await health(request)

    return app


def _ref(s: AppState, station_id: str) -> StationRef:
    return StationRef(id=station_id, name=s.stations[station_id].name)


def _station_out(s: AppState, station) -> StationOut:
    return StationOut(id=station.id, name=station.name, latitude=station.latitude,
                      longitude=station.longitude, municipality=station.municipality,
                      lines=station.lines, closed=station.id in s.closures.stations)


def _alert_out(s: AppState, a, now: datetime | None = None) -> AlertOut:
    return AlertOut(id=a.id, source=a.source, effect=a.effect, header=a.header,
                    description=a.description, severity=a.severity, lifecycle=a.lifecycle,
                    routes=a.routes, stations=[_ref(s, x) for x in a.stations if x in s.stations],
                    active_periods=a.active_periods, updated_at=a.updated_at, url=a.url,
                    active=is_active(a, now or datetime.now(timezone.utc)))


def _blocking_alerts(normal: Route | None, closures: Closures) -> list[str]:
    """Alerts closing a station or segment that the undisrupted route would have used."""
    if normal is None:
        return []
    ids = set()
    for leg in normal.legs:
        for a, b in zip(leg.stations, leg.stations[1:]):
            ids.update(closures.segments.get((leg.line, frozenset((a, b))), []))
    for leg in normal.legs[1:]:  # passing through a closed station is fine; changing trains is not
        ids.update(closures.stations.get(leg.stations[0], []))
    return sorted(ids)


app = create_app()
