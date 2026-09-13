"""Adopt an existing tmux agent session into the cube fleet."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine.fleet import record_adopted_session
from cube.engine.run import store_session
from cube.notify import append_event, make_event
from cube.runners.base import Exec, default_exec

PANE_FORMAT = "#{pane_current_command}\t#{pane_current_path}"
RUNNERS = ("codex", "claude", "hermes")


class AdoptError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResumeMatch:
    resume_id: str
    path: str
    source: str | None
    modified: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdoptReport:
    ok: bool
    session: str
    runner: str
    resume_id: str | None
    cwd: str
    project: str
    bead: str | None
    role: str
    adopted: bool = True
    dry_run: bool = True
    renamed_from: str | None = None
    rollout: str | None = None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _exec(exec_fn: Exec, cmd: list[str], cwd: Path) -> Any:
    return exec_fn(cmd, cwd=cwd, env={}, timeout=30.0, stdin_devnull=True)


def _pane(tmux_session: str, exec_fn: Exec, cwd: Path) -> tuple[str, Path]:
    result = _exec(
        exec_fn,
        ["tmux", "display-message", "-p", "-t", tmux_session, PANE_FORMAT],
        cwd,
    )
    if result.returncode != 0:
        raise AdoptError(
            f"cannot inspect tmux session {tmux_session!r}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    command, separator, pane_path = line.partition("\t")
    if not separator or not command.strip() or not pane_path.strip():
        raise AdoptError(f"tmux session {tmux_session!r} did not report a command and pane path")
    return command.strip(), Path(pane_path.strip()).expanduser()


def _runner(command: str) -> str:
    executable = Path(command.split(maxsplit=1)[0]).name.lower()
    for runner in RUNNERS:
        if executable == runner or executable.startswith(f"{runner}-"):
            return runner
    raise AdoptError(
        f"cannot determine runner from tmux pane command {command!r}; "
        f"expected one of {', '.join(RUNNERS)}"
    )


def _same_path(left: str | Path, right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return str(Path(left).expanduser()) == str(right)


def _first_record(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as stream:
            first = stream.readline(1_000_000)
        record = json.loads(first)
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _match(path: Path, resume_id: str, source: str | None) -> ResumeMatch:
    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    return ResumeMatch(resume_id, str(path), source, modified)


def codex_resume_matches(cwd: Path, sessions_root: Path | None = None) -> list[ResumeMatch]:
    root = sessions_root or Path("~/.codex/sessions").expanduser()
    matches: list[ResumeMatch] = []
    for path in root.glob("**/rollout-*.jsonl") if root.exists() else ():
        record = _first_record(path)
        payload = record.get("payload") if record else None
        if (
            not record
            or record.get("type") != "session_meta"
            or not isinstance(payload, dict)
            or not payload.get("session_id")
            or not payload.get("cwd")
            or not _same_path(str(payload["cwd"]), cwd)
        ):
            continue
        matches.append(
            _match(
                path,
                str(payload["session_id"]),
                str(payload["source"]) if payload.get("source") else None,
            )
        )
    matches.sort(
        key=lambda item: (item.source == "tui", Path(item.path).stat().st_mtime_ns),
        reverse=True,
    )
    return matches


def claude_resume_matches(cwd: Path, projects_root: Path | None = None) -> list[ResumeMatch]:
    root = projects_root or Path("~/.claude/projects").expanduser()
    encoded = str(cwd.resolve(strict=False)).replace("/", "-")
    project_dir = root / encoded
    matches: list[ResumeMatch] = []
    for path in project_dir.glob("*.jsonl") if project_dir.exists() else ():
        record = _first_record(path) or {}
        recorded_cwd = record.get("cwd")
        if recorded_cwd and not _same_path(str(recorded_cwd), cwd):
            continue
        resume_id = record.get("sessionId") or record.get("session_id") or path.stem
        matches.append(
            _match(
                path,
                str(resume_id),
                str(record["source"]) if record.get("source") else None,
            )
        )
    matches.sort(key=lambda item: Path(item.path).stat().st_mtime_ns, reverse=True)
    return matches


def _resume_matches(
    runner: str,
    cwd: Path,
    *,
    codex_sessions_root: Path | None,
    claude_projects_root: Path | None,
) -> list[ResumeMatch]:
    if runner == "codex":
        return codex_resume_matches(cwd, codex_sessions_root)
    if runner == "claude":
        return claude_resume_matches(cwd, claude_projects_root)
    return []


def adopt_session(
    settings: Settings,
    tmux_session: str,
    *,
    project: str,
    bead: str | None = None,
    role: str = "programmer",
    dry_run: bool = True,
    exec_fn: Exec | None = None,
    codex_sessions_root: Path | None = None,
    claude_projects_root: Path | None = None,
) -> AdoptReport:
    exec_fn = exec_fn or default_exec
    command, pane_path = _pane(tmux_session, exec_fn, settings.root)
    runner = _runner(command)
    git = _exec(exec_fn, ["git", "rev-parse", "--show-toplevel"], pane_path)
    if git.returncode != 0:
        detail = (git.stderr or git.stdout).strip()
        raise AdoptError(f"tmux pane path is not a git checkout: {pane_path}: {detail}")

    matches = _resume_matches(
        runner,
        pane_path,
        codex_sessions_root=codex_sessions_root,
        claude_projects_root=claude_projects_root,
    )
    selected = matches[0] if matches else None
    target = tmux_session if tmux_session.startswith("cube/") else f"cube/{project}-{runner}"
    rename = ["tmux", "rename-session", "-t", tmux_session, target]
    commands = [rename] if target != tmux_session else []
    message = (
        f"matched {selected.resume_id} from {selected.path}"
        if selected
        else f"no matching {runner} resume id for pane cwd {pane_path}; adopting without one"
    )
    if len(matches) > 1:
        message += f"; {len(matches) - 1} alternative matching rollout(s) reported"
    report = AdoptReport(
        ok=True,
        session=target,
        runner=runner,
        resume_id=selected.resume_id if selected else None,
        cwd=str(pane_path.resolve(strict=False)),
        project=project,
        bead=bead,
        role=role,
        dry_run=dry_run,
        renamed_from=tmux_session if target != tmux_session else None,
        rollout=selected.path if selected else None,
        alternatives=[item.as_dict() for item in matches[1:]],
        commands=commands,
        message=message,
    )
    if dry_run:
        return report

    if commands:
        renamed = _exec(exec_fn, rename, settings.root)
        if renamed.returncode != 0:
            raise AdoptError(
                f"cannot rename tmux session {tmux_session!r} to {target!r}: "
                f"{(renamed.stderr or renamed.stdout).strip()}"
            )
    persistent = {
        key: value
        for key, value in report.as_dict().items()
        if key
        in {
            "session",
            "runner",
            "resume_id",
            "cwd",
            "project",
            "bead",
            "role",
            "adopted",
            "rollout",
            "alternatives",
        }
    }
    record_adopted_session(settings.state_dir(), persistent)
    if bead and selected:
        store_session(
            settings.state_dir(),
            bead,
            runner,
            selected.resume_id,
            None,
            adopted_session=target,
        )
    event = make_event(
        "notification",
        source="cube",
        session=target,
        title=f"adopted {target}",
        body=message,
        bead=bead,
        resume_id=selected.resume_id if selected else None,
        data={"kind": "adopted", "project": project, "runner": runner, "cwd": str(pane_path)},
    )
    event["event"] = "adopted"
    event["severity"] = "info"
    append_event(settings.state_dir(), event)
    return report


def _text(report: AdoptReport) -> str:
    mode = "DRY-RUN would adopt" if report.dry_run else "adopted"
    lines = [
        f"{mode} {report.session}",
        f"runner={report.runner} project={report.project} bead={report.bead or '-'}",
        f"cwd={report.cwd}",
        f"resume_id={report.resume_id or '-'}",
        report.message,
    ]
    for command in report.commands:
        lines.append("command: " + " ".join(command))
    for alternative in report.alternatives:
        lines.append(
            "alternative: "
            f"{alternative['resume_id']} source={alternative.get('source') or '-'} "
            f"file={alternative['path']}"
        )
    return "\n".join(lines)


def cmd_adopt(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        report = adopt_session(
            settings,
            args.tmux_session,
            project=args.project,
            bead=args.bead,
            role=args.role,
            dry_run=args.dry_run,
        )
    except AdoptError as exc:
        helpers.emit(args, {"ok": False, "error": str(exc)}, f"error: {exc}")
        return 3
    helpers.emit(args, report.as_dict(), _text(report))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("adopt", help="adopt an existing tmux agent session")
    parser.add_argument("tmux_session")
    parser.add_argument("--project", required=True)
    parser.add_argument("--bead")
    parser.add_argument("--role", default="programmer")
    helpers.add_json(parser)
    helpers.add_dry(parser)
    parser.set_defaults(fn=lambda args, settings: cmd_adopt(args, settings, helpers))
