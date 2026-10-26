"""Streamlit views. Each module renders one part of the page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import streamlit as st

from autoplanner.config import TZ, install_log_scrubber
from autoplanner.planner import PlanValidationError, PlanView
from autoplanner.storage import StorageUnavailable

log = install_log_scrubber()


def card(title: str | None = None, caption: str | None = None):
    """A bordered section with a consistent heading: every grouped block of the UI uses it."""
    box = st.container(border=True)
    if title:
        box.subheader(title)
    if caption:
        box.caption(caption)
    return box


def run_action(action: Callable[[], PlanView], success: str | None = None) -> PlanView | None:
    """Run a change. On any error, show a plain message and leave everything as it was (R35)."""
    try:
        with st.spinner("Updating your plan…"):
            view = action()
    except StorageUnavailable:
        st.error("Couldn't save: storage is unavailable right now. Nothing was changed; please retry.")
    except PlanValidationError:
        log.exception("plan failed validation")
        st.error("The new plan failed a safety check, so it wasn't saved. Your previous plan is unchanged.")
    except Exception:
        log.exception("action failed")
        st.error("Something went wrong while planning. Nothing was changed; please try again.")
    else:
        if success:
            st.session_state["flash"] = success
        return view
    return None


def flash() -> None:
    """Show the message saved by the last successful action, once."""
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%a %d %b, %H:%M")


def fmt_hours(minutes: float) -> str:
    return f"{minutes / 60:g} h"
