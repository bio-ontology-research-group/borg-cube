"""Tests for the kaust-admin deterministic preparation script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "kaust-admin"
SCRIPT = SKILL / "scripts" / "form_prepare.py"


def load_script():
    spec = importlib.util.spec_from_file_location("kaust_admin_form_prepare", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


form_prepare = load_script()


def form_definition() -> dict:
    return {
        "form": {
            "id": "local-mock-request",
            "title": "Local mock request",
            "workflow": "travel-request",
            "source": {
                "path": "skills/browser-forms/scripts/mock_form.py",
                "locator": "GET /",
                "verified_on": "2026-09-02",
            },
            "steps": ["Prepare draft", "Robert reviews"],
            "signers": [{"role": "requester", "stage": "after review", "source": "local mock"}],
            "evidence_requirements": [
                {
                    "id": "request",
                    "description": "source request",
                    "required": True,
                    "source": "local mock",
                }
            ],
            "submit_selector": "#submit",
        },
        "fields": [
            {
                "id": "requester_name",
                "label": "Requester name",
                "selector": "#requester_name",
                "control": "text",
                "required": True,
                "sensitivity": "personal",
            },
            {
                "id": "purpose",
                "label": "Purpose",
                "selector": "#purpose",
                "control": "textarea",
                "required": True,
            },
            {
                "id": "policy_confirmed",
                "label": "Policy reviewed",
                "selector": "#policy_confirmed",
                "control": "checkbox",
            },
        ],
    }


def complete_answers() -> dict:
    return {
        "request_id": "cube-example",
        "provenance": [{"source": "request.yaml", "locator": "request"}],
        "answers": {
            "requester_name": {
                "value": "Robert Example",
                "evidence": [{"source": "request.yaml", "locator": "requester"}],
            },
            "purpose": {
                "value": "Discuss the project plan",
                "evidence": [{"source": "request.yaml", "locator": "purpose"}],
            },
            "policy_confirmed": {
                "value": False,
                "evidence": [{"source": "request.yaml", "locator": "policy_confirmed"}],
            },
        },
    }


def write_yaml(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_complete_package_is_redacted_and_ready(tmp_path: Path, capsys) -> None:
    form = write_yaml(tmp_path, "form.yaml", form_definition())
    answers = write_yaml(tmp_path, "answers.yaml", complete_answers())
    result_code = form_prepare.main(
        [
            "--form",
            str(form),
            "--answers",
            str(answers),
            "--screenshot",
            "runs/cube-example/form.png",
            "--field-table",
            "runs/cube-example/form.md",
            "--json",
        ]
    )
    assert result_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["approval_ready"] is True
    assert result["missing_required"] == []
    assert result["missing_evidence"] == []
    rows = {row["id"]: row for row in result["fields"]}
    assert rows["requester_name"]["value"] == "[REDACTED: personal]"
    assert rows["requester_name"]["evidence"] == ["[REDACTED: personal evidence]"]
    assert rows["policy_confirmed"]["value"] == "false"
    serialized = json.dumps(result)
    assert "Robert Example" not in serialized
    assert "kind: outbound" in result["approval_bead_body"]
    assert "redacted screenshot: runs/cube-example/form.png" in result["approval_bead_body"]
    assert "Robert performs any submit" in result["approval_bead_body"]


def test_missing_answers_and_evidence_block_approval(tmp_path: Path, capsys) -> None:
    data = complete_answers()
    del data["answers"]["policy_confirmed"]
    data["answers"]["purpose"] = "A scalar has no evidence"
    form = write_yaml(tmp_path, "form.yaml", form_definition())
    answers = write_yaml(tmp_path, "answers.yaml", data)
    assert form_prepare.main(["--form", str(form), "--answers", str(answers), "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["approval_ready"] is False
    assert result["missing_required"] == ["policy_confirmed"]
    assert result["missing_evidence"] == ["purpose"]
    assert "redacted screenshot path is missing" in result["approval_artifact_gaps"]
    assert "missing required answer: policy_confirmed" in result["approval_bead_body"]


def test_definition_gaps_are_reported_not_guessed(tmp_path: Path, capsys) -> None:
    definition = form_definition()
    definition["form"]["source"]["verified_on"] = "UNVERIFIED"
    definition["form"].pop("signers")
    form = write_yaml(tmp_path, "form.yaml", definition)
    answers = write_yaml(tmp_path, "answers.yaml", complete_answers())
    assert (
        form_prepare.main(
            [
                "--form",
                str(form),
                "--answers",
                str(answers),
                "--screenshot",
                "redacted.png",
                "--field-table",
                "redacted.md",
                "--json",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert "form.source.verified_on must be an ISO date" in result["definition_gaps"]
    assert "form.signers must list verified signer or approver roles" in result["definition_gaps"]


def test_password_fields_and_secret_values_are_never_exposed(tmp_path: Path, capsys) -> None:
    definition = form_definition()
    definition["fields"][0]["id"] = "portal_password"
    form = write_yaml(tmp_path, "form.yaml", definition)
    answers_data = complete_answers()
    secret = "do-not-print-this-password"
    answers_data["answers"]["portal_password"] = {"value": secret, "evidence": ["user"]}
    answers = write_yaml(tmp_path, "answers.yaml", answers_data)
    assert form_prepare.main(["--form", str(form), "--answers", str(answers), "--json"]) == 1
    captured = capsys.readouterr()
    assert "password and credential fields are forbidden" in captured.err
    assert secret not in captured.out + captured.err

    definition = form_definition()
    token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    answers_data = complete_answers()
    answers_data["answers"]["purpose"]["value"] = token
    form = write_yaml(tmp_path, "form-2.yaml", definition)
    answers = write_yaml(tmp_path, "answers-2.yaml", answers_data)
    assert (
        form_prepare.main(
            [
                "--form",
                str(form),
                "--answers",
                str(answers),
                "--screenshot",
                "redacted.png",
                "--field-table",
                "redacted.md",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["blocked_secrets"] == ["purpose"]
    assert result["fields"][1]["value"] == "[REDACTED: secret]"


def test_out_is_dry_run_until_apply(tmp_path: Path, capsys) -> None:
    form = write_yaml(tmp_path, "form.yaml", form_definition())
    answers = write_yaml(tmp_path, "answers.yaml", complete_answers())
    out = tmp_path / "result.json"
    args = [
        "--form",
        str(form),
        "--answers",
        str(answers),
        "--screenshot",
        "redacted.png",
        "--field-table",
        "redacted.md",
        "--json",
        "--out",
        str(out),
    ]
    assert form_prepare.main(args) == 0
    assert not out.exists()
    assert "dry run" in capsys.readouterr().err
    assert form_prepare.main([*args, "--apply"]) == 0
    capsys.readouterr()
    assert json.loads(out.read_text(encoding="utf-8"))["approval_ready"] is True
