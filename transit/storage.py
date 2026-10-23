"""Read/write the processed network and alerts as JSON (canonical) and CSV (flat views)."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from transit.config import PROCESSED_DIR, RAW_DIR
from transit.models import Alert, Network

NETWORK_JSON = "network.json"
ALERTS_JSON = "alerts.json"


def write_network(network: Network, out_dir: Path = PROCESSED_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [_write_json(out_dir / NETWORK_JSON, network.to_dict())]
    paths.append(_write_csv(out_dir / "lines.csv", [asdict(x) for x in network.lines]))
    paths.append(_write_csv(out_dir / "stations.csv", [asdict(x) for x in network.stations]))
    paths.append(_write_csv(out_dir / "segments.csv", [asdict(x) for x in network.segments]))
    return paths


def load_network(path: Path = PROCESSED_DIR / NETWORK_JSON) -> Network:
    return Network.from_dict(json.loads(path.read_text()))


def write_alerts(alerts: list[Alert], generated_at: str, out_dir: Path = PROCESSED_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(a) for a in alerts]
    doc = {"generated_at": generated_at, "alerts": rows}
    return [_write_json(out_dir / ALERTS_JSON, doc), _write_csv(out_dir / "alerts.csv", rows)]


def load_alerts(path: Path = PROCESSED_DIR / ALERTS_JSON) -> list[Alert]:
    return [Alert(**a) for a in json.loads(path.read_text())["alerts"]]


def save_raw(name: str, content: dict | list | str, raw_dir: Path = RAW_DIR) -> Path:
    """Keep the unprocessed source response for debugging and reproducibility."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path = raw_dir / name
        path.write_text(content)
        return path
    return _write_json(raw_dir / f"{name}.json", content)


def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: _flatten(v) for k, v in row.items()} for row in rows)
    return path


def _flatten(value):
    if isinstance(value, list):
        return ";".join(json.dumps(v) if isinstance(v, dict) else str(v) for v in value)
    return value
