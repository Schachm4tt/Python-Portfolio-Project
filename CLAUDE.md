# Route Planner

Weekly client visit planner for Europe (DACH + PL + NL).
Input: YAML client list. Output: day-by-day itinerary printed to terminal.

## How to run

    uv run python -m route_planner.main                   # uses route_planner/input.yaml
    uv run python -m route_planner.main path/to/file.yaml

## Architecture

    input.yaml -> main.py -> geocoder.py -> travel.py -> optimizer.py -> renderer.py

- `models.py`    -- dataclasses (Client, Leg, Visit, Day, WeeklyPlan)
- `geocoder.py`  -- city name -> lat/lon via Nominatim (free, OSM). Enforces 1 req/sec sleep.
- `travel.py`    -- pairwise travel time matrix. Straight-line distance + speed factors (no API).
- `optimizer.py` -- two-pass greedy scheduler + overnight insertion
- `renderer.py`  -- terminal output formatter

## Travel time model

Estimated, not real-time. Speed factors:
- Car:    100 km/h, no overhead
- Train:  100 km/h, +30 min overhead
- Flight: 600 km/h, +2.5h overhead

Flight is chosen only if it saves >=4h over ground, OR ground one-way exceeds 6h
(which makes a same-day return infeasible within the 21:00 curfew).

## Scheduling constraints

- Mon-Fri only, depart home earliest 07:00
- Client windows: 08:00-17:00 (hard constraints)
- Return home by 21:00 (soft -- overnight in hotel allowed as last resort for priority clients)
- Priority clients must be scheduled; optional clients are dropped first if week is full

## Overnight logic (optimizer.py)

Two-pass approach:
1. Greedy pass -- fills Mon-Fri starting from home each day, no overnights
2. Overnight pass -- for any unscheduled priority client:
   a. Try empty days first (Mon-Thu only; need a following day)
   b. If none, "steal" the latest optional-only day (prefer Thursday over Wednesday
      to avoid cascading failures), free it, then insert overnight there
   Next day after overnight starts from the hotel city and runs the normal greedy
   (not a forced return-home first -- the full day is usable from the overnight city).

## Input YAML schema

```yaml
home: "Munich"
week_start: "2026-06-22"
clients:
  - name: "Client A"
    city: "Berlin"
    duration_hours: 3
    window_start: "09:00"
    window_end: "17:00"
    priority: true    # must-visit; false = scheduled only if week has capacity
```

## Dependencies

Managed via uv. Added beyond the project baseline:
- geopy==2.4.1   -- geocoding via Nominatim
- pyyaml==6.0.3  -- YAML input parsing
