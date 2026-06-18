from datetime import date, datetime, time, timedelta

from .models import Client, Day, Leg, Location, TravelMode, Visit, WeeklyPlan

DEPART_HOME = time(7, 0)
CURFEW = time(21, 0)


def _dt(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


def _find_feasible(
    candidates: list[Client],
    current_loc: Location,
    current_time: datetime,
    day_date: date,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> list[tuple[Client, datetime, TravelMode, timedelta]]:
    """Return (client, arrive_at, mode, travel_time) for every feasible next visit."""
    results = []
    cur_idx = loc_index[current_loc.city]
    home_idx = loc_index[home.city]

    for client in candidates:
        cli_idx = loc_index[client.city]
        mode, travel = matrix[cur_idx][cli_idx]

        arrive = current_time + travel
        arrive = max(arrive, _dt(day_date, client.window_start))

        if arrive.time() > client.latest_arrival:
            continue

        depart_visit = arrive + client.duration

        if depart_visit.time() > client.window_end:
            continue

        # Must be able to reach home by curfew after the visit
        _, home_travel = matrix[cli_idx][home_idx]
        if (depart_visit + home_travel).time() > CURFEW:
            continue

        results.append((client, arrive, mode, travel))

    return results


def _schedule_day(
    day_date: date,
    candidates: list[Client],
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> tuple[Day, list[str]]:
    """
    Greedily fill one working day.
    Priority clients are always preferred over optional ones.
    Returns the Day and the names of clients that were scheduled.
    """
    day = Day(date=day_date)
    scheduled_names: list[str] = []
    remaining = list(candidates)

    current_loc = home
    current_time = _dt(day_date, DEPART_HOME)

    while True:
        feasible = _find_feasible(
            remaining, current_loc, current_time, day_date, home, loc_index, matrix
        )
        if not feasible:
            break

        # Among feasible, prefer priority clients; within a tier pick earliest arrival
        priority_feasible = [f for f in feasible if f[0].priority]
        pool = priority_feasible if priority_feasible else feasible
        client, arrive, mode, travel = min(pool, key=lambda x: x[1])

        client_loc = client.to_location()
        depart_visit = arrive + client.duration

        day.legs.append(Leg(
            origin=current_loc,
            destination=client_loc,
            mode=mode,
            travel_time=travel,
            depart_at=current_time,
            arrive_at=arrive,
        ))
        day.visits.append(Visit(
            client=client,
            arrive_at=arrive,
            depart_at=depart_visit,
        ))

        current_loc = client_loc
        current_time = depart_visit
        scheduled_names.append(client.name)
        remaining = [c for c in remaining if c.name != client.name]

    # Add return leg home if we left at all
    if current_loc.city != home.city:
        i = loc_index[current_loc.city]
        j = loc_index[home.city]
        mode, travel = matrix[i][j]
        day.legs.append(Leg(
            origin=current_loc,
            destination=home,
            mode=mode,
            travel_time=travel,
            depart_at=current_time,
            arrive_at=current_time + travel,
        ))

    return day, scheduled_names


def build_weekly_plan(
    home: Location,
    clients: list[Client],
    matrix: list[list[tuple[TravelMode, timedelta]]],
    locations: list[Location],
    week_start: date,
) -> WeeklyPlan:
    loc_index = {loc.city: i for i, loc in enumerate(locations)}

    priority_clients = [c for c in clients if c.priority]
    optional_clients = [c for c in clients if not c.priority]

    plan = WeeklyPlan(home=home, week_start=week_start)
    scheduled: set[str] = set()

    week_dates = [week_start + timedelta(days=i) for i in range(5)]

    for day_date in week_dates:
        # Always put priority clients first so the greedy picks them preferentially
        remaining_priority = [c for c in priority_clients if c.name not in scheduled]
        remaining_optional = [c for c in optional_clients if c.name not in scheduled]
        candidates = remaining_priority + remaining_optional

        day, day_scheduled = _schedule_day(
            day_date, candidates, home, loc_index, matrix
        )
        plan.days.append(day)
        scheduled.update(day_scheduled)

    plan.unscheduled = [c for c in clients if c.name not in scheduled]

    for day in plan.days:
        for leg in day.legs:
            if leg.arrive_at.hour >= 21 or leg.arrive_at.hour < 7:
                plan.has_overnight = True

    return plan
