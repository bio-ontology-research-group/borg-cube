"""Data-pull patrol: ``git pull --ff-only`` in the data repos from cube.yaml paths.

Only paths that are git checkouts are touched (pa, org, rkg, website by default). A failed
or non-fast-forward pull becomes a ``needs:robert`` finding; a clean pull closes any earlier
finding. Dry-run lists the commands and runs nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cube.beads import Beads
from cube.config import Settings
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, prov, register
from cube.runners.base import Exec, default_exec
from cube.sync.derivers import DesiredBead

DEFAULT_REPOS = ("pa", "org", "rkg", "website")


def is_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def pull_command(path: Path) -> list[str]:
    return ["git", "-C", str(path), "pull", "--ff-only"]


@dataclass
class DataPullPatrol:
    name: str = "data_pull"
    repos: tuple[str, ...] = DEFAULT_REPOS
    exec_fn: Exec = default_exec
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(self.name, today, dry_run)
        commands: list[list[str]] = []
        pulled = failed = skipped = 0
        for key in self.repos:
            path = settings.dirs.get(key)
            if path is None or not path.exists():
                skipped += 1
                report.findings.append(
                    Finding(f"data-pull:{key}:missing", f"{key}: {path} not present", "info")
                )
                continue
            if not is_checkout(path):
                skipped += 1
                report.findings.append(
                    Finding(f"data-pull:{key}:not-git", f"{key}: {path} is not a git checkout")
                )
                continue
            cmd = pull_command(path)
            commands.append(cmd)
            xid = f"finding:data-pull:{key}"
            header = BeadHeader(xid=xid, provenance=[prov(str(path), " ".join(cmd), today)])
            if dry_run:
                report.findings.append(
                    Finding(f"data-pull:{key}:dry-run", f"{key}: would run {' '.join(cmd)}")
                )
                continue
            res = self.exec_fn(cmd, cwd=path, env=self.env, timeout=180.0, stdin_devnull=True)
            if res.returncode == 0:
                pulled += 1
                first = (res.stdout or "").strip().splitlines()
                report.findings.append(
                    Finding(f"data-pull:{key}:ok", f"{key}: {first[0] if first else 'pulled'}")
                )
                report.findings.append(
                    DesiredBead(
                        xid=xid,
                        title=f"Data pull failed: {key}",
                        kind=WorkKind.finding,
                        labels=["src:data-pull", f"repo:{key}"],
                        header=header,
                        closed=True,
                        close_reason="pull succeeded",
                    )
                )
                continue
            failed += 1
            err = (res.stderr or res.stdout).strip().splitlines()
            tail = "\n".join(err[-6:]) if err else f"exit {res.returncode}"
            body = [
                f"Command: {' '.join(cmd)}",
                f"Exit code: {res.returncode}",
                "Output:",
                tail,
                "Resolve by hand (rebase, stash or merge) in the checkout; cube never resolves "
                "conflicts in a source of record.",
            ]
            report.findings.append(
                DesiredBead(
                    xid=xid,
                    title=f"Data pull failed: {key} ({path})",
                    kind=WorkKind.finding,
                    labels=["src:data-pull", f"repo:{key}", "needs:robert"],
                    header=header,
                    body="\n".join(body),
                    priority=1,
                )
            )
            report.events.append(
                attention_event(
                    self.name,
                    f"git pull failed in {key} ({path})",
                    body="\n".join(body),
                    xid=xid,
                    data={"repo": key},
                )
            )
        report.data["commands"] = commands
        report.summary = (
            f"{len(commands)} checkout(s): "
            + (f"would pull {len(commands)}" if dry_run else f"{pulled} pulled, {failed} failed")
            + f", {skipped} skipped"
        )
        return report


register(DataPullPatrol, "data_pull")
