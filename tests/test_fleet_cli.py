"""Fleet subcommands are auto-discovered and default to no external writes."""

import json

import pytest

from cube.cli import main
from cube.fleet_github import queue_record
from cube.resources import load_limits


@pytest.fixture(autouse=True)
def no_external_process(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run invoked an external process")

    monkeypatch.delenv("CUBE_AGENT", raising=False)
    monkeypatch.setattr("cube.compute._run", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)


def test_limits_cli_discovered_and_set_dry_run_does_not_persist(settings, capsys):
    assert main(["--root", str(settings.root), "fleet", "limits", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["limits"]["concurrent_slurm_jobs"] == 4
    assert (
        main(
            [
                "--root",
                str(settings.root),
                "fleet",
                "limits",
                "--set",
                '{"concurrent_slurm_jobs":2}',
                "--evidence",
                "user:requested",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["new"]["concurrent_slurm_jobs"] == 2
    assert load_limits(settings).concurrent_slurm_jobs == 4


@pytest.mark.parametrize(
    ("target", "workdir", "host"),
    [
        ("ibex", "/ibex/scratch/projects/c2014/research", "dragon"),
        ("unimatrix01", "/storage/research", "unimatrix01"),
    ],
)
def test_submit_cli_discovered_and_only_prepares_commands(
    settings, tmp_path, capsys, target, workdir, host
):
    script = tmp_path / "research.sh"
    script.write_text("#!/bin/sh\ntrue\n")
    assert (
        main(
            [
                "--root",
                str(settings.root),
                "fleet",
                "submit",
                target,
                str(script),
                "--agent",
                "ontology",
                "--workdir",
                workdir,
                "--needs",
                '{"cpus":1,"memory_gib":1,"gpus":0,"walltime_hours":1}',
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry-run"
    assert result["dry_run"] is True
    assert all(host in argv for argv in result["commands"])
    assert "sbatch" in result["commands"][-1][-1]


def test_publish_cli_discovered_and_leaves_queue_pending(settings, capsys):
    record = queue_record(
        settings,
        "ontology",
        "run-test",
        "Reproduced the public benchmark",
        sources=["doi:10.1234/example"],
        dry_run=False,
    )
    assert main(["--root", str(settings.root), "fleet", "publish", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == [{"id": record["id"], "status": "pending", "dry_run": True}]
    saved = json.loads((settings.state_dir() / "fleet-github" / f"{record['id']}.json").read_text())
    assert saved["status"] == "pending"
