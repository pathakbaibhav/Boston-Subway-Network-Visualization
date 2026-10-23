"""HTTP client for the subway network REST API (see api/main.py)."""

import requests

DEFAULT_API = "http://127.0.0.1:8000"


class ApiUnavailableError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_API, timeout: float = 5,
                 session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        try:
            return self.session.get(self.base_url + path, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiUnavailableError(f"API not reachable at {self.base_url}: {exc}") from exc

    def _json(self, path: str, params: dict | None = None):
        resp = self._get(path, params)
        if resp.status_code != 200:
            raise ApiUnavailableError(f"GET {path} returned {resp.status_code}")
        return resp.json()

    def health(self) -> dict:
        return self._json("/health")

    def network(self) -> dict:
        return self._json("/network")

    def closures(self, at: str | None = None) -> dict:
        return self._json("/closures", {"at": at} if at else None)

    def alerts(self) -> list[dict]:
        return self._json("/alerts")

    def route(self, origin: str, destination: str, at: str | None = None) -> tuple[dict | None, str | None]:
        """Return (route, None) on success or (None, reason) when no route can be given."""
        params = {"from": origin, "to": destination}
        if at:
            params["at"] = at
        resp = self._get("/route", params)
        if resp.status_code == 200:
            return resp.json(), None
        detail = resp.json().get("detail")
        message = detail.get("message") if isinstance(detail, dict) else detail
        return None, message or f"route request failed ({resp.status_code})"

    def refresh_alerts(self) -> dict:
        try:
            resp = self.session.post(self.base_url + "/alerts/refresh", timeout=60)
        except requests.RequestException as exc:
            raise ApiUnavailableError(str(exc)) from exc
        return resp.json()
