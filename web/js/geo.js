// Map geometry, ported from viz/subway_map/model.py: projection, zoom/pan view, parallel-line
// offsets, hit-testing and points along a route.

import { pairKey, segmentKey } from "./graph.js";

export const PARALLEL_OFFSET = 3.5;

export function hexToRgb(color) {
  const c = color.replace("#", "");
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
}

export class Projection {
  constructor(points, x, y, w, h, margin = 30) {
    const lats = points.map((p) => p[0]);
    const lons = points.map((p) => p[1]);
    const lat0 = (Math.min(...lats) + Math.max(...lats)) / 2;
    this.kx = Math.cos((lat0 * Math.PI) / 180);
    const spanX = (Math.max(...lons) - Math.min(...lons)) * this.kx || 1e-9;
    const spanY = Math.max(...lats) - Math.min(...lats) || 1e-9;
    this.scale = Math.min((w - 2 * margin) / spanX, (h - 2 * margin) / spanY);
    this.minLon = Math.min(...lons);
    this.maxLat = Math.max(...lats);
    this.offX = x + (w - spanX * this.scale) / 2;
    this.offY = y + (h - spanY * this.scale) / 2;
  }

  toBase(lat, lon) {
    return [this.offX + (lon - this.minLon) * this.kx * this.scale, this.offY + (this.maxLat - lat) * this.scale];
  }
}

export class View {
  constructor(zoom = 1, panX = 0, panY = 0) {
    this.zoom = zoom;
    this.panX = panX;
    this.panY = panY;
    this.minZoom = 0.6;
    this.maxZoom = 8;
  }

  toScreen(bx, by) {
    return [bx * this.zoom + this.panX, by * this.zoom + this.panY];
  }

  toBase(sx, sy) {
    return [(sx - this.panX) / this.zoom, (sy - this.panY) / this.zoom];
  }

  zoomAt(sx, sy, factor) {
    const [bx, by] = this.toBase(sx, sy);
    this.zoom = Math.min(Math.max(this.zoom * factor, this.minZoom), this.maxZoom);
    this.panX = sx - bx * this.zoom;
    this.panY = sy - by * this.zoom;
  }

  // A view fitting base-coordinate points into the rectangle, never zooming out past 1.
  fitted(points, x, y, w, h, padding = 60, maxZoom = 3) {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const spanX = Math.max(Math.max(...xs) - Math.min(...xs), 1);
    const spanY = Math.max(Math.max(...ys) - Math.min(...ys), 1);
    let zoom = Math.min((w - 2 * padding) / spanX, (h - 2 * padding) / spanY, maxZoom);
    zoom = Math.max(zoom, 1);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    return new View(zoom, x + w / 2 - cx * zoom, y + h / 2 - cy * zoom);
  }

  easeToward(target, rate = 0.18) {
    this.zoom += (target.zoom - this.zoom) * rate;
    this.panX += (target.panX - this.panX) * rate;
    this.panY += (target.panY - this.panY) * rate;
  }
}

// Stations and segments in base (zoom 1) coordinates for a canvas of the given size.
export function buildMap(network, x, y, w, h) {
  const projection = new Projection(network.stations.map((s) => [s.latitude, s.longitude]), x, y, w, h);
  const stations = new Map();
  for (const s of network.stations) {
    const [bx, by] = projection.toBase(s.latitude, s.longitude);
    stations.set(s.id, { id: s.id, name: s.name, lines: s.lines, x: bx, y: by, degree: 0 });
  }
  const lineColors = new Map();
  for (const line of network.lines) if (!lineColors.has(line.group)) lineColors.set(line.group, hexToRgb(line.color));

  const byPair = new Map();
  for (const seg of network.segments) {
    const key = pairKey(seg.from_station, seg.to_station);
    (byPair.get(key) || byPair.set(key, []).get(key)).push(seg);
    stations.get(seg.from_station).degree += 1;
    stations.get(seg.to_station).degree += 1;
  }
  const segments = [];
  for (const group of byPair.values()) {
    group.sort((p, q) => (p.line < q.line ? -1 : 1));
    group.forEach((seg, i) => {
      const a = stations.get(seg.from_station);
      const b = stations.get(seg.to_station);
      const [ox, oy] = perpendicularOffset(a, b, (i - (group.length - 1) / 2) * PARALLEL_OFFSET);
      segments.push({
        a: a.id, b: b.id, line: seg.line, color: lineColors.get(seg.line),
        key: segmentKey(seg.line, a.id, b.id), x1: a.x, y1: a.y, x2: b.x, y2: b.y, ox, oy,
      });
    });
  }
  return { stations, segments, lineColors };
}

export function stationAt(map, view, sx, sy, radius = 10) {
  let best = null;
  let bestD = radius;
  for (const s of map.stations.values()) {
    const [x, y] = view.toScreen(s.x, s.y);
    const d = Math.hypot(x - sx, y - sy);
    if (d <= bestD) {
      best = s.id;
      bestD = d;
    }
  }
  return best;
}

export function pointAlong(polyline, fraction) {
  if (polyline.length === 1) return polyline[0];
  const steps = polyline.slice(1).map((q, i) => Math.hypot(q[0] - polyline[i][0], q[1] - polyline[i][1]));
  let target = Math.max(0, Math.min(1, fraction)) * steps.reduce((a, b) => a + b, 0);
  for (let i = 0; i < steps.length; i++) {
    if (target <= steps[i] && steps[i] > 0) {
      const t = target / steps[i];
      const [p, q] = [polyline[i], polyline[i + 1]];
      return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
    }
    target -= steps[i];
  }
  return polyline[polyline.length - 1];
}

function perpendicularOffset(a, b, amount) {
  if (amount === 0) return [0, 0];
  const [p, q] = a.id < b.id ? [a, b] : [b, a];
  const dx = q.x - p.x;
  const dy = q.y - p.y;
  const len = Math.hypot(dx, dy) || 1;
  return [(-dy / len) * amount, (dx / len) * amount];
}
