"""Resolve Teams due text ("Due tomorrow at 11:59 PM") to an IST deadline (R43, D-2).

Every result carries a flag:
- none:       the full date and time were written out;
- inferred:   something was assumed (relative word, weekday, year, time, day/month order);
- ambiguous:  a weekday equal to the screenshot's weekday (read as next week);
- unresolved: no date was found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from autoplanner.config import TZ

Flag = Literal["none", "inferred", "ambiguous", "unresolved"]
DEFAULT_TIME = time(23, 59)

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
          "oct": 10, "nov": 11, "dec": 12}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
            r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
WEEKDAY_RE = (r"\b(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?"
              r"|sat(?:urday)?|sun(?:day)?)\b\.?")
ORD = r"(?:st|nd|rd|th)?"

TIME_12H = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
TIME_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
NOON = re.compile(r"\bnoon\b", re.I)
MIDNIGHT = re.compile(r"\bmidnight\b", re.I)
ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
MONTH_DAY = re.compile(rf"\b{MONTH_RE}\s+(\d{{1,2}}){ORD}\b(?:,?\s+(\d{{4}}))?", re.I)
DAY_MONTH = re.compile(rf"\b(\d{{1,2}}){ORD}\s+(?:of\s+)?{MONTH_RE}(?:,?\s+(\d{{4}}))?", re.I)
RELATIVE = re.compile(r"\b(today|tonight|tomorrow|yesterday)\b", re.I)
IN_DAYS = re.compile(r"\bin\s+(\d{1,2})\s+days?\b", re.I)
WEEKDAY = re.compile(WEEKDAY_RE, re.I)


@dataclass(frozen=True)
class ResolvedDate:
    deadline: datetime | None
    flag: Flag
    reasons: tuple[str, ...] = ()

    @property
    def date_check(self) -> str:
        """Text for the review table's Date check column (R44)."""
        if self.flag == "unresolved":
            return "✖ needs a date"
        if self.flag == "ambiguous":
            return "⚠ " + "; ".join(self.reasons)
        if self.flag == "inferred":
            return "ⓘ " + "; ".join(self.reasons)
        return ""


def _closest_year(month: int, day: int, ref: date) -> date | None:
    candidates = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: (abs((d - ref).days), d < ref))


def _make_date(year: int | None, month: int, day: int, ref: date, reasons: list[str]) -> date | None:
    if year is None:
        found = _closest_year(month, day, ref)
        if found:
            reasons.append("year assumed")
        return found
    year = year + 2000 if year < 100 else year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_time(text: str, reasons: list[str]) -> tuple[time | None, str]:
    m = TIME_12H.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= hour <= 12 and minute < 60:
            hour = hour % 12 + (12 if m.group(3).lower() == "p" else 0)
            return time(hour, minute), text[:m.start()] + " " + text[m.end():]
    m = TIME_24H.search(text)
    if m:
        return time(int(m.group(1)), int(m.group(2))), text[:m.start()] + " " + text[m.end():]
    if NOON.search(text):
        return time(12, 0), NOON.sub(" ", text)
    if MIDNIGHT.search(text):
        reasons.append("midnight read as 23:59")
        return time(23, 59), MIDNIGHT.sub(" ", text)
    return None, text


def _extract_date(text: str, ref: date, reasons: list[str]) -> tuple[date | None, bool]:
    """Returns (date, ambiguous)."""
    m = RELATIVE.search(text)
    if m:
        offset = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}[m.group(1).lower()]
        reasons.append("relative to the screenshot date")
        return ref + timedelta(days=offset), False
    m = ISO.search(text)
    if m:
        return _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), ref, reasons), False
    m = MONTH_DAY.search(text)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(year, MONTHS[m.group(1)[:3].lower()], int(m.group(2)), ref, reasons), False
    m = DAY_MONTH.search(text)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(year, MONTHS[m.group(2)[:3].lower()], int(m.group(1)), ref, reasons), False
    m = NUMERIC.search(text)
    if m:
        first, second = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        if first > 12 or second > 12:
            day, month = (first, second) if first > 12 else (second, first)
        else:
            day, month = first, second
            reasons.append("day/month order assumed")
        return _make_date(year, month, day, ref, reasons), False
    m = IN_DAYS.search(text)
    if m:
        reasons.append("relative to the screenshot date")
        return ref + timedelta(days=int(m.group(1))), False
    m = WEEKDAY.search(text)
    if m:
        target = WEEKDAYS[m.group(1)[:3].lower()]
        ahead = (target - ref.weekday()) % 7
        if ahead == 0:
            reasons.append(f"same weekday as the screenshot date: read as next {WEEKDAY_NAMES[target]}")
            return ref + timedelta(days=7), True
        reasons.append(f"next {WEEKDAY_NAMES[target]} after the screenshot date")
        return ref + timedelta(days=ahead), False
    return None, False


def resolve_due(text: str | None, import_date: date) -> ResolvedDate:
    if not text or not text.strip():
        return ResolvedDate(None, "unresolved")
    reasons: list[str] = []
    cleaned = re.sub(r"[,;]", " ", text)
    at_time, rest = _extract_time(cleaned, reasons)
    day, ambiguous = _extract_date(rest, import_date, reasons)
    if day is None:
        return ResolvedDate(None, "unresolved")
    if at_time is None:
        at_time = DEFAULT_TIME
        reasons.append("time assumed 23:59")
    flag: Flag = "ambiguous" if ambiguous else ("inferred" if reasons else "none")
    return ResolvedDate(datetime.combine(day, at_time, TZ), flag, tuple(reasons))
