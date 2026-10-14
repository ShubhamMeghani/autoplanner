"""Learning from actual time (AC-13)."""

from conftest import NOW, at, make_task

from autoplanner.learning import correction_factor, corrected_estimate, factor_reason
from autoplanner.models import Block, PlannerState, Preferences
from autoplanner.planner import complete_task


def lab(raw: float, actual: float, eligible: bool = True, days_ago: int = 3):
    return make_task("Lab", raw, at(-days_ago, 23, 59), type="lab_report", status="completed",
                     actual_hours=actual, learning_eligible=eligible, completed_at=at(-days_ago, 20))


def test_factor_from_three_labs_and_rounding_ac13():
    tasks = [lab(2, 3, days_ago=d) for d in (3, 4, 5)]
    f = correction_factor(tasks, "lab_report")
    assert (f.n, round(f.r, 3), round(f.factor, 3)) == (3, 1.5, 1.3)
    assert corrected_estimate(2.0, f.factor) == 2.5  # 2.6 -> nearest 0.5
    assert "1.3×" in factor_reason(f, "lab_report") and "3 tasks" in factor_reason(f, "lab_report")


def test_unconfirmed_work_does_not_change_the_factor_then_confirming_does_ac13():
    history = [lab(2, 3, days_ago=d) for d in (3, 4, 5)]
    fourth = make_task("Lab 4", 2, at(1, 23, 59), type="lab_report")
    blocks = [Block(fourth.id, at(-1, 18), at(-1, 21), status="done", actual_minutes=180),
              Block(fourth.id, at(0, 8), at(0, 9))]  # past, unconfirmed
    state = PlannerState(Preferences(), tasks=history + [fourth], blocks=blocks)

    kept = complete_task(state, NOW, fourth.id, actual_hours=6.0, confirm_unconfirmed=False)
    assert kept.task(fourth.id).learning_eligible is False
    assert round(correction_factor(kept.tasks, "lab_report").factor, 3) == 1.3

    confirmed = complete_task(state, NOW, fourth.id, actual_hours=6.0, confirm_unconfirmed=True)
    assert confirmed.task(fourth.id).learning_eligible is True
    assert all(b.status == "done" for b in confirmed.blocks)
    f = correction_factor(confirmed.tasks, "lab_report")
    assert f.n == 4 and round(f.factor, 3) != 1.3


def test_no_history_gives_factor_one_ac13():
    assert correction_factor([], "lab_report").factor == 1.0
    assert correction_factor([lab(2, 3, eligible=False)], "lab_report").factor == 1.0


def test_factor_is_clamped_ac13():
    tasks = [lab(1, 10, days_ago=d) for d in range(2, 12)]
    assert correction_factor(tasks, "lab_report").factor == 2.5
    tasks = [lab(10, 1, days_ago=d) for d in range(2, 12)]
    assert correction_factor(tasks, "lab_report").factor == 0.5


def test_only_the_last_ten_count():
    old = [lab(2, 8, days_ago=d) for d in range(30, 40)]
    recent = [lab(2, 2, days_ago=d) for d in range(2, 12)]
    assert correction_factor(old + recent, "lab_report").factor == 1.0


def test_rounding_ties_go_up():
    assert corrected_estimate(1.25, 1.0) == 1.5
    assert corrected_estimate(1.24, 1.0) == 1.0
