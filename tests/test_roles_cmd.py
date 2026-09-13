"""cube roles lists every roles/*.yaml with runtime, tier and skills."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cube.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_roles_json_lists_repo_roles(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ROOT), "roles", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {r["name"] for r in payload["roles"]}
    assert {"group-leader", "programmer", "auditor", "sysadmin", "secretary"} <= names
    leader = next(r for r in payload["roles"] if r["name"] == "group-leader")
    assert leader["runtime"] == "claude" and leader["tier"] == "plan"
    assert payload["errors"] == {}


def test_roles_text_has_one_line_per_role(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ROOT), "roles"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == len(list((ROOT / "roles").glob("[!_]*.yaml")))
