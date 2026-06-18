from datetime import timedelta

from geopy.distance import geodesic

from .models import Location, TravelMode

# km/h averages including typical stops/overhead
_SPEED = {
    TravelMode.CAR: 80,
    TravelMode.TRAIN: 100,
    TravelMode.FLIGHT: 600,
}

# Fixed overhead added on top of travel time
_OVERHEAD = {
    TravelMode.CAR: timedelta(minutes=0),
    TravelMode.TRAIN: timedelta(minutes=30),   # station time, boarding
    TravelMode.FLIGHT: timedelta(hours=2, minutes=30),  # airport, security, boarding
}

# Distance thresholds in km
_CAR_MAX_KM = 200
_FLIGHT_MIN_KM = 800

# Prefer own car from home up to this distance
_OWN_CAR_PREFERENCE_KM = 400


def distance_km(a: Location, b: Location) -> float:
    return geodesic((a.lat, a.lon), (b.lat, b.lon)).km


def select_mode(km: float, from_home: bool = False) -> TravelMode:
    if km <= _CAR_MAX_KM:
        return TravelMode.CAR
    if from_home and km <= _OWN_CAR_PREFERENCE_KM:
        return TravelMode.CAR
    if km >= _FLIGHT_MIN_KM:
        return TravelMode.FLIGHT
    return TravelMode.TRAIN


def travel_time(km: float, mode: TravelMode) -> timedelta:
    drive_hours = km / _SPEED[mode]
    return timedelta(hours=drive_hours) + _OVERHEAD[mode]


def best_leg(origin: Location, destination: Location, home: Location) -> tuple[TravelMode, timedelta]:
    """Return the fastest (mode, travel_time) for a single leg."""
    km = distance_km(origin, destination)
    from_home = origin.city == home.city

    preferred = select_mode(km, from_home=from_home)
    preferred_time = travel_time(km, preferred)

    # Always compare against alternatives and pick the fastest
    candidates = []
    for mode in TravelMode:
        if mode == TravelMode.FLIGHT and km < 300:
            # Flight never makes sense under 300km
            continue
        candidates.append((mode, travel_time(km, mode)))

    return min(candidates, key=lambda x: x[1])


def build_time_matrix(
    locations: list[Location], home: Location
) -> list[list[tuple[TravelMode, timedelta]]]:
    """
    Build an NxN matrix where matrix[i][j] = (mode, travel_time) from location i to j.
    Diagonal is (CAR, 0).
    """
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
