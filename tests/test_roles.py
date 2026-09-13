from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cube.model import RunResult
from cube.roles import Role, RoleError, assemble_prompt, load_all, load_role, result_schema
from tests.helpers_engine import REPO_ROOT

ROLE_NAMES = {
    "grant-writer",
    "advisor",
    "auditor",
    "concierge",
    "editor",
    "group-leader",
    "lecturer",
    "liaison",
    "marshal",
    "programmer",
    "scribe",
    "secretary",
    "senior",
    "sentinel",
    "sysadmin",
    "student-researcher",
    "student-reviewer",
}


def test_all_repo_roles_load() -> None:
    roles, errors = load_all(REPO_ROOT)
    assert errors == {}
    assert set(roles) == ROLE_NAMES
    for role in roles.values():
        assert role.autonomous_actions == []
        assert (REPO_ROOT / role.system_prompt_file).exists()


def test_group_leader_closes_on_its_own() -> None:
    # Robert, 2026-09-07: the top of the review chain closes; he decides only
    # security and privacy matters.
    role = load_role(REPO_ROOT, "group-leader")
    assert role.can_close and role.review_required_by is None
    assert not role.closes_need_robert
    assert any("closes without a review" in w for w in role.lint_warnings)


def test_role_yaml_is_clean() -> None:
    auditor = load_role(REPO_ROOT, "auditor")
    assert any("secrets, data loss, licence violation" in e.condition for e in auditor.escalation)
    assert not [w for w in auditor.lint_warnings if "unquoted" in w or "flattened" in w]
    assert all(isinstance(t, str) for t in auditor.triggers)


def test_rejects_outbound_autonomous_action(tmp_path: Path) -> None:
    data = yaml.safe_load((REPO_ROOT / "roles" / "senior.yaml").read_text())
    data["autonomous_actions"] = ["send_mattermost_dm"]
    with pytest.raises(ValueError, match="outbound"):
        Role.model_validate(data)


def test_name_must_match_stem(tmp_path: Path) -> None:
    root = tmp_path
    (root / "roles" / "prompts").mkdir(parents=True)
    (root / "roles" / "prompts" / "x.md").write_text("# x\n")
    data = yaml.safe_load((REPO_ROOT / "roles" / "senior.yaml").read_text())
    data["system_prompt_file"] = "roles/prompts/x.md"
    (root / "roles" / "other.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(RoleError, match="does not equal file stem"):
        load_role(root, "other")
    with pytest.raises(RoleError, match="no such role"):
        load_role(root, "missing")


def test_unknown_key_rejected() -> None:
    data = yaml.safe_load((REPO_ROOT / "roles" / "senior.yaml").read_text())
    data["surprise"] = 1
    with pytest.raises(ValueError):
        Role.model_validate(data)


def test_assemble_prompt_sections() -> None:
    role = load_role(REPO_ROOT, "programmer")
    text = assemble_prompt(
        role,
        "### Bead cube-1\nfix the thing",
        root=REPO_ROOT,
        skill_paths={"software-release": Path("/skills/software-release"), "code-audit": None},
    )
    assert text.startswith("# Programmer")
    assert "## Doctrine" in text and "Crons watch, models act" in text
    assert "## Skills available" in text and "/skills/software-release" in text
    assert "not installed here" in text
    assert "## Output contract" in text and '"bead_updates"' in text
    assert text.rstrip().endswith("fix the thing")
    assert "\u2014" not in text


def test_result_schema_matches_model() -> None:
    schema = result_schema()
    assert schema["title"] == "RunResult"
    assert "summary" in schema["required"]
    RunResult.model_validate({"summary": "x"})


def test_timeout_default() -> None:
    role = load_role(REPO_ROOT, "senior")
    assert role.timeout_seconds == 1800.0
