// Run with: node --test web/tests/
// Checks the browser engine against results exported from the Python engine
// (python -m scripts.export_web_fixtures) plus a few behavior tests on a tiny network.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { apiAlertFromRaw, closuresFromAlerts, isActive, mergeLiveAlerts, parseTime } from "../js/alerts.js";
import { hexToRgb, pointAlong, View } from "../js/geo.js";
import { RoutePlanner, segmentKey, StationClosedError, TransitGraph } from "../js/graph.js";

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url)));
const network = read("../../data/processed/network.json");
const fixture = read("./fixtures/engine.json");

function allPairMinutes(graph, stations) {
  const out = [];
  stations.forEach((a, i) => {
    const open = !graph.closedStations.has(a);
    const best = open ? graph.shortestMinutesFrom(a) : new Map();
    for (const b of stations.slice(i + 1)) {
      const reachable = open && !graph.closedStations.has(b) && best.has(b);
      out.push(reachable ? Math.round(best.get(b) * 100) / 100 : null);
    }
  });
  return out;
}

for (const scenario of fixture.scenarios) {
  test(`travel times match Python for all ${fixture.stations.length * (fixture.stations.length - 1) / 2} pairs (at=${scenario.at})`, () => {
    const graph = new TransitGraph(network);
    if (scenario.at) {
      const closures = closuresFromAlerts(fixture.alerts, network, new Date(scenario.at));
      graph.setClosures(closures.stations.keys(), closures.segments.keys());
    }
    const js = allPairMinutes(graph, fixture.stations);
    assert.equal(js.length, scenario.pair_minutes.length);
    js.forEach((m, i) => {
      const py = scenario.pair_minutes[i];
      if (py === null || m === null) assert.equal(m, py, `pair ${i}`);
      else assert.ok(Math.abs(m - py) < 0.011, `pair ${i}: js ${m} vs python ${py}`);
    });
  });

  test(`closures match Python (at=${scenario.at})`, () => {
    if (!scenario.at) return;
    const closures = closuresFromAlerts(fixture.alerts, network, new Date(scenario.at));
    assert.deepEqual(Object.fromEntries([...closures.stations].sort()), scenario.closed_stations);
    const segs = [...closures.segments].map(([key, ids]) => {
      const [line, pair] = key.split(":");
      return [line, ...pair.split("|"), ...ids];
    });
    const cmp = (x, y) => (JSON.stringify(x) < JSON.stringify(y) ? -1 : 1);
    assert.deepEqual(segs.sort(cmp), [...scenario.closed_segments].sort(cmp));
  });
}

test("API alerts normalize exactly like the Python pipeline", () => {
  const ids = new Set(network.stations.map((s) => s.id));
  const js = fixture.raw_api_alerts.map((raw) => apiAlertFromRaw(raw, network, ids));
  assert.deepEqual(js, fixture.normalized_api_alerts);
});

// ---------------------------------------------------------------- behavior on a tiny network

const tiny = {
  lines: [
    { id: "Red", group: "Red", color: "#DA291C" },
    { id: "Green-B", group: "Green", color: "#00843D" },
  ],
  stations: ["a", "b", "c", "d"].map((id) => ({ id, name: id.toUpperCase(), latitude: 42.36, longitude: -71.06, lines: [] })),
  segments: [
    { from_station: "a", to_station: "b", line: "Red", routes: ["Red"], minutes: 2 },
    { from_station: "b", to_station: "c", line: "Red", routes: ["Red"], minutes: 3 },
    { from_station: "b", to_station: "d", line: "Green", routes: ["Green-B"], minutes: 4 },
  ],
  platform_to_station: { 70001: "a" },
};

test("route with a transfer pays the penalty and returns legs", () => {
  const route = new TransitGraph(tiny).shortestPath("a", "d");
  assert.equal(route.minutes, 10);
  assert.deepEqual(route.stations, ["a", "b", "d"]);
  assert.deepEqual(route.legs.map((l) => [l.route, l.line, l.stations, l.minutes]), [
    ["Red", "Red", ["a", "b"], 2],
    ["Green-B", "Green", ["b", "d"], 4],
  ]);
  assert.equal(route.transfers, 1);
});

test("closed station is passed through but blocks transfers and boarding", () => {
  const graph = new TransitGraph(tiny);
  graph.setClosures(["b"], []);
  assert.deepEqual(graph.shortestPath("a", "c").stations, ["a", "b", "c"]);
  assert.equal(graph.shortestPath("a", "d"), null);
  assert.throws(() => graph.shortestPath("b", "c"), StationClosedError);
});

test("planner cache is invalidated when closures change", () => {
  const graph = new TransitGraph(tiny);
  const planner = new RoutePlanner(graph);
  assert.equal(planner.route("a", "c").minutes, 5);
  assert.equal(planner.route("a", "c").minutes, 5);
  assert.equal(planner.hits, 1);
  graph.setClosures([], [segmentKey("Red", "a", "b")]);
  assert.equal(planner.route("a", "c"), null);
});

test("alert activity follows periods, and lifecycle for scraped alerts", () => {
  const at = new Date("2026-10-24T12:00:00Z");
  assert.ok(isActive({ active_periods: [{ start: "2026-10-01T00:00:00-04:00", end: null }] }, at));
  assert.ok(!isActive({ active_periods: [{ start: "2026-11-01T00:00:00-04:00", end: null }] }, at));
  assert.ok(!isActive({ active_periods: [], lifecycle: "UPCOMING" }, at));
  assert.equal(parseTime("2026-10-24T12:00:00").toISOString(), "2026-10-24T12:00:00.000Z");
});

test("live merge keeps scraped-only alerts and drops ended API alerts", () => {
  const live = [{ id: "1", source: "api", severity: 7, stations: [], routes: ["Red"], url: null }];
  const published = [
    { id: "1", source: "api+web", stations: ["a"], routes: [], url: "http://x" },
    { id: "2", source: "web", stations: ["b"], routes: [] },
    { id: "3", source: "api", stations: ["c"], routes: [] },
  ];
  const merged = mergeLiveAlerts(live, published);
  assert.deepEqual(merged.map((a) => [a.id, a.source]), [["1", "api+web"], ["2", "web"]]);
  assert.deepEqual(merged[0].stations, ["a"]);
});

test("geometry helpers", () => {
  assert.deepEqual(hexToRgb("#DA291C"), [218, 41, 28]);
  assert.deepEqual(pointAlong([[0, 0], [10, 0], [10, 10]], 0.75), [10, 5]);
  const view = new View();
  const before = view.toBase(300, 200);
  view.zoomAt(300, 200, 2);
  assert.deepEqual(view.toBase(300, 200), before);
});
