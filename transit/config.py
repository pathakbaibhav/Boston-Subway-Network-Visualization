"""Project-wide paths and settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

load_dotenv(ROOT_DIR / ".env")

MBTA_API_BASE = "https://api-v3.mbta.com"
MBTA_WEB_BASE = "https://www.mbta.com"
USER_AGENT = (
    "BostonSubwayNetworkViz/0.1 "
    "(+https://github.com/pathakbaibhav/Boston-Subway-Network-Visualization)"
)

# GTFS route types: 0 = light rail (Green Line branches, Mattapan), 1 = heavy rail (Red, Orange, Blue)
SUBWAY_ROUTE_TYPES = (0, 1)

# Schedule window used to sample travel times between adjacent stations (midday, off-peak).
SCHEDULE_WINDOW = ("10:00", "14:00")

# Floor for a segment's travel time; timetables are minute-resolution, so some hops read as 0.
MIN_SEGMENT_MINUTES = 0.5

# Cost of changing trains at a station, approximating the average wait for the connecting train.
TRANSFER_MINUTES = 4.0

# Shortest routes kept in the LRU route cache.
ROUTE_CACHE_SIZE = 2048


def mbta_api_key() -> str | None:
    key = os.getenv("MBTA_API_KEY", "").strip()
    # The API works keyless at a lower rate limit; ignore the unedited .env.example placeholder.
    return key if key and key != "your-key-here" else None
