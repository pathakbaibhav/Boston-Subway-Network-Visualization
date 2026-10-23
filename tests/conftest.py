import pytest

from transit.models import Line, Network, Segment, Station


@pytest.fixture(autouse=True)
def no_raw_snapshots(monkeypatch):
    """Keep tests from writing into data/raw."""
    monkeypatch.setattr("transit.pipeline.save_raw", lambda *a, **k: None)


@pytest.fixture
def tiny_network() -> Network:
    """Three stations on one line plus a branch station:  A - B - C, with D off B."""
    stations = [
        Station("place-a", "Alpha", 42.36, -71.06),
        Station("place-b", "Bravo Street", 42.37, -71.07),
        Station("place-c", "Charlie Square", 42.38, -71.08),
        Station("place-d", "Delta", 42.35, -71.09),
    ]
    segments = [
        Segment("place-a", "place-b", "Red", ["Red"], 2.0, "schedule", 10),
        Segment("place-b", "place-c", "Red", ["Red"], 3.0, "schedule", 10),
        Segment("place-b", "place-d", "Green", ["Green-B"], 4.0, "schedule", 10),
    ]
    lines = [Line("Red", "Red Line", "Red", "#DA291C", 1),
             Line("Green-B", "Green Line B", "Green", "#00843D", 0)]
    return Network("2026-10-26", "2026-10-24T00:00:00+00:00", lines, stations, segments,
                   {"70001": "place-a", "70002": "place-b"})
