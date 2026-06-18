from datetime import timedelta

from geopy.distance import geodesic

from .models import Location, TravelMode

# km/h averages including typical stops/overhead
_SPEED = {
    TravelMode.CAR: 100,
    TravelMode.TRAIN: 100,
    TravelMode.FLIGHT: 600,
}

# Fixed overhead added on top of travel time
_OVERHEAD = {
    TravelMode.CAR: timedelta(minutes=0),
    TravelMode.TRAIN: timedelta(minutes=30),   # station time, boarding
    TravelMode.FLIGHT: timedelta(hours=2, minutes=30),  # airport, security, boarding
}

def distance_km(a: Location, b: Location) -> float:
    return geodesic((a.lat, a.lon), (b.lat, b.lon)).km


def travel_time(km: float, mode: TravelMode) -> timedelta:
    drive_hours = km / _SPEED[mode]
    return timedelta(hours=drive_hours) + _OVERHEAD[mode]


_FLIGHT_MIN_ADVANTAGE = timedelta(hours=4)


def best_leg(origin: Location, destination: Location, home: Location) -> tuple[TravelMode, timedelta]:
    """Return the fastest (mode, travel_time) for a single leg.

    Flight is only chosen if it saves at least 4 hours over the best ground alternative.
    """
    km = distance_km(origin, destination)

    ground_candidates = [
        (mode, travel_time(km, mode))
        for mode in (TravelMode.CAR, TravelMode.TRAIN)
    ]
    best_ground = min(ground_candidates, key=lambda x: x[1])

    if km >= 300:
        flight_time = travel_time(km, TravelMode.FLIGHT)
        if best_ground[1] - flight_time >= _FLIGHT_MIN_ADVANTAGE:
            return TravelMode.FLIGHT, flight_time

    return best_ground


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
