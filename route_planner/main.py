import sys
from datetime import date, time
from pathlib import Path

import yaml

from .geocoder import geocode_clients, geocode_location
from .models import Client, Location
from .optimizer import build_weekly_plan
from .renderer import render
from .travel import build_time_matrix


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def load_input(path: Path) -> tuple[Location, list[Client], date]:
    with open(path) as f:
        data = yaml.safe_load(f)

    home_city: str = data["home"]
    week_start = _parse_date(data["week_start"])

    clients = []
    for entry in data["clients"]:
        clients.append(Client(
            name=entry["name"],
            city=entry["city"],
            duration_hours=float(entry["duration_hours"]),
            window_start=_parse_time(entry["window_start"]),
            window_end=_parse_time(entry["window_end"]),
            priority=bool(entry["priority"]),
        ))

    return home_city, clients, week_start


def run(input_path: Path) -> None:
    print("Loading input...")
    home_city, clients, week_start = load_input(input_path)

    print(f"Geocoding {len(clients) + 1} locations...")
    home = geocode_location(home_city)
    geocode_clients(clients)

    # Build location list: home first, then clients in input order
    locations = [home] + [c.to_location() for c in clients]

    print("Computing travel time matrix...")
    matrix = build_time_matrix(locations, home)

    print("Optimizing schedule...")
    plan = build_weekly_plan(home, clients, matrix, locations, week_start)

    print()
    print(render(plan))


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "input.yaml"
    run(path)
