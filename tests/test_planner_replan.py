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
