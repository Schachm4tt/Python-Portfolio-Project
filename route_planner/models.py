from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum


class TravelMode(Enum):
    CAR = "car"
    TRAIN = "train"
    FLIGHT = "flight"


@dataclass
class Location:
    city: str
    lat: float
    lon: float


ALL_DAYS: frozenset = frozenset(range(5))  # Mon=0 … Fri=4


@dataclass
class Client:
    name: str
    city: str
    duration_hours: float
    window_start: time
    window_end: time
    priority: bool
    lat: float = 0.0
    lon: float = 0.0
    allowed_days: frozenset = field(default_factory=lambda: frozenset(range(5)))

    @property
    def duration(self) -> timedelta:
        return timedelta(hours=self.duration_hours)

    @property
    def latest_arrival(self) -> time:
        """Latest time you can arrive and still complete the full visit."""
        end_minutes = self.window_end.hour * 60 + self.window_end.minute
        dur_minutes = int(self.duration_hours * 60)
        arrival_minutes = end_minutes - dur_minutes
        return time(arrival_minutes // 60, arrival_minutes % 60)

    def to_location(self) -> "Location":
        return Location(city=self.city, lat=self.lat, lon=self.lon)


@dataclass
class Leg:
    origin: Location
    destination: Location
    mode: TravelMode
    travel_time: timedelta
    depart_at: datetime
    arrive_at: datetime


@dataclass
class Visit:
    client: Client
    arrive_at: datetime
    depart_at: datetime


@dataclass
class Day:
    date: date
    legs: list[Leg] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)
    overnight_at: "Location | None" = None  # set when sleeping away from home

    @property
    def total_travel_time(self) -> timedelta:
        return sum((leg.travel_time for leg in self.legs), timedelta())

    @property
    def is_empty(self) -> bool:
        return not self.visits


@dataclass
class WeeklyPlan:
    home: Location
    week_start: date
    days: list[Day] = field(default_factory=list)
    unscheduled: list[Client] = field(default_factory=list)
    has_overnight: bool = False

    @property
    def total_travel_time(self) -> timedelta:
        return sum((day.total_travel_time for day in self.days), timedelta())

    @property
    def scheduled_clients(self) -> list[Client]:
        return [visit.client for day in self.days for visit in day.visits]
