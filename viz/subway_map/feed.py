"""Polls the API for live changes; pure Python so it can be tested without py5."""

from collections.abc import Callable

from viz.subway_map.client import ApiClient, ApiUnavailableError


class LiveFeed:
    """Each poll checks /health; when the closure version changes it reloads closures, alerts and
    the selected route, and reports everything through `post(**updates)`.

    Polling the version number keeps steady-state traffic to one small request per interval.
    """

    def __init__(self, client: ApiClient, post: Callable[..., None], at: str | None = None):
        self.client = client
        self.post = post
        self.at = at
        self.version: int | None = None
        self.network_loaded = False
        self.route_pair: tuple[str, str] | None = None  # set by the sketch when a trip is selected

    def poll_once(self) -> None:
        try:
            health = self.client.health()
            if not self.network_loaded:
                self.post(network=self.client.network())
                self.network_loaded = True
            if health["version"] != self.version:
                changed = self.version is not None
                self.version = health["version"]
                self.post(closures=self.client.closures(self.at),
                          alerts={a["id"]: a for a in self.client.alerts()},
                          changed=changed, updated=health.get("alerts_updated_at"))
                if self.route_pair:
                    self.post(route=self.client.route(*self.route_pair, self.at))
            self.post(api_ok=True)
        except ApiUnavailableError as exc:
            self.post(api_ok=False, status=str(exc))
