# Boston Subway Network Optimization & Visualization

A route-optimization backend and live visualization for Boston's MBTA subway network (the "T").
Stations are modeled as graph nodes and track segments as weighted edges (travel minutes); shortest
routes are computed with Dijkstra's algorithm and served over a REST API, and a Processing sketch
renders the network with color-coded lines and live route changes.

> Originally built as Homework 4 for **EECE 5642: Data Visualization** at Northeastern University
> (Spring 2024). The original assignment code is preserved in [`legacy/`](legacy/) and is being
> rebuilt into a full backend + visualization.

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo restructure, tooling, project skeleton | ✅ Done |
| 1 | Data pipeline: BeautifulSoup scraper + MBTA V3 API client, normalized JSON/CSV schema | ✅ Done |
| 2 | Graph engine: adjacency list, heap-based Dijkstra (O(E log V)), route caching, benchmarks | ✅ Done |
| 3 | REST API (FastAPI): stations, network, routes, live alerts | ⏳ Next |
| 4 | Visualization in Processing (py5): color-coded lines, live route updates | Planned |
| 5 | Documentation, measured benchmarks, cleanup of `legacy/` | Planned |

## Data Pipeline

`transit/pipeline.py` builds two datasets from two independent sources:

```
 MBTA V3 API ──────┬─► routes, canonical stop sequences ─► network topology
 (REST, JSON)      ├─► weekday schedules ─────────────────► travel minutes per segment
                   └─► alerts (structured) ──┐
                                              ├─► merged by alert id ─► alerts.json / alerts.csv
 mbta.com/alerts ──► BeautifulSoup ──────────┘
 (HTML)              free-text parsing: effect type + affected stations
```

**Network** (`data/processed/network.json`, plus `stations.csv`, `segments.csv`, `lines.csv`)
- **125 stations, 127 track segments, 8 routes** (Red, Mattapan, Orange, Blue, Green B/C/D/E).
- Topology comes from each route's canonical stop sequence. Green Line branches share trunk
  segments, so they are stored once with every route that runs over them.
- Each segment's travel time is the **mean of real scheduled trips** (10:00–14:00 on a weekday),
  typically 50–240 trips per segment. Segments with no scheduled trips (e.g. during a shutdown)
  fall back to later weekdays, then to a distance-based estimate, and are tagged
  `minutes_source: "estimated"`.
- The network is validated before writing: unknown stations, duplicate segments, non-positive
  times, out-of-area coordinates and disconnected stations all fail the build.

**Alerts** (`data/processed/alerts.json`, plus `alerts.csv`; regenerated on demand, not committed)
- The API provides structured alerts (effect, severity, affected platforms → stations).
- The public alerts page is scraped with BeautifulSoup as a second source, honoring `robots.txt`.
  Its free text is parsed into the same schema: effect type from keywords, affected stations by
  matching station names (handles abbreviations like "Babcock St", ignores direction phrases like
  "Alewife platform"). This covers alerts the API's route filter misses (elevators, escalators)
  and keeps alerts available if the API is down.
- Raw responses from both sources are kept in `data/raw/` for debugging.

Run it:

```bash
python -m transit.pipeline all        # network + alerts
python -m transit.pipeline network    # network only (optionally --date YYYY-MM-DD)
python -m transit.pipeline alerts     # refresh alerts against the existing network
```

## Graph Engine

`transit/graph.py` turns the network into a graph and answers shortest-route queries.

- **Adjacency list, route-level nodes.** Each node is a (station, route) pair, and each station's
  route nodes are joined by transfer edges costing `TRANSFER_MINUTES` (4 min, approximating the
  wait for a connecting train). Fastest routes therefore account for changing trains, and each
  route comes back as per-line legs: 155 nodes and 202 edges for the full network.
- **Dijkstra with a binary heap** (`heapq`, lazy deletion): O(E log V) per query, with early exit
  once the destination is reached. A single-source variant builds the full **all-pairs table for
  all 7,750 station pairs** in about 15 ms.
- **Live closures.** `set_closures()` marks stations as skipped (trains pass through, but no
  boarding or transfers) and segments as out of service (no riding). Phase 3 connects this to the
  live alerts.
- **LRU route cache.** `RoutePlanner` caches compact results (total minutes plus a tuple of node
  indices) instead of full route objects, and clears automatically when closures change the graph.

### Benchmarks

Measured with `python -m scripts.benchmark --write` against the original homework implementation
(a dense adjacency matrix and O(V²) Dijkstra, ported to `scripts/baseline_matrix.py`). Full results
are in **[BENCHMARKS.md](BENCHMARKS.md)**.

| | Original (matrix) | Now (adjacency list) |
|---|---|---|
| Graph memory, same information | 264.5 KB | 27.9 KB (**−89.5%**) |
| Graph memory, full route-level graph | 264.5 KB | 100.1 KB (**−62.2%**) |
| All 7,750 station pairs | 3.65 s | 0.40 s (**9×** faster) |
| Repeated queries (Zipf workload) with LRU cache | n/a | 76.9% hit rate, 2.9× faster |
| 2,000-station synthetic network: memory / query | 61.4 MB / 114 ms | 1.4 MB / 0.54 ms |

Both implementations return identical travel times on all 7,750 pairs (with the transfer penalty
set to 0, matching the original model).

## Tech Stack

- **Python 3.10+**
- **BeautifulSoup** + **requests**: data collection
- **MBTA V3 API**: live alerts and service changes
- **FastAPI** + **Uvicorn**: REST API
- **py5**: Processing for Python (needs a Java 17+ runtime; you don't write any Java)
- **pytest**: tests

## Project Structure

```
├── transit/
│   ├── config.py       # Paths and settings
│   ├── models.py       # Data schema (Line, Station, Segment, Alert, Network) + validation
│   ├── mbta_api.py     # MBTA V3 REST client with rate-limit/5xx retries
│   ├── scraper.py      # BeautifulSoup alerts scraper and free-text parsing
│   ├── storage.py      # JSON/CSV readers and writers
│   ├── pipeline.py     # Builds network + alerts (CLI entry point)
│   └── graph.py        # Adjacency-list graph, heap Dijkstra, closures, LRU route cache
├── api/                # FastAPI service
├── viz/subway_map/     # py5 (Processing) sketch
├── data/
│   ├── raw/            # Raw API/HTML responses (generated, not tracked)
│   └── processed/      # Normalized network snapshot (tracked) and alerts (not tracked)
├── scripts/
│   ├── benchmark.py    # Memory/speed/cache benchmarks → BENCHMARKS.md
│   └── baseline_matrix.py  # Original HW4 matrix Dijkstra, kept as the benchmark baseline
├── tests/              # pytest suite
├── legacy/             # Original EECE 5642 HW4 code (to be removed)
├── requirements.txt
├── pyproject.toml
└── .env.example        # Template for the MBTA API key
```

## Getting Started

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd "Boston Subway Network Visualization"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get an MBTA API key

The MBTA V3 API works without a key at a low rate limit (the pipeline waits out rate limits
automatically, so a keyless run takes about a minute); a free key raises the limit.

1. Register at <https://api-v3.mbta.com/register> and confirm your email.
2. Sign in, open the API key section of the portal, and request a new key.
3. Copy the template and paste your key into it:

   ```bash
   cp .env.example .env
   # edit .env → MBTA_API_KEY=<your key>
   ```

`.env` is git-ignored, so the key is never committed.

### 3. Build the data

```bash
python -m transit.pipeline all
```

A network snapshot is already committed, so this step is only needed to refresh it or to fetch
live alerts.

### 4. Run the tests

```bash
pytest
```

Tests run offline against fakes and fixtures; they don't call the MBTA API or mbta.com.

## License

For educational and portfolio use.
