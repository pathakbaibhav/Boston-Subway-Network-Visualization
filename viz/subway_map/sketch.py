"""Live MBTA subway map in Processing (py5), driven by the REST API.

Click two stations to plan a route; the map dims everything else and animates a pulse along the
route in each line's color. A background thread polls /health and, when the closure version
changes, reloads closures and re-plans the current route, so service changes appear live.
"""

import math
import threading
import time
from datetime import datetime

import py5

from viz.subway_map.client import ApiClient, ApiUnavailableError
from viz.subway_map.feed import LiveFeed
from viz.subway_map.model import MapModel, RouteView, View, point_along

PANEL_W = 340
BG = (246, 245, 241)
INK = (33, 33, 33)
MUTED = (120, 120, 120)
CLOSED = (200, 35, 35)
DIM_ALPHA = 55
PULSE_SECONDS = 4.0  # time for the pulse to travel the whole route


class SubwayMap(py5.Sketch):
    def __init__(self, client: ApiClient, at: str | None = None, poll_seconds: float = 5,
                 size: tuple[int, int] = (1180, 860), density: int | None = None,
                 preselect: tuple[str, str] | None = None, screenshot: str | None = None):
        super().__init__()
        self.client = client
        self.at = at
        self.poll_seconds = poll_seconds
        self.win_w, self.win_h = size
        self.density = density
        self.preselect = preselect
        self.screenshot = screenshot

        self.model: MapModel | None = None
        self.view = View()
        self.alerts: dict[str, dict] = {}
        self.origin: str | None = None
        self.destination: str | None = None
        self.route: RouteView | None = None
        self.route_error: str | None = None
        self.route_started = 0.0
        self.status = "Connecting to API..."
        self.api_ok = False
        self.last_update: str | None = None
        self.toast: tuple[str, float] | None = None

        self._lock = threading.Lock()
        self._pending: dict = {}
        self._wake = threading.Event()
        self._drag_from: tuple[float, float] | None = None
        self._hover: str | None = None
        self._target_view: View | None = None  # auto-fit animation target
        self._user_view = False                # user zoomed/panned: stop auto-fitting

    # ------------------------------------------------------------------ py5 lifecycle

    def settings(self):
        self.size(self.win_w, self.win_h)
        self.smooth(8)
        self.pixel_density(self.density or self.display_density())

    def setup(self):
        title = "MBTA Subway — " + (f"planned for {self.at}" if self.at else "live")
        self.get_surface().set_title(title)
        self.frame_rate(30)
        self.text_font(self.create_font("SansSerif", 13))
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def draw(self):
        self._apply_pending()
        self.background(*BG)
        if self.model is None:
            self._draw_waiting()
            return
        if self._target_view and not self._user_view:
            self.view.ease_toward(self._target_view)
        self._draw_segments()
        self._draw_route()
        self._draw_stations()
        self._draw_hover()
        self._draw_header()
        self._draw_panel()
        self._draw_toast()
        self._maybe_screenshot()

    # ------------------------------------------------------------------ data (background thread)

    def _poll_loop(self):
        feed = LiveFeed(self.client, self._post, self.at)
        while True:
            feed.route_pair = (self.origin, self.destination) if self.origin and self.destination else None
            feed.poll_once()
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _request_route(self):
        origin, destination = self.origin, self.destination

        def fetch():
            try:
                result = self.client.route(origin, destination, self.at)
            except ApiUnavailableError as exc:
                result = (None, str(exc))
            if (origin, destination) == (self.origin, self.destination):
                self._post(route=result)
        threading.Thread(target=fetch, daemon=True).start()

    def _post(self, **updates):
        with self._lock:
            self._pending.update(updates)

    def _apply_pending(self):
        """Apply results from background threads on the animation thread."""
        with self._lock:
            pending, self._pending = self._pending, {}
        if "network" in pending:
            self.model = MapModel.from_network(pending["network"], 0, 56, self.width - PANEL_W, self.height - 56)
            if self.preselect:
                self.origin, self.destination = self._resolve(self.preselect[0]), self._resolve(self.preselect[1])
                if self.origin and self.destination:
                    self._request_route()
        if "api_ok" in pending:
            self.api_ok = pending["api_ok"]
            self.status = pending.get("status", "")
        if "closures" in pending and self.model:
            self.model.apply_closures(pending["closures"])
            self.alerts = pending["alerts"]
            self.last_update = pending.get("updated")
            if pending.get("changed"):
                self.toast = ("Service change received — map and route updated", time.time())
        if "route" in pending and self.model:
            route, error = pending["route"]
            previous = self.route.data if self.route else None
            self.route = self.model.route_view(route) if route else None
            self.route_error = error
            if route is None or previous is None or route["stations"] != previous["stations"]:
                self.route_started = time.time()
            if self.route:
                self._target_view = View().fitted(self.route.polyline, 0, 56, self.width - PANEL_W,
                                                  self.height - 56)

    def _resolve(self, name: str) -> str | None:
        name = name.lower()
        for s in self.model.stations.values():
            if s.id == name or s.name.lower() == name:
                return s.id
        return None

    # ------------------------------------------------------------------ drawing

    def _draw_waiting(self):
        self.fill(*INK)
        self.text_align(py5.CENTER, py5.CENTER)
        self.text_size(16)
        self.text("Waiting for the subway API...", self.width / 2, self.height / 2 - 20)
        self.text_size(13)
        self.fill(*MUTED)
        self.text("Start it with:  uvicorn api.main:app", self.width / 2, self.height / 2 + 8)
        self.text(self.status[:110], self.width / 2, self.height / 2 + 32)
        self.text_align(py5.LEFT, py5.BASELINE)

    def _draw_segments(self):
        route_keys = self._route_segment_keys()
        self.stroke_cap(py5.ROUND)
        for seg in self.model.segments:
            x1, y1, x2, y2 = seg.screen_points(self.view)
            closed = seg.key in self.model.closed_segments
            alpha = DIM_ALPHA if self.route and seg.key not in route_keys else 255
            if closed:
                self._dashed(x1, y1, x2, y2, (*CLOSED, alpha))
                continue
            self.stroke(*seg.color, alpha)
            self.stroke_weight(4)
            self.line(x1, y1, x2, y2)

    def _draw_route(self):
        if not self.route:
            return
        # White casing, then each leg in its line color, then a pulse traveling the route.
        points = [self.view.to_screen(x, y) for x, y in self.route.polyline]
        self.no_fill()
        self.stroke(255)
        self.stroke_weight(12)
        self._polyline(points)
        for color, ids in self.route.legs:
            self.stroke(*color)
            self.stroke_weight(8)
            self._polyline([self.view.to_screen(self.model.stations[i].x, self.model.stations[i].y) for i in ids])

        if len(points) > 1:
            t = ((time.time() - self.route_started) % PULSE_SECONDS) / PULSE_SECONDS
            px, py = point_along(points, t)
            glow = 10 + 4 * math.sin(time.time() * 6)
            self.no_stroke()
            self.fill(255, 255, 255, 200)
            self.circle(px, py, glow + 6)
            self.fill(*INK)
            self.circle(px, py, 8)

    def _draw_stations(self):
        on_route = set(self.route.stations) if self.route else set()
        for s in self.model.stations.values():
            x, y = self.view.to_screen(s.x, s.y)
            dim = self.route and s.id not in on_route
            alpha = DIM_ALPHA if dim else 255
            size = 11 if s.is_transfer else 7
            if s.id in (self.origin, self.destination):
                size = 14
            self.stroke(*INK, alpha)
            self.stroke_weight(1.6 if s.is_transfer else 1.2)
            self.fill(255, 255, 255, alpha)
            self.circle(x, y, size)
            if s.id in self.model.closed_stations:
                self.stroke(*CLOSED, alpha)
                self.stroke_weight(2)
                d = size / 2 + 2
                self.line(x - d, y - d, x + d, y + d)
                self.line(x - d, y + d, x + d, y - d)

            if s.id in (self.origin, self.destination):
                self._label(s.name, x, y, bold=True)
            elif self.route and s.id in self.route.transfer_stations:
                self._label(s.name, x, y)
            elif not self.route and s.is_terminal:
                self._label(s.name, x, y, muted=True)
            elif not self.route and s.is_transfer and self.view.zoom >= 2:  # downtown is dense
                self._label(s.name, x, y, muted=True)
            elif self.view.zoom >= 4:
                self._label(s.name, x, y, muted=True)

    def _draw_hover(self):
        self._hover = self.model.station_at(self.view, self.mouse_x, self.mouse_y)
        if not self._hover or self.mouse_x > self.width - PANEL_W:
            return
        s = self.model.stations[self._hover]
        x, y = self.view.to_screen(s.x, s.y)
        text = f"{s.name}  ·  {', '.join(s.lines)}"
        if s.id in self.model.closed_stations:
            text += "  ·  CLOSED"
        self._tooltip(text, x + 12, y - 12)

    def _draw_header(self):
        self.no_stroke()
        self.fill(*BG)
        self.rect(0, 0, self.width - PANEL_W, 52)
        self.fill(*INK)
        self.text_size(20)
        title = "Boston Subway Network"
        self.text(title, 20, 32)
        x = 20 + self.text_width(title) + 18
        self.text_size(12)
        mode = f"Planned view for {self.at}" if self.at else "Live service"
        dot = (46, 160, 67) if self.api_ok else CLOSED
        self.fill(*dot)
        self.circle(x, 27, 8)
        self.fill(*MUTED)
        updated = f" · alerts updated {_short_time(self.last_update)}" if self.last_update else ""
        self.text(f"{mode}{updated} · v{self.model.version}", x + 10, 31)

    def _draw_panel(self):
        x0 = self.width - PANEL_W
        self.no_stroke()
        self.fill(255)
        self.rect(x0, 0, PANEL_W, self.height)
        self.stroke(225)
        self.line(x0, 0, x0, self.height)
        x, y = x0 + 20, 36

        self.no_stroke()
        self.fill(*INK)
        self.text_size(16)
        self.text("Plan a trip", x, y)
        y += 22
        self.text_size(12)
        self.fill(*MUTED)
        for line in ("Click a station to start, another to finish.",
                     "Scroll to zoom · drag to pan · C clear · R refresh",
                     "0 reset view · S save screenshot"):
            self.text(line, x, y)
            y += 17
        y += 12

        if self.origin:
            y = self._kv("From", self.model.stations[self.origin].name, x, y)
        if self.destination:
            y = self._kv("To", self.model.stations[self.destination].name, x, y)

        if self.route_error:
            y = self._box(self.route_error, x, y + 6, CLOSED)
        elif self.route:
            r = self.route.data
            y += 8
            self.fill(*INK)
            self.text_size(26)
            self.text(f"{r['minutes']:.0f} min", x, y + 22)
            self.text_size(12)
            self.fill(*MUTED)
            transfers = r["transfers"]
            self.text(f"{transfers} transfer{'s' if transfers != 1 else ''} · {len(r['stations'])} stations",
                      x + 110, y + 20)
            y += 44
            for leg in r["legs"]:
                y = self._leg(leg, x, y)
            if r["disrupted"]:
                extra = r["minutes"] - (r["normal_minutes"] or r["minutes"])
                headers = [self.alerts[a]["header"] for a in r["alert_ids"] if a in self.alerts]
                msg = f"Rerouted around a service change (+{extra:.0f} min vs. normal)."
                y = self._box(" ".join([msg, *headers[:1]]), x, y + 6, (214, 134, 0))

        y = max(y + 20, self.height - 300)
        self.fill(*INK)
        self.text_size(14)
        closed = len(self.model.closed_stations) + len(self.model.closed_segments)
        self.text(f"Service changes ({len(self.model.closure_alerts)})", x, y)
        y += 8
        self.text_size(11)
        if not closed:
            self.fill(*MUTED)
            self.text("No closures affecting trains.", x, y + 16)
        for alert_id in self.model.closure_alerts[:5]:
            alert = self.alerts.get(alert_id)
            if alert:
                y = self._wrapped(f"• {alert['header']}", x, y + 16, PANEL_W - 40, MUTED, max_lines=3)

    def _draw_toast(self):
        if not self.toast:
            return
        text, started = self.toast
        age = time.time() - started
        if age > 4:
            self.toast = None
            return
        alpha = 255 if age < 3 else int(255 * (4 - age))
        self.text_size(13)
        w = self.text_width(text) + 28
        x = (self.width - PANEL_W - w) / 2
        self.no_stroke()
        self.fill(*INK, alpha * 0.9)
        self.rect(x, self.height - 54, w, 32, 16)
        self.fill(255, alpha)
        self.text(text, x + 14, self.height - 33)

    def _maybe_screenshot(self):
        if not self.screenshot:
            return
        ready = self.route is not None or self.route_error or not self.preselect
        settled = not self._target_view or abs(self.view.zoom - self._target_view.zoom) < 0.01
        if ready and settled and self.frame_count > 45 and time.time() - self.route_started > 1.2:
            self.save_frame(self.screenshot)
            self.exit_sketch()

    # ------------------------------------------------------------------ drawing helpers

    def _route_segment_keys(self) -> set:
        keys = set()
        if self.route:
            for leg in self.route.data["legs"]:
                ids = [s["id"] for s in leg["stations"]]
                for a, b in zip(ids, ids[1:]):
                    keys.add((leg["line"], frozenset((a, b))))
        return keys

    def _polyline(self, points):
        self.begin_shape()
        for x, y in points:
            self.vertex(x, y)
        self.end_shape()

    def _dashed(self, x1, y1, x2, y2, color, dash=5):
        self.stroke(*color)
        self.stroke_weight(3)
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(length / dash), 1)
        for i in range(0, steps, 2):
            a, b = i / steps, min((i + 1) / steps, 1)
            self.line(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)

    def _label(self, text, x, y, bold=False, muted=False):
        self.text_size(12 if bold else 11)
        w = self.text_width(text)
        self.no_stroke()
        self.fill(*BG, 210)
        self.rect(x + 8, y - 15, w + 6, 16, 3)
        self.fill(*(MUTED if muted else INK))
        self.text(text, x + 11, y - 3)

    def _tooltip(self, text, x, y):
        self.text_size(12)
        w = self.text_width(text) + 16
        x = min(x, self.width - PANEL_W - w - 4)
        self.no_stroke()
        self.fill(*INK, 235)
        self.rect(x, y - 18, w, 24, 4)
        self.fill(255)
        self.text(text, x + 8, y - 1)

    def _kv(self, key, value, x, y):
        self.text_size(12)
        self.fill(*MUTED)
        self.text(key, x, y)
        self.fill(*INK)
        self.text_size(14)
        self.text(value, x + 44, y)
        return y + 22

    def _leg(self, leg, x, y):
        color = self.model.line_colors.get(leg["line"], INK)
        self.no_stroke()
        self.fill(*color)
        self.rect(x, y - 11, 6, 30, 3)
        self.fill(*INK)
        self.text_size(13)
        self.text(f"{leg['route']}  ·  {leg['minutes']:.0f} min", x + 14, y)
        self.fill(*MUTED)
        self.text_size(11)
        first, last = leg["stations"][0]["name"], leg["stations"][-1]["name"]
        stops = len(leg["stations"]) - 1
        self.text(f"{first} → {last} ({stops} stop{'s' if stops != 1 else ''})", x + 14, y + 15)
        return y + 38

    def _box(self, text, x, y, color):
        w = PANEL_W - 40
        self.text_size(12)
        lines = _wrap(self, text, w - 20)
        if len(lines) > 6:
            lines = lines[:6]
            lines[-1] = lines[-1].rsplit(" ", 1)[0] + " …"
        h = 14 + 16 * len(lines)
        self.no_stroke()
        self.fill(*color, 30)
        self.rect(x, y, w, h, 6)
        self.fill(*color)
        self.rect(x, y, 4, h, 2)
        self.fill(*INK)
        for i, line in enumerate(lines):
            self.text(line, x + 12, y + 20 + 16 * i)
        return y + h + 8

    def _wrapped(self, text, x, y, width, color, max_lines=3):
        lines = _wrap(self, text, width)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rsplit(" ", 1)[0] + " …"
        self.fill(*color)
        for i, line in enumerate(lines):
            self.text(line, x, y + 14 * i)
        return y + 14 * (len(lines) - 1) + 4

    # ------------------------------------------------------------------ input

    def mouse_pressed(self):
        self._drag_from = (self.mouse_x, self.mouse_y)

    def mouse_dragged(self):
        if self._drag_from and self.mouse_x < self.width - PANEL_W:
            self._user_view = True
            self.view.pan_x += self.mouse_x - self.pmouse_x
            self.view.pan_y += self.mouse_y - self.pmouse_y

    def mouse_released(self):
        start, self._drag_from = self._drag_from, None
        if not self.model or not start or math.dist(start, (self.mouse_x, self.mouse_y)) > 4:
            return  # it was a drag, not a click
        if self.mouse_button == py5.RIGHT:
            self._clear()
            return
        station = self.model.station_at(self.view, self.mouse_x, self.mouse_y)
        if not station:
            return
        if self.origin is None or self.destination is not None:
            self.origin, self.destination = station, None
            self.route, self.route_error = None, None
        elif station != self.origin:
            self.destination = station
            self._request_route()

    def mouse_wheel(self, event):
        if self.mouse_x < self.width - PANEL_W:
            self._user_view = True
            self.view.zoom_at(self.mouse_x, self.mouse_y, 0.9 if event.get_count() > 0 else 1.1)

    def key_pressed(self):
        key = str(self.key).lower()
        if key == "c":
            self._clear()
        elif key == "0":
            self._user_view = False
            self._target_view = View()  # ease back to the full network
        elif key == "s":
            self.save_frame(f"subway-map-{datetime.now():%Y%m%d-%H%M%S}.png")
        elif key == "r":
            threading.Thread(target=self._force_refresh, daemon=True).start()

    def _force_refresh(self):
        try:
            self.client.refresh_alerts()
        except ApiUnavailableError:
            pass
        self._wake.set()

    def _clear(self):
        self.origin = self.destination = None
        self.route = self.route_error = None
        if not self._user_view:
            self._target_view = View()


def _wrap(sketch, text: str, width: float) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if sketch.text_width(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _short_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except ValueError:
        return iso
