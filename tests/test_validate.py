from conftest import NOW, at, make_task, weekly

from autoplanner.models import Block, Preferences
from autoplanner.planner import build_problem
from autoplanner.validate import validate


def setup(tasks, events=(), prefs=None):
    return build_problem(NOW, prefs or Preferences(), list(events), tasks, [])


def test_clean_plan_passes_every_rule_set():
    task = make_task("A", 2, at(1, 23, 59))
    problem = setup([task])
    blocks = [Block(task.id, at(0, 10, 0), at(0, 12, 0))]
    for kind in ("optimizer", "greedy", "best_effort"):
        assert validate(problem, blocks, kind).ok


def test_base_rules_fail_for_every_plan_type():
    task = make_task("A", 4, at(2, 23, 59))
    problem = setup([task], events=[weekly("DSA", (2,), "14:00", "15:00")])
    cases = {
        "overlap": [Block(task.id, at(0, 10, 0), at(0, 11, 0)), Block(task.id, at(0, 10, 30), at(0, 11, 30))],
        "event clash": [Block(task.id, at(0, 14, 0), at(0, 15, 0))],
        "out of hours": [Block(task.id, at(0, 23, 0), at(0, 23, 30))],
        "past": [Block(task.id, at(0, 9, 0), at(0, 10, 0))],
    }
    for name, blocks in cases.items():
        for kind in ("optimizer", "greedy", "best_effort"):
            assert not validate(problem, blocks, kind).ok, (name, kind)


def test_deadline_misses_and_short_blocks_are_counted_not_failures_for_greedy():
    task = make_task("A", 2, at(0, 12, 0))
    problem = setup([task])
    blocks = [Block(task.id, at(0, 10, 0), at(0, 10, 30)), Block(task.id, at(0, 13, 0), at(0, 14, 30))]
    for kind in ("greedy", "best_effort"):
        result = validate(problem, blocks, kind)
        assert result.ok and result.deadline_misses == 1 and result.short_blocks == 1
    strict = validate(problem, blocks, "optimizer")
    assert not strict.ok and strict.deadline_misses == 1


def test_unscheduled_work_is_reported():
    task = make_task("A", 3, at(1, 23, 59))
    problem = setup([task])
    result = validate(problem, [Block(task.id, at(0, 10, 0), at(0, 12, 0))], "best_effort")
    assert result.ok and result.unscheduled_min == {task.id: 60} and result.deadline_misses == 1


def test_max_block_and_daily_cap_bind_greedy_plans_too():
    task = make_task("A", 6, at(3, 23, 59))
    problem = setup([task], prefs=Preferences(max_work_per_day_min=180))
    too_long = [Block(task.id, at(0, 13, 0), at(0, 15, 30))]
    over_cap = [Block(task.id, at(0, 13, 0), at(0, 15, 0)), Block(task.id, at(0, 16, 0), at(0, 17, 30))]
    assert not validate(problem, too_long, "greedy").ok
    assert not validate(problem, over_cap, "greedy").ok
