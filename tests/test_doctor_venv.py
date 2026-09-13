"""Doctor must catch a venv whose cube entry point cannot import the package."""

from __future__ import annotations

import subprocess

import pytest

from cube.config import Settings
from cube.doctor import check_venv_import


def _fake_run(returncode: int):  # type: ignore[no-untyped-def]
    def run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["cwd"] == "/"
        assert "PYTHONPATH" not in kwargs["env"]
        return subprocess.CompletedProcess(
            cmd, returncode, "", "ModuleNotFoundError" if returncode else ""
        )

    return run


def test_missing_venv_is_a_warning(settings: Settings) -> None:
    (checks,) = [check_venv_import(settings)]
    assert checks[0].name == "venv:import" and not checks[0].ok and checks[0].severity == "warn"


def test_import_failure_is_an_error_with_the_fix(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = settings.root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr("cube.doctor.subprocess.run", _fake_run(1))
    check = check_venv_import(settings)[0]
    assert not check.ok and check.severity == "error"
    assert "reinstall-package borg-cube" in check.detail
    monkeypatch.setattr("cube.doctor.subprocess.run", _fake_run(0))
    assert check_venv_import(settings)[0].ok


def test_openrouter_key_warning_names_the_first_dead_entry(settings: Settings) -> None:
    from cube.config import TierEntry
    from cube.doctor import check_openrouter_key

    settings.tiers["plan"] = [TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash")]
    settings.env.pop("OPENROUTER_API_KEY", None)
    (check,) = check_openrouter_key(settings)
    assert not check.ok and check.severity == "warn" and "z-ai/glm-5.3-flash" in check.detail
    settings.env["OPENROUTER_API_KEY"] = "sk-or-test"
    assert check_openrouter_key(settings)[0].ok
