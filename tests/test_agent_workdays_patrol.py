"""The daily timer must reach every standing agent through the patrol registry."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from cube.config import Settings
from cube.patrols import agent_workdays, base


def test_agent_workday_and_budget_are_registered_patrols() -> None:
    assert "agent_workday" in base.names()
    assert "budget" in base.names()
    assert base.normalise("agent-workday") == "agent_workday"


def test_local_schedule_rotates_without_starting_deferred_work(settings: Settings) -> None:
    from cube.resources import schedule_local_workdays

    settings.fleet_limits.local_workday_concurrency = 1
    names = ["a", "b", "c"]
    assert schedule_local_workdays(settings, names) == ["a"]
    assert not (settings.state_dir() / "local-workday-schedule.json").exists()
    assert schedule_local_workdays(settings, names, dry_run=False) == ["a"]
    assert schedule_local_workdays(settings, names, dry_run=False) == ["b"]
    assert schedule_local_workdays(settings, names, dry_run=False) == ["c"]
    assert schedule_local_workdays(settings, names, dry_run=False) == ["a"]
    settings.fleet_limits.local_inference_concurrency = 0
    assert schedule_local_workdays(settings, names, dry_run=False) == []


def test_fleet_local_wave_does_not_queue_every_agent(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cube.config import TierEntry

    settings.fleet_enabled = True
    settings.tiers = {"plan": [TierEntry(runner="hermes", provider="local")]}
    agents = {
        name: SimpleNamespace(role="senior", runner=None, tier="plan") for name in ("a", "b", "c")
    }
    agents["coordinator"] = SimpleNamespace(role="group-leader", runner=None, tier="plan")
    monkeypatch.setattr(agent_workdays, "load_all_agents", lambda _: (agents, {}))
    seen = []

    class FakeWorkday:
        def __init__(self, name: str, **_: object) -> None:
            self.name = name

        def run(self, *args: object, **kwargs: object) -> SimpleNamespace:
            seen.append(self.name)
            return SimpleNamespace(as_dict=lambda: {"state": "finished"})

    monkeypatch.setattr(agent_workdays, "AgentWorkdayPatrol", FakeWorkday)
    report = agent_workdays.AgentWorkdaysPatrol().run(settings, date(2026, 9, 9), False)
    assert set(seen) == {"a", "coordinator"}
    assert report.data["workdays"]["b"]["state"] == "scheduled"
    seen.clear()
    agent_workdays.AgentWorkdaysPatrol().run(settings, date(2026, 9, 9), False)
    assert set(seen) == {"b", "coordinator"}


def test_patrol_runs_every_agent_and_isolates_failures(
    repo: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = {"coordinator": object(), "expert": object()}
    monkeypatch.setattr(
        agent_workdays, "load_all_agents", lambda _root: (agents, {"broken": "bad yaml"})
    )
    seen: list[str] = []

    class FakeWorkday:
        def __init__(self, name: str, *, runner_name: str | None = None) -> None:
            self.agent_name = name

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            seen.append(self.agent_name)
            if self.agent_name == "expert":
                raise ValueError("no charter")
            return SimpleNamespace(
                state="finished", as_dict=lambda: {"agent": self.agent_name, "state": "finished"}
            )

    monkeypatch.setattr(agent_workdays, "AgentWorkdayPatrol", FakeWorkday)
    patrol = base.make("agent-workday")
    report = patrol.run(settings, date(2026, 9, 3), True, beads=None)
    assert seen == ["coordinator", "expert"]
    assert report.data["workdays"]["coordinator"]["state"] == "finished"
    assert report.data["workdays"]["expert"]["state"] == "failed"
    assert any("broken: bad yaml" in w for w in report.warnings)
    assert any("expert: no charter" in w for w in report.warnings)
    assert report.failed is False
    assert "coordinator=finished" in report.summary


def test_workday_due_hourly_and_daily() -> None:
    from datetime import UTC, datetime

    from cube.agents import AgentWorkday, workday_due

    hourly = SimpleNamespace(
        workday=AgentWorkday(cron="hourly", max_minutes=30, max_runs=48, max_runs_per_tick=2)
    )
    daily = SimpleNamespace(workday=AgentWorkday(cron="07:00", max_minutes=90, max_runs=3))
    own_timer = SimpleNamespace(workday=AgentWorkday(cron="*/5 * * * *", max_minutes=5, max_runs=3))
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    assert workday_due(hourly, now, None)
    assert not workday_due(hourly, now, datetime(2026, 9, 4, 11, 30, tzinfo=UTC))
    assert workday_due(hourly, now, datetime(2026, 9, 4, 11, 0, tzinfo=UTC))
    assert hourly.workday.runs_per_tick == 2 and daily.workday.runs_per_tick == 3
    assert own_timer.workday.hourly and workday_due(own_timer, now, now)
    assert not workday_due(daily, datetime(2026, 9, 4, 6, 59, tzinfo=UTC), None, tz=UTC)
    assert workday_due(daily, datetime(2026, 9, 4, 7, 0, tzinfo=UTC), None, tz=UTC)
    assert not workday_due(daily, now, datetime(2026, 9, 4, 7, 1, tzinfo=UTC), tz=UTC)
    assert workday_due(daily, now, datetime(2026, 9, 3, 7, 1, tzinfo=UTC), tz=UTC)
    with pytest.raises(ValueError):
        AgentWorkday(cron="7am", max_minutes=1, max_runs=1)


def test_patrol_skips_agents_that_are_not_due(
    repo: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    daily = SimpleNamespace(workday=SimpleNamespace(cron="07:00", hourly=False))
    hourly = SimpleNamespace(workday=SimpleNamespace(cron="hourly", hourly=True))
    monkeypatch.setattr(
        agent_workdays, "load_all_agents", lambda _root: ({"daily": daily, "coord": hourly}, {})
    )
    monkeypatch.setattr(agent_workdays, "last_workday_start", lambda _s, _a: None)
    monkeypatch.setattr(
        agent_workdays, "workday_due", lambda agent, now, last: agent.workday.hourly
    )
    seen: list[str] = []

    class FakeWorkday:
        def __init__(self, name: str, *, runner_name: str | None = None) -> None:
            self.agent_name = name

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            seen.append(self.agent_name)
            return SimpleNamespace(state="idle", as_dict=lambda: {"state": "idle"})

    monkeypatch.setattr(agent_workdays, "AgentWorkdayPatrol", FakeWorkday)
    report = agent_workdays.AgentWorkdaysPatrol(now=datetime(2026, 9, 4, 12, tzinfo=UTC)).run(
        settings, date(2026, 9, 4), True
    )
    assert seen == ["coord"]
    assert report.data["workdays"]["daily"]["state"] == "not-due"
    assert "coord=idle" in report.summary
    forced = agent_workdays.AgentWorkdaysPatrol(force=True).run(settings, date(2026, 9, 4), True)
    assert set(forced.data["workdays"]) == {"coord", "daily"}


def test_patrol_never_plays_an_agent_that_lives_on_another_host(
    repo: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The laptop liaison ran on ws and timed out on mail it cannot reach (2026-09-05)."""
    laptop = SimpleNamespace(host="laptop", workday=SimpleNamespace(cron="hourly", hourly=True))
    local = SimpleNamespace(host=settings.host, workday=SimpleNamespace(cron="hourly", hourly=True))
    monkeypatch.setattr(
        agent_workdays,
        "load_all_agents",
        lambda _root: ({"liaison": laptop, "ontology": local}, {}),
    )
    monkeypatch.setattr(agent_workdays, "last_workday_start", lambda _s, _a: None)
    monkeypatch.setattr(agent_workdays, "workday_due", lambda agent, now, last: True)
    seen: list[str] = []

    class FakeWorkday:
        def __init__(self, name: str, *, runner_name: str | None = None) -> None:
            self.agent_name = name

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            seen.append(self.agent_name)
            return SimpleNamespace(state="idle", as_dict=lambda: {"state": "idle"})

    monkeypatch.setattr(agent_workdays, "AgentWorkdayPatrol", FakeWorkday)
    report = base.make("agent-workday").run(settings, date(2026, 9, 5), True, beads=None)
    assert seen == ["ontology"]
    assert report.data["workdays"]["liaison"] == {
        "agent": "liaison",
        "state": "off-host",
        "host": "laptop",
    }
    # an explicit --only still runs it (the laptop worker names its own agents)
    seen.clear()
    agent_workdays.AgentWorkdaysPatrol(only=["liaison"]).run(
        settings, date(2026, 9, 5), True, beads=None
    )
    assert seen == ["liaison"]


def test_due_agents_play_side_by_side_within_the_plan_slots(
    repo: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Robert, 2026-09-07: one twenty minute coordinator step must not hold every
    # other agent back until the next tick.
    import threading
    import time

    agents = {name: object() for name in ("a", "b", "c", "d")}
    monkeypatch.setattr(agent_workdays, "load_all_agents", lambda _root: (agents, {}))
    settings.slots = {"plan": 3, "implement": 1, "bulk": 1, "local": 1}
    running = 0
    peak = 0
    lock = threading.Lock()

    class SlowWorkday:
        def __init__(self, name: str, *, runner_name: str | None = None) -> None:
            self.agent_name = name

        def run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1
            return SimpleNamespace(
                state="finished", as_dict=lambda: {"agent": self.agent_name, "state": "finished"}
            )

    monkeypatch.setattr(agent_workdays, "AgentWorkdayPatrol", SlowWorkday)
    report = base.make("agent-workday").run(settings, date(2026, 9, 7), True, beads=None)
    assert list(report.data["workdays"]) == ["a", "b", "c", "d"]
    assert all(v["state"] == "finished" for v in report.data["workdays"].values())
    assert 2 <= peak <= 3
