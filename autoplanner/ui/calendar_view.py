"""Calendar and block selection (R21, R25). Pure helpers build the FullCalendar input."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import streamlit as st

from autoplanner.config import TZ
from autoplanner.models import Block, Event, Task
from autoplanner.planner import PlanView
from autoplanner.timegrid import event_intervals

COURSE_COLOURS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0d9488", "#65a30d", "#0891b2", "#c026d3"]
EVENT_COLOUR = "#64748b"
BLOCKED_COLOUR = "#cbd5e1"
STATUS_PREFIX = {"done": "✓ ", "not_done": "✗ ", "skipped": "⤼ "}


def course_colour(course: str | None) -> str:
    digest = hashlib.md5((course or "").encode()).digest()
    return COURSE_COLOURS[digest[0] % len(COURSE_COLOURS)]


def wall(dt: datetime) -> str:
    """IST wall-clock time without an offset. FullCalendar runs in UTC mode, so it shows IST
    in every browser (R59)."""
    return dt.astimezone(TZ).replace(tzinfo=None).isoformat(timespec="minutes")


def block_label(block: Block, task: Task | None, now: datetime) -> str:
    title = task.title if task else "Deleted task"
    if task and task.course:
        title = f"{title} ({task.course})"
    prefix = STATUS_PREFIX.get(block.status, "")
    if block.status == "planned" and block.start < now:
        prefix = "⏳ "  # unconfirmed (R25)
    star = "★ " if task and task.demanding else ""
    return f"{prefix}{star}{title}"


def calendar_events(view: PlanView, history_days: int = 7) -> list[dict]:
    """Fixed events, blocked times and task blocks for the visible range."""
    state, now = view.state, view.now
    first = (now - timedelta(days=history_days)).date()
    last = (view.horizon_end - timedelta(minutes=1)).date()
    tasks = {t.id: t for t in state.tasks}
    out: list[dict] = []
    for event in state.events:
        blocked = event.kind == "blocked"
        for start, end in event_intervals(event, first, last):
            out.append({
                "id": f"event:{event.id}:{start:%Y%m%d}", "title": event.title,
                "start": wall(start), "end": wall(end),
                "backgroundColor": BLOCKED_COLOUR if blocked else EVENT_COLOUR,
                "borderColor": BLOCKED_COLOUR if blocked else EVENT_COLOUR,
                "textColor": "#334155" if blocked else "#ffffff",
                "extendedProps": {"kind": "blocked" if blocked else "event"},
            })
    for block in state.blocks:
        if block.start.date() < first or block.status == "skipped":
            continue
        task = tasks.get(block.task_id)
        colour = course_colour(task.course if task else None)
        faded = block.status in ("done", "not_done") or block.start < now
        out.append({
            "id": f"block:{block.id}", "title": block_label(block, task, now),
            "start": wall(block.start), "end": wall(block.end),
            "backgroundColor": colour + ("88" if faded else ""), "borderColor": colour,
            "extendedProps": {"kind": "block", "status": block.status},
        })
    return out


def calendar_options(view: PlanView) -> dict:
    """Week and day views, starting today, limited to the horizon (R21)."""
    today = view.now.date()
    return {
        "initialView": "timeGridWeek",
        "initialDate": today.isoformat(),
        "firstDay": (today.weekday() + 1) % 7,  # the week view starts today
        "timeZone": "UTC",
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridWeek,timeGridDay"},
        "validRange": {"start": (today - timedelta(days=7)).isoformat(),
                       "end": view.horizon_end.date().isoformat()},
        "slotDuration": "00:30:00",
        "slotMinTime": "07:00:00",
        "slotMaxTime": "24:00:00",
        "allDaySlot": False,
        "nowIndicator": True,
        "height": 760,
    }


def block_choices(view: PlanView) -> list[Block]:
    """Blocks the user can act on: the last two days and everything still planned."""
    since = view.now - timedelta(days=2)
    return sorted((b for b in view.state.blocks if b.start >= since and b.status != "skipped"),
                  key=lambda b: b.start)


def render(view: PlanView) -> str | None:
    """Draw the calendar and return the ID of the block the user selected, if any."""
    from streamlit_calendar import calendar

    version = view.meta.get("plan_version", 0)
    state = calendar(events=calendar_events(view), options=calendar_options(view),
                     callbacks=["eventClick"], key=f"calendar-{version}")
    tasks = {t.id: t for t in view.state.tasks}
    choices = block_choices(view)
    ids = [None] + [b.id for b in choices]
    labels = {b.id: f"{b.start:%a %d %b %H:%M}–{b.end:%H:%M} · {block_label(b, tasks.get(b.task_id), view.now)}"
              for b in choices}

    # The component returns its last click on every rerun: apply each click only once.
    if state and state.get("callback") == "eventClick":
        event_id = state["eventClick"]["event"]["id"]
        click_key = (version, event_id)
        if click_key != st.session_state.get("_last_click"):
            st.session_state["_last_click"] = click_key
            block_id = event_id.removeprefix("block:")
            if event_id.startswith("block:") and block_id in labels:
                st.session_state["selected_block"] = block_id
    if st.session_state.get("selected_block") not in labels:
        st.session_state["selected_block"] = None
    selected = st.selectbox("Select a block (or click one in the calendar)", ids,
                            format_func=lambda i: "—" if i is None else labels[i], key="selected_block")
    return selected
