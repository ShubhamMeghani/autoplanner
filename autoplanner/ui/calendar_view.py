"""Calendar and block selection (R21, R25). Pure helpers build the FullCalendar input."""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta

import streamlit as st

from autoplanner.config import TZ
from autoplanner.models import Block, Event, Task
from autoplanner.planner import PlanView
from autoplanner.timegrid import event_intervals

COURSE_COLOURS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0d9488", "#65a30d", "#0891b2", "#c026d3"]
EVENT_COLOUR = "#64748b"
BLOCKED_COLOUR = "#cbd5e1"
STATUS_PREFIX = {"done": "✓ ", "not_done": "✗ ", "skipped": "⤼ "}
RECENT_DAYS = 2  # past days shown first and offered for feedback (R21, R51)
DETAILS_ANCHOR = "block-details"


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
        # The week view opens 2 days before today, so recent blocks can be marked at once (R21).
        "initialDate": (today - timedelta(days=RECENT_DAYS)).isoformat(),
        "firstDay": ((today - timedelta(days=RECENT_DAYS)).weekday() + 1) % 7,  # FullCalendar: 0 = Sunday
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
    """Blocks the user can act on: everything from midnight 2 days ago onwards."""
    since = datetime.combine(view.now.date() - timedelta(days=RECENT_DAYS), time(0), TZ)
    return sorted((b for b in view.state.blocks if b.start >= since and b.status != "skipped"),
                  key=lambda b: b.start)


def apply_click(state: dict | None, version: int, selectable: set[str], session) -> bool:
    """Turn a calendar click into a selection. The component returns its last click on every
    rerun, so each click is applied once. Returns True for a new block selection, and asks the
    details panel to scroll into view and announce itself (R21)."""
    if not state or state.get("callback") != "eventClick":
        return False
    event_id = state["eventClick"]["event"]["id"]
    click_key = (version, event_id)
    if click_key == session.get("_last_click"):
        return False
    session["_last_click"] = click_key
    block_id = event_id.removeprefix("block:")
    if not event_id.startswith("block:") or block_id not in selectable:
        return False
    session["selected_block"] = block_id
    session["scroll_to_block"] = True
    return True


def scroll_to_details() -> None:
    """Smoothly scroll the page to the selected block's details (retries until it is drawn)."""
    import streamlit.components.v1 as components

    components.html(f"""<script>
      const go = (n) => {{
        const el = window.parent.document.getElementById("{DETAILS_ANCHOR}");
        if (el) {{ el.scrollIntoView({{behavior: "smooth", block: "start"}}); }}
        else if (n > 0) {{ setTimeout(() => go(n - 1), 100); }}
      }};
      go(30);
    </script>""", height=0)


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

    apply_click(state, version, set(labels), st.session_state)
    if st.session_state.get("selected_block") not in labels:
        st.session_state["selected_block"] = None
    selected = st.selectbox("Select a block (or click one in the calendar)", ids,
                            format_func=lambda i: "—" if i is None else labels[i], key="selected_block")
    return selected


# ---------- block actions and the infeasibility report (R23, R24, R29-R32) ----------

def block_actions(view: PlanView, service, block_id: str) -> None:
    from autoplanner.ui import fmt_dt

    block = view.state.block(block_id)
    task = view.state.task(block.task_id) if block else None
    if not block or not task:
        return
    status = {"planned": "planned", "done": "done", "not_done": "not done"}.get(block.status, block.status)
    if block.status == "planned" and block.start < view.now:
        status = "unconfirmed"
    with st.container(border=True):  # highlighted details panel (R21)
        st.markdown(f'<div id="{DETAILS_ANCHOR}"></div>', unsafe_allow_html=True)
        st.markdown(":blue-background[**📌 Selected block**]")
        st.markdown(f"**{task.title}** · {fmt_dt(block.start)}–{block.end:%H:%M} · {status}")
        if st.session_state.pop("scroll_to_block", False):
            st.toast(f"Selected: {task.title}, {fmt_dt(block.start)}", icon="📌")
            scroll_to_details()
        _block_buttons(view, service, block)


def _block_buttons(view: PlanView, service, block: Block) -> None:
    from autoplanner.ui import run_action

    if block.start > view.now:
        st.caption("You can mark this block once it has started.")
        if block.status == "planned" and st.button("Can't do this slot", key=f"cantdo_{block.id}"):  # R27
            if run_action(lambda: service.cant_do(block.id),
                          "That time is now blocked and the week was replanned around it."):
                st.rerun()
        return
    left, right = st.columns(2)
    with left:
        minutes = st.number_input("Time taken (minutes)", min_value=0, max_value=600, step=5,
                                  value=block.actual_minutes if block.actual_minutes is not None else block.minutes,
                                  key=f"actual_{block.id}")
        if st.button("Done", type="primary", key=f"done_{block.id}"):
            if run_action(lambda: service.mark_done(block.id, int(minutes)), "Marked done."):
                st.rerun()
    with right:
        completed = st.number_input("Minutes completed, if any", min_value=0, max_value=block.minutes, step=5,
                                    value=0, key=f"partial_{block.id}")  # R28
        if st.button("Not done", key=f"notdone_{block.id}"):
            if run_action(lambda: service.mark_not_done(block.id, int(completed)),
                          "Marked not done; the rest of the week was replanned."):
                st.rerun()


def diagnosis_banner(view: PlanView, service) -> None:
    from autoplanner.ui import fmt_dt, fmt_hours, run_action

    diagnosis = view.diagnosis
    if not diagnosis:
        return
    tasks = {t.id: t for t in view.state.tasks}
    name = lambda tid: tasks[tid].title if tid in tasks else "a deleted task"  # noqa: E731
    shortfall = diagnosis["shortfall_min"]
    st.error(f"**Can't fit everything before the deadlines.** {fmt_hours(sum(shortfall.values()))} of work "
             "doesn't fit. The calendar shows the best plan possible; this work is left out: "
             + ", ".join(f"{name(t)} ({fmt_hours(m)})" for t, m in shortfall.items()) + ".")
    st.markdown("**Ways to make it fit** (each one has been checked):")
    for task_id, iso in diagnosis.get("extend") or []:
        new_deadline = datetime.fromisoformat(iso)
        left, right = st.columns([4, 1])
        left.write(f"Extend “{name(task_id)}” to {fmt_dt(new_deadline)}")
        if right.button("Apply", key=f"extend_{task_id}"):
            if run_action(lambda t=task_id, d=new_deadline: service.extend_deadline(t, d),
                          "Deadline extended and the week replanned."):
                st.rerun()
    cut = diagnosis.get("cut")
    if cut:
        left, right = st.columns([4, 1])
        left.write("Cut hours: " + ", ".join(f"{name(t)} −{fmt_hours(m)}" for t, m in cut.items())
                   + f" ({fmt_hours(sum(cut.values()))} in total)")
        if right.button("Apply", key="apply_cut"):
            if run_action(lambda: service.cut_hours(cut), "Estimates reduced and the week replanned."):
                st.rerun()
    if diagnosis.get("no_single_extension"):
        st.caption("No single deadline extension within this plan's horizon makes everything fit.")
    if diagnosis.get("cut_short"):
        st.caption("The search for options was cut short after 15 seconds; these are the options found so far.")
