from datetime import date
from pathlib import Path

from cube.sources.calendar import events_in_window, load_calendars, match_people, parse_ics

FIX = Path(__file__).parent / "fixtures"


def test_parse_ics() -> None:
    events = parse_ics(FIX / "work.cal")
    assert len(events) == 4
    by = {e.uid: e for e in events}
    e1 = by["ev1@example"]
    assert e1.start == date(2026, 9, 3) and e1.start_dt is not None
    assert e1.start_dt.hour == 10  # 07:00Z in Asia/Riyadh
    assert e1.attendees == ["alex.example@example.org"]  # folded line rejoined
    assert e1.attendee_names == ["alex.example@example.org"]
    e2 = by["ev2@example"]
    assert e2.all_day and e2.start == date(2026, 9, 3) and e2.end == date(2026, 9, 4)
    e3 = by["ev3@example"]
    assert e3.rrule is not None and e3.start == date(2026, 9, 10) and e3.start_dt.hour == 15  # type: ignore[union-attr]
    assert by["ev4@example"].summary == "Old event, escaped comma"
    assert e1.locator.endswith("UID=ev1@example") and "work.cal:" in e1.locator


def test_window_and_matching() -> None:
    events = load_calendars(FIX)
    tomorrow = events_in_window(events, date(2026, 9, 3), date(2026, 9, 3))
    assert [e.uid for e in tomorrow] == ["ev2@example", "ev1@example"]  # all-day first
    # recurrence is ignored beyond DTSTART: the weekly meeting does not appear on 17 Sep
    assert events_in_window(events, date(2026, 9, 17), date(2026, 9, 17)) == []
    people = {
        "alex-example": ["Alex Example", "alex.example@example.org"],
        "bea-sample": ["Bea Sample"],
        "al-other": ["Al"],
    }
    assert match_people(tomorrow[1], people) == ["alex-example"]  # by attendee email
    assert match_people(tomorrow[0], people) == ["bea-sample"]  # by full name in summary
    # a lone first name only matches as a whole word in the summary
    assert "al-other" not in match_people(tomorrow[1], people)
