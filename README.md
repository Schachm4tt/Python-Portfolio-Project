# Route Planner

A weekly client visit planner for field sales and consulting work across Europe (Germany, Austria, Switzerland, Poland, Netherlands). Enter your clients, their on-site time requirements, and time window constraints — the planner finds the optimal visiting order, picks the right transport mode for each leg, and renders the result as a calendar-style weekly view.

---

## Features

- **Optimal scheduling** — greedy algorithm with post-hoc local search (intra-day reordering, cross-day moves and swaps) to minimise total travel time
- **Per-day transport mode** — automatically decides whether each day is a train/flight day or a full car day; car only available when driven from home
- **Time window constraints** — hard constraints on when each client can receive a visit (e.g. 09:00–17:00)
- **Day-of-week restrictions** — specify which weekdays a client is available (e.g. Wednesdays and Fridays only)
- **Priority clients** — mark clients as must-visit; the planner schedules them first and drops optional clients if the week runs out of capacity
- **Overnight stays** — when a destination is too far for a same-day return, the planner books a hotel night and starts the next day from that city
- **Force mode** — optional aggressive scheduling that chains overnight stays day-to-day to fit all clients into one week
- **Interactive UI** — Streamlit web app for data entry, editing, and calendar visualisation
- **CLI mode** — run directly from a YAML file for scripting or testing

---

## Requirements

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) (package manager)

Dependencies are managed via `pyproject.toml`. Key packages:

| Package | Purpose |
|---|---|
| `geopy` | Geocoding city names via OpenStreetMap Nominatim (free, no API key) |
| `pyyaml` | YAML input parsing for CLI mode |
| `streamlit` | Web UI |

---

## Installation

```bash
git clone <repo-url>
cd "Python Portfolio Project"
uv sync
```

---

## Usage

### Web UI (recommended)

```bash
uv run streamlit run route_planner/app.py
```

Opens at `http://localhost:8501`. Use `Ctrl+C` in the terminal to stop the server.

**Workflow:**
1. Set your home city and the Monday of the target week in the sidebar
2. Add clients using the form — name, city, on-site duration, time window, priority flag, and available weekdays
3. Optionally enable **Force all clients into one week** to allow chained overnight stays
4. Click **Generate Plan**
5. The calendar view shows each day's legs and visits with colour-coded cards
6. Use the **✎** button next to any client to edit and then regenerate without re-entering all data

### CLI

```bash
uv run python -m route_planner.main                        # uses route_planner/input.yaml
uv run python -m route_planner.main path/to/myweek.yaml   # custom input file
```

### Input YAML format

```yaml
home: "Frankfurt am Main"
week_start: "2026-07-06"

clients:
  - name: "Client A"
    city: "Hamburg"
    duration_hours: 2
    window_start: "09:00"
    window_end: "17:00"
    priority: true          # must-visit; false = dropped first if week is full

  - name: "Client B"
    city: "Vienna"
    duration_hours: 4
    window_start: "08:00"
    window_end: "17:00"
    priority: false
```

---

## How it works

### Travel time estimation

Travel times are estimated from straight-line (geodesic) distances — no external routing API is required.

| Mode | Speed | Fixed overhead |
|---|---|---|
| Car | 100 km/h | none |
| Train | 150 km/h | +30 min (station access + boarding) |
| Flight | 600 km/h | +2h 30m (airport + security + boarding) |

### Transport mode selection

Each day is scheduled in one of two modes:

**Train/flight day (default)**
The planner never uses a car on these days — not for legs between clients, and not for the return home. Mode per leg:
- **Train** is the default for all distances
- **Flight** is used if it saves at least 4 hours over train, or if the train journey one-way exceeds 6 hours (making a same-day return impossible)

**Car day**
Used when the traveller drives from home and keeps the car all day. Every leg — outbound, between clients, and return home — uses the car. No mode switching mid-day.

For each day, the planner tries both options and picks whichever schedules more clients. Ties are broken by less total travel time. Car days are typically chosen when multiple clients are clustered within a short driving radius of each other.

> Car is **never** available as a one-off rental for a single leg. If you flew or trained somewhere, the return is also by train or flight.

### Scheduling

**Constraints:**
- Mon–Fri only
- Depart home earliest **07:00**
- Client time windows are hard constraints (**08:00–17:00** typical)
- Return home by **21:00** (soft — hotel overnight used as last resort for priority clients)
- Priority clients are always scheduled before optional ones
- Clients can be restricted to specific weekdays (e.g. only available Wednesday and Friday)

**Algorithm — two passes + improvement:**

1. **Greedy pass** — for each day Mon–Fri, try both car and train/flight modes; pick whichever fits more clients. Within each mode, repeatedly pick the feasible client with the earliest arrival, preferring priority clients. Append a return-home leg at the end.

2. **Overnight pass** — for any priority client still unscheduled (round trip too long even with train or flight):
   - Find an empty day Mon–Thu to travel there and stay overnight in a hotel
   - If no empty day exists, release the latest day that contains only optional clients to make room
   - The next morning starts from the hotel city and runs the normal greedy from there

3. **Local search improvement** — iteratively applies until no gain remains:
   - Intra-day reordering (all permutations of a day's visits)
   - Single-client moves between days
   - Client swaps between two days
   
   Car days and overnight days are excluded from this pass (mode consistency would require re-simulation with a different matrix).

**Force mode** (`build_weekly_plan_forced`): instead of returning home each evening, stays overnight at the last visited city whenever unscheduled clients remain. Only returns home on Friday or once all clients are scheduled. Useful when a full week of travel is acceptable to maximise coverage.

### Geocoding

City names are resolved to coordinates using **Nominatim** (OpenStreetMap). Results are cached for the session. Nominatim enforces a 1 request/second rate limit; the planner respects this automatically.

---

## Project structure

```
route_planner/
├── models.py       # Dataclasses: Client, Leg, Visit, Day, WeeklyPlan
├── geocoder.py     # City name → (lat, lon) via Nominatim
├── travel.py       # Travel time matrices and mode selection
├── optimizer.py    # Two-pass scheduler + local search improvement
├── renderer.py     # Terminal output formatter (CLI mode)
├── app.py          # Streamlit web UI
├── main.py         # CLI entry point
└── input.yaml      # Example weekly input
```

---

## Limitations & known trade-offs

- **Estimated travel times** — straight-line distances underestimate road/rail distances (typically by 20–30%). The planner is accurate enough for weekly planning decisions but should not be used to schedule tight connections.
- **No real transport schedules** — actual train departure times and flight availability are not checked. The output is a planning suggestion, not a bookable itinerary.
- **Train speed is a global average** — 150 km/h reflects ICE-level high-speed rail. Slower regional trains (e.g. rural connections) are not modelled; the planner may overestimate train feasibility for non-hub cities.
- **Greedy ordering** — the scheduler is not an exhaustive solver. For weeks with many clients and tight constraints, a different manual ordering might occasionally outperform the result.
- **10 clients maximum** — the local search runs permutations up to 4! per day; beyond ~10 clients performance degrades.
- **Car days are not improved** — once a day is assigned to car mode, the local search does not attempt to reorder visits or move clients to/from that day. The greedy order stands.
