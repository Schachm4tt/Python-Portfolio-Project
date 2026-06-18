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

        _, home_travel = matrix[cli_idx][home_idx]
        if (depart_visit + home_travel).time() > CURFEW:
            continue

        results.append((client, arrive, mode, travel))

    return results


def _run_greedy(
    day_date: date,
    candidates: list[Client],
    start_loc: Location,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
    start_time: datetime | None = None,
) -> tuple[Day, list[str]]:
    """
    Greedy day filler. Starts from start_loc at start_time (default 07:00).
    Priority clients are always preferred within feasible options.
    Returns (Day, scheduled_client_names).
    """
    day = Day(date=day_date)
    scheduled_names: list[str] = []
    remaining = list(candidates)

    current_loc = start_loc
    current_time = start_time or _dt(day_date, DEPART_HOME)

    while True:
        feasible = _find_feasible(remaining, current_loc, current_time, day_date, home, loc_index, matrix)
        if not feasible:
            break

        priority_feasible = [f for f in feasible if f[0].priority]
        pool = priority_feasible if priority_feasible else feasible
        client, arrive, mode, travel = min(pool, key=lambda x: x[1])

        client_loc = client.to_location()
        depart_visit = arrive + client.duration

        day.legs.append(Leg(
            origin=current_loc, destination=client_loc,
            mode=mode, travel_time=travel,
            depart_at=current_time, arrive_at=arrive,
        ))
        day.visits.append(Visit(client=client, arrive_at=arrive, depart_at=depart_visit))

        current_loc = client_loc
        current_time = depart_visit
        scheduled_names.append(client.name)
        remaining = [c for c in remaining if c.name != client.name]

    if current_loc.city != home.city:
        i = loc_index[current_loc.city]
        j = loc_index[home.city]
        mode, travel = matrix[i][j]
        day.legs.append(Leg(
            origin=current_loc, destination=home,
            mode=mode, travel_time=travel,
            depart_at=current_time, arrive_at=current_time + travel,
        ))

    return day, scheduled_names


def _try_overnight(
    client: Client,
    day_idx: int,
    plan: WeeklyPlan,
    scheduled: set[str],
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
    week_dates: list[date],
    priority_clients: list[Client],
    optional_clients: list[Client],
) -> bool:
    """
    Try to schedule client as an overnight trip on day_idx.
    Day day_idx: travel to client, visit, stay overnight.
    Day day_idx+1: starts at the overnight city, runs normal greedy from there,
                   returns home at the end (not forced as the first leg).
    Only inserts into empty days. Returns True on success.
    """
    day = plan.days[day_idx]
    if not day.is_empty or day.overnight_at is not None or day_idx >= 4:
        return False

    day_date = week_dates[day_idx]
    client_loc = client.to_location()
    home_idx = loc_index[home.city]
    cli_idx = loc_index[client.city]

    mode, travel = matrix[home_idx][cli_idx]
    depart = _dt(day_date, DEPART_HOME)
    arrive = depart + travel
    arrive = max(arrive, _dt(day_date, client.window_start))

    if arrive.time() > client.latest_arrival:
        return False
    depart_visit = arrive + client.duration
    if depart_visit.time() > client.window_end:
        return False

    # Commit the overnight on day_idx
    day.legs.append(Leg(
        origin=home, destination=client_loc,
        mode=mode, travel_time=travel,
        depart_at=depart, arrive_at=arrive,
    ))
    day.visits.append(Visit(client=client, arrive_at=arrive, depart_at=depart_visit))
    day.overnight_at = client_loc

    # Rebuild the next day starting FROM the overnight city — no forced return first.
    # The greedy picks up any reachable clients from there, then returns home at the end.
    next_idx = day_idx + 1
    next_date = week_dates[next_idx]

    # Unschedule clients from the old next day so they can be reconsidered
    old_next = plan.days[next_idx]
    for v in old_next.visits:
        scheduled.discard(v.client.name)

    rem_priority = [c for c in priority_clients if c.name not in scheduled and c.name != client.name]
    rem_optional = [c for c in optional_clients if c.name not in scheduled]

    new_next, next_scheduled = _run_greedy(
        next_date, rem_priority + rem_optional, client_loc, home, loc_index, matrix
    )
    for name in next_scheduled:
        scheduled.add(name)

    plan.days[next_idx] = new_next
    return True


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

    # Pass 1: greedy scheduling, all days start at home, no overnights
    for day_date in week_dates:
        rem_priority = [c for c in priority_clients if c.name not in scheduled]
        rem_optional = [c for c in optional_clients if c.name not in scheduled]
        day, day_scheduled = _run_greedy(
            day_date, rem_priority + rem_optional, home, home, loc_index, matrix
        )
        plan.days.append(day)
        scheduled.update(day_scheduled)

    # Pass 2: overnight trips for priority clients that still couldn't be scheduled
    for client in [c for c in priority_clients if c.name not in scheduled]:
        placed = False

        # First: try any empty day (Mon–Thu)
        for day_idx in range(4):
            if plan.days[day_idx].is_empty:
                if _try_overnight(client, day_idx, plan, scheduled, home, loc_index, matrix,
                                  week_dates, priority_clients, optional_clients):
                    scheduled.add(client.name)
                    plan.has_overnight = True
                    placed = True
                    break

        if placed:
            continue

        # Second: steal a day occupied only by optional clients (prefer later days
        # to avoid cascading — Thursday before Wednesday, etc.)
        for day_idx in range(3, -1, -1):
            day = plan.days[day_idx]
            if day.overnight_at is not None:
                continue
            if not day.visits or any(v.client.priority for v in day.visits):
                continue

            # Release optional clients from this day
            for v in day.visits:
                scheduled.discard(v.client.name)
            plan.days[day_idx] = Day(date=week_dates[day_idx])

            if _try_overnight(client, day_idx, plan, scheduled, home, loc_index, matrix,
                              week_dates, priority_clients, optional_clients):
                scheduled.add(client.name)
                plan.has_overnight = True
                placed = True
                break

    plan.unscheduled = [c for c in clients if c.name not in scheduled]

    for day in plan.days:
        if day.overnight_at:
            plan.has_overnight = True
        for leg in day.legs:
            if leg.arrive_at.hour >= 21 or leg.arrive_at.hour < 7:
                plan.has_overnight = True

    return plan
