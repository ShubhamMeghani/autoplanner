"""Paste parser (AC-18)."""

from datetime import date
from pathlib import Path

from autoplanner.importers.dates import resolve_due
from autoplanner.importers.text_parser import parse_text

FIXTURE = Path(__file__).parent / "fixtures" / "paste_samples.txt"
IMPORT = date(2026, 10, 14)


def load_fixture():
    text = FIXTURE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("# "))
    paste, expected = body.split("=== EXPECTED ===")
    paste = paste.replace("=== INPUT ===", "")
    rows = []
    for line in expected.strip().splitlines():
        title, course, deadline, flag = [part.strip() for part in line.split(" | ")]
        rows.append((title, None if course == "-" else course, None if deadline == "-" else deadline, flag))
    return paste, rows


def test_paste_fixture_gives_the_expected_records_ac18():
    paste, expected = load_fixture()
    got = []
    for row in parse_text(paste):
        resolved = resolve_due(row.due_text, IMPORT)
        got.append((row.title, row.course, resolved.deadline.isoformat() if resolved.deadline else None,
                    resolved.flag))
    assert got == expected


def test_status_lines_are_recognised():
    rows = parse_text(load_fixture()[0])
    status = {r.title: r.status for r in rows}
    assert status["Problem set 5"] == "past_due"
    assert status["Mini-project milestone 2"] == "completed"
    assert status["Assignment 4: Graph algorithms"] == "upcoming"


def test_ocr_merged_lines_are_split():
    rows = parse_text("Lab 3 report\nE9 241 Due tomorrow at 11:59 PM\n")
    assert [(r.title, r.course, r.due_text) for r in rows] == [("Lab 3 report", "E9 241", "Due tomorrow at 11:59 PM")]


def test_titles_with_dashes_are_not_split():
    rows = parse_text("Assignment 3 - Graphs\nE0 251\nDue Friday\n")
    assert rows[0].title == "Assignment 3 - Graphs" and rows[0].course == "E0 251"


def test_ocr_shaped_text_from_the_teams_list():
    """What Tesseract reads from a Teams-style list: a heading and tab row come first."""
    text = ("Assignments\nUpcoming Past due Completed\n\nAssignment 4: Graph algorithms\n"
            "E0 251 Data Structures and Algorithms\nDue tomorrow at 11:59 PM\n\nProblem set 5\n"
            "MA 261 Probability Models\nDue Friday at 5:00 PM\n")
    rows = parse_text(text)
    assert [(r.title, r.course) for r in rows] == [
        ("Assignment 4: Graph algorithms", "E0 251 Data Structures and Algorithms"),
        ("Problem set 5", "MA 261 Probability Models")]
