"""Export the plan as an .ics file for Google Calendar (R49, R50)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from icalendar import Calendar
from icalendar import Event as IcsEvent

from autoplanner.config import TZ
from autoplanner.models import PlannerState
from autoplanner.timegrid import event_intervals

PRODID = "-//AutoPlanner//autoplanner//EN"
GOOGLE_STEPS = [
    "Download the file.",
    "In Google Calendar on a computer, open Settings (⚙) → Import & export → Import.",
    "Choose the file, pick a calendar (a separate “Study plan” calendar is easiest to remove later), "
    "and click Import.",
]


def filename(now: datetime) -> str:
    return f"autoplanner-{now.astimezone(TZ):%Y-%m-%d}.ics"


def build_ics(state: PlannerState, now: datetime, horizon_end: datetime, include_events: bool = False) -> bytes:
    """One VEVENT per future planned task block, with a stable UID per block."""
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "AutoPlanner study plan")
    stamp = now.astimezone(timezone.utc)
    tasks = {t.id: t for t in state.tasks}

    for block in sorted(state.blocks, key=lambda b: b.start):
        if block.status != "planned" or block.start < now or block.task_id not in tasks:
            continue
        task = tasks[block.task_id]
        event = IcsEvent()
        event.add("uid", f"{block.id}@autoplanner")
        event.add("dtstamp", stamp)
        event.add("dtstart", block.start.astimezone(TZ))
        event.add("dtend", block.end.astimezone(TZ))
        event.add("summary", f"{task.title} ({task.course})" if task.course else task.title)
        event.add("description", f"Deadline: {task.deadline.astimezone(TZ):%a %d %b %Y, %H:%M} IST\n"
                                 "Planned by AutoPlanner")
        cal.add_component(event)

    if include_events:  # R50
        last_day = (horizon_end - timedelta(minutes=1)).date()
        for fixed in state.events:
            if fixed.kind == "blocked":
                continue
            for start, end in event_intervals(fixed, now.astimezone(TZ).date(), last_day):
                if end <= now:
                    continue
                event = IcsEvent()
                event.add("uid", f"{fixed.id}-{start:%Y%m%d}@autoplanner")
                event.add("dtstamp", stamp)
                event.add("dtstart", start)
                event.add("dtend", end)
                event.add("summary", fixed.title)
                cal.add_component(event)

    cal.add_missing_timezones()
    return cal.to_ical()
