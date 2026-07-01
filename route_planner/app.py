import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit.components.v1 as components
from datetime import date, time, timedelta

from route_planner.geocoder import geocode_city  # noqa: E402
from route_planner.models import Client, Location, WeeklyPlan  # noqa: E402
from route_planner.optimizer import build_weekly_plan, build_weekly_plan_forced  # noqa: E402
from route_planner.travel import build_time_matrix  # noqa: E402

ALL_DAYS: frozenset = frozenset(range(5))  # Mon=0 … Fri=4

# ── Constants ─────────────────────────────────────────────────────────────────

_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

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


def _days_label(allowed: frozenset) -> str:
    if allowed == ALL_DAYS:
        return "all days"
    return " · ".join(_DAY_LABELS[i] for i in sorted(allowed))


# ── Client form (shared by add and edit) ──────────────────────────────────────

def _client_form(form_key: str, submit_label: str, defaults: Client | None = None):
    """
    Renders a client form. Returns the submitted Client or None if not submitted.
    Pass defaults=None for a blank add-form, or an existing Client for edit mode.
    """
    d = defaults
    with st.form(form_key, clear_on_submit=(d is None)):
        name    = st.text_input("Name",  value=d.name  if d else "")
        city    = st.text_input("City",  value=d.city  if d else "")
        dur     = st.slider("On-site hours", 0.5, 8.0,
                            float(d.duration_hours) if d else 2.0, 0.5)
        c1, c2  = st.columns(2)
        w_start = c1.time_input("Window from",  value=d.window_start if d else time(9, 0))
        w_end   = c2.time_input("Window until", value=d.window_end   if d else time(17, 0))
        prio    = st.checkbox("Priority (must-visit)", value=d.priority if d else False)

        current_days = (
            [_DAY_LABELS[i] for i in sorted(d.allowed_days)] if d else _DAY_LABELS
        )
        selected = st.multiselect(
            "Available days", _DAY_LABELS, default=current_days,
            help="Days this client can receive a visit",
        )
        allowed = frozenset(_DAY_LABELS.index(s) for s in selected) if selected else ALL_DAYS

        col_a, col_b = st.columns([3, 1]) if d else (st, None)
        submitted = col_a.form_submit_button(submit_label, use_container_width=True,
                                             type="primary")
        cancelled = col_b.form_submit_button("Cancel", use_container_width=True) if d else False

        if cancelled:
            return "cancel"
        if submitted and name.strip() and city.strip():
            return Client(
                name=name.strip(), city=city.strip(),
                duration_hours=dur,
                window_start=w_start, window_end=w_end,
                priority=prio, allowed_days=allowed,
            )
    return None


# ── Calendar HTML ──────────────────────────────────────────────────────────────

_CLR = {
    "travel_out":    "#BFDBFE",
    "travel_return": "#E5E7EB",
    "priority":      "#BBF7D0",
    "optional":      "#FEF08A",
    "overnight":     "#FED7AA",
}


def _card(time_str: str, label: str, title: str, subtitle: str, color: str) -> str:
    sub = (f'<div style="color:#6B7280;font-size:11px;margin-top:1px;">{subtitle}</div>'
           if subtitle else "")
    return (
        f'<div style="background:{color};border-radius:8px;padding:8px 10px;margin-bottom:5px;">'
        f'<div style="color:#6B7280;font-size:10px;font-weight:600;letter-spacing:.4px;'
        f'text-transform:uppercase;">{time_str}</div>'
        f'<div style="font-weight:700;font-size:10.5px;text-transform:uppercase;'
        f'letter-spacing:.5px;margin:2px 0;color:#374151;">{label}</div>'
        f'<div style="font-weight:600;font-size:12.5px;">{title}</div>'
        f'{sub}</div>'
    )


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
        [("leg",   obj.depart_at,  obj) for obj in day.legs] +
        [("visit", obj.arrive_at,  obj) for obj in day.visits],
        key=lambda x: x[1],
    )
    cards = ""
    for kind, _, obj in events:
        if kind == "leg":
            is_return = obj.destination.city == home_city
            color = _CLR["travel_return"] if is_return else _CLR["travel_out"]
            cards += _card(
                f"{_fmt_time(obj.depart_at)} → {_fmt_time(obj.arrive_at)}",
                obj.mode.value, f"{obj.origin.city} → {obj.destination.city}",
                _fmt_dur(obj.travel_time), color,
            )
        else:
            color = _CLR["priority"] if obj.client.priority else _CLR["optional"]
            label = "★ Priority" if obj.client.priority else "On-site"
            cards += _card(
                f"{_fmt_time(obj.arrive_at)} – {_fmt_time(obj.depart_at)}",
                label, obj.client.name,
                f"{obj.client.city} · {_fmt_dur(obj.client.duration)}", color,
            )
    if day.overnight_at:
        cards += _card("", "Hotel", f"Overnight · {day.overnight_at.city}", "",
                       _CLR["overnight"])
    return f'<div style="flex:1;padding:0 5px;min-width:0;">{header}{cards}</div>'


def _render_calendar(plan: WeeklyPlan) -> None:
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    cols = "".join(_day_column(plan.days[i], day_names[i], plan.home.city) for i in range(5))
    components.html(
        '<div style="display:flex;gap:6px;font-family:-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',sans-serif;padding:4px 2px;">' + cols + '</div>',
        height=640, scrolling=True,
    )


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


# ── App setup ─────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Route Planner", layout="wide", page_icon="\U0001f5fa")

for key, val in [("clients", []), ("plan", None), ("editing_idx", None), ("force_mode", False)]:
    if key not in st.session_state:
        st.session_state[key] = val


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Route Planner")

    st.subheader("Week")
    home_input = st.text_input("Home city", value="Berlin")
    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    week_input = st.date_input("Week start (Monday)",
                               value=today + timedelta(days=days_to_monday))

    st.divider()

    # ── Add or edit client form ────────────────────────────────────────────────
    editing = st.session_state.editing_idx

    if editing is None:
        st.subheader("Add client")
        result = _client_form("add_client", "Add client")
        if isinstance(result, Client):
            st.session_state.clients.append(result)
            st.session_state.plan = None
            st.rerun()
    else:
        st.subheader(f"Edit — {st.session_state.clients[editing].name}")
        result = _client_form("edit_client", "Save changes",
                              defaults=st.session_state.clients[editing])
        if isinstance(result, Client):
            st.session_state.clients[editing] = result
            st.session_state.editing_idx = None
            st.session_state.plan = None
            st.rerun()
        elif result == "cancel":
            st.session_state.editing_idx = None
            st.rerun()

    # ── Client list ───────────────────────────────────────────────────────────
    if st.session_state.clients:
        st.divider()
        st.subheader(f"This week ({len(st.session_state.clients)})")

        for i, c in enumerate(st.session_state.clients):
            marker = "★ " if c.priority else ""
            days_str = _days_label(c.allowed_days)

            col_name, col_edit, col_del = st.columns([5, 1, 1])
            col_name.markdown(
                f"**{marker}{c.name}** — {c.city}  \n"
                f"<span style='font-size:11px;color:gray;'>"
                f"{c.duration_hours}h &nbsp;·&nbsp; "
                f"{c.window_start.strftime('%H:%M')}–{c.window_end.strftime('%H:%M')}"
                f" &nbsp;·&nbsp; {days_str}</span>",
                unsafe_allow_html=True,
            )
            if col_edit.button("✎", key=f"edit_{i}", help="Edit"):
                st.session_state.editing_idx = i
                st.rerun()
            if col_del.button("✕", key=f"del_{i}", help="Remove"):
                st.session_state.clients.pop(i)
                st.session_state.plan = None
                if st.session_state.editing_idx == i:
                    st.session_state.editing_idx = None
                st.rerun()

        if st.button("Clear all clients", use_container_width=True):
            st.session_state.clients.clear()
            st.session_state.plan = None
            st.session_state.editing_idx = None
            st.rerun()

    st.divider()
    force_mode = st.checkbox(
        "Force all clients into one week",
        help="Chains overnight stays day-to-day instead of returning home each evening. "
             "Fits more clients at the cost of more nights away from home.",
    )
    generate = st.button(
        "Generate Plan", type="primary", use_container_width=True,
        disabled=not st.session_state.clients,
    )


# ── Generate plan ──────────────────────────────────────────────────────────────

if generate and st.session_state.clients:
    errors: list[str] = []
    geocoded: list[Client] = []

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
                    geocoded.append(Client(
                        name=c.name, city=c.city,
                        duration_hours=c.duration_hours,
                        window_start=c.window_start, window_end=c.window_end,
                        priority=c.priority, allowed_days=c.allowed_days,
                        lat=lat, lon=lon,
                    ))
                except ValueError as e:
                    errors.append(f"{c.city}: {e}")

    for msg in errors:
        st.error(msg)

    if home_loc and geocoded:
        with st.spinner("Optimizing schedule…"):
            locations = [home_loc] + [c.to_location() for c in geocoded]
            matrix    = build_time_matrix(locations, home_loc)
            week_start = week_input if isinstance(week_input, date) else date.today()
            if force_mode:
                plan = build_weekly_plan_forced(home_loc, geocoded, matrix, locations, week_start)
            else:
                plan = build_weekly_plan(home_loc, geocoded, matrix, locations, week_start)
            st.session_state.plan = plan
            st.session_state.force_mode = force_mode


# ── Display ────────────────────────────────────────────────────────────────────

st.title("Weekly Route Plan")

if st.session_state.plan:
    plan = st.session_state.plan

    total_mins = int(plan.total_travel_time.total_seconds() // 60)
    h, m = divmod(total_mins, 60)
    n_sched = len(plan.scheduled_clients)
    n_total = n_sched + len(plan.unscheduled)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total travel time",  f"{h}h {m:02d}m")
    c2.metric("Clients scheduled",  f"{n_sched} / {n_total}")
    c3.metric("Overnight stays",    "Yes" if plan.has_overnight else "No")
    c4.metric("Mode", "Forced" if st.session_state.get("force_mode") else "Normal")

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
