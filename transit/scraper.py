"""Scrape live subway alerts from mbta.com with BeautifulSoup.

The MBTA V3 API is the structured source of truth; the public alerts page is scraped as a second,
independent source. It carries the rider-facing wording, and its free text is parsed into the same
Alert schema (affected stations, effect type) so alerts can still be produced if the API is down.
"""

import re
from datetime import datetime
from urllib import robotparser

import requests
from bs4 import BeautifulSoup, Tag

from transit.config import MBTA_WEB_BASE, USER_AGENT
from transit.models import Alert, Station

ALERTS_PATH = "/alerts/subway"

# Ordered: first match wins. Facility alerts come first because their text also says "closed".
EFFECT_KEYWORDS = [
    ("ELEVATOR_CLOSURE", ("elevator",)),
    ("ESCALATOR_CLOSURE", ("escalator",)),
    ("SHUTTLE", ("shuttle",)),
    ("SUSPENSION", ("suspension", "no trains", "suspended")),
    ("STATION_CLOSURE", ("station closure", "closed", "skipping", "not stopping", "bypass")),
    ("DELAY", ("delay", "slower", "speed restriction")),
    ("DETOUR", ("detour",)),
    ("ACCESS_ISSUE", ("access", "staircase", "stairway", "platform")),
]
FACILITY_EFFECTS = {"ELEVATOR_CLOSURE", "ESCALATOR_CLOSURE"}

# A station name followed by one of these is a direction ("Alewife platform", "Mattapan-bound"),
# not an affected station.
DIRECTION_WORDS = {"platform", "platforms", "bound", "side", "branch"}

# Abbreviations used in alert text vs. full words in official station names.
ABBREVIATIONS = {"st": "street", "sq": "square", "ave": "avenue", "rd": "road", "ctr": "center",
                 "hosp": "hospital", "univ": "university", "mt": "mount"}

_ALERT_ID = re.compile(r"alert_id:(\d+)")
_UPDATED = re.compile(r"Updated:\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)")


class ScrapeBlockedError(RuntimeError):
    pass


def fetch_alerts_page(session: requests.Session | None = None, timeout: float = 20) -> str:
    """Download the subway alerts page, honoring mbta.com's robots.txt."""
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    url = MBTA_WEB_BASE + ALERTS_PATH

    robots = robotparser.RobotFileParser()
    robots_resp = session.get(MBTA_WEB_BASE + "/robots.txt", timeout=timeout)
    robots.parse(robots_resp.text.splitlines() if robots_resp.ok else [])
    if not robots.can_fetch(session.headers["User-Agent"], url):
        raise ScrapeBlockedError(f"robots.txt disallows {url}")

    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_alerts_html(html: str, stations: list[Station] | None = None,
                      line_routes: dict[str, list[str]] | None = None) -> list[Alert]:
    """Parse alert items from the alerts page into Alert records (source="web").

    `stations` enables extracting affected stations from free text; `line_routes` maps the page's
    line headings (e.g. "Green Line D") to route ids.
    """
    soup = BeautifulSoup(html, "html.parser")
    line_routes = line_routes or {}
    matcher = StationMatcher(stations or [])
    alerts: dict[str, Alert] = {}

    for item in soup.select(".c-alert-item"):
        id_holder = item if item.has_attr("data-test") else item.select_one("[data-test^='alert_id:']")
        match = _ALERT_ID.search(id_holder.get("data-test", "")) if id_holder else None
        if not match or match.group(1) in alerts:
            continue

        line_heading = _line_heading(item)
        title, summary, description = _item_text(item)
        header = summary or title
        headline = f"{title} {summary}".strip()
        # The headline states the alert; details often mention side issues (e.g. elevators).
        effect = classify_effect(headline)
        if effect == "NOTICE":
            effect = classify_effect(description)
        updated = _UPDATED.search(item.get_text(" ", strip=True))
        badge = item.select_one(".c-alert-item__badge")
        link = item.find("a", href=True)

        if effect in FACILITY_EFFECTS:
            stations = matcher.find(title, leading_only=True) or matcher.find(summary, leading_only=True)
        elif block := _affected_stations_block(item):
            stations = matcher.find(block)
        else:  # the headline names the affected stretch; the details often list detour stations
            stations = matcher.find(headline) or matcher.find(description)

        alerts[match.group(1)] = Alert(
            id=match.group(1),
            source="web",
            effect=effect,
            header=header,
            description=description,
            lifecycle=badge.get_text(strip=True).upper() if badge else None,
            routes=list(line_routes.get(line_heading, [])) if line_heading else [],
            stations=stations,
            updated_at=_parse_updated(updated.group(1)) if updated else None,
            url=link["href"] if link else None,
        )
    return list(alerts.values())


def classify_effect(text: str) -> str:
    lowered = text.lower()
    for effect, keywords in EFFECT_KEYWORDS:
        if any(k in lowered for k in keywords):
            return effect
    return "NOTICE"


class StationMatcher:
    """Find station mentions in free text, tolerant of abbreviations like "Babcock St"."""

    def __init__(self, stations: list[Station]):
        self._patterns = []
        for s in stations:
            tokens = [word for word, _ in _tokenize(s.name)]
            if tokens:
                self._patterns.append((tokens, s.id))
        # Longest names first so "Harvard Avenue" wins over "Harvard".
        self._patterns.sort(key=lambda p: len(p[0]), reverse=True)

    def find(self, text: str, leading_only: bool = False) -> list[str]:
        """Station ids mentioned in `text`, in order of appearance.

        With `leading_only`, only a station name at the very start counts (facility alerts are
        phrased "Downtown Crossing Elevator 869 (Alewife platform to ...)").
        """
        tokenized = _tokenize(text)
        tokens = [word for word, _ in tokenized]
        used = [False] * len(tokens)
        found = []
        for pattern, station_id in self._patterns:
            n = len(pattern)
            for i in range(1 if leading_only else len(tokens) - n + 1):
                # Proper nouns only: avoids matching prose like "in a safe state" to State station.
                if (tokens[i:i + n] == pattern and tokenized[i][1]
                        and not any(used[i:i + n])):
                    used[i:i + n] = [True] * n
                    following = tokens[i + n] if i + n < len(tokens) else None
                    if following not in DIRECTION_WORDS:
                        found.append((i, station_id))
        ordered = []
        for _, station_id in sorted(found):
            if station_id not in ordered:
                ordered.append(station_id)
        return ordered


def _tokenize(text: str) -> list[tuple[str, bool]]:
    """Split into (normalized word, starts with a capital/digit) pairs."""
    text = text.replace("’", "'").replace("'", "")
    return [(ABBREVIATIONS.get(w.lower(), w.lower()), w[0].isupper() or w[0].isdigit())
            for w in re.findall(r"[A-Za-z0-9]+", text)]


def _line_heading(item: Tag) -> str | None:
    heading = item.find_previous(class_="m-alerts-header__name")
    return heading.get_text(strip=True) if heading else None


def _item_text(item: Tag) -> tuple[str, str, str]:
    """Return (title, summary, description) for either alert layout on the page."""
    effect = item.select_one(".c-alert-item__effect")
    if effect:  # expandable item: title + summary in <summary>, details below
        badge = effect.select_one(".c-alert-item__badge")
        title = effect.get_text(" ", strip=True)
        if badge:
            title = title.replace(badge.get_text(" ", strip=True), "").strip()
        summary = _text_without_updated(item.select_one(".c-alert-item__content"))
        description = _text_without_updated(item.select_one(".c-alert-item__description"))
        return title, summary, description

    # banner item: leading text node is the summary, a nested block holds the details
    details = item.find("div")
    summary = " ".join(s.strip() for s in item.find_all(string=True, recursive=False) if s.strip())
    return "", summary, _text_without_updated(details)


def _text_without_updated(node: Tag | None) -> str:
    if node is None:
        return ""
    text = node.get_text(" ", strip=True)
    return _UPDATED.sub("", text).strip()


def _affected_stations_block(item: Tag) -> str | None:
    """Text following an "Affected stations:" label, when the page lists them explicitly."""
    label = item.find("strong", string=re.compile("Affected stations", re.I))
    if not label:
        return None
    parts = []
    for sib in label.next_siblings:
        if isinstance(sib, Tag) and sib.name in ("hr", "p", "div", "strong"):
            break
        parts.append(sib.get_text(" ", strip=True) if isinstance(sib, Tag) else str(sib).strip())
    return " ".join(p for p in parts if p) or None


def _parse_updated(value: str) -> str | None:
    try:
        return datetime.strptime(" ".join(value.split()), "%m/%d/%Y %I:%M %p").isoformat()
    except ValueError:
        return None
