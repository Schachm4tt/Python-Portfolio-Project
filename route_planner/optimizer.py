from datetime import date, datetime, time, timedelta
from itertools import permutations

from .models import Client, Day, Leg, Location, TravelMode, Visit, WeeklyPlan
from .travel import build_car_matrix

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
        if day_date.weekday() not in client.allowed_days:
            continue

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


def _find_feasible_chain(
    candidates: list[Client],
    current_loc: Location,
    current_time: datetime,
    day_date: date,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> list[tuple[Client, datetime, TravelMode, timedelta]]:
    """Like _find_feasible but skips the home-return curfew check (for chained overnights)."""
    results = []
    cur_idx = loc_index[current_loc.city]
    for client in candidates:
        if day_date.weekday() not in client.allowed_days:
            continue
        cli_idx = loc_index[client.city]
        mode, travel = matrix[cur_idx][cli_idx]
        arrive = current_time + travel
        arrive = max(arrive, _dt(day_date, client.window_start))
        if arrive.time() > client.latest_arrival:
            continue
        depart_visit = arrive + client.duration
        if depart_visit.time() > client.window_end:
            continue
        results.append((client, arrive, mode, travel))
    return results


def _run_greedy_chain(
    day_date: date,
    candidates: list[Client],
    start_loc: Location,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
    start_time: datetime | None = None,
) -> tuple[Day, list[str], Location, datetime]:
    """
    Greedy day filler without a forced return-home leg.
    Returns (Day, scheduled_names, end_loc, end_time).
    """
    day = Day(date=day_date)
    scheduled_names: list[str] = []
    remaining = list(candidates)
    current_loc = start_loc
    current_time = start_time or _dt(day_date, DEPART_HOME)

    while True:
        feasible = _find_feasible_chain(remaining, current_loc, current_time, day_date, loc_index, matrix)
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

    return day, scheduled_names, current_loc, current_time


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
    if week_dates[day_idx].weekday() not in client.allowed_days:
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


def _simulate_day(
    day_date: date,
    clients: list[Client],
    start_loc: Location,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> "Day | None":
    """
    Simulate a day with clients visited in a fixed order from start_loc.
    Returns the Day if all constraints are satisfied, None if infeasible.
    """
    if not clients:
        return Day(date=day_date)

    day = Day(date=day_date)
    current_loc = start_loc
    current_time = _dt(day_date, DEPART_HOME)
    home_idx = loc_index[home.city]

    for client in clients:
        cur_idx = loc_index[current_loc.city]
        cli_idx = loc_index[client.city]
        mode, travel = matrix[cur_idx][cli_idx]

        arrive = current_time + travel
        arrive = max(arrive, _dt(day_date, client.window_start))

        if arrive.time() > client.latest_arrival:
            return None

        depart_visit = arrive + client.duration
        if depart_visit.time() > client.window_end:
            return None

        _, home_travel = matrix[cli_idx][home_idx]
        if (depart_visit + home_travel).time() > CURFEW:
            return None

        day.legs.append(Leg(
            origin=current_loc, destination=client.to_location(),
            mode=mode, travel_time=travel,
            depart_at=current_time, arrive_at=arrive,
        ))
        day.visits.append(Visit(client=client, arrive_at=arrive, depart_at=depart_visit))
        current_loc = client.to_location()
        current_time = depart_visit

    if current_loc.city != home.city:
        cur_idx = loc_index[current_loc.city]
        mode, travel = matrix[cur_idx][home_idx]
        day.legs.append(Leg(
            origin=current_loc, destination=home,
            mode=mode, travel_time=travel,
            depart_at=current_time, arrive_at=current_time + travel,
        ))

    return day


def _best_order(
    day: Day,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> Day:
    """Try every visit ordering for a single day, return the fastest feasible one."""
    clients = [v.client for v in day.visits]
    best = day
    for perm in permutations(clients):
        candidate = _simulate_day(day.date, list(perm), home, home, loc_index, matrix)
        if candidate and candidate.total_travel_time < best.total_travel_time:
            best = candidate
    return best


def _improve(
    plan: WeeklyPlan,
    home: Location,
    loc_index: dict[str, int],
    matrix: list[list[tuple[TravelMode, timedelta]]],
) -> WeeklyPlan:
    """
    Local search improvement over the greedy plan. Runs until no improvement is found.
    Three move types (in order of increasing complexity):
      1. Intra-day reorder  — try all visit orderings within each day
      2. Single move        — move one client from day i to day j
      3. Swap               — exchange one client between day i and day j
    Overnight days and their follow-up days (which start from a non-home city) are skipped.
    """
    def _is_improvable(day_idx: int) -> bool:
        day = plan.days[day_idx]
        if day.overnight_at:
            return False
        if day_idx > 0 and plan.days[day_idx - 1].overnight_at:
            return False  # Starts from non-home city — simulation would be wrong
        # Car days use a different matrix; don't mix them with train/flight days
        if day.legs and all(leg.mode == TravelMode.CAR for leg in day.legs):
            return False
        return True

    def _try_all_orders(clients: list[Client], day_date: date) -> "Day | None":
        best: "Day | None" = None
        for perm in permutations(clients):
            c = _simulate_day(day_date, list(perm), home, home, loc_index, matrix)
            if c and (best is None or c.total_travel_time < best.total_travel_time):
                best = c
        return best

    improved = True
    while improved:
        improved = False

        # 1. Intra-day reorder
        for i in range(5):
            if not _is_improvable(i) or len(plan.days[i].visits) <= 1:
                continue
            better = _best_order(plan.days[i], home, loc_index, matrix)
            if better.total_travel_time < plan.days[i].total_travel_time:
                plan.days[i] = better
                improved = True

        # 2. Move one client from day i to day j
        for i in range(5):
            if not _is_improvable(i):
                continue
            for j in range(5):
                if i == j or not _is_improvable(j):
                    continue
                for visit in plan.days[i].visits:
                    if plan.days[j].date.weekday() not in visit.client.allowed_days:
                        continue
                    clients_i = [v.client for v in plan.days[i].visits if v.client.name != visit.client.name]
                    clients_j = [v.client for v in plan.days[j].visits] + [visit.client]

                    new_i = _simulate_day(plan.days[i].date, clients_i, home, home, loc_index, matrix) \
                            if clients_i else Day(date=plan.days[i].date)
                    new_j = _try_all_orders(clients_j, plan.days[j].date)

                    if new_i is not None and new_j is not None:
                        old = plan.days[i].total_travel_time + plan.days[j].total_travel_time
                        new = new_i.total_travel_time + new_j.total_travel_time
                        if new < old:
                            plan.days[i] = new_i
                            plan.days[j] = new_j
                            improved = True
                            break
                if improved:
                    break
            if improved:
                break

        # 3. Swap one client between day i and day j
        if not improved:
            for i in range(5):
                if not _is_improvable(i):
                    continue
                for j in range(i + 1, 5):
                    if not _is_improvable(j):
                        continue
                    for vi in plan.days[i].visits:
                        for vj in plan.days[j].visits:
                            if plan.days[j].date.weekday() not in vi.client.allowed_days:
                                continue
                            if plan.days[i].date.weekday() not in vj.client.allowed_days:
                                continue
                            clients_i = [vj.client if v.client.name == vi.client.name else v.client
                                         for v in plan.days[i].visits]
                            clients_j = [vi.client if v.client.name == vj.client.name else v.client
                                         for v in plan.days[j].visits]

                            new_i = _try_all_orders(clients_i, plan.days[i].date)
                            new_j = _try_all_orders(clients_j, plan.days[j].date)

                            if new_i and new_j:
                                old = plan.days[i].total_travel_time + plan.days[j].total_travel_time
                                new = new_i.total_travel_time + new_j.total_travel_time
                                if new < old:
                                    plan.days[i] = new_i
                                    plan.days[j] = new_j
                                    improved = True
                                    break
                        if improved:
                            break
                    if improved:
                        break
                if improved:
                    break

    return plan


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
    car_matrix = build_car_matrix(locations)

    # Pass 1: greedy scheduling, all days start at home, no overnights.
    # Each day independently tries train/flight and car modes; best result wins.
    for day_date in week_dates:
        rem_priority = [c for c in priority_clients if c.name not in scheduled]
        rem_optional = [c for c in optional_clients if c.name not in scheduled]
        rem = rem_priority + rem_optional

        day_t, sched_t = _run_greedy(day_date, rem, home, home, loc_index, matrix)
        day_c, sched_c = _run_greedy(day_date, rem, home, home, loc_index, car_matrix)

        # Prefer more clients scheduled; break ties with less total travel time
        use_car = (
            len(sched_c) > len(sched_t) or
            (len(sched_c) == len(sched_t) and day_c.total_travel_time < day_t.total_travel_time)
        )
        if use_car:
            plan.days.append(day_c)
            scheduled.update(sched_c)
        else:
            plan.days.append(day_t)
            scheduled.update(sched_t)

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

    # Local search: improve visit ordering and cross-day assignments
    plan = _improve(plan, home, loc_index, matrix)

    for day in plan.days:
        if day.overnight_at:
            plan.has_overnight = True
        for leg in day.legs:
            if leg.arrive_at.hour >= 21 or leg.arrive_at.hour < 7:
                plan.has_overnight = True

    return plan


def build_weekly_plan_forced(
    home: Location,
    clients: list[Client],
    matrix: list[list[tuple[TravelMode, timedelta]]],
    locations: list[Location],
    week_start: date,
) -> WeeklyPlan:
    """
    Aggressive scheduler: chains overnight stays day-to-day to maximise visits
    in one week. Instead of returning home each evening, stays overnight at the
    last visited city whenever unscheduled clients remain.
    Only returns home on Friday (or once all clients are scheduled).
    """
    loc_index = {loc.city: i for i, loc in enumerate(locations)}
    priority_clients = [c for c in clients if c.priority]
    optional_clients = [c for c in clients if not c.priority]

    plan = WeeklyPlan(home=home, week_start=week_start)
    scheduled: set[str] = set()
    week_dates = [week_start + timedelta(days=i) for i in range(5)]
    current_loc = home

    for day_idx, day_date in enumerate(week_dates):
        rem_priority = [c for c in priority_clients if c.name not in scheduled]
        rem_optional = [c for c in optional_clients if c.name not in scheduled]
        rem = rem_priority + rem_optional
        is_last = day_idx == 4

        if is_last or not rem:
            # Last day or all done: run normal greedy with return home at end
            day, day_scheduled = _run_greedy(
                day_date, rem, current_loc, home, loc_index, matrix
            )
            plan.days.append(day)
            scheduled.update(day_scheduled)
            current_loc = home
        else:
            day, day_scheduled, end_loc, end_time = _run_greedy_chain(
                day_date, rem, current_loc, home, loc_index, matrix
            )
            scheduled.update(day_scheduled)

            rem_after = [c for c in priority_clients + optional_clients if c.name not in scheduled]

            if rem_after and day.visits and end_loc.city != home.city:
                # Stay overnight — tomorrow starts from here
                day.overnight_at = end_loc
                plan.has_overnight = True
                current_loc = end_loc
            else:
                # All scheduled, no visits today, or already at home — return home
                if end_loc.city != home.city:
                    i_idx = loc_index[end_loc.city]
                    j_idx = loc_index[home.city]
                    mode, travel = matrix[i_idx][j_idx]
                    day.legs.append(Leg(
                        origin=end_loc, destination=home,
                        mode=mode, travel_time=travel,
                        depart_at=end_time, arrive_at=end_time + travel,
                    ))
                current_loc = home

            plan.days.append(day)

    plan.unscheduled = [c for c in clients if c.name not in scheduled]
    plan = _improve(plan, home, loc_index, matrix)

    for day in plan.days:
        if day.overnight_at:
            plan.has_overnight = True

    return plan
