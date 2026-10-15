"""Demo data dated relative to today (R51), and the overload scenario (R53)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from autoplanner.config import TZ
from autoplanner.models import Block, Event, PlannerState, Preferences, Task
from autoplanner.storage import MemoryRepo

DEMO_PLANNER_ID = "demo"


def _at(today: date, days: int, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(today + timedelta(days=days), time(hh, mm), TZ)


def _weekly(title: str, days: tuple[int, ...], start: str, end: str, kind: str = "class") -> Event:
    return Event(title=title, kind=kind, start_time=time.fromisoformat(start),
                 end_time=time.fromisoformat(end), weekdays=days, id=f"demo-ev-{title}-{start}")


def demo_events() -> list[Event]:
    """An IISc-style timetable: 11 classes and labs a week, plus blocked times."""
    return [
        _weekly("E0 251 Data Structures & Algorithms", (0, 2, 4), "10:00", "11:00"),
        _weekly("MA 261 Probability Models", (1, 3), "11:30", "13:00"),
        _weekly("DS 221 Scalable Systems", (0, 2), "14:00", "15:30"),
        _weekly("E9 241 Digital Image Processing", (1, 3), "14:00", "15:30"),
        _weekly("E9 241 DIP lab", (4,), "14:00", "17:00", "lab"),
        _weekly("DS 221 Systems lab", (0,), "16:00", "18:00", "lab"),
        _weekly("Gym", (0, 2, 4), "18:00", "19:00", "blocked"),
        _weekly("Mess dinner", (0, 1, 2, 3, 4, 5, 6), "20:00", "20:30", "blocked"),
    ]


def _task(tid: str, title: str, course: str, type_: str, hours: float, deadline: datetime,
          demanding: bool, raw: float | None = None, **kw) -> Task:
    return Task(id=f"demo-{tid}", title=title, course=course, type=type_, est_hours_raw=raw or hours,
                est_hours=hours, deadline=deadline, demanding=demanding, source="demo", **kw)


def build_demo(now: datetime) -> PlannerState:
    today = now.astimezone(TZ).date()
    d = lambda days, hh, mm=0: _at(today, days, hh, mm)  # noqa: E731
    tasks = [
        _task("dsa4", "Assignment 4: graph algorithms", "E0 251", "assignment", 7, d(3, 23, 59), True),
        _task("prob5", "Problem set 5", "MA 261", "assignment", 4, d(2, 17), True),
        _task("dip3", "Lab 3 report: histogram equalisation", "E9 241", "lab_report", 3, d(4, 23, 59),
              False, raw=2.5),
        _task("mini2", "Mini-project milestone 2", "DS 221", "project", 8, d(6, 23, 59), True),
        _task("clrs24", "Read CLRS ch. 24 (shortest paths)", "E0 251", "reading", 1.5, d(2, 8), False),
        _task("quiz3", "Quiz 3 prep", "MA 261", "quiz", 1, d(5, 11, 30), False),
        _task("mid", "Midterm preparation", "E9 241", "exam_prep", 6, d(10, 9), True),
        _task("mapred", "Read the MapReduce paper", "DS 221", "reading", 2, d(3, 23, 59), False),
    ]
    completed = [
        _task("dip1", "Lab 1 report", "E9 241", "lab_report", 2, d(-12, 23, 59), False, raw=2,
              status="completed", actual_hours=3.0, learning_eligible=True, completed_at=d(-12, 22)),
        _task("dip2", "Lab 2 report", "E9 241", "lab_report", 2.5, d(-5, 23, 59), False, raw=2.5,
              status="completed", actual_hours=3.5, learning_eligible=True, completed_at=d(-5, 21)),
        _task("prob4", "Problem set 4", "MA 261", "assignment", 3, d(-3, 17), True, raw=3,
              status="completed", actual_hours=4.0, learning_eligible=True, completed_at=d(-3, 16)),
        _task("clrs22", "Read CLRS ch. 22", "E0 251", "reading", 1.5, d(-6, 8), False, raw=1.5,
              status="completed", actual_hours=1.5, learning_eligible=True, completed_at=d(-7, 22)),
    ]
    # Past blocks from the previous 2 days (R51). Five have no feedback yet, so a visitor can mark
    # them done (with the time taken) or not done straight away (AC-9); one shows a done block.
    # Mornings before 10:00 and evenings avoid every class, the gym and dinner.
    past = [
        Block("demo-dip3", d(-2, 19), d(-2, 20), status="done", actual_minutes=60, id="demo-b1"),
        Block("demo-mapred", d(-2, 8), d(-2, 9), id="demo-b6"),
        Block("demo-dsa4", d(-2, 21), d(-2, 22, 30), id="demo-b2"),
        Block("demo-dsa4", d(-1, 19), d(-1, 20), id="demo-b3"),
        Block("demo-prob5", d(-1, 21), d(-1, 22), id="demo-b4"),
        Block("demo-mini2", d(-1, 22), d(-1, 23), id="demo-b5"),
    ]
    return PlannerState(prefs=Preferences(), events=demo_events(), tasks=tasks + completed, blocks=past)


def overload_tasks(now: datetime) -> list[Task]:
    """R53: extra work that cannot fit before its deadlines, at any time of day: 18 h due tomorrow
    night is more than two days of the 8 h daily cap."""
    today = now.astimezone(TZ).date()
    return [
        _task("ov1", "Surprise assignment: dynamic programming", "E0 251", "assignment", 18,
              _at(today, 1, 23, 59), True),
        _task("ov2", "Extra problem set (re-submission)", "MA 261", "assignment", 6,
              _at(today, 2, 12), True),
    ]


def demo_repo(now: datetime) -> MemoryRepo:
    repo = MemoryRepo()
    state = build_demo(now)
    repo.create_planner(state.prefs, planner_id=DEMO_PLANNER_ID)
    repo.upsert_events(DEMO_PLANNER_ID, state.events)
    repo.upsert_tasks(DEMO_PLANNER_ID, state.tasks)
    repo.upsert_blocks(DEMO_PLANNER_ID, state.blocks)
    return repo


def with_overload(state: PlannerState, now: datetime, on: bool) -> PlannerState:
    others = [t for t in state.tasks if not t.id.startswith("demo-ov")]
    return replace(state, tasks=others + (overload_tasks(now) if on else []))
