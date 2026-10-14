"""Metrics shared by both methods (R56)."""

from __future__ import annotations

from dataclasses import dataclass

from autoplanner.config import SLOT
from autoplanner.timegrid import Problem


@dataclass
class Metrics:
    tasks: int
    deadlines_met: int
    total_lateness_h: float
    focus_violations: int  # demanding slots outside focus windows
    short_blocks: int  # blocks shorter than min(min block, the task's work)
    solve_seconds: float

    @property
    def preference_violations(self) -> int:
        return self.focus_violations + self.short_blocks


def runs_of(slots: list[int]) -> list[tuple[int, int]]:
    """Sorted slot indices -> (first, last) of each consecutive run."""
    out: list[tuple[int, int]] = []
    for s in sorted(slots):
        if out and s == out[-1][1] + 1:
            out[-1] = (out[-1][0], s)
        else:
            out.append((s, s))
    return out


def compute_metrics(problem: Problem, assignment: dict[str, list[int]], solve_seconds: float) -> Metrics:
    """Unplaced work is treated as done right after the horizon end, in order."""
    grid = problem.grid
    met = focus = short = 0
    lateness_h = 0.0
    for job in problem.jobs:
        slots = assignment.get(job.task_id, [])
        missing = job.required - len(slots)
        finish = grid.slot_end(max(slots)) if slots else grid.start
        if missing > 0:
            finish = grid.end + missing * SLOT
        late_h = max(0.0, (finish - job.deadline).total_seconds() / 3600)
        lateness_h += late_h
        if missing <= 0 and late_h == 0:
            met += 1
        if job.demanding:
            focus += sum(1 for s in slots if not grid.focus[s])
        short += sum(1 for a, b in runs_of(slots) if b - a + 1 < job.min_block)
    return Metrics(len(problem.jobs), met, round(lateness_h, 2), focus, short, solve_seconds)
