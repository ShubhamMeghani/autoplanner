"""Domain dataclasses (SPEC §4) and input validation (R10, R11, R13)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from typing import Literal

from autoplanner.config import MAX_ESTIMATE_H, MAX_HORIZON_DAYS, MIN_ESTIMATE_H, SLOT_MINUTES, TASK_TYPES

EventKind = Literal["class", "lab", "other", "blocked"]
TaskStatus = Literal["open", "completed", "overdue"]
BlockStatus = Literal["planned", "done", "not_done", "skipped"]
PlanKind = Literal["optimizer", "greedy", "best_effort"]


def new_id() -> str:
    return str(uuid.uuid4())


def _t(value: str | time) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


@dataclass(frozen=True)
class Preferences:
    day_start: time = time(8, 0)
    no_work_after: time = time(23, 0)
    focus_windows: tuple[tuple[time, time], ...] = ((time(9, 0), time(12, 0)), (time(18, 0), time(21, 0)))
    min_block_min: int = 60
    max_block_min: int = 120
    max_work_per_day_min: int = 480
    horizon_days: int = 7

    def to_dict(self) -> dict:
        return {
            "day_start": self.day_start.strftime("%H:%M"),
            "no_work_after": self.no_work_after.strftime("%H:%M"),
            "focus_windows": [[a.strftime("%H:%M"), b.strftime("%H:%M")] for a, b in self.focus_windows],
            "min_block_min": self.min_block_min,
            "max_block_min": self.max_block_min,
            "max_work_per_day_min": self.max_work_per_day_min,
            "horizon_days": self.horizon_days,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> Preferences:
        data = data or {}
        d = cls()
        return cls(
            day_start=_t(data.get("day_start", d.day_start)),
            no_work_after=_t(data.get("no_work_after", d.no_work_after)),
            focus_windows=tuple((_t(a), _t(b)) for a, b in data.get("focus_windows", d.focus_windows)),
            min_block_min=int(data.get("min_block_min", d.min_block_min)),
            max_block_min=int(data.get("max_block_min", d.max_block_min)),
            max_work_per_day_min=int(data.get("max_work_per_day_min", d.max_work_per_day_min)),
            horizon_days=int(data.get("horizon_days", d.horizon_days)),
        )


@dataclass(frozen=True)
class Event:
    """A fixed event or blocked time: one-off (on_date) or weekly (weekdays, 0 = Monday)."""

    title: str
    kind: EventKind
    start_time: time
    end_time: time
    on_date: date | None = None
    weekdays: tuple[int, ...] | None = None
    until_date: date | None = None
    id: str = field(default_factory=new_id)

    def occurs_on(self, day: date) -> bool:
        if self.on_date is not None:
            return day == self.on_date
        if self.until_date is not None and day > self.until_date:
            return False
        return day.weekday() in (self.weekdays or ())


@dataclass(frozen=True)
class Task:
    title: str
    type: str
    est_hours_raw: float
    est_hours: float
    deadline: datetime
    demanding: bool
    course: str | None = None
    status: TaskStatus = "open"
    source: str = "manual"
    actual_hours: float | None = None
    learning_eligible: bool = False
    created_at: datetime | None = None
    completed_at: datetime | None = None
    id: str = field(default_factory=new_id)

    @property
    def est_minutes(self) -> int:
        return round(self.est_hours * 60)


@dataclass(frozen=True)
class Block:
    task_id: str
    start: datetime
    end: datetime
    status: BlockStatus = "planned"
    actual_minutes: int | None = None
    plan_version: int = 0
    id: str = field(default_factory=new_id)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def confirmed(self) -> bool:
        return self.status in ("done", "not_done")

    def done_minutes(self, now: datetime) -> int:
        """Minutes of work this block counts as done (R24, R25, R28)."""
        if self.status == "done":
            return self.actual_minutes if self.actual_minutes is not None else self.minutes
        if self.status == "not_done":
            return self.actual_minutes or 0
        if self.status == "planned" and self.start < now:
            return self.minutes  # past and unconfirmed: assumed done (R25)
        return 0


@dataclass
class Plan:
    """Future task blocks plus what the plan could not do."""

    blocks: list[Block]
    kind: PlanKind
    status: str  # solver status name, or "GREEDY"
    fallback: bool = False
    unscheduled_min: dict[str, int] = field(default_factory=dict)
    deadline_misses: int = 0
    short_blocks: int = 0
    beyond_horizon: set[str] = field(default_factory=set)
    solve_seconds: float = 0.0
    optimal: bool = False


@dataclass(frozen=True)
class ExtendOption:
    task_id: str
    new_deadline: datetime


@dataclass
class Diagnosis:
    """R29-R31, R34: why the deadlines don't fit, and verified ways out."""

    shortfall_min: dict[str, int]
    extend_options: list[ExtendOption]
    cut_option: dict[str, int] | None  # task id -> minutes to cut
    best_effort: Plan
    no_single_extension: bool = False
    cut_short: bool = False

    @property
    def total_shortfall_min(self) -> int:
        return sum(self.shortfall_min.values())


@dataclass
class PlannerState:
    """Everything stored for one planner. `meta` describes the stored plan (R62)."""

    prefs: Preferences
    events: list[Event] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.id == block_id), None)


# ---------- validation (R10, R11, R13) ----------

def validate_task_input(title: str, est_hours: float, deadline: datetime | None, now: datetime) -> dict[str, str]:
    """Field name -> reason. An empty dict means valid."""
    errors: dict[str, str] = {}
    if not title or not title.strip():
        errors["title"] = "Give the task a title."
    if est_hours is None or not (MIN_ESTIMATE_H <= est_hours <= MAX_ESTIMATE_H):
        errors["estimate"] = f"The estimate must be between {MIN_ESTIMATE_H:g} and {MAX_ESTIMATE_H:g} hours."
    elif round(est_hours * 2) != est_hours * 2:
        errors["estimate"] = "Use steps of 0.5 hours."
    if deadline is None:
        errors["deadline"] = "Set a deadline."
    elif deadline <= now:
        errors["deadline"] = "The deadline must be in the future."
    return errors


def default_demanding(task_type: str) -> bool:
    return TASK_TYPES.get(task_type, TASK_TYPES["other"]).demanding


def validate_prefs(prefs: Preferences) -> tuple[dict[str, str], list[str], Preferences]:
    """Return (errors, notices, prefs with focus windows clipped to the working day)."""
    errors: dict[str, str] = {}
    notices: list[str] = []
    if prefs.day_start >= prefs.no_work_after:
        errors["day"] = "Day start must be earlier than 'no work at or after'."
    if prefs.min_block_min > prefs.max_block_min:
        errors["blocks"] = "The min block length can't be longer than the max block length."
    if not (60 <= prefs.max_block_min <= 240):
        errors["max_block"] = "The max block length must be between 1 and 4 hours."
    if prefs.min_block_min < SLOT_MINUTES:
        errors["min_block"] = "The min block length must be at least 30 minutes."
    if not (1 <= prefs.horizon_days <= MAX_HORIZON_DAYS):
        errors["horizon"] = f"The horizon must be 1 to {MAX_HORIZON_DAYS} days."
    if prefs.max_work_per_day_min < SLOT_MINUTES:
        errors["daily_cap"] = "Max work per day must be at least 30 minutes."
    for value in (prefs.day_start, prefs.no_work_after, *[t for w in prefs.focus_windows for t in w]):
        if value.minute % SLOT_MINUTES or value.second:
            errors["grid"] = "Times must be on the half hour (:00 or :30)."
    if errors:
        return errors, notices, prefs

    clipped: list[tuple[time, time]] = []
    for start, end in prefs.focus_windows:
        new_start, new_end = max(start, prefs.day_start), min(end, prefs.no_work_after)
        if (new_start, new_end) != (start, end):
            if new_start < new_end:
                notices.append(f"Focus window {start:%H:%M}–{end:%H:%M} was clipped to "
                               f"{new_start:%H:%M}–{new_end:%H:%M} to fit your working day.")
            else:
                notices.append(f"Focus window {start:%H:%M}–{end:%H:%M} is outside your working day "
                               "and was removed.")
        if new_start < new_end:
            clipped.append((new_start, new_end))
    return errors, notices, replace(prefs, focus_windows=tuple(clipped))
