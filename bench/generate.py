"""Seeded benchmark workloads (R54).

Sizes: 10 tasks / 7 days, 20 / 7, 30 / 14. Load ratio rho in {0.6, 0.9, 1.15}, where rho is the
largest value, over all deadlines d, of (work due by d) / (capacity before d). Capacity counts
available slots, each day capped at the daily work limit. Estimates are scaled to hit the
target rho within 0.05 while total work stays <= 90 % of the horizon's capacity, so all work
fits somewhere. "Now" is fixed at Monday 2026-10-12 08:00 IST.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from autoplanner.config import SLOT_MINUTES, TASK_TYPES, TZ
from autoplanner.models import Event, Preferences, Task
from autoplanner.timegrid import build_grid

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)  # a Monday
SIZES = [(10, 7), (20, 7), (30, 14)]
RHOS = [0.6, 0.9, 1.15]
TOLERANCE = 0.05
MAX_TOTAL_SHARE = 0.90
TYPE_WEIGHTS = {"assignment": 4, "lab_report": 2, "project": 1, "exam_prep": 1, "reading": 2, "quiz": 1}


@dataclass
class Instance:
    name: str
    n_tasks: int
    horizon_days: int
    rho_target: float
    rho: float
    seed: int
    now: datetime
    prefs: Preferences
    events: list[Event]
    tasks: list[Task]


def _timetable(rng: random.Random) -> list[Event]:
    events = []
    for weekday in range(5):
        taken: list[tuple[int, int]] = []
        for k in range(rng.randint(3, 5)):
            for _ in range(20):
                length = rng.choice([2, 3, 4, 6])  # half-hours
                start = rng.randrange(16, 36 - length + 1)  # 08:00 .. 18:00
                if all(start + length <= a or b <= start for a, b in taken):
                    taken.append((start, start + length))
                    kind = "lab" if length == 6 else "class"
                    events.append(Event(title=f"Class {weekday}-{k}", kind=kind,
                                        start_time=time(start // 2, 30 * (start % 2)),
                                        end_time=time((start + length) // 2, 30 * ((start + length) % 2)),
                                        weekdays=(weekday,), id=f"ev-{weekday}-{k}"))
                    break
    return events


def _blocked(rng: random.Random, horizon_days: int) -> list[Event]:
    out = []
    for k in range(rng.randint(0, 3)):
        day = NOW.date() + timedelta(days=rng.randrange(horizon_days))
        start = rng.randrange(16, 42)  # 08:00 .. 21:00
        length = rng.choice([2, 3, 4])
        out.append(Event(title=f"Blocked {k}", kind="blocked", start_time=time(start // 2, 30 * (start % 2)),
                         end_time=time(min(47, start + length) // 2, 30 * (min(47, start + length) % 2)),
                         on_date=day, id=f"blk-{k}"))
    return out


def capacity_by(deadlines: list[datetime], prefs: Preferences, events: list[Event]) -> tuple[dict, int]:
    """Capped available slots before each deadline, and over the whole horizon."""
    grid = build_grid(NOW, prefs, events)
    cap = prefs.max_work_per_day_min // SLOT_MINUTES
    out = {}
    for deadline in deadlines + [grid.end]:
        per_day: dict[date, int] = {}
        for s in range(grid.slots_ending_by(deadline)):
            if grid.available[s]:
                per_day[grid.day_of[s]] = per_day.get(grid.day_of[s], 0) + 1
        out[deadline] = sum(min(cap, v) for v in per_day.values())
    return out, out[grid.end]


def load_ratio(slots: list[int], deadlines: list[datetime], capacity: dict) -> float:
    ratio = 0.0
    for d in set(deadlines):
        due = sum(s for s, dd in zip(slots, deadlines) if dd <= d)
        ratio = max(ratio, due / max(1, capacity[d]))
    return ratio


def make_instance(n_tasks: int, horizon_days: int, rho_target: float, seed: int) -> Instance:
    prefs = Preferences(horizon_days=horizon_days)
    for attempt in range(500):
        rng = random.Random(seed * 1000 + attempt)
        events = _timetable(rng) + _blocked(rng, horizon_days)
        types = rng.choices(list(TYPE_WEIGHTS), weights=list(TYPE_WEIGHTS.values()), k=n_tasks)
        base = [TASK_TYPES[t].default_hours * rng.uniform(0.5, 1.5) for t in types]
        deadlines = [datetime.combine(NOW.date() + timedelta(days=rng.randint(1, horizon_days - 1)),
                                      rng.choice([time(17, 0), time(23, 59)]), TZ) for _ in types]
        capacity, total_capacity = capacity_by(deadlines, prefs, events)

        def slots_for(k: float) -> list[int]:
            return [max(1, round(b * k * 60 / SLOT_MINUTES)) for b in base]

        lo, hi = 0.01, 20.0  # rho grows with k: binary search the scale
        for _ in range(40):
            mid = (lo + hi) / 2
            if load_ratio(slots_for(mid), deadlines, capacity) < rho_target:
                lo = mid
            else:
                hi = mid
        slots = slots_for(hi)
        rho = load_ratio(slots, deadlines, capacity)
        if abs(rho - rho_target) > TOLERANCE or sum(slots) > MAX_TOTAL_SHARE * total_capacity:
            continue
        tasks = [Task(id=f"t{i:02d}", title=f"Task {i}", type=t, est_hours_raw=s * SLOT_MINUTES / 60,
                      est_hours=s * SLOT_MINUTES / 60, deadline=d, demanding=TASK_TYPES[t].demanding,
                      course=f"Course {i % 5}")
                 for i, (t, s, d) in enumerate(zip(types, slots, deadlines))]
        name = f"n{n_tasks}-d{horizon_days}-rho{rho_target}-s{seed}"
        return Instance(name, n_tasks, horizon_days, rho_target, round(rho, 3), seed, NOW, prefs, events, tasks)
    raise RuntimeError(f"no instance for n={n_tasks} d={horizon_days} rho={rho_target} seed={seed}")


def suite(seeds: int = 10) -> list[Instance]:
    return [make_instance(n, d, rho, seed) for n, d in SIZES for rho in RHOS for seed in range(seeds)]
