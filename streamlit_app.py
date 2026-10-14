"""AutoPlanner: Phase 1 deployment check (PLAN.md 1.5).

Temporary page. Phase 3 (PLAN.md 3.2) replaces it with the real app.
It checks the free-tier stack on Streamlit Community Cloud: Python 3.13,
OR-Tools, Tesseract, streamlit-calendar, a Supabase write and read, and one
Gemini vision call. Secrets and planner IDs are never displayed (R5).
"""

from __future__ import annotations

import io
import json
import secrets
import sys
import time
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from zoneinfo import ZoneInfo

import streamlit as st

IST = ZoneInfo("Asia/Kolkata")
GEMINI_TIMEOUT_MS = 20_000
SECRET_NAMES = ("SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY", "GEMINI_MODEL")

# Gemini transcribes due text verbatim; dates are resolved locally (R40, R43).
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "rows": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"title": {"type": "STRING"}, "due_text": {"type": "STRING"}},
                "required": ["title", "due_text"],
            },
        }
    },
    "required": ["rows"],
}
GEMINI_PROMPT = (
    "Transcribe every assignment in this image. Copy the due text exactly as shown; "
    "do not interpret or convert dates."
)


def get_secret(name: str) -> str | None:
    """Return a secret, or None if the file or key is missing. Never display it."""
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets.toml at all
        return None
    return str(value) if value else None


def pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


# ---------- environment ----------

def check_cp_sat() -> tuple[bool, str]:
    """x > y > z, x + y + z = 12, maximise z. The unique optimum is (5, 4, 3)."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x, y, z = (model.new_int_var(0, 10, n) for n in "xyz")
    model.add(x + y + z == 12)
    model.add(x > y)
    model.add(y > z)
    model.maximize(z)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.solve(model)
    values = (solver.value(x), solver.value(y), solver.value(z))
    ok = status == cp_model.OPTIMAL and values == (5, 4, 3)
    return ok, f"{solver.status_name(status)} {values}"


def check_tesseract() -> tuple[bool, str]:
    import pytesseract

    try:
        return True, str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError:
        return False, "not found on PATH (Cloud installs it from packages.txt)"


def environment_rows() -> list[tuple[str, bool, str]]:
    py_ok = sys.version_info[:2] == (3, 13)
    rows = [("Python", py_ok, sys.version.split()[0])]
    try:
        cp_ok, cp_detail = check_cp_sat()
        rows.append((f"OR-Tools {pkg_version('ortools')} CP-SAT", cp_ok, cp_detail))
    except Exception as exc:  # import or solve failure
        rows.append(("OR-Tools CP-SAT", False, type(exc).__name__))
    rows.append(("Tesseract", *check_tesseract()))
    rows.append(("Time in IST", True, datetime.now(IST).strftime("%Y-%m-%d %H:%M %Z")))
    for name in SECRET_NAMES:
        rows.append((f"Secret {name}", get_secret(name) is not None, "configured" if get_secret(name) else "missing"))
    return rows


# ---------- Supabase ----------

def supabase_round_trip(url: str, key: str) -> float:
    """Insert, read back and delete one throwaway planners row (D-20). Returns ms."""
    from supabase import create_client

    planner_id = secrets.token_urlsafe(32)
    client = create_client(url, key)
    started = time.perf_counter()
    try:
        client.table("planners").insert({"id": planner_id}).execute()
        try:
            rows = client.table("planners").select("id").eq("id", planner_id).execute().data
            if len(rows) != 1:
                raise RuntimeError("the row was written but could not be read back")
        finally:
            client.table("planners").delete().eq("id", planner_id).execute()
    except Exception as exc:
        # Error texts can echo the row; scrub the planner ID before it is shown (R5).
        raise RuntimeError(str(exc).replace(planner_id, "<planner id>")) from None
    return (time.perf_counter() - started) * 1000


def explain_supabase_error(message: str) -> str:
    lowered = message.lower()
    if "pgrst205" in lowered or "42p01" in lowered or "could not find the table" in lowered:
        return "The `planners` table doesn't exist yet. Run `db/schema.sql` in the Supabase SQL editor."
    if "42501" in lowered or "row-level security" in lowered or "permission denied" in lowered:
        return ("Row-level security blocked the write. `SUPABASE_KEY` must be the server-side secret "
                "key, not the publishable/anon key.")
    if "invalid api key" in lowered or "401" in lowered or "no api key" in lowered:
        return "Supabase rejected `SUPABASE_KEY`. Check that it is the project's secret key."
    if "connect" in lowered or "name or service not known" in lowered or "getaddrinfo" in lowered:
        return "Could not reach Supabase. Check `SUPABASE_URL`."
    return "Supabase returned an unexpected error."


# ---------- Gemini ----------

def make_test_png() -> bytes:
    """A small Teams-like row, drawn with Pillow's built-in font."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (520, 90), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    draw.text((12, 10), "Lab report 3", fill="black", font=font)
    draw.text((12, 50), "Due tomorrow at 11:59 PM", fill=(90, 90, 90), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def gemini_call(api_key: str, model: str, png: bytes) -> tuple[dict, float]:
    """One generate_content call: inline image bytes (no Files API) and a JSON schema."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    started = time.perf_counter()
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), GEMINI_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GEMINI_SCHEMA,
            temperature=0,
        ),
    )
    elapsed = (time.perf_counter() - started) * 1000
    return json.loads(response.text), elapsed


def explain_gemini_error(exc: Exception) -> str:
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        text = f"{exc.status or ''} {exc.message or ''}"
        if exc.code == 401 or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in text:
            return (f"**Gemini rejected the key: HTTP {exc.code} {exc.status}.** The key was sent as an API key "
                    "(`x-goog-api-key`) through the official google-genai SDK, and Google does not accept "
                    "this key type for this request. No workaround was attempted.\n\n"
                    f"Google's message: {exc.message}")
        if exc.code == 400 and "API_KEY_INVALID" in str(exc):
            return "Gemini says `GEMINI_API_KEY` is invalid."
        if exc.code == 403:
            return f"Gemini refused the request (HTTP 403 {exc.status}): {exc.message}"
        if exc.code == 404:
            return f"Model `{get_secret('GEMINI_MODEL')}` was not found. Check `GEMINI_MODEL`."
        if exc.code == 429:
            return "Gemini quota or rate limit reached (HTTP 429). Try again later."
        if exc.code == 503:
            return (f"Model `{get_secret('GEMINI_MODEL')}` is overloaded (HTTP 503). Try again later, "
                    "or set `GEMINI_MODEL` to another Flash model.")
        return f"Gemini error HTTP {exc.code} {exc.status}: {exc.message}"
    if "timeout" in type(exc).__name__.lower():
        return f"Gemini did not answer within {GEMINI_TIMEOUT_MS // 1000} s."
    return f"Gemini call failed ({type(exc).__name__})."


# ---------- page ----------

st.set_page_config(page_title="AutoPlanner: deployment check", page_icon="🗓️")
st.title("AutoPlanner: deployment check")
st.caption("Phase 1 of PLAN.md. This temporary page is replaced by the real app in Phase 3.")

st.subheader("1. Environment")
for label, ok, detail in environment_rows():
    st.markdown(f"{'✅' if ok else '⚠️'} **{label}**: {detail}")

st.subheader("2. Calendar component (D-6)")
try:
    from streamlit_calendar import calendar

    start = datetime.now(IST).replace(minute=0, second=0, microsecond=0)
    state = calendar(
        events=[{"id": "smoke-1", "title": "Click me",
                 "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}],
        options={"initialView": "timeGridDay", "slotDuration": "00:30:00", "height": 360},
        callbacks=["eventClick"],
        key="smoke_calendar",
    )
    if state and state.get("callback") == "eventClick":
        st.success(f"✅ Click received for event `{state['eventClick']['event']['id']}`.")
    else:
        st.info("Click the event to test the click callback.")
except Exception as exc:
    st.error(f"streamlit-calendar failed to load ({type(exc).__name__}). Use the D-6 fallback.")

st.subheader("3. Supabase write and read")
if st.button("Run Supabase check"):
    url, key = get_secret("SUPABASE_URL"), get_secret("SUPABASE_KEY")
    if not (url and key):
        st.session_state["supabase"] = ("error", "`SUPABASE_URL` and `SUPABASE_KEY` are not configured.")
    else:
        try:
            ms = supabase_round_trip(url, key)
            st.session_state["supabase"] = ("ok", f"Wrote, read back and deleted one `planners` row in {ms:.0f} ms.")
        except Exception as exc:
            st.session_state["supabase"] = ("error", f"{explain_supabase_error(str(exc))}\n\nDetails: {exc}")
if "supabase" in st.session_state:
    kind, message = st.session_state["supabase"]
    (st.success if kind == "ok" else st.error)(("✅ " if kind == "ok" else "") + message)

st.subheader("4. Gemini call")
st.caption("Runs only when clicked, so loading the page doesn't use quota.")
if st.button("Run Gemini check"):
    api_key, model = get_secret("GEMINI_API_KEY"), get_secret("GEMINI_MODEL")
    if not (api_key and model):
        st.session_state["gemini"] = ("error", "`GEMINI_API_KEY` and `GEMINI_MODEL` are not configured.", None)
    else:
        png = make_test_png()
        try:
            result, ms = gemini_call(api_key, model, png)
            st.session_state["gemini"] = ("ok", f"`{model}` answered in {ms:.0f} ms.", result)
        except Exception as exc:
            st.session_state["gemini"] = ("error", explain_gemini_error(exc), None)
        finally:
            del png  # inline bytes only; nothing is stored (R42)
if "gemini" in st.session_state:
    kind, message, result = st.session_state["gemini"]
    (st.success if kind == "ok" else st.error)(("✅ " if kind == "ok" else "") + message)
    if result is not None:
        st.json(result)
