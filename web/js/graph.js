// Browser port of transit/graph.py: adjacency-list graph with (station, route) nodes, transfer
// edges, heap-based Dijkstra (O(E log V)), live closures and an LRU route cache.
// Kept behaviorally identical to the Python engine; web/tests checks travel times against it.

export const RIDE = 0;
export const TRANSFER = 1;
export const TRANSFER_MINUTES = 4.0;
export const ROUTE_CACHE_SIZE = 2048;

export class StationNotFoundError extends Error {}

export class StationClosedError extends Error {
  constructor(station) {
    super(`${station} is closed`);
    this.station = station;
  }
}

export const pairKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
export const segmentKey = (line, a, b) => `${line}:${pairKey(a, b)}`;
const round2 = (x) => Math.round(x * 100) / 100;

// Binary min-heap of [distance, node]; ties break on node index, like Python's heapq on tuples.
class MinHeap {
  constructor() {
    this.items = [];
  }
  get size() {
    return this.items.length;
  }
  static less(a, b) {
    return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);
  }
  push(item) {
    const h = this.items;
    h.push(item);
    let i = h.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!MinHeap.less(h[i], h[parent])) break;
      [h[i], h[parent]] = [h[parent], h[i]];
      i = parent;
    }
  }
  pop() {
    const h = this.items;
    const top = h[0];
    const last = h.pop();
    if (h.length > 0) {
      h[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < h.length && MinHeap.less(h[l], h[m])) m = l;
        if (r < h.length && MinHeap.less(h[r], h[m])) m = r;
        if (m === i) break;
        [h[i], h[m]] = [h[m], h[i]];
        i = m;
      }
    }
    return top;
  }
}

export class TransitGraph {
  constructor(network, transferMinutes = TRANSFER_MINUTES) {
    this.transferMinutes = transferMinutes;
    this.lineOf = new Map(network.lines.map((l) => [l.id, l.group]));
    this.nodes = []; // index -> [stationId, routeId]
    this.adjacency = []; // index -> [[neighbor, minutes, kind, segmentKey|null]]
    this.stationNodes = new Map();
    this.index = new Map();

    for (const seg of network.segments) {
      const key = segmentKey(seg.line, seg.from_station, seg.to_station);
      for (const route of seg.routes) {
        const a = this.node(seg.from_station, route);
        const b = this.node(seg.to_station, route);
        this.adjacency[a].push([b, seg.minutes, RIDE, key]);
        this.adjacency[b].push([a, seg.minutes, RIDE, key]);
      }
    }
    for (const nodes of this.stationNodes.values()) {
      for (const u of nodes) {
        for (const v of nodes) {
          if (u !== v) this.adjacency[u].push([v, transferMinutes, TRANSFER, null]);
        }
      }
    }
    this.closedStations = new Set();
    this.closedSegments = new Set(); // segmentKey strings
    this.version = 0;
  }

  node(station, route) {
    const id = `${station}\u0000${route}`;
    if (!this.index.has(id)) {
      this.index.set(id, this.nodes.length);
      this.nodes.push([station, route]);
      this.adjacency.push([]);
      if (!this.stationNodes.has(station)) this.stationNodes.set(station, []);
      this.stationNodes.get(station).push(this.nodes.length - 1);
    }
    return this.index.get(id);
  }

  get edgeCount() {
    return this.adjacency.reduce((n, edges) => n + edges.length, 0) / 2;
  }

  // Closed stations are skipped by trains (no boarding or transfers); closed segments can't be ridden.
  setClosures(stations = [], segmentKeys = []) {
    const s = new Set(stations);
    const g = new Set(segmentKeys);
    if (!sameSet(s, this.closedStations) || !sameSet(g, this.closedSegments)) {
      this.closedStations = s;
      this.closedSegments = g;
      this.version += 1;
    }
  }

  shortestPath(origin, destination) {
    const found = this.findPath(origin, destination);
    return found ? this.buildRoute(origin, destination, found.minutes, found.path) : null;
  }

  findPath(origin, destination) {
    for (const station of [origin, destination]) {
      if (!this.stationNodes.has(station)) throw new StationNotFoundError(station);
      if (this.closedStations.has(station)) throw new StationClosedError(station);
    }
    if (origin === destination) return { minutes: 0, path: [] };

    const targets = new Set(this.stationNodes.get(destination));
    const { dist, prev, end } = this.dijkstra(origin, targets);
    if (end === -1) return null;
    const path = [end];
    while (prev[path[path.length - 1]] !== -1) path.push(prev[path[path.length - 1]]);
    return { minutes: dist[end], path: path.reverse() };
  }

  shortestMinutesFrom(origin) {
    const { dist } = this.dijkstra(origin, null);
    const best = new Map();
    dist.forEach((d, node) => {
      const station = this.nodes[node][0];
      if (d < (best.get(station) ?? Infinity)) best.set(station, d);
    });
    return best;
  }

  dijkstra(origin, targets) {
    const n = this.nodes.length;
    const dist = new Array(n).fill(Infinity);
    const prev = new Array(n).fill(-1);
    const heap = new MinHeap();
    for (const node of this.stationNodes.get(origin)) {
      dist[node] = 0;
      heap.push([0, node]);
    }
    while (heap.size > 0) {
      const [d, u] = heap.pop();
      if (d > dist[u]) continue; // stale entry
      if (targets && targets.has(u)) return { dist, prev, end: u };
      const station = this.nodes[u][0];
      for (const [v, minutes, kind, key] of this.adjacency[u]) {
        if (kind === TRANSFER && this.closedStations.has(station)) continue;
        if (key !== null && this.closedSegments.has(key)) continue;
        const nd = d + minutes;
        if (nd < dist[v]) {
          dist[v] = nd;
          prev[v] = u;
          heap.push([nd, v]);
        }
      }
    }
    return { dist, prev, end: -1 };
  }

  buildRoute(origin, destination, minutes, path) {
    const legs = [];
    for (let i = 0; i + 1 < path.length; i++) {
      const [sa, ra] = this.nodes[path[i]];
      const [sb, rb] = this.nodes[path[i + 1]];
      if (ra !== rb) continue; // transfer: the next ride starts a new leg
      let leg = legs[legs.length - 1];
      if (!leg || leg.route !== ra || leg.stations[leg.stations.length - 1] !== sa) {
        leg = { route: ra, line: this.lineOf.get(ra), stations: [sa], minutes: 0 };
        legs.push(leg);
      }
      leg.stations.push(sb);
      const edge = this.adjacency[path[i]].find(([v, , kind]) => v === path[i + 1] && kind === RIDE);
      leg.minutes += edge[1];
    }
    const stations = [origin];
    for (const leg of legs) {
      stations.push(...leg.stations.slice(1));
      leg.minutes = round2(leg.minutes);
    }
    return {
      origin,
      destination,
      minutes: round2(minutes),
      stations,
      legs,
      transfers: Math.max(legs.length - 1, 0),
    };
  }
}

export class RoutePlanner {
  constructor(graph, cacheSize = ROUTE_CACHE_SIZE) {
    this.graph = graph;
    this.cacheSize = cacheSize;
    this.cache = new Map(); // insertion order = recency
    this.cacheVersion = graph.version;
    this.hits = 0;
    this.misses = 0;
  }

  route(origin, destination) {
    if (this.graph.version !== this.cacheVersion) {
      this.cache.clear();
      this.cacheVersion = this.graph.version;
    }
    const key = `${origin}>${destination}`;
    let found;
    if (this.cache.has(key)) {
      found = this.cache.get(key);
      this.cache.delete(key);
      this.hits += 1;
    } else {
      found = this.graph.findPath(origin, destination);
      this.misses += 1;
    }
    this.cache.set(key, found);
    if (this.cache.size > this.cacheSize) this.cache.delete(this.cache.keys().next().value);
    return found ? this.graph.buildRoute(origin, destination, found.minutes, found.path) : null;
  }
}

function sameSet(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}
