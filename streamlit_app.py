"""AutoPlanner: plans a student's week automatically (SPEC.md).

Routes: no query parameters -> landing page; ?demo=1 -> demo; ?p=<planner id> -> a planner.
"""

from __future__ import annotations

import logging
from datetime import datetime

import streamlit as st

from autoplanner.config import TZ
from autoplanner.demo import DEMO_PLANNER_ID, demo_repo
from autoplanner.planner import PlannerService, PlanView
from autoplanner.ui import calendar_view

log = logging.getLogger("autoplanner")
st.set_page_config(page_title="AutoPlanner", page_icon="🗓️", layout="wide")


def now() -> datetime:
    return datetime.now(TZ)


# ---------- pages ----------

def landing() -> None:
    st.title("AutoPlanner")
    st.write("Plans your week automatically. Add your classes and deadlines, and AutoPlanner "
             "places study blocks so that every deadline is met, demanding work lands in your focus "
             "hours, and big tasks are split into chunks. When a block doesn't happen, the rest of "
             "the week is replanned instantly.")
    left, right = st.columns(2)
    if left.button("Try the demo", type="primary", use_container_width=True):
        st.query_params["demo"] = "1"
        st.rerun()
    if right.button("Create my planner", use_container_width=True):
        st.session_state["create_planner"] = True
        st.rerun()


def demo_service() -> PlannerService:
    if "demo_repo" not in st.session_state:
        st.session_state["demo_repo"] = demo_repo(now())
    return PlannerService(st.session_state["demo_repo"], DEMO_PLANNER_ID)


def plan_banners(view: PlanView) -> None:
    meta = view.meta
    if meta.get("fallback"):
        st.warning("Showing a quick plan — the optimizer ran out of time. "
                   f"Deadline misses: {meta.get('deadline_misses', 0)}, "
                   f"blocks shorter than your minimum: {meta.get('short_blocks', 0)}.")
    if view.diagnosis:
        hours = sum(view.diagnosis["shortfall_min"].values()) / 60
        st.error(f"Can't fit everything before the deadlines: {hours:g} h don't fit.")


def plan_tab(view: PlanView) -> None:
    plan_banners(view)
    selected = calendar_view.render(view)
    if selected:
        block = view.state.block(selected)
        task = view.state.task(block.task_id) if block else None
        if block and task:
            st.markdown(f"**{task.title}** · {block.start:%a %d %b %H:%M}–{block.end:%H:%M} · {block.status}")


def planner_page(service: PlannerService, demo: bool) -> None:
    if demo:
        st.info("Demo — changes are not saved.")
        if st.button("Reset demo"):
            st.session_state.pop("demo_repo", None)
            st.rerun()
    view = service.view()
    st.title("AutoPlanner")
    (plan,) = st.tabs(["Plan"])
    with plan:
        plan_tab(view)


def main() -> None:
    params = st.query_params
    if params.get("demo") == "1":
        planner_page(demo_service(), demo=True)
    else:
        landing()


try:
    main()
except Exception:
    log.exception("unhandled error")
    st.error("Something went wrong, and nothing was changed. Please reload the page.")
