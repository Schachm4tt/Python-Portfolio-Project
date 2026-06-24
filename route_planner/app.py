import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit.components.v1 as components
from datetime import date, time, timedelta

from route_planner.geocoder import geocode_city
from route_planner.models import Client, Location, WeeklyPlan
from route_planner.optimizer import build_weekly_plan
from route_planner.travel import build_time_matrix

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _geocode(city: str) -> tuple[float, float]:
    return geocode_city(city)


def _fmt_time(dt) -> str:
    return dt.strftime("%H:%M")


def _fmt_dur(td) -> str:
    mins = int(td.total_seconds() // 60)
    h, m = divmod(mins, 60)
    return f"{h}h {m:02d}m"


# ── Calendar HTML ──────────────────────────────────────────────────────────────

_CLR = {
    "travel_out":    "#BFDBFE",  # blue-200
    "travel_return": "#E5E7EB",  # gray-200
    "priority":      "#BBF7D0",  # green-200
    "optional":      "#FEF08A",  # yellow-200
    "overnight":     "#FED7AA",  # orange-200
}


def _card(time_str: str, label: str, title: str, subtitle: str, color: str) -> str:
    sub = f'<div style="color:#6B7280;font-size:11px;margin-top:1px;">{subtitle}</div>' if subtitle else ""
    return f"""
    <div style="background:{color};border-radius:8px;padding:8px 10px;margin-bottom:5px;">
      <div style="color:#6B7280;font-size:10px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;">{time_str}</div>
      <div style="font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;margin:2px 0;color:#374151;">{label}</div>
      <div style="font-weight:600;font-size:12.5px;">{title}</div>
      {sub}
    </div>"""


def _day_column(day, name: str, home_city: str) -> str:
    date_str = day.date.strftime("%d %b")
    header = (
        f'<div style="font-weight:700;font-size:13px;text-align:center;'
        f'padding:6px 0 8px;border-bottom:2px solid #E5E7EB;margin-bottom:8px;">'
        f'{name}<br>'
        f'<span style="font-weight:400;color:#9CA3AF;font-size:11px;">{date_str}</span></div>'
    )

    if day.is_empty and not day.legs:
        return (
            f'<div style="flex:1;padding:0 5px;min-width:0;">{header}'
            f'<div style="color:#D1D5DB;text-align:center;padding:32px 0;font-size:20px;">—</div>'
            f'</div>'
        )

    events = sorted(
        [("leg",   leg.depart_at,     leg)   for leg   in day.legs]   +
        [("visit", visit.arrive_at,   visit) for visit in day.visits],
        key=lambda x: x[1],
    )

    cards = ""
    for kind, _, obj in events:
        if kind == "leg":
            is_return = obj.destination.city == home_city
            color = _CLR["travel_return"] if is_return else _CLR["travel_out"]
            cards += _card(
                f"{_fmt_time(obj.depart_at)} → {_fmt_time(obj.arrive_at)}",
                obj.mode.value,
                f"{obj.origin.city} → {obj.destination.city}",
                _fmt_dur(obj.travel_time),
                color,
            )
        else:
            color = _CLR["priority"] if obj.client.priority else _CLR["optional"]
            label = "★ Priority" if obj.client.priority else "On-site"
            cards += _card(
                f"{_fmt_time(obj.arrive_at)} – {_fmt_time(obj.depart_at)}",
                label,
                obj.client.name,
                f"{obj.client.city} · {_fmt_dur(obj.client.duration)}",
                color,
            )

    if day.overnight_at:
        cards += _card("", "Hotel", f"Overnight · {day.overnight_at.city}", "", _CLR["overnight"])

    return f'<div style="flex:1;padding:0 5px;min-width:0;">{header}{cards}</div>'


def _render_calendar(plan: WeeklyPlan) -> None:
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    cols = "".join(_day_column(plan.days[i], day_names[i], plan.home.city) for i in range(5))
    html = (
        '<div style="display:flex;gap:6px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;padding:4px 2px;">'
        + cols +
        '</div>'
    )
    components.html(html, height=640, scrolling=True)


# ── Legend ─────────────────────────────────────────────────────────────────────

def _render_legend() -> None:
    items = [
        (_CLR["travel_out"],    "Travel (outbound)"),
        (_CLR["travel_return"], "Travel (return)"),
        (_CLR["priority"],      "On-site · priority"),
        (_CLR["optional"],      "On-site · optional"),
        (_CLR["overnight"],     "Hotel overnight"),
    ]
    badges = " ".join(
        f'<span style="background:{c};border-radius:5px;padding:3px 10px;'
        f'font-size:11.5px;font-weight:500;white-space:nowrap;">{label}</span>'
        for c, label in items
    )
    components.html(
        f'<div style="display:flex;flex-wrap:wrap;gap:6px;'
        f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{badges}</div>',
        height=38,
    )


# ── Main app ──────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Route Planner", layout="wide", page_icon="🗺")

for key, val in [("clients", []), ("plan", None)]:
    if key not in st.session_state:
        st.session_state[key] = val


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Route Planner")

    st.subheader("Week")
    home_input = st.text_input("Home city", value="Berlin")

    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    default_monday = today + timedelta(days=days_to_monday)
    week_input = st.date_input("Week start (Monday)", value=default_monday)

    st.divider()
    st.subheader("Add client")

    with st.form("add_client", clear_on_submit=True):
        name  = st.text_input("Name")
        city  = st.text_input("City")
        dur   = st.slider("On-site hours", 0.5, 8.0, 2.0, 0.5)
        c1, c2 = st.columns(2)
        w_start = c1.time_input("Window from",  value=time(9, 0))
        w_end   = c2.time_input("Window until", value=time(17, 0))
        prio  = st.checkbox("Priority (must-visit)")
        added = st.form_submit_button("Add client", use_container_width=True)

        if added and name.strip() and city.strip():
            st.session_state.clients.append(Client(
                name=name.strip(), city=city.strip(),
                duration_hours=dur,
                window_start=w_start, window_end=w_end,
                priority=prio,
            ))
            st.session_state.plan = None

    if st.session_state.clients:
        st.divider()
        st.subheader(f"This week ({len(st.session_state.clients)})")
        for i, c in enumerate(st.session_state.clients):
            col_a, col_b = st.columns([5, 1])
            marker = "★ " if c.priority else ""
            col_a.markdown(f"**{marker}{c.name}** — {c.city}  \n"
                           f"<span style='font-size:11px;color:gray;'>{c.duration_hours}h &nbsp;·&nbsp; "
                           f"{c.window_start.strftime('%H:%M')}–{c.window_end.strftime('%H:%M')}</span>",
                           unsafe_allow_html=True)
            if col_b.button("✕", key=f"del_{i}"):
                st.session_state.clients.pop(i)
                st.session_state.plan = None
                st.rerun()

        if st.button("Clear all clients", use_container_width=True):
            st.session_state.clients.clear()
            st.session_state.plan = None
            st.rerun()

    st.divider()
    generate = st.button(
        "Generate Plan",
        type="primary",
        use_container_width=True,
        disabled=not st.session_state.clients,
    )


# ── Generate plan ──────────────────────────────────────────────────────────────

if generate and st.session_state.clients:
    errors: list[str] = []
    geocoded_clients: list[Client] = []

    with st.spinner("Geocoding locations…"):
        try:
            h_lat, h_lon = _geocode(home_input)
            home_loc = Location(city=home_input, lat=h_lat, lon=h_lon)
        except ValueError as e:
            errors.append(str(e))
            home_loc = None

        if home_loc:
            for c in st.session_state.clients:
                try:
                    lat, lon = _geocode(c.city)
                    geocoded_clients.append(Client(
                        name=c.name, city=c.city,
                        duration_hours=c.duration_hours,
                        window_start=c.window_start, window_end=c.window_end,
                        priority=c.priority, lat=lat, lon=lon,
                    ))
                except ValueError as e:
                    errors.append(f"{c.city}: {e}")

    for msg in errors:
        st.error(msg)

    if home_loc and geocoded_clients:
        with st.spinner("Optimizing schedule…"):
            locations = [home_loc] + [c.to_location() for c in geocoded_clients]
            matrix = build_time_matrix(locations, home_loc)
            week_start = week_input if isinstance(week_input, date) else week_input
            plan = build_weekly_plan(home_loc, geocoded_clients, matrix, locations, week_start)
            st.session_state.plan = plan


# ── Display ────────────────────────────────────────────────────────────────────

st.title("Weekly Route Plan")

if st.session_state.plan:
    plan = st.session_state.plan

    total_mins = int(plan.total_travel_time.total_seconds() // 60)
    h, m = divmod(total_mins, 60)
    n_sched = len(plan.scheduled_clients)
    n_total = n_sched + len(plan.unscheduled)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total travel time", f"{h}h {m:02d}m")
    col2.metric("Clients scheduled", f"{n_sched} / {n_total}")
    col3.metric("Overnight stays", "Yes" if plan.has_overnight else "No")

    _render_legend()
    st.divider()
    _render_calendar(plan)

    if plan.unscheduled:
        st.divider()
        prio_missed = [c for c in plan.unscheduled if c.priority]
        opt_missed  = [c for c in plan.unscheduled if not c.priority]
        if prio_missed:
            st.error("Unscheduled priority clients: " +
                     ", ".join(f"{c.name} ({c.city})" for c in prio_missed))
        if opt_missed:
            st.warning("Unscheduled optional clients: " +
                       ", ".join(f"{c.name} ({c.city})" for c in opt_missed))

elif not st.session_state.clients:
    st.info("Add clients in the sidebar, then click **Generate Plan**.")
else:
    st.info(f"{len(st.session_state.clients)} client(s) ready — click **Generate Plan**.")
