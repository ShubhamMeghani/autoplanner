"""Constants, the type table, defaults and secret access (SPEC §3, §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")
SLOT_MINUTES = 30
SLOT = timedelta(minutes=SLOT_MINUTES)
MAX_HORIZON_DAYS = 14

SOLVER_TIME_LIMIT_S = 10.0  # R18
SOLVER_WORKERS = 4  # R18, C7
DIAGNOSIS_BUDGET_S = 15.0  # R34
MAX_EXTEND_OPTIONS = 3  # R29

GEMINI_TIMEOUT_S = 20  # R41
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # §4.1
MAX_UPLOAD_FILES = 5
GEMINI_DAILY_LIMIT = 20  # R47
GEMINI_DEMO_SESSION_LIMIT = 10  # R47

MIN_ESTIMATE_H = 0.5  # R10
MAX_ESTIMATE_H = 40.0


@dataclass(frozen=True)
class TaskType:
    demanding: bool
    default_hours: float
    keywords: tuple[str, ...]


# §4.1 type table. Dict order is the keyword-matching order (most specific first).
TASK_TYPES: dict[str, TaskType] = {
    "exam_prep": TaskType(True, 5.0, ("exam", "midterm", "midsem", "endsem", "final")),
    "lab_report": TaskType(False, 3.0, ("lab", "experiment")),
    "project": TaskType(True, 6.0, ("project", "mini-project")),
    "quiz": TaskType(False, 1.0, ("quiz", "test")),
    "reading": TaskType(False, 1.5, ("read", "reading", "chapter")),
    "assignment": TaskType(True, 3.0, ()),  # fallback
    "other": TaskType(False, 2.0, ()),
}
TYPE_LABELS = {
    "assignment": "Assignment",
    "lab_report": "Lab report",
    "project": "Project",
    "exam_prep": "Exam prep",
    "reading": "Reading",
    "quiz": "Quiz",
    "other": "Other",
}


def get_secret(name: str) -> str | None:
    """Read a Streamlit secret; None when the file or key is missing. Never log the value (R5)."""
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return None
    return str(value) if value else None
