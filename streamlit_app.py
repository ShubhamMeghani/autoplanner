"""AutoPlanner: plans a student's week automatically (SPEC.md).

Routes: no query parameters -> landing page; ?demo=1 -> demo; ?p=<planner id> -> a planner.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from autoplanner.config import TZ, install_log_scrubber
from autoplanner.demo import DEMO_PLANNER_ID, demo_repo
from autoplanner.models import Preferences
from autoplanner.planner import PlannerService, PlanView
from autoplanner.storage import StorageUnavailable, get_repo, is_valid_planner_id
from autoplanner.ui import calendar_view, flash, run_action, settings_view, tasks_view

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

def landing(message: str | None = None) -> None:
    st.title("AutoPlanner")
    if message:
        st.error(message)
    st.write("Plans your week automatically. Add your classes and deadlines, and AutoPlanner "
             "places study blocks so that every deadline is met, demanding work lands in your focus "
             "hours, and big tasks are split into chunks. When a block doesn't happen, the rest of "
             "the week is replanned instantly.")
    left, right = st.columns(2)
    if left.button("Try the demo", type="primary", use_container_width=True):
        st.query_params.clear()
        st.query_params["demo"] = "1"
        st.rerun()
    if right.button("Create my planner", use_container_width=True):
        create_planner()


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


def plan_tab(view: PlanView, service: PlannerService) -> None:
    if view.meta.get("fallback"):
        st.warning("Showing a quick plan — the optimizer ran out of time. "
                   f"Deadline misses: {view.meta.get('deadline_misses', 0)}, "
                   f"blocks shorter than your minimum: {view.meta.get('short_blocks', 0)}.")
    calendar_view.diagnosis_banner(view, service)
    tasks_view.overdue_panel(view, service)
    tasks_view.completion_prompts(view, service)
    selected = calendar_view.render(view)
    if selected:
        calendar_view.block_actions(view, service, selected)
    if st.button("Replan now", key="replan"):
        if run_action(service.replan, "Replanned."):
            st.rerun()


def planner_page(service: PlannerService, demo: bool, link: str | None = None) -> None:
    st.title("AutoPlanner")
    if demo:
        left, right = st.columns([4, 1])
        left.info("Demo — changes are not saved.")
        if right.button("Reset demo"):
            st.session_state.pop("demo_repo", None)
            st.rerun()
    if link and st.session_state.pop("just_created", False):
        st.success("Your planner is ready. Save this link:")
        settings_view.show_link(link)
    flash()
    try:
        view = service.view()
    except StorageUnavailable:
        st.error(STORAGE_DOWN)
        return
    plan, tasks, settings = st.tabs(["Plan", "Tasks & events", "Settings"])
    with plan:
        plan_tab(view, service)
    with tasks:
        tasks_view.render(view, service)
    with settings:
        settings_view.render(view, service, link)


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
