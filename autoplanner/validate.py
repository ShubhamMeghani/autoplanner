"""Independent plan validator with per-plan-type rule sets (R20, D-12).

It re-derives every rule from datetimes, events and preferences, never from the
solver's variables:
- base rules (every plan): R14.1 available time only, R14.2 no overlaps;
- optimizer plans: base + R14.3-R14.6;
- greedy and best-effort plans: base + R14.4 and R14.6; deadline misses (R14.3),
  short blocks (R14.5) and unscheduled work are counted, not failures.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime

from autoplanner.config import SLOT_MINUTES
from autoplanner.models import Block, PlanKind
from autoplanner.timegrid import Problem, event_intervals, to_ist, within_working_day


@dataclass
class ValidationResult:
    failures: list[str] = field(default_factory=list)
    deadline_misses: int = 0
    short_blocks: int = 0
    unscheduled_min: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures


def merge_runs(blocks: list[Block]) -> dict[str, list[tuple[datetime, datetime]]]:
    """Task id -> maximal runs (adjacent blocks of the same task are one block)."""
    runs: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for b in sorted(blocks, key=lambda b: (b.task_id, b.start)):
        task_runs = runs[b.task_id]
        if task_runs and task_runs[-1][1] == b.start:
            task_runs[-1] = (task_runs[-1][0], b.end)
        else:
            task_runs.append((b.start, b.end))
    return runs


def validate(problem: Problem, blocks: list[Block], kind: PlanKind) -> ValidationResult:
    result = ValidationResult()
    fail = result.failures.append
    blocks = [replace(b, start=to_ist(b.start), end=to_ist(b.end)) for b in blocks]
    prefs, grid = problem.prefs, problem.grid
    jobs = {job.task_id: job for job in problem.jobs}
    strict = kind == "optimizer"

    # ---- base rules ----
    busy = [iv for e in problem.events
            for iv in event_intervals(e, grid.start.date(), grid.end.date())]
    for b in blocks:
        label = f"block {b.start:%a %H:%M}-{b.end:%H:%M}"
        if b.task_id not in jobs:
            fail(f"{label}: belongs to no task in this plan")
        if b.end <= b.start or b.start.minute % SLOT_MINUTES or b.end.minute % SLOT_MINUTES or b.start.second:
            fail(f"{label}: not on the 30-minute grid")
        if b.start < grid.start or b.end > grid.end:
            fail(f"{label}: outside the planning horizon or in the past")
        if not within_working_day(b.start, b.end, prefs):
            fail(f"{label}: outside working hours")
        if any(s < b.end and b.start < e for s, e in busy):
            fail(f"{label}: clashes with a fixed event or blocked time")
    ordered = sorted(blocks, key=lambda b: b.start)
    for a, b in zip(ordered, ordered[1:]):
        if b.start < a.end:
            fail(f"blocks overlap at {b.start:%a %H:%M}")

    # ---- R14.4 max block and R14.6 daily cap (all plan types) ----
    runs = merge_runs(blocks)
    for task_id, task_runs in runs.items():
        for start, end in task_runs:
            if (end - start).total_seconds() / 60 > prefs.max_block_min:
                fail(f"block {start:%a %H:%M} is longer than the max block length")
    per_day: dict = defaultdict(int)
    for b in blocks:
        per_day[b.start.date()] += b.minutes
    for day, minutes in per_day.items():
        if minutes + problem.day_used_min.get(day, 0) > prefs.max_work_per_day_min:
            fail(f"{day:%a %d %b}: more task work than the daily cap")

    # ---- R14.3 deadlines and R14.5 min block: failures for the optimizer, counts otherwise ----
    for task_id, job in jobs.items():
        task_runs = runs.get(task_id, [])
        placed = sum(int((e - s).total_seconds() // 60) for s, e in task_runs)
        required = job.required * SLOT_MINUTES
        if placed > required:
            fail(f"task {task_id}: {placed} min placed but only {required} required")
        late = any(e > job.deadline for _, e in task_runs)
        missing = required - placed
        if missing > 0:
            result.unscheduled_min[task_id] = missing
        if late or missing > 0:
            result.deadline_misses += 1
            if strict:
                fail(f"task {task_id}: misses its deadline")
        min_minutes = job.min_block * SLOT_MINUTES
        short = sum(1 for s, e in task_runs if (e - s).total_seconds() / 60 < min_minutes)
        result.short_blocks += short
        if strict and short:
            fail(f"task {task_id}: {short} block(s) shorter than the min block length")
    return result
