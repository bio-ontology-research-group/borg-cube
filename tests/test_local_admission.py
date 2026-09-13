"""One physical local inference budget, regardless of logical tier or harness."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from cube.config import TierEntry
from cube.engine import execute
from cube.engine import lease as leases
from cube.model import RunResult
from cube.resources import (
    LocalCapacityFull,
    cancel_unstarted_research,
    local_inference_slot,
    reserve_research_run,
    update_limits,
)
from cube.router import Backoff
from cube.runners import StubRunner
from cube.runners.base import RunOutcome
from tests.helpers_engine import fixtures

globals().update(fixtures())
NOW = datetime(2026, 9, 8, 20, tzinfo=UTC)


def test_local_slots_shared_across_harnesses_and_threads(engine_settings):
    update_limits(engine_settings, {"local_inference_concurrency": 1}, "test:slots", False)

    def attempt():
        with pytest.raises(LocalCapacityFull):
            with local_inference_slot(engine_settings, "claude@local"):
                pytest.fail("must not start")

    with local_inference_slot(engine_settings, "hermes@local"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(attempt).result()
        with local_inference_slot(engine_settings, "claude@openrouter"):
            pass
    with pytest.raises(RuntimeError, match="fixture"):
        with local_inference_slot(engine_settings, "local"):
            raise RuntimeError("fixture")
    with local_inference_slot(engine_settings, "hermes@local"):
        pass


def test_engine_local_admission_queues_without_running_or_charging(engine_settings, fake_bd):
    engine_settings.tiers["plan"] = [TierEntry(runner="hermes", provider="local", model="fixture")]
    update_limits(engine_settings, {"local_inference_concurrency": 0}, "test:pause", False)
    fake_bd.add(
        "cube-1", labels=["kind:finding"], description="---\nxid: fixture:slots\n---\nInspect"
    )
    runner = StubRunner(RunResult(summary="fixture"))
    result = execute(
        engine_settings, "senior", bead="cube-1", runner=runner, available=lambda _: True, now=NOW
    )
    assert result.state == "queued", result.error
    assert not runner.calls
    assert leases.load(engine_settings.state_dir(), "cube-1") is None
    assert not (engine_settings.state_dir() / "budget.json").exists()


def test_local_timeout_and_lease_match_without_changing_cloud(engine_settings, fake_bd):
    engine_settings.tiers["plan"] = [TierEntry(runner="hermes", provider="local", model="fixture")]
    fake_bd.add(
        "cube-1", labels=["kind:finding"], description="---\nxid: fixture:deadline\n---\nInspect"
    )

    class CheckLease(StubRunner):
        def run(self, ctx):
            lease = leases.load(engine_settings.state_dir(), "cube-1")
            assert (datetime.fromisoformat(lease.expires) - NOW).total_seconds() == 3300
            return super().run(ctx)

    runner = CheckLease(RunResult(summary="fixture"))
    result = execute(
        engine_settings, "senior", bead="cube-1", runner=runner, available=lambda _: True, now=NOW
    )
    assert result.ok, result.error
    assert runner.calls[0].timeout == 2700
    assert runner.calls[0].env["CUBE_LOCAL_MAX_TURNS"] == "6"
    cloud = StubRunner(RunResult(summary="fixture"))
    result = execute(engine_settings, "senior", runner_name="stub", runner=cloud, now=NOW)
    assert result.ok
    assert cloud.calls[0].timeout == 1800


def test_cancelled_admission_preserves_audit_without_spending_interval(engine_settings):
    first = reserve_research_run(
        engine_settings, "fixture", autonomous=True, dry_run=False, now=NOW
    )
    cancel_unstarted_research(engine_settings, first["id"], "local endpoint full")
    second = reserve_research_run(
        engine_settings, "fixture", autonomous=True, dry_run=False, now=NOW
    )
    assert second["id"] != first["id"]
    records = json.loads((engine_settings.state_dir() / "fleet-research.json").read_text())
    assert len(records) == 2 and records[0]["cancelled_before_start"]


def test_timeout_releases_slot_and_backs_off_from_finish_time(engine_settings, fake_bd):
    engine_settings.tiers["plan"] = [TierEntry(runner="hermes", provider="local", model="fixture")]

    class TimedOut(StubRunner):
        def run(self, ctx):
            return RunOutcome("", None, None, {}, 124, "timeout", [], error="timeout")

    report = execute(
        engine_settings,
        "senior",
        runner=TimedOut(),
        available=lambda _: True,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    assert report.state == "error"
    backoff = Backoff(engine_settings.state_dir())
    until = backoff.blocked_until("hermes@local", model="fixture")
    assert until and until > datetime.fromisoformat(report.finished)
    with local_inference_slot(engine_settings, "hermes@local"):
        pass
