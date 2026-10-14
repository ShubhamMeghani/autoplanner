"""Repository contract and planner IDs (AC-1, AC-2, AC-40). SupabaseRepo shares this contract."""

from datetime import datetime, timedelta

from conftest import NOW, at, make_task, weekly

from autoplanner.config import TZ
from autoplanner.models import Block, PlannerState, Preferences
from autoplanner.storage import MemoryRepo, is_valid_planner_id, new_planner_id, save_changes


def test_planner_ids_are_long_random_and_validated_ac1():
    ids = {new_planner_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(len(i) == 43 and is_valid_planner_id(i) for i in ids)


def test_malformed_ids_are_rejected_ac2():
    good = new_planner_id()
    for bad in ("", "doesnotexist", good[:-1], good + "x", good[:-1] + "!", None):
        assert not is_valid_planner_id(bad)


def test_create_load_and_exists():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences(horizon_days=5))
    assert repo.planner_exists(pid) and not repo.planner_exists(new_planner_id())
    assert repo.load(pid).prefs.horizon_days == 5


def test_planners_are_isolated_ac40():
    repo = MemoryRepo()
    a, b = repo.create_planner(Preferences()), repo.create_planner(Preferences())
    ta, tb = make_task("A only"), make_task("B only")
    repo.upsert_tasks(a, [ta])
    repo.upsert_tasks(b, [tb])
    repo.upsert_events(b, [weekly("B class", (0,), "09:00", "10:00")])
    repo.upsert_blocks(b, [Block(tb.id, at(1, 9), at(1, 10))])
    state_a = repo.load(a)
    assert [t.title for t in state_a.tasks] == ["A only"]
    assert state_a.events == [] and state_a.blocks == []
    repo.delete_tasks(a, [tb.id])  # an ID from B, via A: no effect on B
    assert [t.title for t in repo.load(b).tasks] == ["B only"]


def test_save_changes_writes_the_difference_and_meta_last():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    keep, drop = make_task("Keep"), make_task("Drop")
    old = PlannerState(Preferences(), tasks=[keep, drop], blocks=[Block(drop.id, at(1, 9), at(1, 10))])
    save_changes(repo, pid, PlannerState(Preferences()), old)
    new = PlannerState(Preferences(horizon_days=3), tasks=[keep], meta={"input_hash": "h"})
    calls = []

    class Spy:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(repo, name)

    save_changes(Spy(), pid, old, new)
    state = repo.load(pid)
    assert [t.title for t in state.tasks] == ["Keep"] and state.blocks == []
    assert state.meta == {"input_hash": "h"} and state.prefs.horizon_days == 3
    assert calls[-1] == "save_prefs"


def test_deleting_a_task_cascades_to_its_blocks():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    task = make_task("A")
    repo.upsert_tasks(pid, [task])
    repo.upsert_blocks(pid, [Block(task.id, at(1, 9), at(1, 10))])
    repo.delete_tasks(pid, [task.id])
    assert repo.load(pid).blocks == []


def test_gemini_calls_are_counted_per_planner_and_day():
    repo = MemoryRepo()
    a, b = repo.create_planner(Preferences()), repo.create_planner(Preferences())
    midnight = datetime.combine(NOW.date(), datetime.min.time(), TZ)
    repo.log_import(a, "gemini", at=NOW)
    repo.log_import(a, "tesseract", at=NOW)
    repo.log_import(a, "gemini", at=midnight - timedelta(minutes=1))
    repo.log_import(b, "gemini", at=NOW)
    assert repo.count_gemini_calls(a, midnight) == 1


def test_delete_planner_removes_everything():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    repo.upsert_tasks(pid, [make_task("A")])
    repo.delete_planner(pid)
    assert not repo.planner_exists(pid)


def test_logs_never_contain_keys_or_planner_ids_r5():
    from autoplanner.config import scrub

    pid = new_planner_id()
    text = f"failed for planner {pid} with key sb_secret_{'x' * 24} and AQ.{'y' * 30}"
    cleaned = scrub(text)
    assert pid not in cleaned and "sb_secret_x" not in cleaned and "AQ.yyy" not in cleaned
    assert cleaned.count("<redacted>") == 3
