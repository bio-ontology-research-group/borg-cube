import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from cube.compute import status, submit
from cube.config import Paths
from cube.resources import FleetLimits, read_usage, update_limits


@pytest.fixture
def setup(tmp_path):
    settings = SimpleNamespace(root=tmp_path, paths=Paths(), fleet_limits=FleetLimits())
    script = tmp_path / "run.sh"
    script.write_bytes(b"#!/bin/bash\nprintf 'research result\\n'\n")
    return settings, script


def output(stdout=b"", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=b"failure" if code else b"")


def storage():
    return output(
        json.dumps(
            {"free_bytes": 100 * 1024**3, "total_bytes": 200 * 1024**3, "free_inodes": 20000}
        ).encode()
    )


def run(setup, **kwargs):
    settings, script = setup
    return submit(
        settings,
        "ontologist",
        kwargs.pop("target", "ibex"),
        script,
        kwargs.pop("workdir", "/ibex/scratch/projects/c2014/test"),
        kwargs.pop("needs", {}),
        **kwargs,
    )


def mock_run(monkeypatch, results):
    calls = []
    pending = iter(results)

    def fake(command, **kwargs):
        calls.append((command, kwargs))
        result = next(pending)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("cube.compute.subprocess.run", fake)
    return calls


def test_dry_run_has_no_calls_or_state(setup, monkeypatch):
    calls = mock_run(monkeypatch, [])
    result = run(setup)
    assert result["status"] == "dry-run"
    assert not calls
    assert not (setup[0].root / "state").exists()
    remote = shlex.split(result["commands"][1][-1])
    assert "--account=c2014" in remote
    assert "--partition=batch" in remote
    assert "--export=NONE" in remote


def test_submits_exact_bytes_and_records_job(setup, monkeypatch):
    calls = mock_run(monkeypatch, [storage(), output(b"123;ibex\n")])
    result = run(setup, dry_run=False)
    assert result["job_id"] == "123"
    assert calls[1][1]["input"] == setup[1].read_bytes()
    assert calls[1][0][-2] == "dragon"
    assert read_usage(setup[0])["reservations"][0]["status"] == "submitted"


def test_unimatrix_excludes_model_server(setup):
    result = run(setup, target="unimatrix01", workdir="/storage/research", needs={"gpus": 1})
    remote = shlex.split(result["commands"][1][-1])
    assert "--exclude=node005" in remote
    assert "--partition=debug" in remote
    assert "--gres=gpu:1" in remote


@pytest.mark.parametrize("workdir", ["/home/user", "/storage/../home", "relative", "/storageevil"])
def test_reject_bad_workdir(setup, workdir):
    with pytest.raises(ValueError):
        run(setup, target="unimatrix01", workdir=workdir)


def test_shell_metacharacters_are_quoted_as_path(setup):
    workdir = "/storage/$(touch bad); research"
    result = run(setup, target="unimatrix01", workdir=workdir)
    assert f"--chdir={workdir}" in shlex.split(result["commands"][1][-1])


def test_directives_rejected(setup):
    setup[1].write_bytes(b"#!/bin/bash\n #SBATCH --nodes=99\necho ok\n")
    with pytest.raises(ValueError, match="#SBATCH"):
        run(setup)


@pytest.mark.parametrize("expected", [-1, float("nan"), float("inf"), True])
def test_bad_output_estimate(setup, expected):
    with pytest.raises(ValueError):
        run(setup, needs={"expected_output_gib": expected})


def test_expected_output_preserves_headroom(setup, monkeypatch):
    calls = mock_run(monkeypatch, [storage()])
    result = run(setup, needs={"expected_output_gib": 90}, dry_run=False)
    assert result["status"] == "queued"
    assert len(calls) == 1
    assert not read_usage(setup[0])["active_jobs"]


def test_budget_queues_without_submission(setup, monkeypatch):
    update_limits(setup[0], {"concurrent_slurm_jobs": 0}, "test:stop", dry_run=False)
    calls = mock_run(monkeypatch, [storage()])
    assert run(setup, dry_run=False)["status"] == "queued"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "result", [output(code=255), output(b"unrecognized"), subprocess.TimeoutExpired("ssh", 45)]
)
def test_uncertain_submission_retains_reservation(setup, monkeypatch, result):
    mock_run(monkeypatch, [storage(), result])
    result = run(setup, dry_run=False)
    assert result["status"] == "uncertain"
    assert result["retry"] is False
    assert read_usage(setup[0])["active_jobs"] == 1


def test_confirmed_failure_releases_slot(setup, monkeypatch):
    mock_run(monkeypatch, [storage(), output(code=1)])
    assert run(setup, dry_run=False)["status"] == "failed"
    assert read_usage(setup[0])["active_jobs"] == 0


def test_missing_queue_does_not_close_job(setup, monkeypatch):
    mock_run(monkeypatch, [storage(), output(b"123"), output(), output(code=1), output(code=1)])
    job = run(setup, dry_run=False)
    assert status(setup[0], job["reservation"], dry_run=False)["status"] == "unknown"
    assert read_usage(setup[0])["active_jobs"] == 1


@pytest.mark.parametrize(
    "responses",
    [
        [output(), output(b"123|COMPLETED\n123.batch|COMPLETED\n")],
        [output(), output(code=1), output(b"JobId=123 JobState=FAILED ExitCode=1:0")],
    ],
)
def test_terminal_accounting_releases_slot(setup, monkeypatch, responses):
    mock_run(monkeypatch, [storage(), output(b"123"), *responses])
    job = run(setup, dry_run=False)
    status(setup[0], job["reservation"], dry_run=False)
    assert read_usage(setup[0])["active_jobs"] == 0
    assert read_usage(setup[0])["cpu_hours"] == 1


def test_status_dry_run_does_not_poll(setup, monkeypatch):
    calls = mock_run(monkeypatch, [storage(), output(b"123")])
    job = run(setup, dry_run=False)
    assert status(setup[0], job["reservation"])["status"] == "dry-run"
    assert len(calls) == 2


def test_invalid_storage_response_queues_without_submission(setup, monkeypatch):
    calls = mock_run(monkeypatch, [output(b"not JSON")])
    assert run(setup, dry_run=False)["status"] == "queued"
    assert len(calls) == 1


@pytest.mark.parametrize("needs", [{"walltime_hours": 1e308}, {"expected_output_gib": 1e308}])
def test_huge_finite_inputs_rejected_cleanly(setup, needs):
    with pytest.raises(ValueError):
        run(setup, needs=needs)
