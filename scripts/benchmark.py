"""Benchmark the adjacency-list graph engine against the original adjacency-matrix approach.

Usage:
    python -m scripts.benchmark            # print results
    python -m scripts.benchmark --write    # also write BENCHMARKS.md
"""

import argparse
import gc
import math
import platform
import random
import time
import tracemalloc
from collections import defaultdict
from datetime import date

from scripts.baseline_matrix import MatrixGraph
from transit.config import ROOT_DIR
from transit.graph import RoutePlanner, TransitGraph
from transit.models import Line, Network, Segment, Station
from transit.storage import load_network

SEED = 42
CACHE_WORKLOAD_QUERIES = 20_000
ZIPF_EXPONENT = 1.1
SCALING_SIZES = (125, 500, 1000, 2000)
SCALING_QUERIES = 30


def retained_bytes(factory):
    """Memory still allocated after building an object (tracemalloc, excludes shared inputs)."""
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    obj = factory()
    gc.collect()
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    return obj, after - before


def station_adjacency_list(network: Network) -> dict:
    """Same information as the baseline matrix, stored as an adjacency list."""
    adjacency = defaultdict(list)
    for seg in network.segments:
        adjacency[seg.from_station].append((seg.to_station, seg.minutes))
        adjacency[seg.to_station].append((seg.from_station, seg.minutes))
    return dict(adjacency)


def all_pairs(network: Network) -> list[tuple[str, str]]:
    ids = sorted(s.id for s in network.stations)
    return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - start


def synthetic_network(n: int, rng: random.Random) -> Network:
    """Connected sparse network shaped like a subway: a random tree plus a few extra links."""
    stations = [Station(f"s{i}", f"S{i}", 42.2 + rng.random() * 0.3, -71.2 + rng.random() * 0.3)
                for i in range(n)]
    segments, seen = [], set()

    def link(a, b):
        key = frozenset((a, b))
        if a != b and key not in seen:
            seen.add(key)
            segments.append(Segment(f"s{a}", f"s{b}", "L", ["L"], round(rng.uniform(1, 4), 1), "schedule"))

    for i in range(1, n):
        link(i, rng.randrange(max(0, i - 5), i))  # mostly-linear chains, like rail lines
    for _ in range(n // 20):
        link(rng.randrange(n), rng.randrange(n))
    return Network(date.today().isoformat(), "", [Line("L", "Line", "L", "#000000", 1)], stations, segments)


# --------------------------------------------------------------------------- benchmarks

def bench_memory(network: Network) -> dict:
    _, matrix = retained_bytes(lambda: MatrixGraph(network))
    _, adj = retained_bytes(lambda: station_adjacency_list(network))
    _, transit = retained_bytes(lambda: TransitGraph(network))
    return {"matrix": matrix, "adjacency_list": adj, "transit_graph": transit}


def bench_queries(network: Network) -> dict:
    pairs = all_pairs(network)
    matrix = MatrixGraph(network)
    heap_same_model = TransitGraph(network, transfer_minutes=0)  # same answers as the baseline
    heap_full = TransitGraph(network)

    _, t_matrix = timed(lambda: [matrix.shortest_path(a, b) for a, b in pairs])
    _, t_heap = timed(lambda: [heap_same_model.shortest_path(a, b) for a, b in pairs])
    _, t_full = timed(lambda: [heap_full.shortest_path(a, b) for a, b in pairs])
    table, t_all = timed(RoutePlanner(heap_full).all_pairs_minutes)

    mismatches = sum(
        1 for a, b in pairs
        if abs(matrix.shortest_path(a, b)[0] - heap_same_model.shortest_path(a, b).minutes) > 0.011
    )
    return {"pairs": len(pairs), "matrix_s": t_matrix, "heap_s": t_heap, "heap_transfers_s": t_full,
            "all_pairs_s": t_all, "all_pairs_count": len(table), "mismatches": mismatches,
            "nodes": len(heap_full.nodes), "edges": heap_full.edge_count}


def bench_cache(network: Network) -> dict:
    rng = random.Random(SEED)
    pairs = all_pairs(network)
    rng.shuffle(pairs)  # popularity rank is random, not alphabetical
    weights = [1 / (rank + 1) ** ZIPF_EXPONENT for rank in range(len(pairs))]
    workload = []
    for a, b in rng.choices(pairs, weights=weights, k=CACHE_WORKLOAD_QUERIES):
        workload.append((a, b) if rng.random() < 0.5 else (b, a))

    graph = TransitGraph(network)
    _, t_uncached = timed(lambda: [graph.shortest_path(a, b) for a, b in workload])
    planner = RoutePlanner(graph)
    _, t_cached = timed(lambda: [planner.route(a, b) for a, b in workload])

    filled, cache_bytes = retained_bytes(lambda: _filled_planner(graph, workload))
    return {"queries": len(workload), "distinct": len(set(workload)), "uncached_s": t_uncached,
            "cached_s": t_cached, **planner.cache.stats(), "cache_bytes": cache_bytes}


def _filled_planner(graph, workload):
    planner = RoutePlanner(graph)
    for a, b in workload:
        planner.route(a, b)
    return planner


def bench_scaling() -> list[dict]:
    rows = []
    for n in SCALING_SIZES:
        rng = random.Random(SEED + n)
        network = synthetic_network(n, rng)
        ids = [s.id for s in network.stations]
        queries = [tuple(rng.sample(ids, 2)) for _ in range(SCALING_QUERIES)]

        matrix, matrix_bytes = retained_bytes(lambda: MatrixGraph(network))
        graph, graph_bytes = retained_bytes(lambda: TransitGraph(network, transfer_minutes=0))
        _, t_matrix = timed(lambda: [matrix.shortest_path(a, b) for a, b in queries])
        _, t_heap = timed(lambda: [graph.shortest_path(a, b) for a, b in queries])
        rows.append({"stations": n, "segments": len(network.segments),
                     "matrix_bytes": matrix_bytes, "graph_bytes": graph_bytes,
                     "matrix_ms": t_matrix / len(queries) * 1000, "heap_ms": t_heap / len(queries) * 1000})
        del matrix, graph
    return rows


# --------------------------------------------------------------------------- report

def kb(b: int) -> str:
    return f"{b / 1024:,.1f} KB" if b < 1024 ** 2 else f"{b / 1024 ** 2:,.1f} MB"


def pct_less(new: float, old: float) -> str:
    return f"{(1 - new / old) * 100:.1f}%"


def report(mem, q, cache, scaling, network) -> str:
    us = lambda seconds, n: f"{seconds / n * 1e6:,.0f} µs"  # noqa: E731
    lines = [
        "# Benchmarks",
        "",
        f"Generated by `python -m scripts.benchmark --write` on {date.today().isoformat()} "
        f"(Python {platform.python_version()}, {platform.system()} {platform.machine()}). "
        "Timings vary by machine; memory figures are deterministic for a given Python version.",
        "",
        f"Network: **{len(network.stations)} stations, {len(network.segments)} segments** "
        f"(service date {network.service_date}). Route-level graph: {q['nodes']} nodes, {q['edges']} edges.",
        "",
        "**Baseline** = the original HW4 implementation (`scripts/baseline_matrix.py`, ported from "
        "`legacy/`): two dense V×V matrices and O(V²) Dijkstra.",
        "",
        "## 1. Graph memory",
        "",
        "Memory retained by each graph structure after construction, measured with `tracemalloc`.",
        "",
        "| Structure | Memory | vs. baseline |",
        "|---|---|---|",
        f"| Baseline: adjacency matrix + edge-index matrix | {kb(mem['matrix'])} | n/a |",
        f"| Adjacency list (same information) | {kb(mem['adjacency_list'])} | "
        f"{pct_less(mem['adjacency_list'], mem['matrix'])} less |",
        f"| `TransitGraph` (route-level nodes, transfer edges, lookups) | {kb(mem['transit_graph'])} | "
        f"{pct_less(mem['transit_graph'], mem['matrix'])} less |",
        "",
        "## 2. Shortest-path queries (all station pairs)",
        "",
        f"Every one of the **{q['pairs']:,} station pairs**, one point-to-point query each.",
        "",
        "| Implementation | Total | Per query | Speed-up |",
        "|---|---|---|---|",
        f"| Baseline O(V²) Dijkstra | {q['matrix_s']:.2f} s | {us(q['matrix_s'], q['pairs'])} | 1.0× |",
        f"| Heap Dijkstra O(E log V), same model | {q['heap_s']:.2f} s | {us(q['heap_s'], q['pairs'])} | "
        f"{q['matrix_s'] / q['heap_s']:.1f}× |",
        f"| Heap Dijkstra with transfer penalties | {q['heap_transfers_s']:.2f} s | "
        f"{us(q['heap_transfers_s'], q['pairs'])} | {q['matrix_s'] / q['heap_transfers_s']:.1f}× |",
        f"| All-pairs table (one single-source run per station) | {q['all_pairs_s']:.3f} s | n/a | n/a |",
        "",
        f"Correctness: with the transfer penalty set to 0, the heap implementation matches the "
        f"baseline on **{q['pairs'] - q['mismatches']:,} of {q['pairs']:,}** pairs.",
        "",
        "## 3. Route cache",
        "",
        f"{cache['queries']:,} queries drawn from a Zipf distribution (exponent {ZIPF_EXPONENT}) over "
        f"all station pairs, so a few popular trips dominate, as in real usage. "
        f"{cache['distinct']:,} distinct (origin, destination) queries.",
        "",
        "| | Total | Per query |",
        "|---|---|---|",
        f"| No cache | {cache['uncached_s']:.3f} s | {us(cache['uncached_s'], cache['queries'])} |",
        f"| LRU cache ({cache['maxsize']:,} routes) | {cache['cached_s']:.3f} s | "
        f"{us(cache['cached_s'], cache['queries'])} |",
        "",
        f"Hit rate **{cache['hit_rate'] * 100:.1f}%**, {cache['uncached_s'] / cache['cached_s']:.1f}× faster. "
        f"The cache trades memory for speed: when full it holds {kb(cache['cache_bytes'])}. It is "
        "cleared whenever live closures change the graph.",
        "",
        "## 4. Scaling (synthetic networks)",
        "",
        f"Random connected subway-like networks; {SCALING_QUERIES} random queries per size.",
        "",
        "| Stations | Segments | Matrix memory | Adjacency-list memory | Memory saved | "
        "Matrix query | Heap query | Speed-up |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in scaling:
        lines.append(
            f"| {r['stations']:,} | {r['segments']:,} | {kb(r['matrix_bytes'])} | {kb(r['graph_bytes'])} | "
            f"{pct_less(r['graph_bytes'], r['matrix_bytes'])} | {r['matrix_ms']:.2f} ms | "
            f"{r['heap_ms']:.3f} ms | {r['matrix_ms'] / r['heap_ms']:.0f}× |")
    lines += [
        "",
        "Matrix memory grows with V² while the adjacency list grows with V + E, so the gap widens "
        "as the network grows.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write BENCHMARKS.md")
    args = parser.parse_args()

    network = load_network()
    print("memory...", flush=True)
    mem = bench_memory(network)
    print("queries...", flush=True)
    q = bench_queries(network)
    print("cache...", flush=True)
    cache = bench_cache(network)
    print("scaling...", flush=True)
    scaling = bench_scaling()

    text = report(mem, q, cache, scaling, network)
    print(text)
    if args.write:
        (ROOT_DIR / "BENCHMARKS.md").write_text(text)
        print("wrote BENCHMARKS.md")


if __name__ == "__main__":
    main()
