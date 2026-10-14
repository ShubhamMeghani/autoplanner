from datetime import datetime, time, timedelta

from conftest import NOW, TODAY, at, one_off, weekly

from autoplanner.config import TZ
from autoplanner.models import Preferences
from autoplanner.timegrid import build_grid, ceil_to_slot, floor_to_slot, horizon_end, snap_times


def test_snap_widens_to_grid_ac26():
    start, end, changed = snap_times(time(9, 10), time(10, 20))
    assert (start, end, changed) == (time(9, 0), time(10, 30), True)


def test_snap_leaves_aligned_times_alone():
    assert snap_times(time(9, 0), time(10, 30)) == (time(9, 0), time(10, 30), False)


def test_snap_end_past_2330_becomes_end_of_day():
    _, end, changed = snap_times(time(22, 0), time(23, 45))
    assert end == time.max and changed


def test_ceil_and_floor():
    t = datetime(2026, 10, 14, 10, 7, tzinfo=TZ)
    assert floor_to_slot(t) == datetime(2026, 10, 14, 10, 0, tzinfo=TZ)
    assert ceil_to_slot(t) == datetime(2026, 10, 14, 10, 30, tzinfo=TZ)
    assert ceil_to_slot(NOW) == NOW


def test_grid_spans_now_to_horizon_end(prefs):
    grid = build_grid(NOW + timedelta(minutes=5), prefs, [])
    assert grid.start == at(0, 10, 30)
    assert grid.end == horizon_end(NOW, 7) == at(7, 0)
    assert grid.n == int((grid.end - grid.start) / timedelta(minutes=30))


def test_working_day_and_focus(prefs):
    grid = build_grid(NOW, prefs, [])
    assert grid.available[grid.index_of(at(0, 22, 30))]
    assert not grid.available[grid.index_of(at(0, 23, 0))]
    assert not grid.available[grid.index_of(at(1, 7, 30))]
    assert grid.available[grid.index_of(at(1, 8, 0))]
    assert grid.focus[grid.index_of(at(1, 9, 0))] and not grid.focus[grid.index_of(at(1, 12, 0))]


def test_events_and_blocked_times_remove_slots(prefs):
    events = [weekly("DSA", (0, 2, 4), "11:00", "12:30"), one_off("Gym", TODAY + timedelta(days=1), "18:00", "19:00")]
    grid = build_grid(NOW, prefs, events)
    assert not grid.available[grid.index_of(at(0, 11, 0))]  # Wednesday class
    assert not grid.available[grid.index_of(at(0, 12, 0))]
    assert grid.available[grid.index_of(at(0, 12, 30))]
    assert grid.available[grid.index_of(at(1, 11, 0))]  # Thursday: no class
    assert not grid.available[grid.index_of(at(1, 18, 30))]  # gym


def test_weekly_event_respects_until_date(prefs):
    ev = weekly("Lab", (2,), "14:00", "16:00")
    ev = ev.__class__(**{**ev.__dict__, "until_date": TODAY})
    grid = build_grid(NOW, Preferences(horizon_days=14), [ev])
    assert not grid.available[grid.index_of(at(0, 14, 0))]
    assert grid.available[grid.index_of(at(7, 14, 0))]
