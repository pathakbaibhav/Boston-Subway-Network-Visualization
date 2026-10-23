"""The browser port is tested against web/tests/fixtures/engine.json; make sure it's current."""

import json

from scripts.export_web_fixtures import FIXTURE, build_fixture
from transit.storage import load_network


def test_web_fixture_matches_python_engine():
    committed = json.loads(FIXTURE.read_text())
    rebuilt = build_fixture(load_network(), committed["alerts"], committed["raw_api_alerts"])
    assert rebuilt == committed, "Python engine changed: run `python -m scripts.export_web_fixtures`"


def test_fixture_covers_closures():
    planned = json.loads(FIXTURE.read_text())["scenarios"][2]
    assert planned["closed_segments"], "the planned-suspension scenario should close segments"
