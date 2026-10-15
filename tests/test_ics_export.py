"""Calendar export (AC-19)."""

from datetime import timezone

from conftest import NOW, at, make_task
from icalendar import Calendar

from autoplanner.ics_export import build_ics, filename
from autoplanner.models import Block, PlannerState, Preferences
from autoplanner.timegrid import horizon_end


def state_with_blocks():
    task = make_task("Lab report", 3, at(3, 23, 59), course="E9 241")
    blocks = [
        Block(task.id, at(0, 21, 0), at(0, 22, 0)),  # future planned
        Block(task.id, at(1, 9, 0), at(1, 11, 0)),  # future planned
        Block(task.id, at(-1, 19, 0), at(-1, 20, 0), status="done"),  # past: not exported
    ]
    return PlannerState(Preferences(), tasks=[task], blocks=blocks)


def events_of(data: bytes):
    return [c for c in Calendar.from_ical(data).walk() if c.name == "VEVENT"]


def test_one_event_per_future_planned_block_ac19():
    state = state_with_blocks()
    events = events_of(build_ics(state, NOW, horizon_end(NOW, 7)))
    assert len(events) == 2
    for e in events:
        assert e.get("uid") and e.get("dtstart") and e.get("dtend")
    assert str(events[0].get("summary")) == "Lab report (E9 241)"
    assert "Deadline:" in str(events[0].get("description"))


def test_times_are_ist_and_convert_to_utc_ac19():
    data = build_ics(state_with_blocks(), NOW, horizon_end(NOW, 7))
    first = events_of(data)[0]
    start, end = first.decoded("dtstart"), first.decoded("dtend")
    assert first["dtstart"].params["TZID"] == "Asia/Kolkata"
    assert (start.astimezone(timezone.utc).strftime("%H:%M"), end.astimezone(timezone.utc).strftime("%H:%M")) \
        == ("15:30", "16:30")
    assert b"BEGIN:VTIMEZONE" in data and b"PRODID:-//AutoPlanner//autoplanner//EN" in data


def test_uids_are_stable_across_exports_ac19():
    state = state_with_blocks()
    first = [str(e["uid"]) for e in events_of(build_ics(state, NOW, horizon_end(NOW, 7)))]
    second = [str(e["uid"]) for e in events_of(build_ics(state, NOW, horizon_end(NOW, 7)))]
    assert first == second and len(set(first)) == 2


def test_filename():
    assert filename(NOW) == "autoplanner-2026-10-14.ics"


def test_fixed_events_can_be_included_r50():
    from conftest import weekly

    state = state_with_blocks()
    state.events = [weekly("DSA", (2, 4), "14:00", "15:00"), weekly("Gym", (2,), "18:00", "19:00", kind="blocked")]
    events = events_of(build_ics(state, NOW, horizon_end(NOW, 7), include_events=True))
    titles = [str(e["summary"]) for e in events]
    assert titles.count("DSA") == 2  # Wed and Fri inside the 7-day horizon; blocked times stay out
    assert "Gym" not in titles
    assert len(events_of(build_ics(state, NOW, horizon_end(NOW, 7)))) == 2
