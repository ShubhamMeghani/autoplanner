"""Manual entry and the task and event tables (R9-R12, R38)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from autoplanner.config import TASK_TYPES, TYPE_LABELS, TZ
from autoplanner.learning import correction_factor, corrected_estimate, factor_reason
from autoplanner.models import Event, Task, default_demanding, validate_task_input
from autoplanner.planner import PlannerService, PlanView
from autoplanner.timegrid import snap_times
from autoplanner.ui import fmt_dt, fmt_hours, run_action

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
KIND_LABELS = {"class": "Class", "lab": "Lab", "other": "Other fixed event", "blocked": "Blocked time"}


def _field_error(errors: dict[str, str], name: str) -> None:
    if name in errors:
        st.caption(f":red[{errors[name]}]")


def _demanding_choice(label: str, task_type: str, key: str, current: bool | None = None) -> bool:
    auto = f"Auto ({'yes' if default_demanding(task_type) else 'no'} for {TYPE_LABELS[task_type].lower()})"
    options = [auto, "Yes", "No"]
    index = 0 if current is None else (1 if current else 2)
    choice = st.radio(label, options, index=index, key=key, horizontal=True)
    return default_demanding(task_type) if choice == auto else choice == "Yes"


def estimate_inputs(tasks: list[Task], task_type: str, key: str) -> tuple[float, float]:
    """Raw estimate, and the planned estimate after the learning factor (R38)."""
    raw = st.number_input("Your estimate (hours)", min_value=0.5, max_value=40.0, step=0.5,
                          value=TASK_TYPES[task_type].default_hours, key=f"{key}_raw_{task_type}")
    factor = correction_factor(tasks, task_type)
    if factor.factor == 1.0:
        return raw, raw
    suggested = corrected_estimate(raw, factor.factor)
    st.caption(factor_reason(factor, task_type))
    used = st.number_input("Planned estimate (hours, editable)", min_value=0.5, max_value=100.0, step=0.5,
                           value=suggested, key=f"{key}_used_{task_type}_{raw}")
    return raw, used


def add_task_section(view: PlanView, service: PlannerService) -> None:
    st.subheader("Add a task")
    gen = st.session_state.setdefault("task_form_gen", 0)
    errors: dict[str, str] = st.session_state.get("task_errors", {})
    left, right = st.columns(2)
    with left:
        title = st.text_input("Title", key=f"nt_title_{gen}")
        _field_error(errors, "title")
        task_type = st.selectbox("Type", list(TYPE_LABELS), format_func=TYPE_LABELS.get, key=f"nt_type_{gen}")
        raw, used = estimate_inputs(view.state.tasks, task_type, f"nt_{gen}")
        _field_error(errors, "estimate")
    with right:
        course = st.text_input("Course (optional)", key=f"nt_course_{gen}")
        due_date = st.date_input("Deadline date", value=view.now.date() + timedelta(days=3), key=f"nt_date_{gen}")
        due_time = st.time_input("Deadline time", value=time(23, 59), step=60, key=f"nt_time_{gen}")
        _field_error(errors, "deadline")
        demanding = _demanding_choice("Demanding?", task_type, f"nt_dem_{gen}")

    if st.button("Add task", type="primary", key=f"nt_add_{gen}"):
        deadline = datetime.combine(due_date, due_time, TZ)
        found = validate_task_input(title, raw, deadline, service.now())
        if found:
            st.session_state["task_errors"] = found
            st.rerun()
        task = Task(title=title.strip(), course=course.strip() or None, type=task_type, est_hours_raw=raw,
                    est_hours=used, deadline=deadline, demanding=demanding, created_at=service.now())
        if run_action(lambda: service.change(lambda s, now: replace(s, tasks=s.tasks + [task])),
                      f"Added “{task.title}” and replanned."):
            st.session_state["task_errors"] = {}
            st.session_state["task_form_gen"] = gen + 1
            st.rerun()


def add_event_section(service: PlannerService) -> None:
    st.subheader("Add a class, lab or blocked time")
    with st.form("event_form", clear_on_submit=True):
        left, right = st.columns(2)
        title = left.text_input("Title")
        kind = right.selectbox("Kind", list(KIND_LABELS), format_func=KIND_LABELS.get)
        start = left.time_input("Start", value=time(9, 0), step=300)
        end = right.time_input("End", value=time(10, 0), step=300)
        repeat = st.radio("Repeats", ["Weekly", "One-off"], horizontal=True)
        days = st.multiselect("Days (weekly)", list(range(7)), format_func=lambda d: WEEKDAYS[d])
        until = st.date_input("Until (weekly, optional)", value=None)
        on_date = st.date_input("Date (one-off)", value=service.now().date())
        submitted = st.form_submit_button("Add")
    if not submitted:
        return
    new_start, new_end, snapped = snap_times(start, end)
    problems = []
    if not title.strip():
        problems.append("Give it a title.")
    if new_end <= new_start:
        problems.append("The end must be after the start.")
    if repeat == "Weekly" and not days:
        problems.append("Pick at least one day.")
    if problems:
        st.error(" ".join(problems))
        return
    event = Event(title=title.strip(), kind=kind, start_time=new_start, end_time=new_end,
                  on_date=on_date if repeat == "One-off" else None,
                  weekdays=tuple(sorted(days)) if repeat == "Weekly" else None,
                  until_date=until if repeat == "Weekly" else None)
    note = (f" Times were widened to the 30-minute grid: {new_start:%H:%M}–"
            f"{'24:00' if new_end == time.max else new_end.strftime('%H:%M')}." if snapped else "")
    if run_action(lambda: service.change(lambda s, now: replace(s, events=s.events + [event])),
                  f"Added “{event.title}” and replanned.{note}"):
        st.rerun()


def task_rows(view: PlanView) -> pd.DataFrame:
    beyond = set(view.meta.get("beyond_horizon", []))
    rows = []
    for t in sorted(view.state.tasks, key=lambda t: (t.status != "open", t.deadline)):
        note = {"overdue": "Overdue", "completed": "Completed"}.get(t.status, "")
        if t.id in beyond:
            note = "Continues beyond this plan"
        rows.append({"Task": t.title, "Course": t.course or "", "Type": TYPE_LABELS.get(t.type, t.type),
                     "Estimate": fmt_hours(t.est_hours * 60),
                     "Remaining": fmt_hours(view.remaining_min(t)) if t.status != "completed" else "",
                     "Deadline": fmt_dt(t.deadline), "Demanding": "★" if t.demanding else "", "Note": note})
    return pd.DataFrame(rows)


def edit_task_section(view: PlanView, service: PlannerService) -> None:
    editable = [t for t in view.state.tasks if t.status != "completed"]
    if not editable:
        return
    st.subheader("Edit or delete a task")
    labels = {t.id: f"{t.title} (due {fmt_dt(t.deadline)})" for t in editable}
    task_id = st.selectbox("Task", list(labels), format_func=labels.get, key="edit_task_id")
    task = view.state.task(task_id)
    with st.form(f"edit_{task.id}"):
        left, right = st.columns(2)
        title = left.text_input("Title", value=task.title)
        course = right.text_input("Course", value=task.course or "")
        task_type = left.selectbox("Type", list(TYPE_LABELS), index=list(TYPE_LABELS).index(task.type),
                                   format_func=TYPE_LABELS.get)
        est = right.number_input("Planned estimate (hours)", min_value=0.5, max_value=40.0, step=0.5,
                                 value=float(min(task.est_hours, 40.0)))
        due_date = left.date_input("Deadline date", value=task.deadline.astimezone(TZ).date())
        due_time = right.time_input("Deadline time", value=task.deadline.astimezone(TZ).time(), step=60)
        demanding = st.checkbox("Demanding", value=task.demanding)
        save = st.form_submit_button("Save changes", type="primary")
        delete = st.form_submit_button("Delete task")
    if save:
        deadline = datetime.combine(due_date, due_time, TZ)
        found = validate_task_input(title, est, deadline, service.now())
        if found:
            st.error(" ".join(found.values()))
            return
        status = "open" if task.status == "overdue" else task.status
        updated = replace(task, title=title.strip(), course=course.strip() or None, type=task_type,
                          est_hours=est, deadline=deadline, demanding=demanding, status=status)
        if run_action(lambda: service.change(
                lambda s, now: replace(s, tasks=[updated if t.id == task.id else t for t in s.tasks])),
                f"Saved “{updated.title}” and replanned."):
            st.rerun()
    if delete:
        if run_action(lambda: service.change(lambda s, now: replace(
                s, tasks=[t for t in s.tasks if t.id != task.id],
                blocks=[b for b in s.blocks if b.task_id != task.id])), f"Deleted “{task.title}” and replanned."):
            st.rerun()


def events_section(view: PlanView, service: PlannerService) -> None:
    st.subheader("Classes, labs and blocked times")
    if not view.state.events:
        st.caption("None yet.")
    for event in sorted(view.state.events, key=lambda e: (e.kind == "blocked", e.title)):
        when = (", ".join(WEEKDAYS[d] for d in event.weekdays) if event.weekdays is not None
                else event.on_date.strftime("%a %d %b"))
        end = "24:00" if event.end_time == time.max else event.end_time.strftime("%H:%M")
        left, right = st.columns([5, 1])
        left.write(f"**{event.title}** · {KIND_LABELS[event.kind]} · {when} {event.start_time:%H:%M}–{end}")
        if right.button("Delete", key=f"del_ev_{event.id}"):
            if run_action(lambda e=event: service.change(
                    lambda s, now: replace(s, events=[x for x in s.events if x.id != e.id])),
                    f"Deleted “{event.title}” and replanned."):
                st.rerun()


def render(view: PlanView, service: PlannerService) -> None:
    st.subheader("Tasks")
    rows = task_rows(view)
    if rows.empty:
        st.caption("No tasks yet.")
    else:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    add_task_section(view, service)
    edit_task_section(view, service)
    add_event_section(service)
    events_section(view, service)
    insights_section(view)



# ---------- prompts shown on the Plan tab (R26, R33) ----------

def completion_prompts(view: PlanView, service: PlannerService) -> None:
    """R26: a task with no work left: confirm, with the actual time."""
    from autoplanner.learning import confirmed_minutes

    for task in view.ready_to_complete():
        unconfirmed = [b for b in view.state.blocks
                       if b.task_id == task.id and b.status == "planned" and b.start < view.now]
        with st.expander(f"“{task.title}” has no work left. Mark complete?", expanded=True):
            confirm = False
            if unconfirmed:
                st.caption("Not yet confirmed: " + ", ".join(f"{fmt_dt(b.start)}–{b.end:%H:%M}" for b in unconfirmed))
                confirm = st.checkbox("Confirm these as done", key=f"confirm_{task.id}")
            minutes = confirmed_minutes(task.id, view.state.blocks)
            if confirm:
                minutes += sum(b.minutes for b in unconfirmed)
            actual = st.number_input("Actual total (hours)", min_value=0.0, max_value=200.0, step=0.25,
                                     value=round(minutes / 60, 2), key=f"actual_total_{task.id}_{confirm}")
            if unconfirmed and not confirm:
                st.caption("While blocks stay unconfirmed, this task won't be used to learn your estimates.")
            if st.button("Mark complete", type="primary", key=f"complete_{task.id}"):
                if run_action(lambda t=task, a=actual, c=confirm: service.complete_task(t.id, a, c),
                              f"“{task.title}” completed."):
                    st.rerun()


def overdue_panel(view: PlanView, service: PlannerService) -> None:
    """R33: past the deadline with work left: extend, or mark complete."""
    from autoplanner.learning import confirmed_minutes

    for task in [t for t in view.state.tasks if t.status == "overdue"]:
        with st.expander(f"Overdue: “{task.title}” (was due {fmt_dt(task.deadline)})", expanded=True):
            left, mid, right = st.columns(3)
            new_date = left.date_input("New deadline", value=view.now.date() + timedelta(days=1),
                                       key=f"od_date_{task.id}")
            new_time = mid.time_input("Time", value=time(23, 59), step=60, key=f"od_time_{task.id}")
            if right.button("Extend deadline", key=f"od_extend_{task.id}"):
                deadline = datetime.combine(new_date, new_time, TZ)
                if deadline <= service.now():
                    st.error("The new deadline must be in the future.")
                elif run_action(lambda t=task, d=deadline: service.extend_deadline(t.id, d),
                                "Deadline extended and the week replanned."):
                    st.rerun()
            if right.button("Mark complete", key=f"od_complete_{task.id}"):
                hours = confirmed_minutes(task.id, view.state.blocks) / 60
                if run_action(lambda t=task, h=hours: service.complete_task(t.id, h), f"“{task.title}” completed."):
                    st.rerun()


# ---------- plan summary (R22) and estimate insights (R39) ----------

def plan_summary_rows(view: PlanView) -> pd.DataFrame:
    """For each open task: hours scheduled, remaining, planned finish, and slack to the deadline."""
    beyond = set(view.meta.get("beyond_horizon", []))
    unscheduled = view.meta.get("unscheduled_min", {}) or {}
    rows = []
    for task in sorted((t for t in view.state.tasks if t.status == "open"), key=lambda t: t.deadline):
        blocks = [b for b in view.future_blocks if b.task_id == task.id]
        scheduled = sum(b.minutes for b in blocks)
        finish = max((b.end for b in blocks), default=None)
        if task.id in unscheduled:
            slack = f"{fmt_hours(unscheduled[task.id])} doesn't fit"
        elif task.id in beyond:
            slack = "Continues beyond this plan"
        elif finish is not None:
            hours = (task.deadline - finish).total_seconds() / 3600
            slack = f"{hours:.0f} h" if hours >= 1 else f"{hours * 60:.0f} min"
        else:
            slack = ""
        rows.append({"Task": task.title, "Scheduled": fmt_hours(scheduled), "Remaining": fmt_hours(view.remaining_min(task)),
                     "Planned finish": fmt_dt(finish) if finish else "", "Deadline": fmt_dt(task.deadline),
                     "Slack": slack})
    return pd.DataFrame(rows)


def insights_rows(tasks: list[Task]) -> pd.DataFrame:
    from autoplanner.learning import correction_factor

    rows = []
    for task_type, label in TYPE_LABELS.items():
        f = correction_factor(tasks, task_type)
        if f.n:
            rows.append({"Type": label, "Factor": f"{f.factor:.2f}×", "Tasks": f.n,
                         "Actual ÷ estimate": f"{f.r:.2f}"})
    return pd.DataFrame(rows)


def summary_section(view: PlanView) -> None:
    rows = plan_summary_rows(view)
    if not rows.empty:
        with st.expander("Plan summary", expanded=False):
            st.dataframe(rows, hide_index=True, use_container_width=True)


def insights_section(view: PlanView) -> None:
    st.subheader("Estimate insights")
    rows = insights_rows(view.state.tasks)
    if rows.empty:
        st.caption("Complete a few tasks (and confirm their blocks) to see how your estimates compare.")
    else:
        st.caption("New tasks of these types get their estimate multiplied by the factor; you can always override it.")
        st.dataframe(rows, hide_index=True, use_container_width=True)
