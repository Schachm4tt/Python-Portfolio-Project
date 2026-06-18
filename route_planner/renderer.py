from datetime import timedelta

from .models import Day, Leg, TravelMode, Visit, WeeklyPlan

_MODE_LABEL = {
    TravelMode.CAR: "Car  ",
    TravelMode.TRAIN: "Train",
    TravelMode.FLIGHT: "Flight",
}

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _fmt_duration(td: timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m:02d}m"


def _fmt_time(dt) -> str:
    return dt.strftime("%H:%M")


def _render_day(day: Day, day_index: int) -> list[str]:
    lines = []
    day_name = _DAY_NAMES[day_index]
    date_str = day.date.strftime("%d %b")
    lines.append(f"{day_name.upper()}, {date_str}")
    lines.append("-" * 54)

    if day.is_empty and not day.legs:
        lines.append("  (no visits scheduled)")
        lines.append("")
        return lines

    # Interleave legs and visits in chronological order
    events: list[tuple] = []
    for leg in day.legs:
        events.append(("leg", leg.depart_at, leg))
    for visit in day.visits:
        events.append(("visit", visit.arrive_at, visit))
    events.sort(key=lambda x: x[1])

    for kind, _, obj in events:
        if kind == "leg":
            leg: Leg = obj
            mode = _MODE_LABEL[leg.mode]
            origin = leg.origin.city
            dest = leg.destination.city
            duration = _fmt_duration(leg.travel_time)
            depart = _fmt_time(leg.depart_at)
            arrive = _fmt_time(leg.arrive_at)
            lines.append(
                f"  {depart} -> {arrive}  {mode}  {origin} -> {dest}  ({duration})"
            )
        else:
            visit: Visit = obj
            client = visit.client
            arrive = _fmt_time(visit.arrive_at)
            depart = _fmt_time(visit.depart_at)
            duration = _fmt_duration(client.duration)
            priority_marker = " [PRIORITY]" if client.priority else ""
            lines.append(
                f"  {arrive} - {depart}  ON-SITE  {client.name} / {client.city}{priority_marker}  ({duration})"
            )

    if day.overnight_at:
        lines.append(f"  ** OVERNIGHT STAY in {day.overnight_at.city} **")

    travel_str = _fmt_duration(day.total_travel_time)
    lines.append(f"  Travel today: {travel_str}")
    lines.append("")
    return lines


def render(plan: WeeklyPlan) -> str:
    lines = []
    week_end = plan.week_start + __import__("datetime").timedelta(days=4)
    start_str = plan.week_start.strftime("%d %b")
    end_str = week_end.strftime("%d %b %Y")

    lines.append("=" * 54)
    lines.append(f"  WEEKLY ROUTE PLAN  |  {start_str} - {end_str}")
    lines.append(f"  Home: {plan.home.city}")
    lines.append("=" * 54)
    lines.append("")

    for i, day in enumerate(plan.days):
        lines.extend(_render_day(day, i))

    total_str = _fmt_duration(plan.total_travel_time)
    total_clients = len(plan.scheduled_clients)
    all_clients = total_clients + len(plan.unscheduled)

    lines.append("=" * 54)
    lines.append(f"  Total travel time : {total_str}")
    lines.append(f"  Clients scheduled : {total_clients} / {all_clients}")

    if plan.has_overnight:
        lines.append("  WARNING: plan contains overnight travel")

    if plan.unscheduled:
        lines.append("")
        priority_missed = [c for c in plan.unscheduled if c.priority]
        optional_missed = [c for c in plan.unscheduled if not c.priority]

        if priority_missed:
            lines.append("  UNSCHEDULED PRIORITY CLIENTS (action required):")
            for c in priority_missed:
                lines.append(f"    - {c.name} / {c.city}  ({c.duration_hours}h on-site)")

        if optional_missed:
            lines.append("  Unscheduled optional clients:")
            for c in optional_missed:
                lines.append(f"    - {c.name} / {c.city}  ({c.duration_hours}h on-site)")

    lines.append("=" * 54)
    return "\n".join(lines)
