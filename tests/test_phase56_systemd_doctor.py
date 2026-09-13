from __future__ import annotations

from pathlib import Path

from cube.doctor import check_corpus_verify_timer, check_course_sources, check_state
from cube.systemd_units import plan_install


def test_corpus_verify_units_are_installable(repo: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "systemd"
    names = {destination.name for _, destination in plan_install(source, repo / "units")}
    assert {"cube-corpus-verify.service", "cube-corpus-verify.timer"} <= names

    service = (source / "cube-corpus-verify.service").read_text(encoding="utf-8")
    timer = (source / "cube-corpus-verify.timer").read_text(encoding="utf-8")
    assert "WorkingDirectory=%h/Public/software/borg-cube" in service
    assert "uv run python tools/corpus_verify.py" in service
    assert "uv run cube notify --kind error" in service
    assert "OnCalendar=monthly" in timer and "Persistent=true" in timer

    laptop_service = (source / "cube-worker-laptop.service").read_text(encoding="utf-8")
    laptop_timer = (source / "cube-worker-laptop.timer").read_text(encoding="utf-8")
    assert "cube worker --once --host laptop" in laptop_service
    assert "ConditionHost=lc-dell" in laptop_service
    assert "OnCalendar=*:0/5" in laptop_timer and "Persistent=true" in laptop_timer


def test_doctor_phase56_checks(repo: Path, settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config_home = repo / "xdg"
    unit_dir = config_home / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "cube-corpus-verify.timer").write_text("[Timer]\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    events = repo / "state" / "events.jsonl"
    events.write_text("{}\n", encoding="utf-8")
    configured = repo / "org" / "custom-course.org"
    configured.write_text("#+COURSE_CODE: CS 123\n", encoding="utf-8")
    settings.course_files = [Path("org/custom-course.org")]

    assert check_corpus_verify_timer(settings)[0].ok
    assert check_course_sources(settings)[0].ok
    state = {check.name: check for check in check_state(settings)}
    assert state["state:events-readable"].ok

    settings.course_files = [Path("org/missing-course.org")]
    assert not check_course_sources(settings)[0].ok
