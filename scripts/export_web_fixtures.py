"""Export Python engine results as fixtures for the browser port's tests (web/tests).

    python -m scripts.export_web_fixtures

The fixture embeds its inputs (alerts and raw API alerts), so tests/test_web_fixtures.py can
rebuild it from them and fail if the Python engine changes without re-exporting.
"""

import json
from datetime import datetime

from transit.closures import closures_from_alerts
from transit.config import PROCESSED_DIR, RAW_DIR, ROOT_DIR
from transit.graph import RoutePlanner, TransitGraph
from transit.models import Alert, Network
from transit.pipeline import _api_alert
from transit.storage import load_network

FIXTURE = ROOT_DIR / "web" / "tests" / "fixtures" / "engine.json"
SCENARIO_TIMES = ["2026-10-24T16:00:00+00:00", "2026-11-08T17:00:00+00:00"]
RAW_ALERT_SAMPLE = 5


def build_fixture(network: Network, alerts: list[dict], raw_alerts: list[dict]) -> dict:
    stations = sorted(s.id for s in network.stations)
    alert_objs = [Alert(**a) for a in alerts]
    scenarios = [{"at": None, **_scenario(network, stations, None, [])}]
    for at in SCENARIO_TIMES:
        scenarios.append({"at": at, **_scenario(network, stations, datetime.fromisoformat(at), alert_objs)})
    return {
        "stations": stations,
        "alerts": alerts,
        "scenarios": scenarios,
        "raw_api_alerts": raw_alerts,
        "normalized_api_alerts": [_as_dict(_api_alert(r, network)) for r in raw_alerts],
    }


def _scenario(network, stations, at, alerts) -> dict:
    graph = TransitGraph(network)
    closures = closures_from_alerts(alerts, network, at) if at else None
    if closures:
        graph.set_closures(closures.stations, closures.segments)
    best = RoutePlanner(graph).all_pairs_minutes()
    minutes = [best.get((a, b)) for i, a in enumerate(stations) for b in stations[i + 1:]]
    return {
        "closed_stations": {k: v for k, v in sorted((closures.stations if closures else {}).items())},
        "closed_segments": sorted([line, *sorted(pair), *ids] for (line, pair), ids in
                                  (closures.segments if closures else {}).items()),
        "pair_minutes": minutes,
    }


def _as_dict(alert: Alert) -> dict:
    return dict(vars(alert))


def main() -> None:
    network = load_network()
    alerts = json.loads((PROCESSED_DIR / "alerts.json").read_text())["alerts"]
    raw = json.loads((RAW_DIR / "alerts_api.json").read_text())[:RAW_ALERT_SAMPLE]
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(build_fixture(network, alerts, raw), separators=(",", ":")) + "\n")
    print(f"wrote {FIXTURE.relative_to(ROOT_DIR)} ({FIXTURE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
