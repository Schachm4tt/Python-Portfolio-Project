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


def build_car_matrix(locations: list[Location]) -> list[list[tuple[TravelMode, timedelta]]]:
    """All-car matrix — only valid for days where the car was taken from home.
    Every leg uses CAR; the car travels with the user for the entire day and back.
    """
    n = len(locations)
    matrix: list[list[tuple[TravelMode, timedelta]]] = [
        [(TravelMode.CAR, timedelta())] * n for _ in range(n)
    ]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            km = distance_km(locations[i], locations[j])
            matrix[i][j] = (TravelMode.CAR, travel_time(km, TravelMode.CAR))
    return matrix
