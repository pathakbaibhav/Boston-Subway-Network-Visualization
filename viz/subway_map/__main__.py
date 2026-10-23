"""Run the live subway map.

    python -m viz.subway_map                                  # live, API at 127.0.0.1:8000
    python -m viz.subway_map --at 2026-11-08T12:00             # map as planned for that time
    python -m viz.subway_map --route Alewife "Heath Street"    # open with a route selected
    python -m viz.subway_map --route Alewife Copley --screenshot docs/map.png
"""

import argparse

from viz.subway_map.client import DEFAULT_API, ApiClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    parser.add_argument("--at", help="plan against closures scheduled for this ISO time instead of now")
    parser.add_argument("--route", nargs=2, metavar=("FROM", "TO"), help="station names or ids to preselect")
    parser.add_argument("--poll", type=float, default=5, help="seconds between live update checks")
    parser.add_argument("--size", default="1180x860", help="window size WxH")
    parser.add_argument("--density", type=int, help="pixel density (default: display density)")
    parser.add_argument("--screenshot", help="save a PNG once loaded, then exit")
    args = parser.parse_args()

    # Imported here so `--help` works without starting the JVM.
    from viz.subway_map.sketch import SubwayMap

    width, height = (int(v) for v in args.size.lower().split("x"))
    SubwayMap(ApiClient(args.api), at=args.at, poll_seconds=args.poll, size=(width, height),
              density=args.density, preselect=tuple(args.route) if args.route else None,
              screenshot=args.screenshot).run_sketch(block=True)


if __name__ == "__main__":
    main()
