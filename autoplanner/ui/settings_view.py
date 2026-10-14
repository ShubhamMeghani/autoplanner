"""Preferences (R13) and the private link (R2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import time

import streamlit as st

from autoplanner.config import MAX_HORIZON_DAYS
from autoplanner.models import Preferences, validate_prefs
from autoplanner.planner import PlannerService, PlanView
from autoplanner.ui import run_action

LINK_WARNING = ("Anyone with this link can view and edit your planner. "
                "Bookmark it — there is no other way back in.")


def show_link(link: str) -> None:
    st.code(link, language=None)
    st.warning(LINK_WARNING)


def render(view: PlanView, service: PlannerService, link: str | None = None) -> None:
    if link:
        st.subheader("Your private link")
        show_link(link)

    prefs = view.state.prefs
    st.subheader("Preferences")
    windows = list(prefs.focus_windows) + [(None, None)] * (3 - len(prefs.focus_windows))
    with st.form("prefs_form"):
        left, right = st.columns(2)
        day_start = left.time_input("Day starts at", value=prefs.day_start, step=1800)
        no_work_after = right.time_input("No work at or after", value=prefs.no_work_after, step=1800)
        st.markdown("**Focus windows** (demanding work goes here)")
        new_windows = []
        for i, (start, end) in enumerate(windows[:3]):
            a, b, c = st.columns([1, 2, 2])
            on = a.checkbox("Use", value=start is not None, key=f"fw_on_{i}")
            s = b.time_input(f"From #{i + 1}", value=start or time(15, 0), step=1800, key=f"fw_s_{i}")
            e = c.time_input(f"To #{i + 1}", value=end or time(17, 0), step=1800, key=f"fw_e_{i}")
            if on:
                new_windows.append((s, e))
        min_block = left.selectbox("Min block length (minutes)", [30, 60, 90, 120],
                                   index=[30, 60, 90, 120].index(prefs.min_block_min)
                                   if prefs.min_block_min in (30, 60, 90, 120) else 1)
        max_options = list(range(60, 241, 30))
        max_block = right.selectbox("Max block length (minutes)", max_options,
                                    index=max_options.index(prefs.max_block_min)
                                    if prefs.max_block_min in max_options else 2)
        daily = left.number_input("Max work per day (hours)", min_value=0.5, max_value=16.0, step=0.5,
                                  value=prefs.max_work_per_day_min / 60)
        horizon = right.slider("Plan this many days ahead", 1, MAX_HORIZON_DAYS, prefs.horizon_days)
        submitted = st.form_submit_button("Save preferences", type="primary")
    if not submitted:
        return
    candidate = Preferences(day_start=day_start, no_work_after=no_work_after,
                            focus_windows=tuple(w for w in new_windows if w[0] < w[1]),
                            min_block_min=min_block, max_block_min=max_block,
                            max_work_per_day_min=round(daily * 60), horizon_days=horizon)
    errors, notices, cleaned = validate_prefs(candidate)
    if errors:
        for message in errors.values():
            st.error(message)
        return
    message = "Preferences saved and the week replanned." + ("".join(f" {n}" for n in notices))
    if run_action(lambda: service.change(lambda s, now: replace(s, prefs=cleaned)), message):
        st.rerun()
