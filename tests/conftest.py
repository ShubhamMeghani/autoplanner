"""Shared test fixtures: a fixed "now", task/event builders (R60)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from autoplanner.config import TZ
from autoplanner.models import Event, Preferences, Task, default_demanding

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=TZ)  # Wednesday 10:00 IST
TODAY = NOW.date()


def at(days: int, hour: int, minute: int = 0) -> datetime:
    """IST datetime `days` after today at hh:mm."""
    return datetime.combine(TODAY + timedelta(days=days), time(hour, minute), TZ)


def make_task(title: str = "Task", hours: float = 2.0, deadline: datetime | None = None,
              type: str = "assignment", demanding: bool | None = None, **kw) -> Task:
    return Task(title=title, type=type, est_hours_raw=kw.pop("est_hours_raw", hours), est_hours=hours,
                deadline=deadline or at(2, 23, 59),
                demanding=default_demanding(type) if demanding is None else demanding, **kw)


def weekly(title: str, days: tuple[int, ...], start: str, end: str, kind: str = "class") -> Event:
    return Event(title=title, kind=kind, start_time=time.fromisoformat(start),
                 end_time=time.fromisoformat(end), weekdays=days)


def one_off(title: str, day: date, start: str, end: str, kind: str = "blocked") -> Event:
    return Event(title=title, kind=kind, start_time=time.fromisoformat(start),
                 end_time=time.fromisoformat(end), on_date=day)


@pytest.fixture
def prefs() -> Preferences:
    return Preferences()
