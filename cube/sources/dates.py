"""Fuzzy date parsing shared by the source adapters.

Handles the forms found in ~/org: ``Dec 2026``, ``December 2026``, ``1 Jan 2025``,
``16 April 2026``, ``<2023-10-26 Thu>``, ``2026-08-30``, ``[2025-10-23 Thu 07:21]`` and
season words (``Spring 2026``, ``summer 2025``, ``Fall 2023``).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# Season words map to the KAUST semester start used in cube.milestones.kaust_rules.
SEASONS: dict[str, tuple[int, int]] = {
    "spring": (1, 15),
    "summer": (6, 1),
    "fall": (8, 25),
    "autumn": (8, 25),
    "winter": (1, 15),
}

Precision = Literal["day", "month", "season"]

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_SEASON_RE = "|".join(SEASONS)

RE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
RE_DMY = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({_MONTH_RE})\.?\s+(\d{{4}})\b", re.I
)
RE_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
RE_MY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{4}})\b", re.I)
RE_SEASON = re.compile(rf"\b({_SEASON_RE})\s+(\d{{4}})\b", re.I)
RE_DM = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b(?!\s+\d{{4}})", re.I)


@dataclass(frozen=True)
class FuzzyDate:
    """A parsed date with the precision the text supported."""

    value: date
    precision: Precision
    raw: str

    def end_of_period(self) -> date:
        """Return the last day covered by the text (end of month for month precision)."""
        if self.precision == "month":
            last = calendar.monthrange(self.value.year, self.value.month)[1]
            return self.value.replace(day=last)
        return self.value


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_fuzzy_date(
    text: str, *, month_anchor: Literal["start", "end"] = "start"
) -> FuzzyDate | None:
    """Return the first date mentioned in ``text``, or None.

    ``month_anchor`` decides which day a month-only mention resolves to. Day-less
    mentions without a year (``9 April``) are deliberately not resolved.
    """
    m = RE_ISO.search(text)
    if m:
        try:
            return FuzzyDate(date(int(m[1]), int(m[2]), int(m[3])), "day", m[0])
        except ValueError:
            pass
    m = RE_DMY.search(text)
    if m:
        try:
            return FuzzyDate(date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), "day", m[0])
        except ValueError:
            pass
    m = RE_MDY.search(text)
    if m:
        try:
            return FuzzyDate(date(int(m[3]), MONTHS[m[1].lower()], int(m[2])), "day", m[0])
        except ValueError:
            pass
    m = RE_MY.search(text)
    if m:
        year, month = int(m[2]), MONTHS[m[1].lower()]
        value = _month_end(year, month) if month_anchor == "end" else date(year, month, 1)
        return FuzzyDate(value, "month", m[0])
    m = RE_SEASON.search(text)
    if m:
        month, day = SEASONS[m[1].lower()]
        return FuzzyDate(date(int(m[2]), month, day), "season", m[0])
    return None


def parse_day_month(text: str, year: int) -> date | None:
    """Resolve ``9 April`` style mentions with a caller-supplied year."""
    m = RE_DM.search(text)
    if not m:
        return None
    try:
        return date(year, MONTHS[m[2].lower()], int(m[1]))
    except ValueError:
        return None
