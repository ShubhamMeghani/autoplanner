"""Date resolver table (AC-14). Import date: Wednesday 2026-10-14."""

from datetime import date, datetime

import pytest

from autoplanner.config import TZ
from autoplanner.importers.dates import resolve_due

IMPORT = date(2026, 10, 14)


def ist(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


CASES = [
    # AC-14 examples
    ("Due tomorrow at 11:59 PM", ist(2026, 10, 15, 23, 59), "inferred"),
    ("Due today at 5:00 PM", ist(2026, 10, 14, 17, 0), "inferred"),
    ("Due Friday", ist(2026, 10, 16, 23, 59), "inferred"),
    ("Due Wednesday 9 AM", ist(2026, 10, 21, 9, 0), "ambiguous"),
    ("Due Oct 20", ist(2026, 10, 20, 23, 59), "inferred"),
    ("Due 3 Jan", ist(2027, 1, 3, 23, 59), "inferred"),
    ("Due yesterday at 11:59 PM", ist(2026, 10, 13, 23, 59), "inferred"),
    ("Due October 17, 2026 21:00", ist(2026, 10, 17, 21, 0), "none"),
    ("Due sometime", None, "unresolved"),
    # more relative words and weekdays
    ("Due tonight at 9 pm", ist(2026, 10, 14, 21, 0), "inferred"),
    ("due tomorrow 8:30am", ist(2026, 10, 15, 8, 30), "inferred"),
    ("Due Thu at 11:59 PM", ist(2026, 10, 15, 23, 59), "inferred"),
    ("Due Tuesday", ist(2026, 10, 20, 23, 59), "inferred"),
    ("Due Sunday at noon", ist(2026, 10, 18, 12, 0), "inferred"),
    ("Due Wed", ist(2026, 10, 21, 23, 59), "ambiguous"),
    ("Due in 3 days", ist(2026, 10, 17, 23, 59), "inferred"),
    # month names, with and without years and weekdays
    ("Due Mon, Oct 20", ist(2026, 10, 20, 23, 59), "inferred"),
    ("Due October 20 at 11:59 PM", ist(2026, 10, 20, 23, 59), "inferred"),
    ("Due 20 October 2026, 10:00 AM", ist(2026, 10, 20, 10, 0), "none"),
    ("Due Nov 2nd 2026 at 5 PM", ist(2026, 11, 2, 17, 0), "none"),
    ("Past due Oct 13, 11:59 PM", ist(2026, 10, 13, 23, 59), "inferred"),
    ("Due Dec 31", ist(2026, 12, 31, 23, 59), "inferred"),
    ("Due Feb 1", ist(2027, 2, 1, 23, 59), "inferred"),
    ("Due Sept 30, 2026 23:59", ist(2026, 9, 30, 23, 59), "none"),
    # numeric and ISO dates
    ("Due 2026-10-25 18:00", ist(2026, 10, 25, 18, 0), "none"),
    ("Due 25/10/2026 6:00 PM", ist(2026, 10, 25, 18, 0), "none"),
    ("Due 05/11/2026 17:00", ist(2026, 11, 5, 17, 0), "inferred"),  # day/month order assumed
    ("Due 10/25/2026", ist(2026, 10, 25, 23, 59), "inferred"),  # US order is unambiguous here
    # midnight and empty input
    ("Due Friday at midnight", ist(2026, 10, 16, 23, 59), "inferred"),
    ("", None, "unresolved"),
    ("Assigned", None, "unresolved"),
]


@pytest.mark.parametrize("text,deadline,flag", CASES)
def test_resolver_table_ac14(text, deadline, flag):
    result = resolve_due(text, IMPORT)
    assert (result.deadline, result.flag) == (deadline, flag)


def test_table_has_at_least_25_cases():
    assert len(CASES) >= 25


def test_date_check_text_shows_the_reason():
    assert resolve_due("Due Wednesday", IMPORT).date_check.startswith("⚠ same weekday")
    assert resolve_due("Due sometime", IMPORT).date_check == "✖ needs a date"
    assert "time assumed 23:59" in resolve_due("Due Oct 20", IMPORT).date_check
    assert resolve_due("Due October 17, 2026 21:00", IMPORT).date_check == ""
