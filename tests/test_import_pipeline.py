"""Import pipeline: review table (AC-15), fallback (AC-16), no retention (AC-29), errors (AC-47)."""

import dataclasses
import os
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

from conftest import NOW, FakeGemini, at, make_task, synthetic_png

from autoplanner.importers.pipeline import (TESSERACT_FALLBACK, import_screenshots, import_text, infer_type,
                                            rows_to_tasks)
from autoplanner.models import Preferences
from autoplanner.planner import PlannerService
from autoplanner.storage import MemoryRepo

IMPORT = date(2026, 10, 14)
OCR_TEXT = "Lab 3 report\nE9 241 Digital Image Processing\nDue Friday at 11:59 PM\n"


def gemini_rows():
    return [
        {"title": "Assignment 4", "course": "E0 251", "due_text": "Due tomorrow at 11:59 PM", "status": "upcoming"},
        {"title": "Problem set 4", "course": "MA 261", "due_text": "Due Oct 10", "status": "completed"},
        {"title": "Problem set 5", "course": "MA 261", "due_text": "Due Friday at 5:00 PM", "status": "upcoming"},
        {"title": "Mini-project", "course": "DS 221", "due_text": "Due Wednesday", "status": "upcoming"},
        {"title": "Essay", "course": "HS 202", "due_text": "Due sometime", "status": "upcoming"},
    ]


def run(client, existing=(), **kw):
    return import_screenshots([synthetic_png()], IMPORT, NOW, list(existing), api_key="test-key",
                              model="test-model", gemini_client=client, **kw)


def test_review_table_orders_flags_and_unticks_ac15():
    duplicate = make_task("Problem set 5", 3, at(2, 17, 0), course="MA 261")
    result = run(FakeGemini(gemini_rows()), existing=[duplicate])
    rows = result.rows
    assert len(rows) == 5
    assert [r.flag for r in rows[:2]] == ["unresolved", "ambiguous"]
    assert rows[0].date_check == "✖ needs a date" and rows[1].date_check.startswith("⚠")
    ticked = {r.title: r.include for r in rows}
    assert ticked == {"Essay": True, "Mini-project": True, "Assignment 4": True,
                      "Problem set 4": False, "Problem set 5": False}
    assert all(r.engine == "Gemini" for r in rows)


def test_save_is_refused_until_every_ticked_row_has_a_deadline_ac15():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    service = PlannerService(repo, pid, clock=lambda: NOW)
    rows = run(FakeGemini(gemini_rows())).rows

    tasks, errors = rows_to_tasks(rows, NOW, "screenshot")
    assert tasks == [] and any("needs a deadline" in e for e in errors)
    assert repo.load(pid).tasks == []  # nothing saved yet

    fixed = [replace(r, include=False) if r.flag == "unresolved" else r for r in rows]
    tasks, errors = rows_to_tasks(fixed, NOW, "screenshot")
    assert errors == [] and len(tasks) == 3
    service.change(lambda s, now: replace(s, tasks=s.tasks + tasks))
    assert len(repo.load(pid).tasks) == 3


def test_missing_key_falls_back_to_tesseract_ac16():
    result = import_screenshots([synthetic_png()], IMPORT, NOW, [], api_key=None, model=None,
                                ocr_fn=lambda image: OCR_TEXT, ocr_available=lambda: True)
    assert [r.engine for r in result.rows] == [TESSERACT_FALLBACK]
    assert "read with Tesseract (fallback)" in result.notes[0] and "isn't configured" in result.notes[0]


def test_timeout_falls_back_to_tesseract_ac16():
    class ReadTimeout(Exception):
        pass

    result = run(FakeGemini(error=ReadTimeout("timed out")), ocr_fn=lambda image: OCR_TEXT,
                 ocr_available=lambda: True)
    assert [r.engine for r in result.rows] == [TESSERACT_FALLBACK]
    assert "didn't answer within 20 seconds" in result.notes[0]


def test_invalid_json_and_empty_answers_fall_back_r41():
    for client in (FakeGemini(text="not json"), FakeGemini(rows=[])):
        result = run(client, ocr_fn=lambda image: OCR_TEXT, ocr_available=lambda: True)
        assert [r.engine for r in result.rows] == [TESSERACT_FALLBACK]


def test_key_type_rejection_is_reported_plainly():
    class APIError(Exception):
        code, status, message = 401, "UNAUTHENTICATED", "ACCESS_TOKEN_TYPE_UNSUPPORTED"

    result = run(FakeGemini(error=APIError()), ocr_fn=lambda image: OCR_TEXT, ocr_available=lambda: True)
    assert "Gemini rejected the API key (HTTP 401" in result.notes[0]


def _walk(value, seen=None):
    """Yield every leaf value inside dataclasses, dicts, lists and sets."""
    seen = seen if seen is not None else set()
    if id(value) in seen:
        return
    seen.add(id(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from _walk(getattr(value, f.name), seen)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(k, seen)
            yield from _walk(v, seen)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _walk(v, seen)
    else:
        yield value


def _files_under(root: Path) -> set[str]:
    skip = {".venv", "__pycache__", ".pytest_cache", ".git"}
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        out.update(os.path.join(dirpath, f) for f in filenames)
    return out


def test_screenshots_are_never_stored_ac29():
    image = synthetic_png()
    project, temp = Path(__file__).resolve().parents[1], Path(tempfile.gettempdir())
    before_project, before_temp = _files_under(project), set(os.listdir(temp))
    client = FakeGemini(gemini_rows())

    result = import_screenshots([image], IMPORT, NOW, [], api_key="k", model="m", gemini_client=client)
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    tasks, _ = rows_to_tasks([r for r in result.rows if r.flag != "unresolved"], NOW, "screenshot")
    PlannerService(repo, pid, clock=lambda: NOW).change(lambda s, now: replace(s, tasks=tasks))

    part = client.calls[0].contents[0]
    assert part.inline_data.data == image and part.inline_data.mime_type == "image/png"  # inline bytes
    assert client.uploads == []  # no Files API
    assert not any(isinstance(v, (bytes, bytearray)) for v in _walk(repo._planners))
    assert not any(isinstance(v, (bytes, bytearray)) for v in _walk(result))  # text rows only
    assert _files_under(project) == before_project
    assert set(os.listdir(temp)) - before_temp == set()


def test_gemini_crash_never_escapes_and_saves_nothing_ac47():
    repo = MemoryRepo()
    pid = repo.create_planner(Preferences())
    result = run(FakeGemini(error=RuntimeError("boom")), ocr_available=lambda: False)
    assert result.rows == []
    assert "couldn't be read" in result.notes[0] and "Traceback" not in result.notes[0]
    assert repo.load(pid).tasks == []


def test_paste_import_uses_the_same_review_rows():
    result = import_text(OCR_TEXT, IMPORT, NOW, [])
    assert [(r.title, r.type, r.engine) for r in result.rows] == [("Lab 3 report", "lab_report", "Paste")]


def test_type_inference_and_learned_estimates():
    assert infer_type("Midterm preparation worksheet") == "exam_prep"
    assert infer_type("Lab 4 report: edge detection") == "lab_report"
    assert infer_type("Mini-project milestone 2") == "project"
    assert infer_type("Quiz 3") == "quiz"
    assert infer_type("Chapter 24 exercises") == "reading"
    assert infer_type("Problem set 5") == "assignment"
    history = [make_task("Old lab", 2, at(-5, 23, 59), type="lab_report", status="completed",
                         actual_hours=3.0, learning_eligible=True, completed_at=at(-5, 20)) for _ in range(3)]
    row = import_text(OCR_TEXT, IMPORT, NOW, history).rows[0]
    assert (row.estimate_raw, row.estimate) == (3.0, 4.0)  # 3 h default x 1.3 = 3.9 -> 4.0
