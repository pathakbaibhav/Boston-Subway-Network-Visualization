// Browser port of transit/closures.py plus the API-alert normalization from transit/pipeline.py,
// so the site can turn live MBTA alerts into closures without a backend.

import { segmentKey } from "./graph.js";

export const STATION_EFFECTS = new Set(["STATION_CLOSURE", "STOP_CLOSURE"]);
export const SEGMENT_EFFECTS = new Set(["SUSPENSION", "SHUTTLE", "NO_SERVICE", "SHUTDOWN"]);
export const MBTA_ALERTS_URL = "https://api-v3.mbta.com/alerts?filter%5Broute_type%5D=0,1";

// Timestamps without an offset are treated as UTC, matching transit/closures.py.
export function parseTime(value) {
  if (!value) return null;
  return new Date(/([+-]\d\d:\d\d|Z)$/.test(value) ? value : `${value}Z`);
}

export function isActive(alert, at) {
  const periods = alert.active_periods || [];
  if (periods.length) {
    return periods.some((p) => {
      const start = parseTime(p.start);
      const end = parseTime(p.end);
      return (!start || start <= at) && (!end || at < end);
    });
  }
  // Scraped-only alerts carry no periods; the page's badge says whether they've started.
  return alert.lifecycle !== "UPCOMING";
}

// Returns { stations: Map<stationId, alertIds[]>, segments: Map<segmentKey, alertIds[]> }.
export function closuresFromAlerts(alerts, network, at) {
  const stations = new Map();
  const segments = new Map();
  const add = (map, key, id) => (map.get(key) || map.set(key, []).get(key)).push(id);

  for (const alert of alerts) {
    if (!isActive(alert, at)) continue;
    if (STATION_EFFECTS.has(alert.effect)) {
      for (const station of alert.stations) add(stations, station, alert.id);
    } else if (SEGMENT_EFFECTS.has(alert.effect)) {
      const named = new Set(alert.stations);
      const routes = new Set(alert.routes);
      for (const seg of network.segments) {
        const onRoute = routes.size === 0 || seg.routes.some((r) => routes.has(r));
        if (named.has(seg.from_station) && named.has(seg.to_station) && onRoute) {
          add(segments, segmentKey(seg.line, seg.from_station, seg.to_station), alert.id);
        }
      }
    }
  }
  return { stations, segments };
}

// Normalize a raw MBTA V3 alert (JSON:API resource) into the project's Alert schema.
export function apiAlertFromRaw(raw, network, stationIds) {
  const attrs = raw.attributes;
  const routes = [];
  const stations = [];
  for (const entity of attrs.informed_entity || []) {
    if (entity.route && !routes.includes(entity.route)) routes.push(entity.route);
    if (entity.stop) {
      const station = network.platform_to_station[entity.stop] ?? entity.stop;
      if (stationIds.has(station) && !stations.includes(station)) stations.push(station);
    }
  }
  return {
    id: raw.id,
    source: "api",
    effect: attrs.effect,
    header: attrs.header,
    description: attrs.description || "",
    severity: attrs.severity ?? null,
    lifecycle: attrs.lifecycle ?? null,
    routes,
    stations,
    active_periods: (attrs.active_period || []).map((p) => ({ start: p.start ?? null, end: p.end ?? null })),
    updated_at: attrs.updated_at ?? null,
    url: attrs.url ?? null,
  };
}

// Live API alerts are authoritative; published alerts contribute what only the scraper sees.
// Published API alerts missing from the live feed have ended and are dropped.
export function mergeLiveAlerts(liveAlerts, publishedAlerts) {
  const merged = new Map(liveAlerts.map((a) => [a.id, { ...a }]));
  for (const pub of publishedAlerts) {
    const live = merged.get(pub.id);
    if (live) {
      live.source = "api+web";
      if (!live.stations.length) live.stations = pub.stations;
      if (!live.routes.length) live.routes = pub.routes;
      live.url = live.url || pub.url;
    } else if (pub.source === "web") {
      merged.set(pub.id, pub);
    }
  }
  return [...merged.values()].sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0) || (a.id < b.id ? -1 : 1));
}

export async function fetchLiveAlerts(network, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(MBTA_ALERTS_URL, { signal: controller.signal });
    if (!resp.ok) throw new Error(`MBTA API returned ${resp.status}`);
    const stationIds = new Set(network.stations.map((s) => s.id));
    return (await resp.json()).data.map((raw) => apiAlertFromRaw(raw, network, stationIds));
  } finally {
    clearTimeout(timer);
  }
}
