// Web version of the subway map: p5.js (Processing for the web) draws the network; routing runs
// in the browser on the same graph model as the Python engine; alerts come live from the MBTA API
// with the GitHub Actions-published snapshot (which includes scraped alerts) as a fallback.

import { closuresFromAlerts, fetchLiveAlerts, mergeLiveAlerts } from "./alerts.js";
import { buildMap, pointAlong, stationAt, View } from "./geo.js";
import { RoutePlanner, segmentKey, StationClosedError, TransitGraph } from "./graph.js";

const LIVE_POLL_MS = 60_000;
const CLOSURE_RECHECK_MS = 30_000; // alerts start and end on their own schedule
const PULSE_SECONDS = 4;
const BG = [246, 245, 241];
const INK = [33, 33, 33];
const MUTED = [120, 120, 120];
const CLOSED = [200, 35, 35];
const DIM = 55;

const $ = (id) => document.getElementById(id);

const state = {
  network: null,
  stations: new Map(),
  graph: null,
  planner: null,
  normalPlanner: null,
  published: [],
  publishedAt: null,
  alerts: [],
  alertsById: new Map(),
  live: false,
  liveCheckedAt: null,
  planAt: null, // Date when planning for a later time
  closures: { stations: new Map(), segments: new Map() },
  closureSignature: null,
  origin: null,
  destination: null,
  route: null,
  normal: null,
  routeError: null,
  blocking: [],
  map: null,
  view: new View(),
  targetView: null,
  userView: false,
  routeStarted: 0,
};

// ------------------------------------------------------------------------------- startup

async function main() {
  const [network, published, meta] = await Promise.all([
    getJSON("data/network.json"),
    getJSON("data/alerts.json").catch(() => ({ alerts: [], generated_at: null })),
    getJSON("data/meta.json").catch(() => ({})),
  ]);
  state.network = network;
  state.stations = new Map(network.stations.map((s) => [s.id, s]));
  state.graph = new TransitGraph(network);
  state.planner = new RoutePlanner(state.graph);
  state.normalPlanner = new RoutePlanner(new TransitGraph(network));
  state.published = published.alerts;
  state.publishedAt = published.generated_at || meta.alerts_generated_at || null;
  state.alerts = published.alerts;

  setupPanel(meta);
  applyUrlParams();
  new p5(sketch, $("map"));
  applyClosures(false);
  await refreshLiveAlerts();
  setInterval(refreshLiveAlerts, LIVE_POLL_MS);
  setInterval(() => applyClosures(true), CLOSURE_RECHECK_MS);
}

async function getJSON(path) {
  const resp = await fetch(path, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

async function refreshLiveAlerts() {
  try {
    const live = await fetchLiveAlerts(state.network);
    state.alerts = mergeLiveAlerts(live, state.published);
    state.live = true;
    state.liveCheckedAt = new Date();
  } catch (err) {
    console.warn("Live MBTA alerts unavailable, using published snapshot:", err);
    state.alerts = state.published;
    state.live = false;
  }
  applyClosures(true);
}

// Recompute closures for now (or the planned time); announce and re-plan when they change.
function applyClosures(announce) {
  state.alertsById = new Map(state.alerts.map((a) => [a.id, a]));
  const at = state.planAt || new Date();
  const closures = closuresFromAlerts(state.alerts, state.network, at);
  const signature = JSON.stringify([[...closures.stations.keys()].sort(), [...closures.segments.keys()].sort()]);
  const changed = state.closureSignature !== null && signature !== state.closureSignature;
  state.closures = closures;
  state.closureSignature = signature;
  state.graph.setClosures(closures.stations.keys(), closures.segments.keys());
  if (changed && announce && !state.planAt) toast("Service change received — map and route updated");
  plan();
  renderStatus();
  renderChanges();
}

// ------------------------------------------------------------------------------- routing

function plan() {
  const previous = state.route?.stations.join();
  state.route = state.normal = state.routeError = null;
  state.blocking = [];
  if (!state.origin || !state.destination) {
    renderResult();
    return;
  }
  try {
    state.normal = state.normalPlanner.route(state.origin, state.destination);
    state.route = state.planner.route(state.origin, state.destination);
    state.blocking = blockingAlerts(state.normal);
    if (!state.route) {
      const [a, b] = [name(state.origin), name(state.destination)];
      state.routeError = `No train route from ${a} to ${b} while service is disrupted.`;
    }
  } catch (err) {
    if (!(err instanceof StationClosedError)) throw err;
    state.routeError = `${name(err.station)} is closed.`;
    state.blocking = state.closures.stations.get(err.station) || [];
  }
  if (state.route && state.route.stations.join() !== previous) state.routeStarted = performance.now();
  if (state.route && state.map) fitToRoute();
  renderResult();
  updateUrl();
}

// Shareable links: ?from=Alewife&to=Heath%20Street&at=2026-11-08T12:00 (station names or ids).
function applyUrlParams() {
  const params = new URLSearchParams(location.search);
  const find = (q) => {
    if (!q) return null;
    if (state.stations.has(q)) return q;
    return state.network.stations.find((s) => s.name.toLowerCase() === q.trim().toLowerCase())?.id ?? null;
  };
  state.origin = find(params.get("from"));
  state.destination = find(params.get("to"));
  const at = params.get("at");
  if (at && /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(at)) {
    state.planAt = fromBostonInput(at.slice(0, 16));
    $("when").value = "later";
    $("when-time").hidden = false;
    $("when-time").value = toLocalInput(state.planAt);
  }
  syncInputs();
}

function updateUrl() {
  const params = new URLSearchParams();
  if (state.origin) params.set("from", name(state.origin));
  if (state.destination) params.set("to", name(state.destination));
  if (state.planAt) params.set("at", toLocalInput(state.planAt));
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

// Alerts closing a segment or transfer station that the normal route would have used.
function blockingAlerts(normal) {
  if (!normal) return [];
  const ids = new Set();
  for (const leg of normal.legs) {
    for (let i = 0; i + 1 < leg.stations.length; i++) {
      for (const id of state.closures.segments.get(segmentKey(leg.line, leg.stations[i], leg.stations[i + 1])) || []) ids.add(id);
    }
  }
  for (const leg of normal.legs.slice(1)) {
    for (const id of state.closures.stations.get(leg.stations[0]) || []) ids.add(id);
  }
  return [...ids].sort();
}

function isDisrupted() {
  const { route, normal } = state;
  return Boolean(route && normal && (route.minutes !== normal.minutes || route.stations.join() !== normal.stations.join()));
}

function selectStation(id) {
  if (!state.origin || state.destination) {
    state.origin = id;
    state.destination = null;
  } else if (id !== state.origin) {
    state.destination = id;
  }
  syncInputs();
  plan();
}

const name = (id) => state.stations.get(id)?.name ?? id;

// ------------------------------------------------------------------------------- panel (DOM)

function setupPanel(meta) {
  const list = $("station-list");
  for (const s of [...state.network.stations].sort((a, b) => a.name.localeCompare(b.name))) {
    const option = document.createElement("option");
    option.value = s.name;
    list.append(option);
  }
  $("about-stations").textContent = state.network.stations.length;
  $("about-published").textContent = state.publishedAt ? `last run ${formatTime(new Date(state.publishedAt))}` : "not yet run";

  const byName = new Map(state.network.stations.map((s) => [s.name.toLowerCase(), s.id]));
  const onInput = (field) => () => {
    const id = byName.get($(field).value.trim().toLowerCase());
    if (id || !$(field).value.trim()) {
      state[field === "from" ? "origin" : "destination"] = id || null;
      plan();
    }
  };
  $("from").addEventListener("change", onInput("from"));
  $("to").addEventListener("change", onInput("to"));
  $("swap").addEventListener("click", () => {
    [state.origin, state.destination] = [state.destination, state.origin];
    syncInputs();
    plan();
  });
  $("clear").addEventListener("click", clearTrip);
  $("trip").addEventListener("submit", (e) => e.preventDefault());

  const when = $("when");
  const whenTime = $("when-time");
  when.addEventListener("change", () => {
    whenTime.hidden = when.value !== "later";
    if (when.value === "now") {
      state.planAt = null;
      applyClosures(false);
    } else if (!whenTime.value) {
      const soon = new Date(Date.now() + 24 * 3600 * 1000);
      soon.setMinutes(0, 0, 0);
      whenTime.value = toLocalInput(soon);
      whenTime.dispatchEvent(new Event("change"));
    }
  });
  whenTime.addEventListener("change", () => {
    if (!whenTime.value) return;
    state.planAt = fromBostonInput(whenTime.value);
    applyClosures(false);
  });

  $("zoom-in").addEventListener("click", () => zoomButton(1.4));
  $("zoom-out").addEventListener("click", () => zoomButton(1 / 1.4));
  $("zoom-reset").addEventListener("click", () => {
    state.userView = false;
    state.targetView = state.route ? fittedView() : new View();
  });
}

function syncInputs() {
  $("from").value = state.origin ? name(state.origin) : "";
  $("to").value = state.destination ? name(state.destination) : "";
}

function clearTrip() {
  state.origin = state.destination = null;
  syncInputs();
  plan();
  if (!state.userView) state.targetView = new View();
}

function renderStatus() {
  const status = $("status");
  if (state.planAt) {
    status.dataset.state = "planned";
    $("status-text").textContent = `Planning for ${formatDateTime(state.planAt)}`;
  } else if (state.live) {
    status.dataset.state = "live";
    $("status-text").textContent = `Live · MBTA alerts checked ${formatTime(state.liveCheckedAt)}`;
  } else {
    status.dataset.state = "snapshot";
    const when = state.publishedAt ? ` from ${formatTime(new Date(state.publishedAt))}` : "";
    $("status-text").textContent = `Live feed unavailable · using alerts snapshot${when}`;
  }
}

function renderResult() {
  const el = $("result");
  el.replaceChildren();
  if (state.routeError) {
    el.append(notice(state.routeError, state.blocking, true));
    return;
  }
  const r = state.route;
  if (!r) return;
  const head = document.createElement("div");
  head.innerHTML = `<span class="minutes">${Math.round(r.minutes)} min</span>` +
    `<span class="summary">${r.transfers} transfer${r.transfers === 1 ? "" : "s"} · ${r.stations.length} stations</span>`;
  const legs = document.createElement("ol");
  legs.className = "legs";
  for (const leg of r.legs) {
    const [cr, cg, cb] = state.map?.lineColors.get(leg.line) ?? INK;
    const stops = leg.stations.length - 1;
    const li = document.createElement("li");
    li.className = "leg";
    li.innerHTML = `<div class="bar" style="background: rgb(${cr} ${cg} ${cb})"></div>` +
      `<div><strong>${leg.route} · ${Math.round(leg.minutes)} min</strong>` +
      `<span>${esc(name(leg.stations[0]))} → ${esc(name(leg.stations[stops]))} (${stops} stop${stops === 1 ? "" : "s"})</span></div>`;
    legs.append(li);
  }
  el.append(head, legs);
  if (isDisrupted()) {
    const extra = Math.round(r.minutes - state.normal.minutes);
    el.append(notice(`Rerouted around a service change (+${extra} min vs. normal).`, state.blocking, false));
  }
}

function notice(message, alertIds, isError) {
  const div = document.createElement("div");
  div.className = isError ? "notice error" : "notice";
  const headers = alertIds.map((id) => state.alertsById.get(id)?.header).filter(Boolean);
  div.textContent = [message, ...headers.slice(0, 1)].join(" ");
  return div;
}

function renderChanges() {
  const ids = new Set();
  for (const list of [...state.closures.stations.values(), ...state.closures.segments.values()]) list.forEach((id) => ids.add(id));
  const items = [...ids].map((id) => state.alertsById.get(id)).filter(Boolean);
  $("changes-count").textContent = `(${items.length})`;
  const ul = $("changes");
  ul.replaceChildren();
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No closures affecting trains.";
    ul.append(li);
  }
  for (const alert of items) {
    const li = document.createElement("li");
    li.textContent = alert.header;
    ul.append(li);
  }
}

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 4000);
}

// ------------------------------------------------------------------------------- map (p5.js)

function fittedView() {
  const points = state.route.stations.map((id) => {
    const s = state.map.stations.get(id);
    return [s.x, s.y];
  });
  const { width, height } = state.canvasSize;
  return new View().fitted(points, 0, 0, width, height);
}

function fitToRoute() {
  if (!state.userView) state.targetView = fittedView();
}

function zoomButton(factor) {
  const { width, height } = state.canvasSize;
  state.userView = true;
  state.targetView = null;
  state.view.zoomAt(width / 2, height / 2, factor);
}

function sketch(p) {
  let dragFrom = null;
  let hover = null;

  const rebuild = () => {
    const el = $("map");
    state.canvasSize = { width: el.clientWidth, height: el.clientHeight };
    state.map = buildMap(state.network, 0, 0, el.clientWidth, el.clientHeight);
    state.view = new View();
    state.targetView = state.route && !state.userView ? fittedView() : null;
  };

  p.setup = () => {
    const el = $("map");
    p.createCanvas(el.clientWidth, el.clientHeight);
    p.pixelDensity(Math.min(2, p.displayDensity()));
    p.textFont("Helvetica");
    rebuild();
    renderResult();
  };

  p.windowResized = () => {
    const el = $("map");
    p.resizeCanvas(el.clientWidth, el.clientHeight);
    rebuild();
  };

  p.draw = () => {
    p.background(...BG);
    if (state.targetView && !state.userView) state.view.easeToward(state.targetView);
    drawSegments(p);
    drawRoute(p);
    drawStations(p);
    hover = inside(p) ? stationAt(state.map, state.view, p.mouseX, p.mouseY) : null;
    p.cursor(hover ? p.HAND : dragFrom ? p.MOVE : p.ARROW);
    if (hover) drawTooltip(p, hover);
  };

  p.mousePressed = () => {
    dragFrom = inside(p) ? [p.mouseX, p.mouseY] : null;
  };

  p.mouseDragged = () => {
    if (!dragFrom) return;
    state.userView = true;
    state.view.panX += p.mouseX - p.pmouseX;
    state.view.panY += p.mouseY - p.pmouseY;
    return false;
  };

  p.mouseReleased = () => {
    const start = dragFrom;
    dragFrom = null;
    if (!start || Math.hypot(start[0] - p.mouseX, start[1] - p.mouseY) > 5) return;
    const id = stationAt(state.map, state.view, p.mouseX, p.mouseY, 14);
    if (id) selectStation(id);
  };

  p.mouseWheel = (event) => {
    if (!inside(p)) return true;
    state.userView = true;
    state.view.zoomAt(p.mouseX, p.mouseY, event.delta > 0 ? 0.9 : 1.1);
    return false; // don't scroll the page
  };
}

const inside = (p) => p.mouseX >= 0 && p.mouseY >= 0 && p.mouseX <= p.width && p.mouseY <= p.height;

function routeSegmentKeys() {
  const keys = new Set();
  for (const leg of state.route?.legs || []) {
    for (let i = 0; i + 1 < leg.stations.length; i++) keys.add(segmentKey(leg.line, leg.stations[i], leg.stations[i + 1]));
  }
  return keys;
}

function drawSegments(p) {
  const onRoute = routeSegmentKeys();
  p.strokeCap(p.ROUND);
  for (const seg of state.map.segments) {
    const [x1, y1] = state.view.toScreen(seg.x1, seg.y1);
    const [x2, y2] = state.view.toScreen(seg.x2, seg.y2);
    const alpha = state.route && !onRoute.has(seg.key) ? DIM : 255;
    if (state.closures.segments.has(seg.key)) {
      dashed(p, x1 + seg.ox, y1 + seg.oy, x2 + seg.ox, y2 + seg.oy, [...CLOSED, alpha]);
      continue;
    }
    p.stroke(...seg.color, alpha);
    p.strokeWeight(4);
    p.line(x1 + seg.ox, y1 + seg.oy, x2 + seg.ox, y2 + seg.oy);
  }
}

function drawRoute(p) {
  const route = state.route;
  if (!route) return;
  const toScreen = (id) => {
    const s = state.map.stations.get(id);
    return state.view.toScreen(s.x, s.y);
  };
  const points = route.stations.map(toScreen);
  p.noFill();
  p.stroke(255);
  p.strokeWeight(12);
  polyline(p, points);
  for (const leg of route.legs) {
    p.stroke(...state.map.lineColors.get(leg.line));
    p.strokeWeight(8);
    polyline(p, leg.stations.map(toScreen));
  }
  if (points.length > 1) {
    const t = (((performance.now() - state.routeStarted) / 1000) % PULSE_SECONDS) / PULSE_SECONDS;
    const [px, py] = pointAlong(points, t);
    p.noStroke();
    p.fill(255, 255, 255, 200);
    p.circle(px, py, 16 + 4 * Math.sin(performance.now() / 160));
    p.fill(...INK);
    p.circle(px, py, 8);
  }
}

function drawStations(p) {
  const onRoute = new Set(state.route?.stations || []);
  const transfers = new Set((state.route?.legs || []).slice(1).map((l) => l.stations[0]));
  for (const s of state.map.stations.values()) {
    const [x, y] = state.view.toScreen(s.x, s.y);
    const alpha = state.route && !onRoute.has(s.id) ? DIM : 255;
    const isTransfer = s.lines.length > 1;
    const selected = s.id === state.origin || s.id === state.destination;
    const size = selected ? 14 : isTransfer ? 11 : 7;
    p.stroke(...INK, alpha);
    p.strokeWeight(isTransfer ? 1.6 : 1.2);
    p.fill(255, 255, 255, alpha);
    p.circle(x, y, size);
    if (state.closures.stations.has(s.id)) {
      const d = size / 2 + 2;
      p.stroke(...CLOSED, alpha);
      p.strokeWeight(2);
      p.line(x - d, y - d, x + d, y + d);
      p.line(x - d, y + d, x + d, y - d);
    }
    if (selected) label(p, s.name, x, y, INK, 13);
    else if (state.route && transfers.has(s.id)) label(p, s.name, x, y, INK, 12);
    else if (!state.route && s.degree === 1) label(p, s.name, x, y, MUTED, 11);
    else if (!state.route && isTransfer && state.view.zoom >= 2) label(p, s.name, x, y, MUTED, 11);
    else if (state.view.zoom >= 4) label(p, s.name, x, y, MUTED, 11);
  }
}

function drawTooltip(p, id) {
  const s = state.map.stations.get(id);
  const [x, y] = state.view.toScreen(s.x, s.y);
  let text = `${s.name}  ·  ${s.lines.join(", ")}`;
  if (state.closures.stations.has(id)) text += "  ·  CLOSED";
  p.textSize(12);
  const w = p.textWidth(text) + 16;
  const tx = Math.min(x + 12, p.width - w - 4);
  p.noStroke();
  p.fill(...INK, 235);
  p.rect(tx, y - 30, w, 24, 4);
  p.fill(255);
  p.text(text, tx + 8, y - 13);
}

function label(p, text, x, y, color, size) {
  p.textSize(size);
  const w = p.textWidth(text);
  p.noStroke();
  p.fill(...BG, 210);
  p.rect(x + 8, y - 15, w + 6, 16, 3);
  p.fill(...color);
  p.text(text, x + 11, y - 3);
}

function polyline(p, points) {
  p.beginShape();
  for (const [x, y] of points) p.vertex(x, y);
  p.endShape();
}

function dashed(p, x1, y1, x2, y2, color, dash = 5) {
  p.stroke(...color);
  p.strokeWeight(3);
  const steps = Math.max(Math.floor(Math.hypot(x2 - x1, y2 - y1) / dash), 1);
  for (let i = 0; i < steps; i += 2) {
    const a = i / steps;
    const b = Math.min((i + 1) / steps, 1);
    p.line(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b);
  }
}

// ------------------------------------------------------------------------------- formatting

// Planning times are Boston wall-clock times, whatever the visitor's own time zone is.
const BOSTON = "America/New_York";
const formatTime = (d) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const formatDateTime = (d) => d.toLocaleString([], {
  timeZone: BOSTON, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
}) + " (Boston time)";

function bostonParts(date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: BOSTON, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(date);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return [get("year"), get("month"), get("day"), get("hour"), get("minute")];
}

// "2026-11-08T12:00" in Boston -> Date
function fromBostonInput(value) {
  const [y, mo, d, h, mi] = value.split(/[-T:]/).map(Number);
  const wall = Date.UTC(y, mo - 1, d, h, mi);
  let guess = wall;
  for (let i = 0; i < 2; i++) {  // converge on the offset in effect at that instant (handles DST)
    const [by, bmo, bd, bh, bmi] = bostonParts(new Date(guess));
    guess += wall - Date.UTC(by, bmo - 1, bd, bh, bmi);
  }
  return new Date(guess);
}

// Date -> "2026-11-08T12:00" as Boston wall-clock time
function toLocalInput(date) {
  const [y, mo, d, h, mi] = bostonParts(date);
  const pad = (n) => String(n).padStart(2, "0");
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}`;
}
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

main().catch((err) => {
  console.error(err);
  $("status-text").textContent = `Failed to load: ${err.message}`;
});
