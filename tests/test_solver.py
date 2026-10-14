from dataclasses import replace

from conftest import NOW, at, make_task, weekly

from autoplanner.metrics import runs_of
from autoplanner.models import Preferences
from autoplanner.planner import build_problem, make_plan
from autoplanner.solver import solve
from autoplanner.validate import validate


def plan_for(tasks, prefs=None, events=(), blocks=()):
    problem = build_problem(NOW, prefs or Preferences(), list(events), tasks, list(blocks))
    return problem, make_plan(problem, time_limit=10)


def test_feasible_week_meets_every_deadline_ac6():
    tasks = [make_task("A", 4, at(1, 23, 59)), make_task("B", 3, at(2, 17, 0), type="reading"),
             make_task("C", 6, at(4, 23, 59), type="project"), make_task("D", 1.5, at(3, 12, 0), type="quiz")]
    events = [weekly("DSA", (0, 2, 4), "11:00", "12:30"), weekly("Prob", (1, 3), "14:00", "15:30")]
    problem, outcome = plan_for(tasks, events=events)
    assert outcome.plan.kind == "optimizer" and outcome.validation.ok
    assert outcome.validation.deadline_misses == 0 and not outcome.plan.unscheduled_min
    scheduled = {t.id: sum(b.minutes for b in outcome.plan.blocks if b.task_id == t.id) for t in tasks}
    assert scheduled == {t.id: t.est_minutes for t in tasks}


def test_big_task_is_split_into_chunks_ac7():
    task = make_task("Big", 5, at(2, 23, 59))
    _, outcome = plan_for([task], prefs=Preferences(min_block_min=60, max_block_min=120))
    lengths = [b.minutes for b in outcome.plan.blocks]
    assert len(lengths) >= 3 and all(60 <= m <= 120 for m in lengths) and sum(lengths) == 300


def test_demanding_work_goes_in_focus_windows_ac8():
    tasks = [make_task("D1", 2, at(1, 23, 59), demanding=True), make_task("D2", 2, at(1, 23, 59), demanding=True)]
    problem, outcome = plan_for(tasks)
    grid = problem.grid
    slots = [grid.index_of(b.start) + k for b in outcome.plan.blocks for k in range(b.minutes // 30)]
    assert slots and all(grid.focus[s] for s in slots)


def test_task_beyond_horizon_gets_pro_rata_share_ac27():
    far = make_task("Midterm prep", 10, at(14, 10, 0), type="exam_prep")  # due 14 days from now
    problem, outcome = plan_for([far])
    assert outcome.plan.kind == "optimizer"
    assert sum(b.minutes for b in outcome.plan.blocks) == 300  # 10 h x 158 h / 336 h, rounded up to slots
    assert far.id in outcome.plan.beyond_horizon
    grid = problem.grid
    assert all(grid.focus[grid.index_of(b.start)] for b in outcome.plan.blocks)  # demanding share in focus


def test_too_much_work_is_infeasible():
    problem = build_problem(NOW, Preferences(), [], [make_task("Huge", 20, at(1, 12, 0))], [])
    assert solve(problem, "strict", time_limit=5).status == "INFEASIBLE"


def test_shortfall_mode_minimises_unplaced_work():
    # Before tomorrow 12:00 there are 12 h available but the daily cap allows 8 h today + 4 h tomorrow.
    problem = build_problem(NOW, Preferences(), [], [make_task("Huge", 20, at(1, 12, 0))], [])
    result = solve(problem, "shortfall", time_limit=5)
    placed = len(result.assignment[problem.jobs[0].task_id])
    assert result.feasible and placed + result.shortfall[problem.jobs[0].task_id] == problem.jobs[0].required
    # today: the 8 h cap (16 slots); tomorrow 08:00-12:00: runs of <= 4 slots need a gap, so 7 of 8
    assert placed == 16 + 7


def test_daily_cap_counts_work_done_today_d15():
    from autoplanner.models import Block
    task = make_task("A", 10, at(5, 23, 59))
    done_today = Block(task_id=task.id, start=at(0, 8, 0), end=at(0, 10, 0), status="done")
    problem, outcome = plan_for([task], prefs=Preferences(max_work_per_day_min=240), blocks=[done_today])
    today = [b for b in outcome.plan.blocks if b.start.date() == NOW.date()]
    assert sum(b.minutes for b in today) <= 120
    assert validate(problem, outcome.plan.blocks, "optimizer").ok


def test_lateness_mode_places_everything_and_minimises_lateness():
    tasks = [make_task("A", 6, at(0, 14, 0)), make_task("B", 2, at(3, 23, 59))]
    problem = build_problem(NOW, Preferences(), [], tasks, [])
    result = solve(problem, "lateness", time_limit=5)
    assert result.feasible
    assert all(len(result.assignment[j.task_id]) == j.required for j in problem.jobs)
    a_slots = result.assignment[tasks[0].id]
    assert runs_of(a_slots)[0][0] == 0  # the late task starts immediately
