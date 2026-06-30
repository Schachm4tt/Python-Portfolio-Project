# Route Planner

A weekly client visit planner for field sales and consulting work across Europe (Germany, Austria, Switzerland, Poland, Netherlands). Enter your clients, their on-site time requirements, and time window constraints — the planner finds the optimal visiting order, picks the right transport mode for each leg, and renders the result as a calendar-style weekly view.

---

## Features

- **Optimal scheduling** — greedy algorithm with post-hoc local search (intra-day reordering, cross-day moves and swaps) to minimise total travel time
- **Multi-modal transport** — automatically chooses Car, Train, or Flight per leg based on distance and a configurable time-saving threshold
- **Time window constraints** — hard constraints on when each client can receive a visit (e.g. 09:00–17:00)
- **Day-of-week restrictions** — specify which weekdays a client is available (e.g. Wednesdays and Fridays only)
- **Priority clients** — mark clients as must-visit; the planner schedules them first and drops optional clients if the week runs out of capacity
- **Overnight stays** — when a destination is too far for a same-day return, the planner books a hotel night and starts the next day from that city
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
3. Click **Generate Plan**
4. The calendar view shows each day's legs and visits with colour-coded cards
5. Use the **✎** button next to any client to edit and then regenerate without re-entering all data

### CLI

```bash
uv run python -m route_planner.main                        # uses route_planner/input.yaml
uv run python -m route_planner.main path/to/myweek.yaml   # custom input file
```

### Input YAML format

```yaml
home: "Berlin"
week_start: "2026-06-22"

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
| Train | 100 km/h | +30 min (station time) |
| Flight | 600 km/h | +2h 30m (airport overhead) |

**Mode selection:** the planner always picks the fastest option, with two rules applied:

1. Flight is only chosen if it saves **at least 4 hours** over the best ground alternative
2. If the ground option one-way exceeds **6 hours** (making a same-day return impossible within the 21:00 curfew), flight is used regardless of the 4-hour rule

### Scheduling

**Constraints:**
- Mon–Fri only
- Depart home earliest **07:00**
- Client time windows are hard constraints (**08:00–17:00** typical)
- Return home by **21:00** (soft — hotel overnight used as last resort)
- Priority clients are always scheduled before optional ones

**Algorithm — two passes:**

1. **Greedy pass** — for each day Mon–Fri, repeatedly pick the feasible client with the earliest arrival time, preferring priority clients. Appends a return-home leg at the end of each day.

2. **Overnight pass** — for any priority client still unscheduled after pass 1 (because the round trip exceeds the daily budget):
   - Find an empty day (Mon–Thu) to travel to the client and stay overnight
   - If no empty day exists, release the latest optional-client-only day to make room
   - The following day starts from the hotel city and runs the normal greedy from there

3. **Local search improvement** — after both passes, iteratively applies:
   - Intra-day reordering (all permutations of a day's visits)
   - Single-client moves between days
   - Client swaps between two days
   — until no further reduction in total travel time is found

### Geocoding

City names are resolved to coordinates using **Nominatim** (OpenStreetMap). Results are cached for the session. Nominatim enforces a 1 request/second rate limit; the planner respects this automatically.

---

## Project structure

```
route_planner/
├── models.py       # Dataclasses: Client, Leg, Visit, Day, WeeklyPlan
├── geocoder.py     # City name → (lat, lon) via Nominatim
├── travel.py       # Pairwise travel time matrix and mode selection
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
- **Greedy ordering** — the scheduler is not an exhaustive solver. For weeks with many clients and tight constraints, a different manual ordering might occasionally outperform the result.
- **10 clients maximum** — the local search runs permutations up to 4! per day; beyond ~10 clients performance degrades.
