from __future__ import annotations

import json

import pytest
import yaml

from cube.cli import main
from cube.model import BeadHeader
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())


def _assignment_header() -> str:
    return BeadHeader(
        xid="manual:existing",
        provenance=[{"source": "tests/test_assign_create.py", "locator": "fixture"}],
    ).render()


def test_assign_updates_labels_and_header(engine_repo, fake_bd: FakeBd, capsys) -> None:
    fake_bd.add("cube-1", description=_assignment_header(), labels=["role:senior", "old:keep"])

    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "assign",
                "cube-1",
                "--role",
                "programmer",
                "--person",
                "alex-example",
                "--project",
                "test-project",
                "--deadline",
                "2026-10-01",
                "--note",
                "Robert assigned this",
                "--priority",
                "1",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["bead"]["labels"] == [
        "old:keep",
        "role:programmer",
        "person:alex-example",
        "project:test-project",
    ]
    updated = fake_bd.bead("cube-1")
    header = yaml.safe_load(updated["description"].split("---", 2)[1])
    assert header["deadline"] == "2026-10-01"
    assert header["provenance"][-1]["source"] == "cube assign"
    assert header["provenance"][-1]["by"] == "robert"
    assert updated["priority"] == 1


def test_assign_refuses_unknown_role_person_or_project(
    engine_repo, fake_bd: FakeBd, capsys
) -> None:
    fake_bd.add("cube-1", description=_assignment_header())
    for flag, value, message in (
        ("--role", "nope", "no such role"),
        ("--person", "nope", "no such person"),
        ("--project", "nope", "no such project"),
    ):
        assert main(["--root", str(engine_repo), "assign", "cube-1", flag, value]) == 2
        assert message in capsys.readouterr().err


def test_create_requires_provenance_and_acceptance(engine_repo, capsys) -> None:
    assert main(["--root", str(engine_repo), "create", "--title", "A task", "--kind", "audit"]) == 2
    assert "provenance" in capsys.readouterr().err
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "create",
                "--title",
                "A task",
                "--kind",
                "audit",
                "--provenance",
                "tests/test_assign_create.py::test",
            ]
        )
        == 2
    )
    assert "acceptance" in capsys.readouterr().err


def test_create_dry_run_prints_exact_bd_call(engine_repo, capsys) -> None:
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "create",
                "--title",
                "Check the report",
                "--kind",
                "audit",
                "--role",
                "auditor",
                "--person",
                "alex-example",
                "--project",
                "test-project",
                "--provenance",
                "tests/test_assign_create.py::test_create_dry_run_prints_exact_bd_call",
                "--acceptance",
                "pytest reports this task's expected evidence",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["commands"][0].startswith("bd create 'Check the report'")
    assert "role:auditor" in payload["commands"][0]


def test_create_approval_is_a_decision_not_design_work(engine_repo, capsys) -> None:
    # Robert, 2026-09-07: the sysadmin's per-host change bundle waits for him
    # and is never dispatched by the marshal.
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "create",
                "--title",
                "ws: 87 security upgrades",
                "--kind",
                "approval",
                "--xid",
                "sysadmin:ws:upgrades",
                "--provenance",
                "ws:apt list --upgradable::1",
                "--acceptance",
                "apt list --upgradable is empty",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert "kind:approval" in payload["labels"]
    assert "needs:robert" in payload["labels"]
    assert not any(label.startswith("stage:") for label in payload["labels"])
    assert payload["xid"] == "sysadmin:ws:upgrades"


def test_a_configured_checkout_counts_as_a_project(engine_repo, engine_settings) -> None:
    # Robert, 2026-09-07: FLOPO has a checkout under cube.yaml projects but no
    # project node in the research KG; the configured checkout is enough.
    from cube.commands._common import require_project
    from cube.config import ProjectRunnerProfile

    engine_settings.projects["flopo"] = ProjectRunnerProfile(path=engine_repo, runner="codex")
    assert require_project(engine_settings, "flopo") == "flopo"
    with pytest.raises(ValueError, match="no such project"):
        require_project(engine_settings, "nowhere")
