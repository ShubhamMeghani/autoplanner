"""From screenshots or pasted text to the review table, and from the table to tasks
(R38, R40-R46). Images are used once, in memory, and never stored (R42)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from autoplanner.config import TASK_TYPES, TZ
from autoplanner.importers import gemini_vision
from autoplanner.importers.dates import resolve_due
from autoplanner.importers.ocr import ocr_text, tesseract_available
from autoplanner.importers.text_parser import RawRow, parse_text
from autoplanner.learning import correction_factor, corrected_estimate
from autoplanner.models import Task

GEMINI = "Gemini"
TESSERACT_FALLBACK = "Tesseract (fallback)"
TESSERACT = "Tesseract"
PASTE = "Paste"


@dataclass
class ReviewRow:
    include: bool
    title: str
    course: str | None
    type: str
    estimate_raw: float
    estimate: float
    deadline: datetime | None
    date_check: str
    flag: str
    demanding: bool
    source_text: str
    engine: str
    status: str = "upcoming"


@dataclass
class ImportResult:
    rows: list[ReviewRow]
    notes: list[str] = field(default_factory=list)  # plain-language messages for the user
    gemini_calls: int = 0  # for the R47 daily limit

LIMIT_REACHED = "The limit for Gemini reads was reached (20 a day per planner, 10 per demo session)."


def infer_type(title: str) -> str:
    """Keyword match in type-table order (§4.1); 'assignment' is the fallback."""
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", title.lower()))
    for task_type, info in TASK_TYPES.items():
        if any(k in words for k in info.keywords):
            return task_type
    return "assignment"


def normalise(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def is_duplicate(title: str, course: str | None, deadline: datetime | None, existing: list[Task]) -> bool:
    for task in existing:
        if normalise(task.title) == normalise(title) and normalise(task.course) == normalise(course):
            if deadline is None or abs(task.deadline - deadline) <= timedelta(hours=1):
                return True
    return False


def build_rows(raw_rows: list[RawRow], import_date: date, now: datetime, existing: list[Task],
               engine: str) -> list[ReviewRow]:
    rows = []
    for raw in raw_rows:
        resolved = resolve_due(raw.due_text, import_date)
        task_type = infer_type(raw.title)
        default = TASK_TYPES[task_type].default_hours
        factor = correction_factor(existing, task_type).factor
        include = not (raw.status == "completed"
                       or is_duplicate(raw.title, raw.course, resolved.deadline, existing)
                       or (resolved.deadline is not None and resolved.deadline <= now))
        rows.append(ReviewRow(include=include, title=raw.title, course=raw.course, type=task_type,
                              estimate_raw=default, estimate=corrected_estimate(default, factor),
                              deadline=resolved.deadline, date_check=resolved.date_check, flag=resolved.flag,
                              demanding=TASK_TYPES[task_type].demanding, source_text=raw.source_text,
                              engine=engine, status=raw.status))
    # Rows that need attention first (R44), then by deadline.
    order = {"unresolved": 0, "ambiguous": 1}
    rows.sort(key=lambda r: (order.get(r.flag, 2), r.deadline or datetime.max.replace(tzinfo=TZ)))
    return rows


def import_screenshots(images: list[bytes], import_date: date, now: datetime, existing: list[Task], *,
                       api_key: str | None, model: str | None, gemini_allowed: bool = True,
                       gemini_budget: int | None = None, gemini_client=None, ocr_fn: Callable[[bytes], str] | None = None,
                       ocr_available: Callable[[], bool] = tesseract_available) -> ImportResult:
    """Read each image with Gemini, or with Tesseract when Gemini can't be used (R41)."""
    ocr_fn = ocr_fn or ocr_text
    result = ImportResult(rows=[])
    for number, image in enumerate(images, 1):
        label = f"Screenshot {number}" if len(images) > 1 else "The screenshot"
        try:
            gemini_vision.image_mime(image)
        except ValueError as exc:
            result.notes.append(f"{label}: {exc}")
            continue
        reason = None
        within_budget = gemini_budget is None or result.gemini_calls < gemini_budget
        if gemini_allowed and within_budget:
            try:
                if api_key and model:
                    result.gemini_calls += 1
                raw = gemini_vision.extract_rows(image, api_key=api_key, model=model, client=gemini_client)
                result.rows += build_rows(raw, import_date, now, existing, GEMINI)
                continue
            except gemini_vision.GeminiUnavailable as exc:
                reason = str(exc)
            except Exception as exc:  # never let an unexpected client error escape (R35)
                reason = gemini_vision.explain(exc)
        elif not within_budget:
            reason = LIMIT_REACHED
        else:
            reason = "Gemini reading is turned off."
        if not ocr_available():
            result.notes.append(f"{label}: {reason} Tesseract isn't installed either, so it couldn't be read.")
            continue
        try:
            raw = parse_text(ocr_fn(image))
        except Exception:
            result.notes.append(f"{label}: {reason} Tesseract couldn't read it either.")
            continue
        result.notes.append(f"{label}: read with Tesseract (fallback). {reason}")
        result.rows += build_rows(raw, import_date, now, existing, TESSERACT_FALLBACK)
    order = {"unresolved": 0, "ambiguous": 1}
    result.rows.sort(key=lambda r: (order.get(r.flag, 2), r.deadline or datetime.max.replace(tzinfo=TZ)))
    if not result.rows and not result.notes:
        result.notes.append("No assignments were found.")
    return result


def import_text(text: str, import_date: date, now: datetime, existing: list[Task]) -> ImportResult:
    rows = build_rows(parse_text(text), import_date, now, existing, PASTE)
    return ImportResult(rows=rows, notes=[] if rows else ["No assignments were found in the text."])


def rows_to_tasks(rows: list[ReviewRow], now: datetime, source: str) -> tuple[list[Task], list[str]]:
    """Ticked rows -> tasks. Any problem refuses the whole save (R45)."""
    errors, tasks = [], []
    for row in rows:
        if not row.include:
            continue
        name = row.title or "(untitled)"
        if not row.title.strip():
            errors.append("A ticked row has no title.")
        if row.deadline is None:
            errors.append(f"“{name}” needs a deadline (or untick it).")
        elif row.deadline <= now:
            errors.append(f"“{name}” has a deadline in the past.")
        if not (0.5 <= row.estimate <= 100):
            errors.append(f"“{name}”: the estimate must be between 0.5 and 100 hours.")
        if not errors:
            tasks.append(Task(title=row.title.strip(), course=(row.course or "").strip() or None, type=row.type,
                              est_hours_raw=row.estimate_raw, est_hours=row.estimate, deadline=row.deadline,
                              demanding=row.demanding, source=source, created_at=now))
    return ([] if errors else tasks), errors

