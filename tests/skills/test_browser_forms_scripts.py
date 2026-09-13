"""Tests for browser-forms fill_plan.py and mock_form.py on loopback only."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "browser-forms"
SCRIPTS = SKILL / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"browser_forms_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fill_plan = load_script("fill_plan")
mock_form = load_script("mock_form")


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
                "id": "travel_date",
                "label": "Travel date",
                "selector": "#travel_date",
                "control": "date",
                "required": True,
            },
            {
                "id": "cost_center",
                "label": "Cost center",
                "selector": "#cost_center",
                "control": "select",
                "required": True,
            },
            {
                "id": "policy_confirmed",
                "label": "Policy reviewed",
                "selector": "#policy_confirmed",
                "control": "checkbox",
            },
            {
                "id": "follow_up",
                "label": "Needs follow-up",
                "selector": '[name="follow_up"]',
                "control": "yes-no",
                "expected_matches": 2,
            },
        ],
    }


def answers() -> dict:
    evidence = [{"source": "request.yaml", "locator": "request"}]
    return {
        "answers": {
            "requester_name": {"value": "Robert Example", "evidence": evidence},
            "purpose": {"value": "Discuss the project plan", "evidence": evidence},
            "travel_date": {"value": "2026-10-01", "evidence": evidence},
            "cost_center": {"value": "mock-001", "evidence": evidence},
            "policy_confirmed": {"value": False, "evidence": evidence},
            "follow_up": {"value": "no", "evidence": evidence},
        }
    }


def write_yaml(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def mock_url():
    server = mock_form.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_mock_form_is_loopback_and_rejects_post(mock_url: str) -> None:
    with urlopen(mock_url, timeout=3) as response:
        html = response.read().decode("utf-8")
    assert '<form id="admin-request"' in html
    assert 'id="submit"' in html
    with pytest.raises(HTTPError) as error:
        urlopen(Request(mock_url + "submit", data=b"purpose=test", method="POST"), timeout=3)
    assert error.value.code == 405
    with pytest.raises(ValueError, match="loopback"):
        mock_form.make_server("0.0.0.0", 0)


def test_plan_checks_mock_selectors_redacts_and_stops(
    tmp_path: Path, capsys, mock_url: str
) -> None:
    form = write_yaml(tmp_path, "form.yaml", form_definition())
    answer_file = write_yaml(tmp_path, "answers.yaml", answers())
    assert (
        fill_plan.main(
            [
                "--form",
                str(form),
                "--answers",
                str(answer_file),
                "--check-url",
                mock_url,
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["ready_to_fill"] is True
    assert result["layout_changes"] == []
    assert [entry["order"] for entry in result["plan"]] == list(range(1, 8))
    assert result["plan"][0]["value"] == "[REDACTED: personal]"
    assert result["plan"][4]["action"] == "uncheck"
    assert result["plan"][5]["action"] == "click_choice"
    assert result["plan"][-1]["action"] == "stop_before_submit"
    assert all(entry["action"] != "submit" for entry in result["plan"])
    assert "Robert Example" not in json.dumps(result)


def test_layout_change_is_reported(tmp_path: Path, capsys, mock_url: str) -> None:
    definition = form_definition()
    definition["fields"][1]["selector"] = "#purpose_changed"
    form = write_yaml(tmp_path, "form.yaml", definition)
    answer_file = write_yaml(tmp_path, "answers.yaml", answers())
    assert (
        fill_plan.main(
            [
                "--form",
                str(form),
                "--answers",
                str(answer_file),
                "--check-url",
                mock_url,
                "--json",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["layout_changes"] == ["purpose: selector matched 0 elements, expected 1"]
    assert result["ready_to_fill"] is False


def test_missing_and_secret_values_are_safe(tmp_path: Path, capsys) -> None:
    answer_data = answers()
    del answer_data["answers"]["travel_date"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    answer_data["answers"]["purpose"]["value"] = token
    form = write_yaml(tmp_path, "form.yaml", form_definition())
    answer_file = write_yaml(tmp_path, "answers.yaml", answer_data)
    assert fill_plan.main(["--form", str(form), "--answers", str(answer_file), "--json"]) == 2
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["missing_required"] == ["travel_date"]
    assert result["blocked_secrets"] == ["purpose"]
    purpose = next(entry for entry in result["plan"] if entry["field"] == "purpose")
    assert purpose["value"] == "[REDACTED: secret]"
    assert purpose["action"] == "blocked_secret"


def test_password_field_and_remote_check_url_are_refused(tmp_path: Path, capsys) -> None:
    definition = form_definition()
    definition["fields"][0]["id"] = "password"
    secret = "never-print-this-value"
    answer_data = answers()
    answer_data["answers"]["password"] = {"value": secret, "evidence": ["user"]}
    form = write_yaml(tmp_path, "form.yaml", definition)
    answer_file = write_yaml(tmp_path, "answers.yaml", answer_data)
    assert fill_plan.main(["--form", str(form), "--answers", str(answer_file), "--json"]) == 1
    captured = capsys.readouterr()
    assert "password and credential fields are forbidden" in captured.err
    assert secret not in captured.out + captured.err

    definition = form_definition()
    form = write_yaml(tmp_path, "form-2.yaml", definition)
    assert (
        fill_plan.main(
            [
                "--form",
                str(form),
                "--answers",
                str(answer_file),
                "--check-url",
                "https://portal.example.invalid/form",
                "--json",
            ]
        )
        == 1
    )
    assert "accepts only" in capsys.readouterr().err


def test_unverified_source_blocks_the_plan(tmp_path: Path, capsys) -> None:
    definition = form_definition()
    definition["form"]["source"]["verified_on"] = "UNVERIFIED"
    definition["fields"][1]["selector"] = "<purpose selector>"
    form = write_yaml(tmp_path, "form.yaml", definition)
    answer_file = write_yaml(tmp_path, "answers.yaml", answers())
    assert fill_plan.main(["--form", str(form), "--answers", str(answer_file), "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert "form.source.verified_on must be an ISO date" in result["definition_gaps"]
    assert "purpose: selector is a placeholder" in result["definition_gaps"]
    assert result["ready_to_fill"] is False
