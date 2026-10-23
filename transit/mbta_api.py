"""Thin client for the MBTA V3 REST API (https://api-v3.mbta.com/docs/swagger)."""

import time

import requests

from transit.config import MBTA_API_BASE, SUBWAY_ROUTE_TYPES, USER_AGENT, mbta_api_key


class MbtaApiError(RuntimeError):
    pass


def index_included(document: dict) -> dict[tuple[str, str], dict]:
    """Map (type, id) to resource for a JSON:API document's `included` section."""
    return {(r["type"], r["id"]): r for r in document.get("included", [])}


def related_id(resource: dict, name: str) -> str | None:
    data = resource.get("relationships", {}).get(name, {}).get("data")
    return data["id"] if data else None


class MbtaClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 base_url: str = MBTA_API_BASE, max_retries: int = 4, timeout: float = 20):
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/vnd.api+json"})
        if key := api_key or mbta_api_key():
            self.session.headers["x-api-key"] = key

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET a JSON:API document, retrying on rate limits (429) and server errors (5xx)."""
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise MbtaApiError(f"GET {path} failed: {exc}") from exc
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 429 and attempt < self.max_retries:
                reset = resp.headers.get("x-ratelimit-reset")
                wait = max(1.0, float(reset) - time.time()) if reset else 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            if resp.status_code >= 500 and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                raise MbtaApiError(f"GET {path} returned {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise MbtaApiError(f"GET {path} exhausted retries")

    def subway_routes(self) -> list[dict]:
        types = ",".join(map(str, SUBWAY_ROUTE_TYPES))
        return self.get("/routes", {"filter[type]": types})["data"]

    def canonical_patterns(self, route_ids: list[str]) -> list[dict]:
        params = {"filter[route]": ",".join(route_ids), "filter[canonical]": "true"}
        return self.get("/route_patterns", params)["data"]

    def trip_stops(self, trip_id: str) -> list[dict]:
        """Ordered platform stops of a trip (works for MBTA's synthetic canonical trips)."""
        doc = self.get(f"/trips/{trip_id}", {"include": "stops"})
        included = index_included(doc)
        return [included[("stop", ref["id"])] for ref in doc["data"]["relationships"]["stops"]["data"]]

    def schedules(self, route_id: str, direction_id: int, date: str,
                  min_time: str, max_time: str) -> list[dict]:
        params = {
            "filter[route]": route_id,
            "filter[direction_id]": direction_id,
            "filter[date]": date,
            "filter[min_time]": min_time,
            "filter[max_time]": max_time,
            "sort": "departure_time",
        }
        return self.get("/schedules", params)["data"]

    def subway_platforms(self) -> list[dict]:
        types = ",".join(map(str, SUBWAY_ROUTE_TYPES))
        return self.get("/stops", {"filter[route_type]": types})["data"]

    def stops_by_id(self, stop_ids: list[str]) -> list[dict]:
        return self.get("/stops", {"filter[id]": ",".join(stop_ids)})["data"]

    def subway_alerts(self) -> list[dict]:
        types = ",".join(map(str, SUBWAY_ROUTE_TYPES))
        return self.get("/alerts", {"filter[route_type]": types})["data"]
