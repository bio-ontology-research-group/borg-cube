from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from cube.config import Paths
from cube.resources import (
    FleetLimits,
    finish_job,
    load_limits,
    mark_submitted,
    read_usage,
    release_job,
    reserve_job,
    reserve_research_run,
    update_limits,
)


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(root=tmp_path, paths=Paths(), fleet_limits=FleetLimits())


def reserve(settings, *, needs=None, dry_run=False, **storage):
    return reserve_job(
        settings,
        "ontologist",
        "dragon",
        needs or {"cpus": 8, "walltime_hours": 4},
        **(
            {"free_bytes": 100 * 1024**3, "total_bytes": 200 * 1024**3, "free_inodes": 20000}
            | storage
        ),
        dry_run=dry_run,
    )


def test_defaults_and_dry_runs_write_nothing(settings):
    assert load_limits(settings).daily_cpu_hours == 128
    update_limits(settings, {"daily_cpu_hours": 64}, "mattermost:message-1")
    reserve(settings, dry_run=True)
    assert not (settings.root / "state").exists()
    assert read_usage(settings)["active_jobs"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"job_cpus": -1},
        {"daily_cost_usd": float("nan")},
        {"daily_cpu_hours": float("inf")},
        {"job_gpus": True},
        {"unknown": 1},
        {"min_free_percent": 101},
    ],
)
def test_invalid_limits(settings, changes):
    with pytest.raises(ValueError):
        update_limits(settings, changes, "mattermost:message-1", dry_run=False)
    assert load_limits(settings) == FleetLimits()


@pytest.mark.parametrize(
    "needs",
    [
        {"cpus": -1},
        {"gpus": -1},
        {"walltime_hours": float("nan")},
        {"memory_gib": float("inf")},
        {"cpus": True},
        {"walltime_hours": 0},
        {"cpus": 9},
        {"memory_gib": 33},
        {"gpus": 2},
        {"walltime_hours": 5},
    ],
)
def test_invalid_job(settings, needs):
    with pytest.raises(ValueError):
        reserve(settings, needs=needs)
    assert read_usage(settings)["active_jobs"] == 0


def test_parallel_reservations_share_budget(settings):
    def attempt(_):
        try:
            return reserve(settings)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(12)))
    assert len([r for r in results if r]) == 4
    assert read_usage(settings)["cpu_hours"] == 128


def test_release_and_finish_preserve_charged_budget(settings):
    first, second = reserve(settings), reserve(settings)
    mark_submitted(settings, first, "123", dry_run=False)
    finish_job(settings, first, dry_run=False)
    release_job(settings, second, dry_run=False)
    assert read_usage(settings)["active_jobs"] == 0
    assert read_usage(settings)["cpu_hours"] == 64
    update_limits(settings, {"daily_cpu_hours": 64}, "mattermost:lower-budget", dry_run=False)
    with pytest.raises(ValueError, match="CPU"):
        reserve(settings)


def test_lower_limits_applies_without_cancelling_jobs(settings):
    reserve(settings)
    change = update_limits(
        settings,
        {"concurrent_slurm_jobs": 0},
        "mattermost:stop-new-jobs",
        dry_run=False,
    )
    assert change["previous"]["concurrent_slurm_jobs"] == 4
    assert load_limits(settings).concurrent_slurm_jobs == 0
    assert read_usage(settings)["active_jobs"] == 1
    with pytest.raises(ValueError, match="concurrent"):
        reserve(settings)


@pytest.mark.parametrize(
    "storage",
    [
        {"free_bytes": 10 * 1024**3},
        {"free_inodes": 2},
        {"total_bytes": 0},
        {"free_bytes": -1},
        {"free_bytes": float("nan")},
        {"total_bytes": 2000 * 1024**3},
    ],
)
def test_storage_headroom(settings, storage):
    with pytest.raises(ValueError):
        reserve(settings, **storage)


def test_gpu_hours_and_transition_preview(settings):
    update_limits(settings, {"daily_gpu_hours": 1}, "mattermost:budget", dry_run=False)
    job = reserve(settings, needs={"gpus": 1, "walltime_hours": 1})
    mark_submitted(settings, job, "77")
    assert read_usage(settings)["reservations"][0]["status"] == "reserved"
    with pytest.raises(ValueError, match="GPU"):
        reserve(settings, needs={"gpus": 1, "walltime_hours": 1})


def test_finishing_after_midnight_does_not_refund_today(settings, monkeypatch):
    job = reserve(settings)
    tomorrow = datetime.now(UTC) + timedelta(days=1)

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return tomorrow

    monkeypatch.setattr("cube.resources.datetime", NextDay)
    assert read_usage(settings)["cpu_hours"] == 32
    finish_job(settings, job, dry_run=False)
    assert read_usage(settings)["cpu_hours"] == 32


def test_research_preview_is_nonmutating(settings):
    result = reserve_research_run(settings, "ontologist", autonomous=True)
    assert result["dry_run"]
    assert not (settings.root / "state").exists()


def test_research_daily_limits_apply_to_inbox_work(settings):
    update_limits(settings, {"per_agent_daily_research_runs": 1}, "test:limits", dry_run=False)
    reserve_research_run(settings, "ontologist", dry_run=False)
    with pytest.raises(ValueError, match="agent research"):
        reserve_research_run(settings, "ontologist", dry_run=False)
    assert read_usage(settings)["research_runs_by_agent"] == {"ontologist": 1}


def test_research_global_limits_are_serialized(settings):
    update_limits(settings, {"daily_research_runs": 2}, "test:limits", dry_run=False)

    def attempt(index):
        try:
            return reserve_research_run(settings, f"agent-{index}", dry_run=False)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(8)))
    assert sum(result is not None for result in results) == 2
    assert read_usage(settings)["research_runs"] == 2


def test_autonomous_interval_spans_midnight_and_allows_inbox_work(settings):
    start = datetime(2026, 9, 8, 23, 0, tzinfo=UTC)
    reserve_research_run(settings, "ontologist", autonomous=True, dry_run=False, now=start)
    with pytest.raises(ValueError, match="interval"):
        reserve_research_run(
            settings,
            "ontologist",
            autonomous=True,
            dry_run=False,
            now=start + timedelta(hours=2),
        )
    reserve_research_run(settings, "ontologist", dry_run=False, now=start + timedelta(hours=2))
    reserve_research_run(
        settings,
        "ontologist",
        autonomous=True,
        dry_run=False,
        now=start + timedelta(hours=6),
    )


def test_daily_research_limit_resets_and_reduction_stops_new_work(settings):
    start = datetime(2026, 9, 8, 23, 0, tzinfo=UTC)
    update_limits(settings, {"daily_research_runs": 1}, "test:limits", dry_run=False)
    reserve_research_run(settings, "ontologist", dry_run=False, now=start)
    reserve_research_run(settings, "ontologist", dry_run=False, now=start + timedelta(days=1))
    update_limits(settings, {"daily_research_runs": 0}, "test:stop", dry_run=False)
    with pytest.raises(ValueError, match="fleet research"):
        reserve_research_run(settings, "ontologist", dry_run=False, now=start + timedelta(days=2))


def test_research_requires_unambiguous_time(settings):
    with pytest.raises(ValueError, match="timezone"):
        reserve_research_run(settings, "ontologist", now=datetime(2026, 9, 8))
