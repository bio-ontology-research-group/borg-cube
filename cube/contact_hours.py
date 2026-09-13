"""Contact hours: when real people may be reached. Agents work 24/7; people do not."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cube.config import ContactHours

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _hhmm(value: str) -> tuple[int, int]:
    hours, minutes = value.split(":")
    return int(hours), int(minutes)


def within_contact_hours(hours: ContactHours, now: datetime) -> bool:
    """True when ``now`` falls inside the contact window on a contact day."""
    local = now.astimezone(ZoneInfo(hours.tz))
    if _DAYS[local.weekday()] not in hours.days:
        return False
    start, end = _hhmm(hours.start), _hhmm(hours.end)
    return start <= (local.hour, local.minute) < end


def next_contact_window(hours: ContactHours, now: datetime) -> datetime:
    """The next instant inside the window at or after ``now`` (``now`` itself when inside)."""
    if within_contact_hours(hours, now):
        return now
    local = now.astimezone(ZoneInfo(hours.tz))
    start_h, start_m = _hhmm(hours.start)
    candidate = local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    for _ in range(8):
        if _DAYS[candidate.weekday()] in hours.days:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def contact_hours_text(hours: ContactHours) -> str:
    return f"{hours.start}-{hours.end} {hours.tz} on {', '.join(hours.days)}"
