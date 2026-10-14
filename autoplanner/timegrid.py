"""The 30-minute slot grid in IST: availability, focus windows and snapping (R9, R14.1, R59)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from autoplanner.config import SLOT, SLOT_MINUTES, TZ
from autoplanner.models import Event, Preferences


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: every datetime must carry a timezone")
    return dt.astimezone(TZ)


def floor_to_slot(dt: datetime) -> datetime:
    dt = to_ist(dt)
    return dt.replace(minute=dt.minute - dt.minute % SLOT_MINUTES, second=0, microsecond=0)


def ceil_to_slot(dt: datetime) -> datetime:
    floored = floor_to_slot(dt)
    return floored if floored == to_ist(dt) else floored + SLOT


def snap_times(start: time, end: time) -> tuple[time, time, bool]:
    """Widen times to the slot grid: start down, end up (R9). Returns (start, end, changed)."""
    new_start = start.replace(minute=start.minute - start.minute % SLOT_MINUTES, second=0, microsecond=0)
    end_minutes = end.hour * 60 + end.minute + (1 if end.second or end.microsecond else 0)
    end_minutes = -(-end_minutes // SLOT_MINUTES) * SLOT_MINUTES
    new_end = time.max if end_minutes >= 24 * 60 else time(end_minutes // 60, end_minutes % 60)
    return new_start, new_end, (new_start, new_end) != (start, end)


def at(day: date, t: time) -> datetime:
    """IST datetime for a wall-clock time; time.max means midnight at the end of the day."""
    if t == time.max:
        return datetime.combine(day + timedelta(days=1), time(0), TZ)
    return datetime.combine(day, t, TZ)


def horizon_end(now: datetime, horizon_days: int) -> datetime:
    """24:00 on the last horizon day; day 1 is today (R14)."""
    return datetime.combine(to_ist(now).date() + timedelta(days=horizon_days), time(0), TZ)


def event_intervals(event: Event, first_day: date, last_day: date) -> list[tuple[datetime, datetime]]:
    """Occurrences of an event between two dates, inclusive."""
    out = []
    day = first_day
    while day <= last_day:
        if event.occurs_on(day):
            out.append((at(day, event.start_time), at(day, event.end_time)))
        day += timedelta(days=1)
    return out


def in_windows(start: datetime, end: datetime, windows: tuple[tuple[time, time], ...]) -> bool:
    day = start.date()
    return any(at(day, a) <= start and end <= at(day, b) for a, b in windows)


def within_working_day(start: datetime, end: datetime, prefs: Preferences) -> bool:
    day = start.date()
    return at(day, prefs.day_start) <= start and end <= at(day, prefs.no_work_after)


@dataclass
class Grid:
    start: datetime  # start of slot 0 (now, rounded up)
    end: datetime  # horizon end
    available: list[bool]
    focus: list[bool]
    day_of: list[date]

    @property
    def n(self) -> int:
        return len(self.available)

    def slot_start(self, i: int) -> datetime:
        return self.start + i * SLOT

    def slot_end(self, i: int) -> datetime:
        return self.start + (i + 1) * SLOT

    def index_of(self, dt: datetime) -> int:
        """Index of the slot that starts at dt (dt must be on the grid)."""
        return int((to_ist(dt) - self.start) / SLOT)

    def slots_ending_by(self, dt: datetime) -> int:
        """How many slots end at or before dt, clamped to [0, n]."""
        count = int((to_ist(dt) - self.start) // SLOT)
        return max(0, min(self.n, count))

    @property
    def days(self) -> list[date]:
        return sorted(set(self.day_of))


@dataclass(frozen=True)
class Job:
    """One task's work for this plan, in slots."""

    task_id: str
    required: int  # slots that must be placed
    deadline: datetime  # real deadline; the horizon end for a pro-rata share
    deadline_slot: int  # slots s < deadline_slot end at or before the deadline
    demanding: bool
    min_block: int  # min(min block length, required), R14.5
    share: bool = False  # task due after the horizon (R17)


@dataclass
class Problem:
    """Everything the solver, the greedy baseline, the validator and the metrics need."""

    now: datetime
    prefs: Preferences
    events: list[Event]
    grid: Grid
    jobs: list[Job]
    day_cap: dict[date, int]  # slots still allowed per day, after work already done (D-15)
    day_used_min: dict[date, int]  # task minutes already done or past per day

    @property
    def max_block(self) -> int:
        return self.prefs.max_block_min // SLOT_MINUTES


def build_grid(now: datetime, prefs: Preferences, events: list[Event]) -> Grid:
    start = ceil_to_slot(now)
    end = horizon_end(now, prefs.horizon_days)
    n = max(0, int((end - start) / SLOT))
    first_day, last_day = start.date(), (end - SLOT).date()
    busy = [iv for e in events for iv in event_intervals(e, first_day, last_day)]

    available, focus, day_of = [], [], []
    for i in range(n):
        a, b = start + i * SLOT, start + (i + 1) * SLOT
        free = within_working_day(a, b, prefs) and not any(s < b and a < e for s, e in busy)
        available.append(free)
        focus.append(in_windows(a, b, prefs.focus_windows))
        day_of.append(a.date())
    return Grid(start=start, end=end, available=available, focus=focus, day_of=day_of)
