"""Install the systemd user units from systemd/ into ~/.config/systemd/user (dry-run by default)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def plan_install(src_dir: Path, target_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for unit in sorted(src_dir.glob("*.service")) + sorted(src_dir.glob("*.timer")):
        pairs.append((unit, target_dir / unit.name))
    # Per-instance drop-ins (systemd/<unit>.d/*.conf), e.g. a longer timeout for
    # the composite agent-workday patrol.
    for conf in sorted(src_dir.glob("*.d/*.conf")):
        pairs.append((conf, target_dir / conf.parent.name / conf.name))
    return pairs


def install(
    src_dir: Path, target_dir: Path, *, apply: bool = False, enable_timers: bool = False
) -> list[str]:
    actions: list[str] = []
    for src, dst in plan_install(src_dir, target_dir):
        actions.append(f"copy {src} -> {dst}")
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if apply:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        actions.append("systemctl --user daemon-reload")
        if enable_timers:
            for _, dst in plan_install(src_dir, target_dir):
                if dst.suffix == ".timer":
                    subprocess.run(
                        ["systemctl", "--user", "enable", "--now", dst.name], check=False
                    )
                    actions.append(f"enable --now {dst.name}")
    return actions
