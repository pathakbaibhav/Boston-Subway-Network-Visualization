from transit.models import Station
from transit.scraper import StationMatcher, classify_effect, parse_alerts_html

STATIONS = [
    Station("place-babck", "Babcock Street", 42.35, -71.13),
    Station("place-nsta", "North Station", 42.36, -71.06),
    Station("place-state", "State", 42.36, -71.06),
    Station("place-harsq", "Harvard", 42.37, -71.12),
    Station("place-harvd", "Harvard Avenue", 42.35, -71.13),
    Station("place-alfcl", "Alewife", 42.40, -71.14),
    Station("place-dwnxg", "Downtown Crossing", 42.36, -71.06),
    Station("place-hwsst", "Hawes Street", 42.34, -71.11),
]

# Mirrors the two alert layouts used on mbta.com/alerts/subway.
PAGE = """
<section>
  <div class="m-alerts-header"><a href="/schedules/Green"><h3 class="m-alerts-header__name">Green Line B</h3></a></div>
  <ul class="c-alert-group">
    <li class="c-alert-item c-alert-item--high js-toggle-alert c-alert-item--expandable">
      <details><summary>
        <div class="c-alert-item__top" data-test="alert_id:111">
          <div class="c-alert-item__effect">Shuttle Buses <span class="c-alert-item__badge">Upcoming</span></div>
          <div class="c-alert-item__content">No trains between North Station &amp; Babcock St. Shuttle buses replace service.</div>
        </div>
      </summary>
      <div class="c-alert-item__bottom"><div class="c-alert-item__description">
        Use the Red Line at Harvard instead.
        <div class="c-alert-item__updated">Updated: 10/19/2026 10:14 AM</div>
      </div></div></details>
    </li>
  </ul>
  <div class="m-alerts-header"><a href="/schedules/Red"><h3 class="m-alerts-header__name">Red Line</h3></a></div>
  <ul class="c-alert-group">
    <li class="c-alert-item c-alert-item--low js-toggle-alert c-alert-item--expandable">
      <details><summary>
        <div class="c-alert-item__top" data-test="alert_id:222">
          <div class="c-alert-item__effect">Downtown Crossing Elevator 869 (Alewife platform to Summer Street) <span class="c-alert-item__badge">Ongoing</span></div>
          <div class="c-alert-item__content">The elevator is closed for upgrades.</div>
        </div>
      </summary></details>
    </li>
    <div class="p-md c-alert-item c-alert-item--high" data-test="alert_id:333">
      Green Line C Branch: Trains are skipping Hawes St outbound through Nov 7.
      <div class="mt-sm">Affected direction: westbound<br/><strong>Affected stations:</strong><br/>Hawes Street
        <hr/><p>More: <a href="http://mbta.com/CBranch">MBTA.com/CBranch</a></p>
        <div class="c-alert-item__updated">Updated: 10/19/2026 9:05 AM</div>
      </div>
    </div>
  </ul>
</section>
"""

LINE_ROUTES = {"Green Line B": ["Green-B"], "Red Line": ["Red"]}


def _by_id():
    return {a.id: a for a in parse_alerts_html(PAGE, STATIONS, LINE_ROUTES)}


def test_parses_expandable_alert():
    alert = _by_id()["111"]
    assert alert.source == "web"
    assert alert.effect == "SHUTTLE"
    assert alert.lifecycle == "UPCOMING"
    assert alert.routes == ["Green-B"]
    assert alert.header.startswith("No trains between North Station")
    assert alert.description == "Use the Red Line at Harvard instead."
    assert alert.updated_at == "2026-10-19T10:14:00"


def test_headline_stations_preferred_over_detour_mentions():
    # "Harvard" appears only in the detour advice, so it is not an affected station.
    assert _by_id()["111"].stations == ["place-nsta", "place-babck"]


def test_facility_alert_uses_leading_station_only():
    alert = _by_id()["222"]
    assert alert.effect == "ELEVATOR_CLOSURE"  # not STATION_CLOSURE despite "closed"
    assert alert.stations == ["place-dwnxg"]
    assert alert.routes == ["Red"]


def test_banner_alert_uses_affected_stations_block():
    alert = _by_id()["333"]
    assert alert.effect == "STATION_CLOSURE"
    assert alert.stations == ["place-hwsst"]
    assert alert.url == "http://mbta.com/CBranch"
    assert alert.updated_at == "2026-10-19T09:05:00"


def test_matcher_expands_abbreviations_and_prefers_longest_name():
    matcher = StationMatcher(STATIONS)
    assert matcher.find("Shuttles from Harvard Ave to Babcock St") == ["place-harvd", "place-babck"]


def test_matcher_ignores_lowercase_prose_and_directions():
    matcher = StationMatcher(STATIONS)
    assert matcher.find("left in a safe state") == []
    assert matcher.find("Take the Alewife platform or an Alewife-bound train") == []


def test_classify_effect_defaults_to_notice():
    assert classify_effect("Premium parking is available") == "NOTICE"
    assert classify_effect("Expect delays of 10 minutes") == "DELAY"
