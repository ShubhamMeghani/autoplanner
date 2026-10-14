"""Learning from actual time (R36-R38, D-1): only user-confirmed work feeds the factor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from autoplanner.config import TYPE_LABELS
from autoplanner.models import Block, Task

WINDOW = 10  # last N eligible completed tasks per type
SHRINK = 2  # factor = 1 + n / (n + SHRINK) * (r - 1)
MIN_FACTOR, MAX_FACTOR = 0.5, 2.5


@dataclass(frozen=True)
class Factor:
    factor: float
    n: int
    r: float


def correction_factor(tasks: list[Task], task_type: str) -> Factor:
    """R37: from the last 10 completed, learning-eligible tasks of this type with actual > 0."""
    history = [t for t in tasks
               if t.type == task_type and t.status == "completed" and t.learning_eligible
               and (t.actual_hours or 0) > 0 and t.est_hours_raw > 0]
    history.sort(key=lambda t: t.completed_at or t.deadline, reverse=True)
    history = history[:WINDOW]
    n = len(history)
    if n == 0:
        return Factor(1.0, 0, 1.0)
    r = sum(t.actual_hours for t in history) / sum(t.est_hours_raw for t in history)
    factor = 1 + n / (n + SHRINK) * (r - 1)
    return Factor(min(MAX_FACTOR, max(MIN_FACTOR, factor)), n, r)


def corrected_estimate(raw_hours: float, factor: float) -> float:
    """raw x factor rounded to the nearest 0.5 h, ties up (R38)."""
    halves = Decimal(str(round(raw_hours * factor, 6))) * 2
    return float((halves + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR) / 2)


def factor_reason(f: Factor, task_type: str) -> str:
    label = TYPE_LABELS.get(task_type, task_type).lower() + "s"
    return f"You usually take {f.factor:.2g}× your estimate on {label} ({f.n} task{'s' if f.n != 1 else ''})."


def learning_eligible(task_id: str, blocks: list[Block], now: datetime) -> bool:
    """D-1: a task counts only if none of its past blocks is unconfirmed."""
    return not any(b.task_id == task_id and b.status == "planned" and b.start < now for b in blocks)


def confirmed_minutes(task_id: str, blocks: list[Block]) -> int:
    """Work the user confirmed: done blocks plus minutes completed in not-done blocks."""
    total = 0
    for b in blocks:
        if b.task_id != task_id:
            continue
        if b.status == "done":
            total += b.actual_minutes if b.actual_minutes is not None else b.minutes
        elif b.status == "not_done":
            total += b.actual_minutes or 0
    return total
