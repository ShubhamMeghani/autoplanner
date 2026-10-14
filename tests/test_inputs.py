"""Task and preference validation (AC-41, AC-43) and auto-replan on every change (AC-42)."""

from dataclasses import replace
from datetime import time

from conftest import NOW, at, make_task, weekly

from autoplanner.models import Preferences, default_demanding, validate_prefs, validate_task_input
from autoplanner.planner import PlannerService
from autoplanner.storage import MemoryRepo


def test_invalid_tasks_are_rejected_with_a_reason_per_field_ac41():
    assert set(validate_task_input("", 2, at(1, 12), NOW)) == {"title"}
    assert set(validate_task_input("   ", 2, at(1, 12), NOW)) == {"title"}
    assert set(validate_task_input("A", 0, at(1, 12), NOW)) == {"estimate"}
    assert set(validate_task_input("A", 40.5, at(1, 12), NOW)) == {"estimate"}
    assert set(validate_task_input("A", 2, at(0, 9), NOW)) == {"deadline"}
    assert validate_task_input("A", 2, at(1, 12), NOW) == {}


def test_demanding_defaults_from_the_type_table_ac41():
    assert default_demanding("project") is True
    assert default_demanding("reading") is False


def test_valid_task_is_saved_open_ac41():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    service = PlannerService(repo, pid, clock=lambda: NOW)
    task = make_task("Project", 3, at(3, 23, 59), type="project")
    service.change(lambda s, now: replace(s, tasks=s.tasks + [task]))
    saved = repo.load(pid).task(task.id)
    assert saved.status == "open" and saved.demanding is True


def test_preference_rules_ac43():
    errors, _, _ = validate_prefs(Preferences(day_start=time(23, 0), no_work_after=time(23, 0)))
    assert "day" in errors
    errors, _, _ = validate_prefs(Preferences(min_block_min=180, max_block_min=120))
    assert "blocks" in errors
    errors, notices, cleaned = validate_prefs(Preferences(day_start=time(8, 0),
                                                          focus_windows=((time(6, 0), time(9, 0)),)))
    assert not errors and notices
    assert cleaned.focus_windows == ((time(8, 0), time(9, 0)),)


def test_every_change_replans_without_user_action_ac42():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    service = PlannerService(repo, pid, clock=lambda: NOW)
    a, b = make_task("A", 2, at(2, 23, 59)), make_task("B", 2, at(3, 23, 59))
    view = service.change(lambda s, now: replace(s, tasks=[a, b]))
    versions = [view.meta["plan_version"]]

    def total(view, task):
        return sum(x.minutes for x in view.future_blocks if x.task_id == task.id)

    view = service.change(lambda s, now: replace(s, tasks=[replace(a, est_hours=3.0), b]))  # edit estimate
    versions.append(view.meta["plan_version"])
    assert total(view, a) == 180
    view = service.change(lambda s, now: replace(s, tasks=[t for t in s.tasks if t.id != b.id]))  # delete
    versions.append(view.meta["plan_version"])
    assert total(view, b) == 0
    view = service.change(lambda s, now: replace(s, events=[weekly("Class", (2,), "10:00", "12:00")]))  # event
    versions.append(view.meta["plan_version"])
    assert all(not (x.start < at(0, 12) and x.end > at(0, 10)) for x in view.future_blocks)
    view = service.change(lambda s, now: replace(s, prefs=replace(s.prefs, horizon_days=5)))  # preference
    versions.append(view.meta["plan_version"])
    assert versions == sorted(set(versions)) and len(versions) == 5


def test_view_does_not_resolve_when_nothing_changed_r62():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    calls = []

    def counting_solve(*args, **kwargs):
        from autoplanner.solver import solve
        calls.append(1)
        return solve(*args, **kwargs)

    service = PlannerService(repo, pid, clock=lambda: NOW, solve_fn=counting_solve)
    service.change(lambda s, now: replace(s, tasks=[make_task("A")]))
    first = len(calls)
    service.view()
    service.view()
    assert len(calls) == first
