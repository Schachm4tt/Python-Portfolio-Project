import time

from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

from .models import Client, Location

_geolocator = Nominatim(user_agent="route_planner_app", timeout=10)


def geocode_city(city: str) -> tuple[float, float]:
    """Return (lat, lon) for a city name. Raises ValueError if not found."""
    try:
        result = _geolocator.geocode(city, exactly_one=True, language="en")
    except GeocoderTimedOut:
        raise ValueError(f"Geocoding timed out for '{city}'. Check your internet connection.")
    except GeocoderUnavailable:
        raise ValueError(f"Geocoding service unavailable. Check your internet connection.")

    if result is None:
        raise ValueError(f"Could not find location for '{city}'. Check the city name in your input.")

    # Nominatim rate limit: max 1 request/second
    time.sleep(1.1)

    return result.latitude, result.longitude


def geocode_location(city: str) -> Location:
    lat, lon = geocode_city(city)
    return Location(city=city, lat=lat, lon=lon)


def geocode_clients(clients: list[Client]) -> list[Client]:
    """Geocode all clients in-place. Returns the same list with lat/lon filled in."""
    for client in clients:
        print(f"  Geocoding {client.city}...")
        client.lat, client.lon = geocode_city(client.city)
    return clients
