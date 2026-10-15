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


# ---------- Gemini mock (R60): records calls, never touches the network ----------

import json  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class FakeGemini:
    """Stands in for google.genai.Client: .models.generate_content and .files.upload."""

    def __init__(self, rows=None, error: Exception | None = None, text: str | None = None):
        self.calls, self.uploads = [], []
        outer = self

        class Models:
            def generate_content(self, model, contents, config):
                outer.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
                if error is not None:
                    raise error
                return SimpleNamespace(text=text if text is not None else json.dumps({"rows": rows or []}))

        class Files:
            def upload(self, *args, **kwargs):
                outer.uploads.append((args, kwargs))
                raise AssertionError("the Files API must not be used (R40)")

        self.models, self.files = Models(), Files()


def synthetic_png(number: int = 1) -> bytes:
    return (FIXTURES / "teams_synthetic" / f"teams_{number}.png").read_bytes()
