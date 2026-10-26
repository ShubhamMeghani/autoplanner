"""AutoPlanner: plans a student's week automatically (SPEC.md).

Routes: no query parameters -> landing page; ?demo=1 -> demo; ?p=<planner id> -> a planner.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from autoplanner.config import TZ, install_log_scrubber
from autoplanner.demo import DEMO_PLANNER_ID, demo_repo, with_overload
from autoplanner.ics_export import GOOGLE_STEPS, build_ics, filename
from autoplanner.models import Preferences
from autoplanner.planner import PlannerService, PlanView
from autoplanner.storage import StorageUnavailable, get_repo, is_valid_planner_id
from autoplanner.ui import (calendar_view, card, flash, import_view, results_view, run_action, settings_view,
                            tasks_view)

log = install_log_scrubber()
st.set_page_config(page_title="AutoPlanner", page_icon="🗓️", layout="wide")

NOT_FOUND = "Planner not found. Check the link, or start fresh below."
STORAGE_DOWN = "Storage is unavailable right now; try the demo or retry later."


def now() -> datetime:
    return datetime.now(TZ)


def planner_link(planner_id: str) -> str:
    base = (st.context.url or "").split("?")[0] or "/"
    return f"{base}?p={planner_id}"


# ---------- pages ----------

FEATURES = [
    ("🎯", "Every deadline met",
     "An optimizer places 30-minute study blocks before each deadline, with demanding work in your focus hours."),
    ("🔁", "Replans instantly",
     "Mark a block not done and the rest of the week is rebuilt from now. If it can't all fit, you get "
     "checked options."),
    ("📋", "Import from Teams",
     "Paste a screenshot of the Assignments list with Ctrl+V. Titles, courses and due dates are read for you "
     "to review."),
]


def landing(message: str | None = None) -> None:
    st.title("🗓️ AutoPlanner")
    st.markdown("##### Your week, planned automatically.")
    if message:
        st.error(message)
    deleted = st.session_state.pop("landing_message", None)
    if deleted:
        st.success(deleted)
    st.write("Add your classes and deadlines, and AutoPlanner "
             "places study blocks so that every deadline is met, demanding work lands in your focus "
             "hours, and big tasks are split into chunks. When a block doesn't happen, the rest of "
             "the week is replanned instantly.")
    left, right = st.columns(2, gap="medium")
    if left.button("Try the demo", type="primary", width="stretch"):
        st.query_params.clear()
        st.query_params["demo"] = "1"
        st.rerun()
    if right.button("Create my planner", width="stretch"):
        create_planner()
    st.caption("Free · no sign-up · your planner lives at a private link")
    st.write("")
    for column, (icon, title, text) in zip(st.columns(3, gap="medium"), FEATURES):
        with column.container(border=True, height="stretch"):
            st.markdown(f"**{icon} {title}**")
            st.caption(text)


def create_planner() -> None:
    try:
        planner_id = get_repo().create_planner(Preferences())
    except StorageUnavailable:
        st.error(STORAGE_DOWN)
        return
    st.session_state["just_created"] = True
    st.query_params.clear()
    st.query_params["p"] = planner_id
    st.rerun()


def demo_service() -> PlannerService:
    if "demo_repo" not in st.session_state:
        st.session_state["demo_repo"] = demo_repo(now())
    return PlannerService(st.session_state["demo_repo"], DEMO_PLANNER_ID)


def overload_toggle(view: PlanView, service: PlannerService) -> None:
    """R53: demo only. Adds work that can't fit, to show the infeasibility report."""
    loaded = any(t.id.startswith("demo-ov") for t in view.state.tasks)
    wanted = st.toggle("Overload the week", value=loaded, key="overload",
                       help="Adds two big assignments due in the next two days.")
    if wanted != loaded:
        message = "Added two big assignments." if wanted else "Removed the extra assignments."
        if run_action(lambda: service.change(lambda s, now: with_overload(s, now, wanted)), message):
            st.rerun()


def status_strip(view: PlanView) -> None:
    """Three numbers at a glance: display only."""
    future = view.future_blocks
    if view.diagnosis:
        status = "Doesn't fit"
    elif view.meta.get("fallback"):
        status = "Quick plan"
    else:
        status = "All deadlines fit"
    hours, tasks, state = st.columns(3, gap="medium")
    hours.metric("Study time planned", f"{sum(b.minutes for b in future) / 60:g} h", border=True)
    tasks.metric("Tasks scheduled", len({b.task_id for b in future}), border=True)
    state.metric("Plan status", status, border=True)


def plan_tab(view: PlanView, service: PlannerService, demo: bool = False) -> None:
    status_strip(view)
    if demo:
        overload_toggle(view, service)
    if view.meta.get("fallback"):
        st.warning("Showing a quick plan — the optimizer ran out of time. "
                   f"Deadline misses: {view.meta.get('deadline_misses', 0)}, "
                   f"blocks shorter than your minimum: {view.meta.get('short_blocks', 0)}.")
    calendar_view.diagnosis_banner(view, service)
    tasks_view.overdue_panel(view, service)
    tasks_view.completion_prompts(view, service)
    if not view.state.events and not any(t.status == "open" for t in view.state.tasks):
        st.info("Your week is empty. Add your classes and tasks on the **Tasks & events** tab, "
                "or import assignments on the **Import** tab.", icon="🗓️")
    with st.container(border=True):
        selected = calendar_view.render(view)
        if st.button("Replan now", key="replan", help="Rebuild the plan from now with the latest data."):
            if run_action(service.replan, "Replanned."):
                st.rerun()
    if selected:
        calendar_view.block_actions(view, service, selected)
    tasks_view.summary_section(view)
    export_section(view)


def export_section(view: PlanView) -> None:
    with card("Export to Google Calendar", "Your planned study blocks as an .ics file."):
        include = st.checkbox("Include classes and labs", key="ics_events")  # R50
        data = build_ics(view.state, view.now, view.horizon_end, include_events=include)
        st.download_button("Export to Google Calendar (.ics)", data=data, file_name=filename(view.now),
                           mime="text/calendar", key="export_ics", icon="📥")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(GOOGLE_STEPS, 1)))


def page_header(demo: bool) -> None:
    title, action = st.columns([5, 1], vertical_alignment="center")
    title.title("🗓️ AutoPlanner")
    if demo:
        if action.button("Reset demo", width="stretch"):
            st.session_state.pop("demo_repo", None)
            st.rerun()
        st.info("Demo — changes are not saved.", icon="🧪")


def planner_page(service: PlannerService, demo: bool, link: str | None = None) -> None:
    page_header(demo)
    if link and st.session_state.pop("just_created", False):
        st.success("Your planner is ready. Save this link:")
        settings_view.show_link(link)
    flash()
    try:
        with st.spinner("Planning your week…"):
            view = service.view()
    except StorageUnavailable:
        st.error(STORAGE_DOWN)
        return
    plan, tasks, imports, settings, results = st.tabs(["Plan", "Tasks & events", "Import", "Settings", "Results"])
    with plan:
        plan_tab(view, service, demo)
    with tasks:
        tasks_view.render(view, service)
    with imports:
        import_view.render(view, service, demo)
    with settings:
        settings_view.render(view, service, link)
    with results:
        results_view.render()


def planner_route(planner_id: str) -> None:
    if not is_valid_planner_id(planner_id):
        landing(NOT_FOUND)
        return
    try:
        repo = get_repo()
        exists = repo.planner_exists(planner_id)
    except StorageUnavailable:
        landing(STORAGE_DOWN)
        return
    if not exists:
        landing(NOT_FOUND)  # same message as a malformed ID (R4)
        return
    planner_page(PlannerService(repo, planner_id), demo=False, link=planner_link(planner_id))


def main() -> None:
    params = st.query_params
    if params.get("demo") == "1":
        planner_page(demo_service(), demo=True)
    elif "p" in params:
        planner_route(params.get("p", ""))
    else:
        landing()


try:
    main()
except Exception:
    log.exception("unhandled error")
    st.error("Something went wrong, and nothing was changed. Please reload the page.")
