"""Assemble the static GitHub Pages site into _site/.

    python -m scripts.build_site            # then: python -m http.server -d _site 8080

Copies web/ (without its tests) and publishes the network snapshot plus the latest alerts from
the pipeline as data/*.json, with build metadata in data/meta.json.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from transit.config import PROCESSED_DIR, ROOT_DIR
from transit.storage import ALERTS_JSON, NETWORK_JSON

WEB_DIR = ROOT_DIR / "web"
SITE_DIR = ROOT_DIR / "_site"


def build() -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    shutil.copytree(WEB_DIR, SITE_DIR, ignore=shutil.ignore_patterns("tests", "package.json"))
    data_dir = SITE_DIR / "data"
    data_dir.mkdir()

    network = json.loads((PROCESSED_DIR / NETWORK_JSON).read_text())
    (data_dir / "network.json").write_text(json.dumps(network, separators=(",", ":")))

    alerts_path = PROCESSED_DIR / ALERTS_JSON
    alerts = json.loads(alerts_path.read_text()) if alerts_path.exists() else {"generated_at": None, "alerts": []}
    (data_dir / "alerts.json").write_text(json.dumps(alerts, separators=(",", ":")))

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alerts_generated_at": alerts["generated_at"],
        "service_date": network["service_date"],
        "commit": os.getenv("GITHUB_SHA") or _git_sha(),
    }
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (SITE_DIR / ".nojekyll").touch()  # serve files as-is
    print(f"built {SITE_DIR.relative_to(ROOT_DIR)}/ with {len(alerts['alerts'])} alerts")


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=ROOT_DIR, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


if __name__ == "__main__":
    build()
