from conftest import NOW, at, make_task

from autoplanner.models import Block, Preferences
from autoplanner.planner import build_problem, make_plan, refresh_overdue, remaining_minutes
from autoplanner.solver import SolveResult


def test_unknown_solver_status_falls_back_to_greedy_ac11():
    tasks = [make_task("A", 3, at(1, 23, 59)), make_task("B", 2, at(2, 12, 0))]
    problem = build_problem(NOW, Preferences(), [], tasks, [])

    def timed_out(*args, **kwargs):
        return SolveResult("UNKNOWN")

    outcome = make_plan(problem, solve_fn=timed_out)
    assert outcome.plan.fallback and outcome.plan.kind == "greedy"
    assert outcome.validation.ok
    assert outcome.plan.deadline_misses == 0 and outcome.plan.short_blocks >= 0  # counts present
    assert sum(b.minutes for b in outcome.plan.blocks) == 300


def test_past_deadline_with_work_left_is_overdue_and_not_planned_ac12():
    overdue = make_task("Late", 2, at(0, 9, 0))  # 1 h before now
    fine = make_task("Fine", 1, at(1, 23, 59))
    tasks = refresh_overdue([overdue, fine], [], NOW)
    assert [t.status for t in tasks] == ["overdue", "open"]
    problem = build_problem(NOW, Preferences(), [], tasks, [])
    assert [j.task_id for j in problem.jobs] == [fine.id]


def test_remaining_work_counts_done_unconfirmed_and_partial_blocks():
    task = make_task("A", 5, at(3, 23, 59))
    blocks = [
        Block(task.id, at(-1, 18, 0), at(-1, 19, 0), status="done", actual_minutes=75),
        Block(task.id, at(-1, 20, 0), at(-1, 21, 0), status="planned"),  # past, unconfirmed: counted as done
        Block(task.id, at(0, 8, 0), at(0, 9, 0), status="not_done"),  # counts nothing
        Block(task.id, at(1, 9, 0), at(1, 10, 0), status="planned"),  # future: counts nothing
    ]
    assert remaining_minutes(task, blocks, NOW) == 300 - 75 - 60


# ---------- feedback (AC-9 logic, AC-45) ----------

from autoplanner.demo import DEMO_PLANNER_ID, demo_repo  # noqa: E402
from autoplanner.planner import PlannerService, mark_done  # noqa: E402
from autoplanner.timegrid import ceil_to_slot  # noqa: E402
from autoplanner.ui.calendar_view import block_label  # noqa: E402
from autoplanner.validate import validate  # noqa: E402


def test_not_done_returns_work_and_replans_from_now_ac9():
    service = PlannerService(demo_repo(NOW), DEMO_PLANNER_ID, clock=lambda: NOW)
    view = service.view()
    started = [b for b in view.state.blocks if b.start <= NOW and b.status in ("planned", "done")]
    assert len(started) >= 5
    for block in started[:5]:
        task = view.state.task(block.task_id)
        before_remaining = view.remaining_min(task)
        frozen = {b.id: b for b in view.state.blocks if b.start < NOW and b.id != block.id}
        view = service.mark_not_done(block.id)
        counted = block.actual_minutes if block.status == "done" and block.actual_minutes is not None else block.minutes
        assert view.remaining_min(view.state.task(task.id)) == before_remaining + counted
        assert {b.id: b for b in view.state.blocks if b.id in frozen} == frozen  # past and done unchanged
        assert all(b.start >= ceil_to_slot(NOW) for b in view.future_blocks)
        assert view.meta["kind"] == "optimizer"
        problem = build_problem(NOW, view.state.prefs, view.state.events, view.state.tasks, view.state.blocks)
        assert validate(problem, view.future_blocks, "optimizer").ok  # the validator passes


def test_done_stores_actual_minutes_and_clears_the_badge_ac45():
    task = make_task("A", 3, at(2, 23, 59))
    past = Block(task.id, at(0, 8), at(0, 9))
    other = Block(task.id, at(-1, 20), at(-1, 21))
    from autoplanner.models import PlannerState
    state = PlannerState(Preferences(), tasks=[task], blocks=[past, other])
    assert block_label(past, task, NOW).startswith("⏳")
    state = mark_done(state, NOW, past.id, 75)
    done = state.block(past.id)
    assert (done.status, done.confirmed, done.actual_minutes) == ("done", True, 75)
    assert not block_label(done, task, NOW).startswith("⏳")
    state = mark_done(state, NOW, other.id)
    assert state.block(other.id).actual_minutes == 60


def test_future_blocks_cannot_be_marked():
    import pytest
    task = make_task("A", 3, at(2, 23, 59))
    future = Block(task.id, at(1, 9), at(1, 10))
    from autoplanner.models import PlannerState
    state = PlannerState(Preferences(), tasks=[task], blocks=[future])
    with pytest.raises(ValueError):
        mark_done(state, NOW, future.id)


# ---------- Should items: R27 (AC-31), R28 (AC-39), R64 (AC-34) ----------

from dataclasses import replace as _replace  # noqa: E402

from autoplanner.planner import cant_do, mark_not_done  # noqa: E402
from autoplanner.storage import MemoryRepo  # noqa: E402


def test_cant_do_blocks_the_slot_and_replans_around_it_ac31():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    service = PlannerService(repo, pid, clock=lambda: NOW)
    view = service.change(lambda s, now: _replace(s, tasks=[make_task("A", 4, at(2, 23, 59))]))
    block = next(b for b in view.future_blocks if b.start > NOW)  # one that has not started
    view = service.cant_do(block.id)
    blocked = [e for e in view.state.events if e.kind == "blocked"]
    assert len(blocked) == 1 and blocked[0].on_date == block.start.date()
    assert (blocked[0].start_time, blocked[0].end_time) == (block.start.time(), block.end.time())
    assert all(not (b.start < block.end and block.start < b.end) for b in view.future_blocks)
    assert sum(b.minutes for b in view.future_blocks) == 240


def test_partial_minutes_return_only_the_rest_ac39():
    from autoplanner.models import PlannerState
    task = make_task("A", 3, at(2, 23, 59))
    block = Block(task.id, at(0, 8), at(0, 9))  # 60 minutes, started
    state = PlannerState(Preferences(), tasks=[task], blocks=[block])
    before = remaining_minutes(task, state.blocks, NOW)  # unconfirmed: counted as done
    after_state = mark_not_done(state, NOW, block.id, minutes_completed=30)
    after = remaining_minutes(task, after_state.blocks, NOW)
    assert after - before == 30  # exactly the unfinished 30 minutes come back
    assert after_state.block(block.id).actual_minutes == 30


def test_replanning_an_unchanged_instance_keeps_the_plan_ac34():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    service = PlannerService(repo, pid, clock=lambda: NOW)
    tasks = [make_task("A", 3, at(1, 23, 59)), make_task("B", 2, at(2, 23, 59), type="reading")]
    first = service.change(lambda s, now: _replace(s, tasks=tasks))
    before = sorted((b.task_id, b.start, b.end) for b in first.future_blocks)
    second = service.replan()
    after = sorted((b.task_id, b.start, b.end) for b in second.future_blocks)
    assert after == before
    assert second.meta["plan_version"] == first.meta["plan_version"] + 1
