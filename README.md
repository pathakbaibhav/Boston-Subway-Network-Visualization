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
| 1 | Data pipeline: BeautifulSoup scraper + MBTA V3 API client, normalized JSON/CSV schema | ⏳ Next |
| 2 | Graph engine: adjacency list, heap-based Dijkstra (O(E log V)), route caching, benchmarks | Planned |
| 3 | REST API (FastAPI): stations, network, routes, live alerts | Planned |
| 4 | Visualization in Processing (py5): color-coded lines, live route updates | Planned |
| 5 | Documentation, measured benchmarks, cleanup of `legacy/` | Planned |

## Tech Stack

- **Python 3.10+**
- **BeautifulSoup** + **requests**: data collection
- **MBTA V3 API**: live alerts and service changes
- **FastAPI** + **Uvicorn**: REST API
- **py5**: Processing for Python (needs a Java 17+ runtime; you don't write any Java)
- **pytest**: tests

## Project Structure

```
├── transit/            # Core package: data pipeline, graph model, routing
├── api/                # FastAPI service
├── viz/subway_map/     # py5 (Processing) sketch
├── data/
│   ├── raw/            # Pipeline input snapshots (generated, not tracked)
│   └── processed/      # Normalized JSON/CSV output (generated, not tracked)
├── scripts/            # Benchmarks and utility scripts
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

The MBTA V3 API works without a key at a low rate limit; a free key raises it.

1. Register at <https://api-v3.mbta.com/register> and confirm your email.
2. Sign in, open the API key section of the portal, and request a new key.
3. Copy the template and paste your key into it:

   ```bash
   cp .env.example .env
   # edit .env → MBTA_API_KEY=<your key>
   ```

`.env` is git-ignored, so the key is never committed.

### 3. Run the tests

```bash
pytest
```

## License

For educational and portfolio use.
