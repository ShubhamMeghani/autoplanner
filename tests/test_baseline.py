from conftest import NOW, at, make_task

from autoplanner.baseline import greedy_plan
from autoplanner.metrics import compute_metrics, runs_of
from autoplanner.models import Preferences
from autoplanner.planner import build_problem


def problem_for(tasks, prefs=None):
    return build_problem(NOW, prefs or Preferences(), [], tasks, [])


def test_earliest_deadline_goes_first():
    late, early = make_task("Late", 1, at(3, 23, 59)), make_task("Early", 1, at(1, 23, 59))
    assignment = greedy_plan(problem_for([late, early]))
    assert assignment[early.id] == [0, 1] and assignment[late.id] == [2, 3]


def test_runs_never_exceed_max_block():
    a, b = make_task("A", 4, at(1, 23, 59)), make_task("B", 4, at(2, 23, 59))
    problem = problem_for([a, b])
    assignment = greedy_plan(problem)
    for slots in assignment.values():
        assert all(last - first + 1 <= problem.max_block for first, last in runs_of(slots))


def test_single_task_pauses_after_max_run():
    task = make_task("Solo", 3, at(2, 23, 59))
    assignment = greedy_plan(problem_for([task]))
    assert runs_of(assignment[task.id]) == [(0, 3), (5, 6)]  # 2 h run, a skipped slot, then 1 h


def test_work_continues_past_the_deadline():
    task = make_task("Tight", 6, at(0, 14, 0))
    problem = problem_for([task])
    assignment = greedy_plan(problem)
    assert len(assignment[task.id]) == problem.jobs[0].required
    metrics = compute_metrics(problem, assignment, 0.0)
    assert metrics.deadlines_met == 0 and metrics.total_lateness_h > 0


def test_daily_cap_is_respected():
    task = make_task("Long", 12, at(3, 23, 59))
    problem = problem_for([task], Preferences(max_work_per_day_min=120))
    assignment = greedy_plan(problem)
    per_day = {}
    for s in assignment[task.id]:
        per_day[problem.grid.day_of[s]] = per_day.get(problem.grid.day_of[s], 0) + 1
    assert max(per_day.values()) <= 4
