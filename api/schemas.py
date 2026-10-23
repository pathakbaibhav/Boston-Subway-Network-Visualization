"""Response models; FastAPI uses these for validation and the OpenAPI docs at /docs."""

from pydantic import BaseModel


class StationRef(BaseModel):
    id: str
    name: str


class LineOut(BaseModel):
    id: str
    name: str
    group: str
    color: str
    route_type: int


class StationOut(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    municipality: str | None
    lines: list[str]
    closed: bool


class StationDetail(StationOut):
    neighbors: list[StationRef]
    alerts: list["AlertOut"]


class SegmentOut(BaseModel):
    from_station: str
    to_station: str
    line: str
    routes: list[str]
    minutes: float
    minutes_source: str
    closed: bool
    alert_ids: list[str]


class NetworkOut(BaseModel):
    service_date: str
    generated_at: str
    version: int
    lines: list[LineOut]
    stations: list[StationOut]
    segments: list[SegmentOut]


class LegOut(BaseModel):
    route: str
    line: str
    color: str
    stations: list[StationRef]
    minutes: float


class RouteOut(BaseModel):
    origin: StationRef
    destination: StationRef
    minutes: float
    transfers: int
    stations: list[StationRef]
    legs: list[LegOut]
    disrupted: bool                   # live closures changed this route
    normal_minutes: float | None      # same trip with no closures
    alert_ids: list[str]              # closures on the normal route that forced the change
    version: int
    at: str | None = None             # set when planned for a requested time


class AlertOut(BaseModel):
    id: str
    source: str
    effect: str
    header: str
    description: str
    severity: int | None
    lifecycle: str | None
    routes: list[str]
    stations: list[StationRef]
    active_periods: list[dict]
    updated_at: str | None
    url: str | None
    active: bool


class ClosedStationOut(BaseModel):
    station: StationRef
    alert_ids: list[str]


class ClosedSegmentOut(BaseModel):
    line: str
    stations: list[StationRef]
    alert_ids: list[str]


class ClosuresOut(BaseModel):
    version: int
    at: str
    stations: list[ClosedStationOut]
    segments: list[ClosedSegmentOut]


class HealthOut(BaseModel):
    status: str
    service_date: str
    stations: int
    segments: int
    alerts: int
    alerts_updated_at: str | None
    last_refresh_error: str | None
    version: int
    route_cache: dict


StationDetail.model_rebuild()
