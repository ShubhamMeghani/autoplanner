"""Infeasibility diagnosis: verified options (AC-10), shares (AC-27), the 15 s budget (AC-46)."""

from dataclasses import replace

from conftest import NOW, at, make_task

from autoplanner.diagnose import diagnose, with_deadline, with_required
from autoplanner.models import Preferences, PlannerState
from autoplanner.planner import build_problem, cut_hours, extend_deadline, make_plan
from autoplanner.solver import solve


def three_hours_over():
    """Today 10:00-23:00 has room, but the 8 h daily cap leaves 3 h of the 11 h unplaced."""
    a = make_task("A", 6, at(0, 18, 0))
    b = make_task("B", 5, at(0, 23, 0))
    return PlannerState(Preferences(), tasks=[a, b]), a, b


def test_diagnosis_reports_exact_shortfall_and_verified_options_ac10():
    state, a, b = three_hours_over()
    problem = build_problem(NOW, state.prefs, [], state.tasks, [])
    outcome = make_plan(problem, time_limit=10)
    diagnosis = outcome.diagnosis
    assert diagnosis is not None and outcome.plan.kind == "best_effort"
    assert diagnosis.total_shortfall_min == 180
    assert diagnosis.extend_options and diagnosis.cut_option
    assert sum(diagnosis.cut_option.values()) == 180

    for option in diagnosis.extend_options:  # each option, applied alone, is strict-feasible
        fixed = extend_deadline(state, NOW, option.task_id, option.new_deadline)
        p = build_problem(NOW, fixed.prefs, [], fixed.tasks, [])
        assert solve(p, "strict", time_limit=10).feasible
        earlier = with_deadline(problem, option.task_id, option.new_deadline - (at(0, 10, 30) - at(0, 10)))
        assert not solve(earlier, "strict", time_limit=10).feasible  # and it is the earliest such deadline

    cut = cut_hours(state, NOW, diagnosis.cut_option)
    p = build_problem(NOW, cut.prefs, [], cut.tasks, [])
    assert solve(p, "strict", time_limit=10).feasible


def test_share_that_cannot_fit_gets_a_cut_but_no_extend_option_ac27():
    far = make_task("Midterm prep", 20, at(2, 23, 59), type="exam_prep")
    prefs = Preferences(horizon_days=1, max_work_per_day_min=240)
    problem = build_problem(NOW, prefs, [], [far], [])
    assert problem.jobs[0].share and problem.jobs[0].required > 8
    diagnosis = make_plan(problem, time_limit=10).diagnosis
    assert diagnosis is not None
    assert diagnosis.extend_options == []
    assert diagnosis.cut_option and far.id in diagnosis.cut_option
    assert diagnosis.no_single_extension


def test_diagnosis_stops_starting_solves_after_the_budget_ac46():
    state, a, b = three_hours_over()
    problem = build_problem(NOW, state.prefs, [], state.tasks, [])
    fake = {"t": 0.0}
    starts = []

    def slow_solve(*args, **kwargs):
        starts.append(fake["t"])
        fake["t"] += 4.0
        return solve(*args, **kwargs)

    diagnosis = diagnose(problem, solve_fn=slow_solve, clock=lambda: fake["t"], budget=15.0)
    assert starts and all(t < 15.0 for t in starts)
    assert diagnosis.cut_short
    assert diagnosis.best_effort.blocks  # the best-effort plan is still returned
    assert diagnosis.total_shortfall_min == 180


def test_problem_helpers():
    state, a, b = three_hours_over()
    problem = build_problem(NOW, state.prefs, [], state.tasks, [])
    reduced = with_required(problem, {a.id: 0})
    assert [j.task_id for j in reduced.jobs] == [b.id]
    moved = with_deadline(problem, a.id, at(1, 12))
    assert next(j for j in moved.jobs if j.task_id == a.id).deadline == at(1, 12)
    assert replace(problem).jobs == problem.jobs
