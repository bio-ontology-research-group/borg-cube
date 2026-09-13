"""Read-only ICS parser for ~/org/*.cal (Google Calendar exports).

Recurrence is handled naively: an event with RRULE is reported only at its DTSTART.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Riyadh"

RE_PROP = re.compile(r"^([A-Z][A-Z0-9-]*)((?:;[^:]*)?):(.*)$")
RE_CN = re.compile(r"CN=([^;:]+)")


@dataclass
class Event:
    uid: str
    summary: str
    start: date
    end: date | None
    start_dt: datetime | None
    all_day: bool
    attendees: list[str] = field(default_factory=list)
    attendee_names: list[str] = field(default_factory=list)
    location: str | None = None
    description: str | None = None
    rrule: str | None = None
    status: str | None = None
    path: Path | None = None
    line: int = 0

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line} UID={self.uid}"

    def haystack(self) -> str:
        parts = [self.summary, self.description or "", *self.attendees, *self.attendee_names]
        return " ".join(parts).lower()


def _unfold(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        if raw[:1] in {" ", "\t"} and out:
            ln, prev = out[-1]
            out[-1] = (ln, prev + raw[1:])
        else:
            out.append((i, raw.rstrip("\r")))
    return out


def _tz(name: str | None, default: str) -> ZoneInfo | None:
    for candidate in (name, default):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return None


def _parse_dt(
    value: str, params: str, default_tz: str
) -> tuple[date, datetime | None, bool] | None:
    value = value.strip()
    tzid = None
    m = re.search(r"TZID=([^;]+)", params)
    if m:
        tzid = m[1]
    local = _tz(None, default_tz)
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value, "%Y%m%d").date(), None, True
        except ValueError:
            return None
    try:
        if value.endswith("Z"):
            dt = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            if local is not None:
                dt = dt.astimezone(local)
        else:
            dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
            tz = _tz(tzid, default_tz)
            if tz is not None:
                dt = dt.replace(tzinfo=tz)
                if local is not None:
                    dt = dt.astimezone(local)
    except ValueError:
        return None
    return dt.date(), dt, False


def parse_ics(path: Path, default_tz: str = DEFAULT_TZ) -> list[Event]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_ics_text(text, path=path, default_tz=default_tz)


def parse_ics_text(
    text: str, path: Path | None = None, default_tz: str = DEFAULT_TZ
) -> list[Event]:
    events: list[Event] = []
    cur: dict[str, str] = {}
    params: dict[str, str] = {}
    attendees: list[str] = []
    names: list[str] = []
    start_line = 0
    cal_tz = default_tz
    in_event = False
    depth = 0
    for ln, line in _unfold(text):
        if line == "BEGIN:VEVENT":
            in_event, cur, params, attendees, names, start_line = True, {}, {}, [], [], ln
            continue
        if line == "END:VEVENT" and in_event:
            in_event = False
            ev = _build(cur, params, attendees, names, cal_tz, path, start_line)
            if ev is not None:
                events.append(ev)
            continue
        m = RE_PROP.match(line)
        if not m:
            continue
        key, prm, val = m[1], m[2], m[3]
        if not in_event:
            if key == "BEGIN":
                depth += 1
            elif key == "END":
                depth -= 1
            elif key == "X-WR-TIMEZONE" and depth == 0:
                cal_tz = val.strip() or default_tz
            continue
        if key == "ATTENDEE":
            attendees.append(val.replace("mailto:", "").strip().lower())
            cn = RE_CN.search(prm)
            if cn:
                names.append(cn[1].strip().strip('"'))
            continue
        if key not in cur:  # first occurrence wins (alarms are nested but rare in exports)
            cur[key] = val
            params[key] = prm
    return events


def _build(
    cur: dict[str, str],
    params: dict[str, str],
    attendees: list[str],
    names: list[str],
    cal_tz: str,
    path: Path | None,
    line: int,
) -> Event | None:
    if "DTSTART" not in cur:
        return None
    parsed = _parse_dt(cur["DTSTART"], params.get("DTSTART", ""), cal_tz)
    if parsed is None:
        return None
    start, start_dt, all_day = parsed
    end: date | None = None
    if "DTEND" in cur:
        pe = _parse_dt(cur["DTEND"], params.get("DTEND", ""), cal_tz)
        if pe is not None:
            end = pe[0]
            if all_day and end > start:
                end = end - timedelta(days=1)  # DTEND is exclusive for all-day events
    return Event(
        uid=cur.get("UID", ""),
        summary=_unescape(cur.get("SUMMARY", "")),
        start=start,
        end=end,
        start_dt=start_dt,
        all_day=all_day,
        attendees=attendees,
        attendee_names=names,
        location=_unescape(cur["LOCATION"]) if cur.get("LOCATION") else None,
        description=_unescape(cur["DESCRIPTION"]) if cur.get("DESCRIPTION") else None,
        rrule=cur.get("RRULE"),
        status=cur.get("STATUS"),
        path=path,
        line=line,
    )


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").strip()


def events_in_window(events: list[Event], start: date, end: date) -> list[Event]:
    """Events whose start falls in [start, end] (inclusive)."""
    return sorted(
        (e for e in events if start <= e.start <= end),
        key=lambda e: (e.start, e.start_dt.time() if e.start_dt else time.min),
    )


def load_calendars(org_dir: Path, default_tz: str = DEFAULT_TZ) -> list[Event]:
    events: list[Event] = []
    for path in sorted(org_dir.glob("*.cal")) + sorted(org_dir.glob("*.ics")):
        events.extend(parse_ics(path, default_tz))
    return events


def match_people(event: Event, people: dict[str, list[str]]) -> list[str]:
    """Return slugs whose names or emails appear in the event summary or attendee list.

    ``people`` maps slug to a list of aliases (full name, first name, emails). Single first
    names match only against the summary as a whole word; emails match attendees exactly.
    """
    hay = event.haystack()
    summary = event.summary.lower()
    hits: list[str] = []
    for slug, aliases in people.items():
        for alias in aliases:
            a = alias.lower().strip()
            if not a:
                continue
            if "@" in a:
                if a in event.attendees:
                    hits.append(slug)
                    break
                continue
            if " " in a:
                if a in hay:
                    hits.append(slug)
                    break
                continue
            if re.search(rf"\b{re.escape(a)}\b", summary):
                hits.append(slug)
                break
    return hits
