"""Every shipped patrol timer must start a real, applying patrol run.

A timer that names a service which does not exist never fires, and a patrol
service without ``--apply`` dry-runs forever; both failed silently on ws.
"""

from __future__ import annotations

import re
from pathlib import Path

from cube.patrols import base

SYSTEMD = Path(__file__).resolve().parents[1] / "systemd"


def _unit_line(text: str) -> str:
    match = re.search(r"^Unit=(.+)$", text, flags=re.MULTILINE)
    assert match, "timer has no Unit= line"
    return match.group(1).strip()


def test_patrol_timers_reference_template_instances_of_known_patrols() -> None:
    known = set(base.names())
    timers = sorted(SYSTEMD.glob("cube-patrol-*.timer"))
    assert timers, "no patrol timers shipped"
    for timer in timers:
        unit = _unit_line(timer.read_text(encoding="utf-8"))
        match = re.fullmatch(r"cube-patrol@(.+)\.service", unit)
        assert match, f"{timer.name}: Unit={unit} is not a cube-patrol@ instance"
        assert base.normalise(match.group(1)) in known, f"{timer.name}: unknown patrol {unit}"


def test_patrol_service_applies_and_honours_kill_switch() -> None:
    service = (SYSTEMD / "cube-patrol@.service").read_text(encoding="utf-8")
    exec_line = re.search(r"^ExecStart=(.+)$", service, flags=re.MULTILINE)
    assert exec_line and exec_line.group(1).rstrip().endswith("cube patrol %i --apply")
    assert "ConditionPathExists=!%h/Public/software/borg-cube/state/KILL" in service


def test_every_timer_names_an_existing_service() -> None:
    shipped = {p.name for p in SYSTEMD.iterdir()}
    for timer in SYSTEMD.glob("*.timer"):
        unit = _unit_line(timer.read_text(encoding="utf-8"))
        template = re.sub(r"@.+\.service$", "@.service", unit)
        assert unit in shipped or template in shipped, f"{timer.name}: {unit} not shipped"


def test_every_service_sets_a_path_with_local_bin() -> None:
    """A user service has no login PATH; bd and the runners live in ~/.local/bin."""
    for service in SYSTEMD.glob("*.service"):
        text = service.read_text(encoding="utf-8")
        if "ExecStart=" not in text:
            continue
        paths = [
            line.removeprefix("Environment=PATH=").split(":")
            for line in text.splitlines()
            if line.startswith("Environment=PATH=")
        ]
        assert any("%h/.local/bin" in entries for entries in paths), f"{service.name} lacks a PATH"


def test_worker_units_do_not_kill_the_runs_they_spawn() -> None:
    for service in SYSTEMD.glob("*.service"):
        text = service.read_text(encoding="utf-8")
        if "Type=oneshot" in text and "cube worker" in text:
            assert "KillMode=process" in text, f"{service.name}: exit would kill dispatched runs"


def test_agent_workday_patrol_gets_a_long_start_timeout(tmp_path: Path) -> None:
    """Eleven sequential model runs never fit the template's 20 minute timeout."""
    from cube.systemd_units import plan_install

    dropin = SYSTEMD / "cube-patrol@agent-workday.service.d" / "timeout.conf"
    text = dropin.read_text(encoding="utf-8")
    match = re.search(r"TimeoutStartSec=(\d+)h", text)
    assert match and int(match.group(1)) >= 4
    targets = {dst.relative_to(tmp_path).as_posix() for _, dst in plan_install(SYSTEMD, tmp_path)}
    assert "cube-patrol@agent-workday.service.d/timeout.conf" in targets
