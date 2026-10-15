"""Screenshot and paste import with the review table (R40-R46).

Uploaded images are read once and then dropped: the uploader is reset with a new key and
only the extracted text rows are kept in the session (R42).
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import streamlit as st

from autoplanner.config import (GEMINI_DAILY_LIMIT, GEMINI_DEMO_SESSION_LIMIT, MAX_UPLOAD_BYTES,
                                MAX_UPLOAD_FILES, TYPE_LABELS, TZ, get_secret)
from autoplanner.importers.pipeline import ImportResult, ReviewRow, import_screenshots, import_text, rows_to_tasks
from autoplanner.planner import PlannerService, PlanView
from autoplanner.ui import clipboard_paste, log, run_action

NOTICE = ("Screenshots are sent to Google Gemini for reading and are never stored by AutoPlanner. "
          "Tip: crop the screenshot to the assignment list.")


def _store(result: ImportResult, source: str) -> None:
    st.session_state["import_rows"] = [asdict(r) for r in result.rows]
    st.session_state["import_notes"] = result.notes
    st.session_state["import_source"] = source


def _clear() -> None:
    for key in ("import_rows", "import_notes", "import_source"):
        st.session_state.pop(key, None)


SAMPLE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "teams_synthetic" / "teams_1.png"
DAILY_LIMIT_SESSION_KEY = "demo_gemini_calls"


def gemini_budget(service: PlannerService, demo: bool) -> int:
    """R47: Gemini reads left: 20 per planner per IST day, 10 per demo session."""
    if demo:
        return max(0, GEMINI_DEMO_SESSION_LIMIT - st.session_state.get(DAILY_LIMIT_SESSION_KEY, 0))
    now = service.now()
    midnight = datetime.combine(now.date(), time(0), TZ)
    return max(0, GEMINI_DAILY_LIMIT - service.repo.count_gemini_calls(service.planner_id, midnight))


def _read(images: list[bytes], import_date, view: PlanView, service: PlannerService, demo: bool) -> ImportResult:
    result = import_screenshots(images, import_date, service.now(), view.state.tasks,
                                api_key=get_secret("GEMINI_API_KEY"), model=get_secret("GEMINI_MODEL"),
                                gemini_budget=gemini_budget(service, demo))
    if demo:
        st.session_state[DAILY_LIMIT_SESSION_KEY] = st.session_state.get(DAILY_LIMIT_SESSION_KEY, 0) + result.gemini_calls
    else:
        for _ in range(result.gemini_calls):
            service.repo.log_import(service.planner_id, "gemini")
    return result


def read_pasted(payload, import_date, view: PlanView, service: PlannerService, demo: bool) -> ImportResult:
    """R68: a pasted screenshot goes through exactly the same reader as an uploaded one.
    Raises clipboard_paste.PasteError for content that isn't a usable image."""
    image = clipboard_paste.decode_pasted(payload)
    try:
        return _read([image], import_date, view, service, demo)
    finally:
        del image  # in memory only, never stored (R42)


def pasted_screenshot(view: PlanView, service: PlannerService, demo: bool, import_date) -> None:
    gen = st.session_state.setdefault("paste_gen", 0)
    payload = clipboard_paste.paste_area(key=f"paste_{gen}")
    if not payload:
        return
    st.session_state["paste_gen"] = gen + 1  # a new box next run: Streamlit drops the pasted data (R42)
    try:
        with st.spinner("Reading the pasted screenshot…"):
            result = read_pasted(payload, import_date, view, service, demo)
    except clipboard_paste.PasteError as exc:
        st.error(str(exc))
        return
    except Exception:
        log.exception("pasted screenshot import failed")
        st.error("The pasted screenshot couldn't be read. Nothing was changed; try again or upload it as a file.")
        return
    finally:
        payload = None
    _store(result, "screenshot")
    st.rerun()


def screenshot_section(view: PlanView, service: PlannerService, demo: bool) -> None:
    gen = st.session_state.setdefault("uploader_gen", 0)
    import_date = st.date_input("Screenshot taken on", value=view.now.date(), key="shot_date",
                                help="Relative dates like “Due tomorrow” are read from this date.")
    pasted_screenshot(view, service, demo, import_date)  # R68: the fastest way in
    files = st.file_uploader("Or upload screenshot files (up to 5)", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True, key=f"uploader_{gen}")
    if demo and SAMPLE.exists() and st.button("Try with a sample screenshot", key="sample_shot"):  # R48
        st.image(str(SAMPLE), caption="A synthetic Teams Assignments list (fictional data)")
        try:
            with st.spinner("Reading…"):
                result = _read([SAMPLE.read_bytes()], import_date, view, service, demo)
        except Exception:
            log.exception("sample import failed")
            st.error("The sample couldn't be read. Nothing was changed.")
            return
        _store(result, "screenshot")
        st.rerun()
    if not st.button("Read screenshots", disabled=not files, key="read_shots"):
        return
    if len(files) > MAX_UPLOAD_FILES:
        st.error(f"Upload at most {MAX_UPLOAD_FILES} screenshots at a time.")
        return
    too_big = [f.name for f in files if f.size > MAX_UPLOAD_BYTES]
    if too_big:
        st.error("These files are larger than 10 MB: " + ", ".join(too_big))
        return
    images = [f.getvalue() for f in files]
    try:
        with st.spinner("Reading…"):
            result = _read(images, import_date, view, service, demo)
    except Exception:
        log.exception("screenshot import failed")
        st.error("The screenshots couldn't be read. Nothing was changed; try again or paste the text instead.")
        return
    finally:
        del images
        st.session_state["uploader_gen"] = gen + 1  # drops the uploaded files (R42)
    _store(result, "screenshot")
    st.rerun()


def paste_section(view: PlanView, service: PlannerService) -> None:
    import_date = st.date_input("Copied on", value=view.now.date(), key="paste_date",
                                help="Relative dates like “Due tomorrow” are read from this date.")
    text = st.text_area("Paste the Assignments list, or one assignment per line (title — due date)",
                        height=180, key="paste_text")
    if st.button("Read text", disabled=not text.strip(), key="read_text"):
        _store(import_text(text, import_date, service.now(), view.state.tasks), "paste")
        st.rerun()


def _frame(rows: list[ReviewRow]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Include": r.include, "Title": r.title, "Course": r.course or "", "Type": r.type,
        "Estimate (h)": r.estimate,
        "Deadline": r.deadline.astimezone(TZ).replace(tzinfo=None) if r.deadline else None,
        "Date check": r.date_check, "Demanding": r.demanding, "Source text": r.source_text, "Engine": r.engine,
    } for r in rows])


def _rows_from(edited: pd.DataFrame, original: list[ReviewRow]) -> list[ReviewRow]:
    rows = []
    for (_, rec), row in zip(edited.iterrows(), original):
        deadline = rec["Deadline"]
        deadline = None if deadline is None or pd.isna(deadline) else pd.Timestamp(deadline).to_pydatetime()
        rows.append(replace(row, include=bool(rec["Include"]), title=str(rec["Title"] or "").strip(),
                            course=str(rec["Course"] or "").strip() or None, type=str(rec["Type"]),
                            estimate=float(rec["Estimate (h)"]),
                            deadline=deadline.replace(tzinfo=TZ) if deadline else None,
                            demanding=bool(rec["Demanding"])))
    return rows


def review_section(service: PlannerService) -> None:
    if "import_rows" not in st.session_state:
        return
    for note in st.session_state.get("import_notes", []):
        st.info(note)
    rows = [ReviewRow(**r) for r in st.session_state["import_rows"]]
    if not rows:
        return
    st.subheader("Review before adding")
    st.caption("Nothing is saved until you click “Add selected tasks”. Check the rows marked ⚠ or ✖ first.")
    edited = st.data_editor(
        _frame(rows), key="review_editor", hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=["Date check", "Source text", "Engine"],
        column_config={
            "Include": st.column_config.CheckboxColumn(),
            "Type": st.column_config.SelectboxColumn(options=list(TYPE_LABELS), required=True),
            "Estimate (h)": st.column_config.NumberColumn(min_value=0.5, max_value=100.0, step=0.5),
            "Deadline": st.column_config.DatetimeColumn(format="ddd D MMM YYYY, HH:mm", step=60),
            "Date check": st.column_config.TextColumn(width="medium"),
        })
    left, right = st.columns([1, 1])
    if left.button("Add selected tasks", type="primary", key="add_selected"):
        final = _rows_from(edited, rows)
        source = st.session_state.get("import_source", "paste")
        tasks, errors = rows_to_tasks(final, service.now(), source)
        if errors:
            for message in errors:
                st.error(message)
        elif not tasks:
            st.warning("Nothing is ticked.")
        elif run_action(lambda: service.change(lambda s, now: replace(s, tasks=s.tasks + tasks)),
                        f"Added {len(tasks)} task{'s' if len(tasks) != 1 else ''} and replanned."):
            _clear()
            st.rerun()
    if right.button("Discard", key="discard_import"):
        _clear()
        st.rerun()


def render(view: PlanView, service: PlannerService, demo: bool = False) -> None:
    st.info(NOTICE)
    shot, paste = st.tabs(["Screenshot", "Paste text"])
    with shot:
        screenshot_section(view, service, demo)
    with paste:
        paste_section(view, service)
    review_section(service)

