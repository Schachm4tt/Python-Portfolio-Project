import json
import urllib.request as _urllib
from dataclasses import dataclass
from datetime import timedelta

from geopy.distance import geodesic

from .models import Location, TravelMode


@dataclass
class TravelParams:
    speed_car: int = 100            # km/h — Autobahn average with traffic
    speed_train: int = 150          # km/h — ICE/high-speed effective, city-centre to city-centre
    speed_flight: int = 600         # km/h
    overhead_car_min: int = 0       # minutes of fixed overhead on top of travel time
    overhead_train_min: int = 30    # station access + boarding
    overhead_flight_min: int = 150  # 2 h 30 m: airport + security + boarding
    flight_min_advantage_h: float = 4.0  # min hours saved over train to choose flight
    ground_max_one_way_h: float = 6.0    # train journey above this triggers flight regardless


def distance_km(a: Location, b: Location) -> float:
    return geodesic((a.lat, a.lon), (b.lat, b.lon)).km


def travel_time(km: float, mode: TravelMode, params: TravelParams | None = None) -> timedelta:
    p = params or TravelParams()
    speeds = {
        TravelMode.CAR:    p.speed_car,
        TravelMode.TRAIN:  p.speed_train,
        TravelMode.FLIGHT: p.speed_flight,
    }
    overheads = {
        TravelMode.CAR:    timedelta(minutes=p.overhead_car_min),
        TravelMode.TRAIN:  timedelta(minutes=p.overhead_train_min),
        TravelMode.FLIGHT: timedelta(minutes=p.overhead_flight_min),
    }
    return timedelta(hours=km / speeds[mode]) + overheads[mode]


def best_leg(
    origin: Location, destination: Location, home: Location,
    params: TravelParams | None = None,
) -> tuple[TravelMode, timedelta]:
    """Return the fastest (mode, travel_time) for a single leg — train or flight only.

    Car is never returned here; it is only available via build_car_matrix for days
    where the traveller explicitly drove from home and keeps the car all day.
    Flight is chosen when it saves ≥ flight_min_advantage_h over train,
    OR when train one-way exceeds ground_max_one_way_h (making a same-day return infeasible).
    """
    p = params or TravelParams()
    km = distance_km(origin, destination)
    train_time = travel_time(km, TravelMode.TRAIN, p)

    if km >= 300:
        flight_time = travel_time(km, TravelMode.FLIGHT, p)
        has_advantage   = train_time - flight_time >= timedelta(hours=p.flight_min_advantage_h)
        ground_too_slow = train_time > timedelta(hours=p.ground_max_one_way_h)
        if has_advantage or ground_too_slow:
            return TravelMode.FLIGHT, flight_time

    return TravelMode.TRAIN, train_time


def build_time_matrix(
    locations: list[Location],
    home: Location,
    params: TravelParams | None = None,
) -> list[list[tuple[TravelMode, timedelta]]]:
    """Train/flight matrix — the default for all days without a car."""
    n = len(locations)
    matrix: list[list[tuple[TravelMode, timedelta]]] = [
        [(TravelMode.CAR, timedelta())] * n for _ in range(n)
    ]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            matrix[i][j] = best_leg(locations[i], locations[j], home, params)
    return matrix


_OSRM_TABLE_URL = (
    "http://router.project-osrm.org/table/v1/driving/{coords}?annotations=duration"
)


def _fetch_osrm_durations(locations: list[Location]) -> "list[list[float | None]] | None":
    """Call the OSRM public Table API and return an N×N matrix of road durations (seconds).
    Returns None on any network or API failure so callers can fall back gracefully.
    """
    coords = ";".join(f"{loc.lon:.6f},{loc.lat:.6f}" for loc in locations)
    url = _OSRM_TABLE_URL.format(coords=coords)
    try:
        req = _urllib.Request(url, headers={"User-Agent": "RoutePlannerApp/1.0"})
        with _urllib.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") == "Ok":
            return data["durations"]
    except Exception:
        pass
    return None


def build_car_matrix(
    locations: list[Location],
    params: TravelParams | None = None,
) -> list[list[tuple[TravelMode, timedelta]]]:
    """All-car matrix for days where the car was taken from home.
    Uses actual OSRM road durations; falls back to straight-line / car speed per route
    that OSRM cannot resolve or if the API is unavailable.
    """
    n = len(locations)
    matrix: list[list[tuple[TravelMode, timedelta]]] = [
        [(TravelMode.CAR, timedelta())] * n for _ in range(n)
    ]
    osrm = _fetch_osrm_durations(locations)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if osrm and osrm[i][j] is not None:
                matrix[i][j] = (TravelMode.CAR, timedelta(seconds=osrm[i][j]))
            else:
                km = distance_km(locations[i], locations[j])
                matrix[i][j] = (TravelMode.CAR, travel_time(km, TravelMode.CAR, params))
    return matrix
