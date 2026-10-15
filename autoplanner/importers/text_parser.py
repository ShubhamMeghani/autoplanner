"""Rule-based parser for pasted Teams text and OCR output (R46, D-18).

Accepted layouts:
- the Teams Assignments list: a title line, a course line, then a "Due ..." line;
- single lines "title <sep> due text", where <sep> is — – " - " | or a tab.
Status lines ("Completed", "Turned in", "Past due", "Assigned") and point counts are
recognised and never taken as titles. OCR sometimes merges a line with the due text that
follows it; that is split apart again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from autoplanner.importers.dates import resolve_due

DUE_LINE = re.compile(r"^\W*(past\s+due|overdue|due)\b", re.I)
DUE_INSIDE = re.compile(r"\s(past\s+due|due)\s", re.I)
SEPARATORS = ("\t", " — ", " – ", " | ", " - ", "—", "–", "|")
COMPLETED = re.compile(r"^(completed|turned\s+in|submitted|handed\s+in|graded|returned)\b", re.I)
PAST_DUE = re.compile(r"^\W*(past\s+due|overdue|missing)\b", re.I)
NOISE = re.compile(r"^(assignments?|assigned|upcoming|view|open|\d+\s*(points?|pts)|no\s+points|\W*)$", re.I)
TABS = re.compile(r"^(upcoming|assigned)\b.*\b(past\s+due|completed)\b", re.I)  # the list's tab row
ANY_DATE = date(2026, 1, 1)  # reference for "does this look like a date?" checks only


@dataclass(frozen=True)
class RawRow:
    title: str
    course: str | None
    due_text: str
    status: str  # upcoming | past_due | completed | unknown
    source_text: str


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("​", "")).strip(" •·*—–|\t")


def _is_due(text: str) -> bool:
    return bool(DUE_LINE.match(text))


def _split_single(line: str) -> tuple[str, str] | None:
    """'title <sep> due text' on one line."""
    for sep in SEPARATORS:
        if sep in line:
            left, right = line.split(sep, 1)
            left, right = _clean(left), right.strip()
            if left and right and (_is_due(right) or resolve_due(right, ANY_DATE).flag != "unresolved"):
                return left, right
    return None


def _split_merged(line: str) -> tuple[str, str] | None:
    """'some text Due tomorrow at 11:59 PM' -> ('some text', 'Due tomorrow at 11:59 PM')."""
    m = DUE_INSIDE.search(line)
    if m and m.start() > 0:
        left = _clean(line[:m.start()])
        if left:
            return left, line[m.start():].strip()
    return None


def parse_text(text: str) -> list[RawRow]:
    rows: list[RawRow] = []
    pending: list[str] = []
    status = "unknown"

    def emit(due_text: str, extra: str | None = None) -> None:
        nonlocal pending, status
        content = [p for p in pending + ([extra] if extra else []) if not NOISE.match(p)]
        if content:
            # The two lines right before the due line are title and course; anything earlier
            # (page headings, OCR noise) is ignored.
            title, course = (content[-2], content[-1]) if len(content) >= 2 else (content[0], None)
            row_status = "past_due" if PAST_DUE.match(due_text) else ("upcoming" if status == "unknown" else status)
            rows.append(RawRow(title=title, course=course, due_text=due_text, status=row_status,
                               source_text=" / ".join([x for x in (title, course) if x] + [due_text])))
        pending, status = [], "unknown"

    for raw in text.splitlines():
        line = _clean(raw)
        if not line or TABS.match(line):
            continue
        if COMPLETED.match(line):
            if rows and not pending:  # right after a due line: it belongs to that row
                last = rows[-1]
                rows[-1] = RawRow(last.title, last.course, last.due_text, "completed", last.source_text)
            else:
                status = "completed"
            continue
        if _is_due(line):
            emit(line)
            continue
        if PAST_DUE.match(line):
            status = "past_due"
            continue
        if not pending:
            single = _split_single(raw.strip())
            if single:
                pending = [single[0]]
                emit(single[1])
                continue
        merged = _split_merged(line)
        if merged:
            emit(merged[1], extra=merged[0])
            continue
        pending.append(line)
    return rows
