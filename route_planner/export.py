from datetime import datetime, time, timedelta

from .models import TravelMode, WeeklyPlan

_MODE_LABEL = {
    TravelMode.CAR:    "Car",
    TravelMode.TRAIN:  "Train",
    TravelMode.FLIGHT: "Flight",
}


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _dur_str(td: timedelta) -> str:
    total_mins = int(td.total_seconds() // 60)
    h, m = divmod(total_mins, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _esc(s: str) -> str:
    """Escape ICS special characters per RFC 5545."""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def plan_to_ics(plan: WeeklyPlan) -> str:
    """Convert a WeeklyPlan to an RFC 5545 iCalendar string (UTF-8, CRLF line endings)."""
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Route Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Route Plan {plan.week_start.strftime('%d %b %Y')}",
    ]

    counter = 0

    def _uid() -> str:
        nonlocal counter
        counter += 1
        return f"rp-{plan.week_start.strftime('%Y%m%d')}-{counter}@routeplanner"

    def _event(summary: str, dtstart: datetime, dtend: datetime,
               description: str = "", location: str = "") -> None:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{_uid()}",
            f"DTSTART:{_fmt(dtstart)}",
            f"DTEND:{_fmt(dtend)}",
            f"SUMMARY:{_esc(summary)}",
        ])
        if description:
            lines.append(f"DESCRIPTION:{_esc(description)}")
        if location:
            lines.append(f"LOCATION:{_esc(location)}")
        lines.append("END:VEVENT")

    for day in plan.days:
        events = sorted(
            [("leg",   obj.depart_at, obj) for obj in day.legs] +
            [("visit", obj.arrive_at, obj) for obj in day.visits],
            key=lambda x: x[1],
        )

        for kind, _, obj in events:
            if kind == "leg":
                mode = _MODE_LABEL[obj.mode]
                _event(
                    summary=f"Travel ({mode}): {obj.origin.city} -> {obj.destination.city}",
                    dtstart=obj.depart_at,
                    dtend=obj.arrive_at,
                    description=f"Mode: {mode}\nDuration: {_dur_str(obj.travel_time)}",
                )
            else:
                prio_tag = "[Priority] " if obj.client.priority else ""
                _event(
                    summary=f"{prio_tag}{obj.client.name}",
                    dtstart=obj.arrive_at,
                    dtend=obj.depart_at,
                    description=(
                        f"On-site in {obj.client.city}\n"
                        f"Duration: {_dur_str(obj.client.duration)}\n"
                        f"{'Priority' if obj.client.priority else 'Optional'} client"
                    ),
                    location=obj.client.city,
                )

        if day.overnight_at:
            candidates = [leg.arrive_at for leg in day.legs] + [v.depart_at for v in day.visits]
            overnight_start = max(candidates) if candidates else datetime.combine(day.date, time(20, 0))
            next_morning = datetime.combine(day.date + timedelta(days=1), time(7, 0))
            _event(
                summary=f"Hotel: {day.overnight_at.city}",
                dtstart=overnight_start,
                dtend=next_morning,
                description=f"Overnight stay in {day.overnight_at.city}",
                location=day.overnight_at.city,
            )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
