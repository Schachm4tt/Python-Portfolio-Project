import json
import urllib.request as _urllib
from datetime import timedelta

from geopy.distance import geodesic

from .models import Location, TravelMode

# km/h averages including typical stops/overhead
_SPEED = {
    TravelMode.CAR:    100,   # Autobahn average with traffic
    TravelMode.TRAIN:  150,   # ICE/high-speed effective speed, city-centre to city-centre
    TravelMode.FLIGHT: 600,
}

# Fixed overhead added on top of travel time
_OVERHEAD = {
    TravelMode.CAR:    timedelta(minutes=0),
    TravelMode.TRAIN:  timedelta(minutes=30),          # station access + boarding
    TravelMode.FLIGHT: timedelta(hours=2, minutes=30), # airport + security + boarding
}

def distance_km(a: Location, b: Location) -> float:
    return geodesic((a.lat, a.lon), (b.lat, b.lon)).km


def travel_time(km: float, mode: TravelMode) -> timedelta:
    drive_hours = km / _SPEED[mode]
    return timedelta(hours=drive_hours) + _OVERHEAD[mode]


_FLIGHT_MIN_ADVANTAGE = timedelta(hours=4)
_GROUND_MAX_ONE_WAY   = timedelta(hours=6)   # above this, flight is used regardless of savings


def best_leg(origin: Location, destination: Location, home: Location) -> tuple[TravelMode, timedelta]:
    """Return the fastest (mode, travel_time) for a single leg — train or flight only.

    Car is never returned here; it is only available via build_car_matrix for days
    where the traveller explicitly drove from home and keeps the car all day.
    Flight is chosen when it saves ≥ 4 h over train,
    OR when train one-way exceeds 6 h (making a same-day return infeasible).
    """
    km = distance_km(origin, destination)
    train_time = travel_time(km, TravelMode.TRAIN)

    if km >= 300:
        flight_time = travel_time(km, TravelMode.FLIGHT)
        has_advantage   = train_time - flight_time >= _FLIGHT_MIN_ADVANTAGE
        ground_too_slow = train_time > _GROUND_MAX_ONE_WAY
        if has_advantage or ground_too_slow:
            return TravelMode.FLIGHT, flight_time

    return TravelMode.TRAIN, train_time


def build_time_matrix(
    locations: list[Location], home: Location
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
            matrix[i][j] = best_leg(locations[i], locations[j], home)
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
            return data["durations"]  # list[list[float | None]]
    except Exception:
        pass
    return None


def build_car_matrix(locations: list[Location]) -> list[list[tuple[TravelMode, timedelta]]]:
    """All-car matrix for days where the car was taken from home.
    Uses actual OSRM road durations; falls back to straight-line / 100 km/h per route
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
                matrix[i][j] = (TravelMode.CAR, travel_time(km, TravelMode.CAR))
    return matrix
