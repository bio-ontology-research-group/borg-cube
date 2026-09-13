"""The only module that shells out to `bd`. Everything else goes through Beads."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cube.model import BeadHeader


class BeadsError(RuntimeError):
    pass


@dataclass
class BdResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> Any:
        try:
            return json.loads(self.stdout) if self.stdout.strip() else None
        except json.JSONDecodeError as exc:
            raise BeadsError(f"bd returned non-JSON output for {self.args}: {exc}") from exc


@dataclass
class Beads:
    """Typed wrapper over the `bd` CLI. `dry_run` prints commands instead of running writes."""

    bin: str = "bd"
    cwd: Path | None = None
    dry_run: bool = False
    actor: str | None = None
    log: list[list[str]] = field(default_factory=list)

    # -- plumbing ---------------------------------------------------------

    def available(self) -> bool:
        return shutil.which(self.bin) is not None

    def _run(self, *args: str, write: bool = False, check: bool = True) -> BdResult:
        cmd = [self.bin, *args]
        if self.actor:
            cmd += ["--actor", self.actor]
        self.log.append(cmd)
        if write and self.dry_run:
            return BdResult(cmd, 0, "", "dry-run")
        proc = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        result = BdResult(cmd, proc.returncode, proc.stdout, proc.stderr)
        if check and proc.returncode != 0:
            raise BeadsError(f"{' '.join(cmd)} failed ({proc.returncode}): {proc.stderr.strip()}")
        return result

    # -- ledger sync (Dolt remote on the shared git remote) -----------------

    def dolt_pull(self) -> BdResult:
        """Merge the shared remote into this host's ledger (``bd dolt pull``)."""
        return self._run("dolt", "pull", write=True, check=False)

    def dolt_push(self) -> BdResult:
        """Publish this host's ledger commits to the shared remote (``bd dolt push``)."""
        return self._run("dolt", "push", write=True, check=False)

    # -- reads ------------------------------------------------------------

    def version(self) -> str:
        return self._run("--version", check=False).stdout.strip()

    def prime(self) -> str:
        return self._run("prime", check=False).stdout

    def ready(self, labels: list[str] | None = None) -> list[dict[str, Any]]:
        # bd ready pages at 100 by default; the marshal must see every ready bead
        # (126 on ws on 2026-09-06, the temporal survey sat past the page).
        args = ["ready", "--json", "--limit", "0"]
        for label in labels or []:
            args += ["--label", label]
        data = self._run(*args).json()
        return _as_list(data)

    def show(self, bead_id: str) -> dict[str, Any]:
        data = self._run("show", bead_id, "--json").json()
        if isinstance(data, list):
            data = data[0] if data else {}
        return dict(data or {})

    def list_issues(self, *filters: str) -> list[dict[str, Any]]:
        return _as_list(self._run("list", "--json", *filters).json())

    def find_by_xid(self, xid: str) -> dict[str, Any] | None:
        """xid is stored as the bead's external-ref; fall back to header parsing."""
        for bead in self.list_issues("--all"):
            if bead.get("external_ref") == xid:
                return bead
            header = BeadHeader.parse(bead.get("description") or "")
            if header and header.xid == xid:
                return bead
        return None

    def memories(self) -> list[dict[str, Any]]:
        return _as_list(self._run("memories", "--json", check=False).json())

    # -- writes -----------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        header: BeadHeader,
        body: str = "",
        type_: str = "task",
        priority: int = 2,
        labels: list[str] | None = None,
        parent: str | None = None,
        deps: list[str] | None = None,
        acceptance: str | None = None,
    ) -> str | None:
        description = header.render() + ("\n" + body if body else "")
        args = [
            "create",
            title,
            "--type",
            type_,
            "--priority",
            str(priority),
            "--external-ref",
            header.xid,
            "--description",
            description,
            "--silent",
        ]
        if labels:
            args += ["--labels", ",".join(labels)]
        if parent:
            args += ["--parent", parent]
        if deps:
            args += ["--deps", ",".join(deps)]
        if header.deadline:
            args += ["--due", header.deadline.isoformat()]
        if acceptance:
            args += ["--acceptance", acceptance]
        result = self._run(*args, write=True)
        return None if self.dry_run else result.stdout.strip() or None

    def comment(self, bead_id: str, text: str) -> None:
        self._run("comment", bead_id, text, write=True)

    def claim(self, bead_id: str) -> None:
        self._run("update", bead_id, "--claim", write=True)

    def unclaim(self, bead_id: str) -> None:
        """Return a claimed bead to the ready queue (a failed run must not park it)."""
        self._run("update", bead_id, "--status", "open", write=True)

    def close(self, bead_id: str, reason: str) -> None:
        self._run("close", bead_id, "--reason", reason, write=True)

    def add_labels(self, bead_id: str, labels: list[str]) -> None:
        for label in labels:
            self._run("label", "add", bead_id, label, write=True)

    def remove_labels(self, bead_id: str, labels: list[str]) -> None:
        """Remove labels explicitly, rather than leaving stale assignment labels behind."""
        for label in labels:
            self._run("label", "remove", bead_id, label, write=True)

    def update_description(self, bead_id: str, description: str) -> None:
        """Replace a bead description while preserving the typed CLI boundary in this module."""
        self._run("update", bead_id, "--description", description, write=True)

    def set_priority(self, bead_id: str, priority: int) -> None:
        self._run("update", bead_id, "--priority", str(priority), write=True)

    def logged_commands(self) -> list[list[str]]:
        """Return recorded commands including the actor appended by :meth:`_run`."""
        if not self.actor:
            return [list(command) for command in self.log]
        return [
            [*command, "--actor", self.actor] if "--actor" not in command else list(command)
            for command in self.log
        ]

    def dep(self, child: str, parent: str, dep_type: str = "blocks") -> None:
        self._run("dep", "add", child, parent, "--type", dep_type, write=True)

    def remember(self, content: str, key: str | None = None) -> None:
        args = ["remember", content]
        if key:
            args += ["--key", key]
        self._run(*args, write=True)


def _as_list(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, dict):
        for key in ("issues", "beads", "items", "memories", "results"):
            if isinstance(data.get(key), list):
                return [dict(x) for x in data[key]]
        return [data]
    if isinstance(data, list):
        return [dict(x) for x in data]
    return []
