"""Demo data invariants (R51) and plan validity at any time of the week."""

from datetime import datetime, timedelta

import pytest
from conftest import NOW

from autoplanner.config import TZ
from autoplanner.demo import DEMO_PLANNER_ID, build_demo, demo_repo, demo_events, with_overload
from autoplanner.learning import correction_factor
from autoplanner.planner import PlannerService, build_problem, make_plan
from autoplanner.validate import validate


def test_demo_content_meets_r51():
    state = build_demo(NOW)
    weekly_classes = sum(len(e.weekdays or ()) for e in demo_events() if e.kind in ("class", "lab"))
    open_tasks = [t for t in state.tasks if t.status == "open"]
    assert weekly_classes >= 8
    assert len(open_tasks) >= 8
    assert sum(t.demanding for t in open_tasks) >= 3
    assert any(t.est_hours * 60 > state.prefs.max_block_min for t in open_tasks)
    assert any(e.kind == "blocked" for e in state.events)
    completed = [t for t in state.tasks if t.status == "completed" and t.learning_eligible]
    assert len(completed) >= 3
    assert correction_factor(state.tasks, "lab_report").factor != 1.0
    started = [b for b in state.blocks if b.start < NOW]
    assert len(started) >= 5  # AC-9 needs five started blocks


@pytest.mark.parametrize("day", range(7))
@pytest.mark.parametrize("hhmm", [(7, 0), (22, 45)])
def test_demo_plans_meet_every_deadline_all_week_ac6(day, hhmm):
    now = datetime(2026, 10, 12, *hhmm, tzinfo=TZ) + timedelta(days=day)
    state = build_demo(now)
    problem = build_problem(now, state.prefs, state.events, state.tasks, state.blocks)
    outcome = make_plan(problem, time_limit=10)
    assert outcome.plan.kind == "optimizer"
    check = validate(problem, outcome.plan.blocks, "optimizer")
    assert check.ok and check.deadline_misses == 0


def test_demo_service_plans_without_storage_ac4():
    repo = demo_repo(NOW)
    view = PlannerService(repo, DEMO_PLANNER_ID, clock=lambda: NOW).view()
    assert view.meta["kind"] == "optimizer"
    assert len(view.future_blocks) >= 8


def test_overload_toggle_adds_and_removes_tasks():
    state = build_demo(NOW)
    heavy = with_overload(state, NOW, True)
    assert len(heavy.tasks) == len(state.tasks) + 2
    assert with_overload(heavy, NOW, False).tasks == state.tasks


@pytest.mark.parametrize("when", [(0, 7, 0), (3, 12, 0), (5, 22, 45)])
def test_overload_is_infeasible_at_any_time_with_a_verified_option_ac33(when):
    day, hh, mm = when
    now = datetime(2026, 10, 12, hh, mm, tzinfo=TZ) + timedelta(days=day)
    state = with_overload(build_demo(now), now, True)
    problem = build_problem(now, state.prefs, state.events, state.tasks, state.blocks)
    diagnosis = make_plan(problem, time_limit=10).diagnosis
    assert diagnosis is not None and diagnosis.total_shortfall_min > 0
    assert diagnosis.extend_options or diagnosis.cut_option


@pytest.mark.parametrize("hhmm", [(7, 0), (10, 0), (23, 30)])
def test_demo_has_unconfirmed_past_blocks_from_the_last_two_days_r51(hhmm):
    from autoplanner.timegrid import event_intervals

    now = datetime(2026, 10, 14, *hhmm, tzinfo=TZ)
    state = build_demo(now)
    start = datetime.combine(now.date() - timedelta(days=2), datetime.min.time(), TZ)
    unconfirmed = [b for b in state.blocks if b.status == "planned" and start <= b.start < now]
    assert len(unconfirmed) >= 5
    busy = [iv for e in state.events for iv in event_intervals(e, start.date(), now.date())]
    for b in state.blocks:
        assert not any(s < b.end and b.start < e for s, e in busy), "a past block clashes with a class or blocked time"
