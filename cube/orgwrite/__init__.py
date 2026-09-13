"""The single, safe write path for Org files owned outside borg-cube.

The source adapters in :mod:`cube.sources.org` are intentionally read-only.
This module owns the small set of approved structural edits made by the
cockpit and command line.  It refuses unclear targets and content before a
diff is produced, writes atomically only when asked, and emits an event the
cockpit can display.
"""

from __future__ import annotations

import difflib
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from cube.notify import append_event, make_event

HEADING_RE = re.compile(r"^(\*+)\s+(.*?)(?:\s+:[\w@#%:]+:)?\s*$")
CHECKBOX_RE = re.compile(r"^(\s*[-+*]\s+)\[([ xX])\](\s+.*)$")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
PRIVATE_CONTENT: dict[str, re.Pattern[str]] = {
    "grades": re.compile(r"\bgrades?\b|\bgpa\b|\bmarks?\s+out\s+of\b", re.I),
    "contract": re.compile(r"\bcontracts?\b|\bsalary\b|\bstipend\b", re.I),
    "visa": re.compile(r"\bvisas?\b|\bresidence permit\b|\biqama\b", re.I),
    "health": re.compile(
        r"\bdiagnos(?:is|ed)\b|\bdepression\b|\banxiety disorder\b|"
        r"\bmedical (?:leave|report)\b|\btherapy\b|\bmedication\b|"
        r"\bsurger(?:y|ies)\b|\bcancer\b|\billness\b|\bsick leave\b",
        re.I,
    ),
}


class OrgWriteError(RuntimeError):
    """A safe, user-facing refusal to alter an Org file."""


@dataclass(frozen=True)
class Heading:
    line: int
    level: int
    title: str


@dataclass
class OrgWriteResult:
    file: str
    action: str
    diff: str
    applied: bool

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def _inside_org_root(path: Path, org_root: Path) -> Path:
    root = org_root.expanduser().resolve()
    target = path.expanduser()
    target = target.resolve() if target.is_absolute() else (root / target).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise OrgWriteError(f"{target} is outside org root {root}; refusing to write") from exc
    if target.suffix.lower() != ".org" or target.name.endswith("~"):
        raise OrgWriteError(f"refusing to edit non-Org or backup file: {target.name}")
    return target


def _locks(path: Path) -> list[Path]:
    candidates = (path.parent / f"#{path.name}#", path.parent / f".#{path.name}")
    return [candidate for candidate in candidates if candidate.exists() or candidate.is_symlink()]


def _refuse_if_locked(path: Path) -> None:
    locks = _locks(path)
    if locks:
        raise OrgWriteError(f"{path.name} is open in Emacs ({locks[0].name}); try again later")


def _refuse_private_content(*parts: str) -> None:
    # CLAUDE.md §5: unclassifiable grades, contracts, visas and health content is local-only.
    text = "\n".join(parts)
    hits = [name for name, pattern in PRIVATE_CONTENT.items() if pattern.search(text)]
    if hits:
        raise OrgWriteError(
            "refusing unclassifiable private content ("
            + ", ".join(hits)
            + "); CLAUDE.md privacy rule keeps it out of Org writes"
        )


def _headings(lines: list[str]) -> list[Heading]:
    out: list[Heading] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            out.append(Heading(index, len(match.group(1)), match.group(2).strip()))
    return out


def _matching_heading(lines: list[str], heading_match: str) -> Heading:
    needle = heading_match.casefold().strip()
    matches = [heading for heading in _headings(lines) if needle in heading.title.casefold()]
    if not matches:
        raise OrgWriteError(f"no heading matches {heading_match!r}")
    if len(matches) != 1:
        choices = ", ".join(f"line {h.line + 1}: {h.title}" for h in matches)
        raise OrgWriteError(f"heading match {heading_match!r} is ambiguous ({choices})")
    return matches[0]


def _subtree_end(lines: list[str], heading: Heading) -> int:
    for candidate in _headings(lines[heading.line + 1 :]):
        absolute = Heading(candidate.line + heading.line + 1, candidate.level, candidate.title)
        if absolute.level <= heading.level:
            return absolute.line
    return len(lines)


def _drawer_end(lines: list[str], heading_line: int) -> int:
    """Skip drawers directly below a heading without moving them or their contents."""
    index = heading_line + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines) and lines[index].strip() in {":PROPERTIES:", ":LOGBOOK:"}:
        index += 1
        while index < len(lines) and lines[index].strip() != ":END:":
            index += 1
        if index == len(lines):
            raise OrgWriteError("unterminated Org drawer; refusing to edit")
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    return index


def _header_end(lines: list[str]) -> int:
    index = 0
    while index < len(lines) and (lines[index].startswith("#+") or not lines[index].strip()):
        index += 1
    return index


def _diff(path: Path, original: str, updated: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(path),
            tofile=f"{path} (proposed)",
        )
    )


def _atomic_write(path: Path, text: str) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _write(
    path: Path,
    org_root: Path,
    action: str,
    updated: str,
    *,
    apply: bool,
    state_dir: Path | None,
) -> OrgWriteResult:
    target = _inside_org_root(path, org_root)
    _refuse_if_locked(target)
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    diff = _diff(target, original, updated)
    if apply and diff:
        _atomic_write(target, updated)
        if state_dir is not None:
            # Use cube.notify's event writer but retain a specific event name for cockpit routing.
            event = make_event(
                "notification",
                source="cube",
                title=f"org-write: {action} {target.name}",
                data={"action": action, "file": str(target)},
            )
            event["event"] = "org-write"
            append_event(state_dir, event)
    return OrgWriteResult(file=str(target), action=action, diff=diff, applied=bool(apply and diff))


def append_dated(
    path: Path,
    org_root: Path,
    *,
    heading: str,
    day: date,
    items: list[str] | None = None,
    body: str = "",
    apply: bool = False,
    state_dir: Path | None = None,
) -> OrgWriteResult:
    """Append a dated work heading under the sole ``Notes`` parent, newest first."""
    target = _inside_org_root(path, org_root)
    _refuse_if_locked(target)
    _refuse_private_content(heading, *(items or []), body)
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = original.splitlines()
    notes = [h for h in _headings(lines) if h.title.casefold() == "notes"]
    if len(notes) > 1:
        raise OrgWriteError("append parent heading 'Notes' is ambiguous")
    entry_lines: list[str]
    if notes:
        parent = notes[0]
        level = parent.level + 1
        position = _drawer_end(lines, parent.line)
    else:
        level = 1
        position = _header_end(lines)
    entry_lines = [f"{'*' * level} {day.isoformat()} {heading.strip()}"]
    entry_lines.extend(f"- [ ] {item}" for item in (items or []))
    if body.strip():
        entry_lines.extend(body.rstrip("\n").splitlines())
    before = lines[:position]
    after = lines[position:]
    if before and before[-1].strip():
        before.append("")
    updated_lines = [*before, *entry_lines, "", *after]
    updated = "\n".join(updated_lines).rstrip("\n") + "\n"
    return _write(target, org_root, "append", updated, apply=apply, state_dir=state_dir)


def toggle_todo(
    path: Path,
    org_root: Path,
    *,
    heading_match: str,
    item: str,
    done: bool | None = None,
    apply: bool = False,
    state_dir: Path | None = None,
) -> OrgWriteResult:
    target = _inside_org_root(path, org_root)
    _refuse_if_locked(target)
    _refuse_private_content(heading_match, item)
    original = target.read_text(encoding="utf-8")
    lines = original.splitlines()
    heading = _matching_heading(lines, heading_match)
    end = _subtree_end(lines, heading)
    needle = item.casefold().strip()
    matches: list[tuple[int, re.Match[str]]] = []
    for index in range(heading.line + 1, end):
        match = CHECKBOX_RE.match(lines[index])
        if match and needle in match.group(3).casefold():
            matches.append((index, match))
    if not matches:
        raise OrgWriteError(f"no checkbox item matching {item!r} under {heading.title!r}")
    if len(matches) != 1:
        raise OrgWriteError(f"checkbox item {item!r} is ambiguous under {heading.title!r}")
    index, match = matches[0]
    current = match.group(2).casefold() == "x"
    want_done = not current if done is None else done
    lines[index] = f"{match.group(1)}[{'X' if want_done else ' '}]{match.group(3)}"
    updated = "\n".join(lines).rstrip("\n") + "\n"
    return _write(target, org_root, "todo", updated, apply=apply, state_dir=state_dir)


def set_property(
    path: Path,
    org_root: Path,
    *,
    heading_match: str,
    key: str,
    value: str,
    apply: bool = False,
    state_dir: Path | None = None,
) -> OrgWriteResult:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
        raise OrgWriteError(f"invalid Org property name: {key!r}")
    target = _inside_org_root(path, org_root)
    _refuse_if_locked(target)
    _refuse_private_content(heading_match, value)
    original = target.read_text(encoding="utf-8")
    lines = original.splitlines()
    heading = _matching_heading(lines, heading_match)
    index = heading.line + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].strip() == ":PROPERTIES:":
        drawer_end = index + 1
        replaced = False
        while drawer_end < len(lines) and lines[drawer_end].strip() != ":END:":
            if re.match(rf"^\s*:{re.escape(key)}:\s*", lines[drawer_end], re.I):
                lines[drawer_end] = f":{key}: {value}"
                replaced = True
                break
            drawer_end += 1
        if not replaced and drawer_end == len(lines):
            raise OrgWriteError("unterminated property drawer; refusing to edit")
        if not replaced:
            lines.insert(drawer_end, f":{key}: {value}")
    else:
        lines[index:index] = [":PROPERTIES:", f":{key}: {value}", ":END:"]
    updated = "\n".join(lines).rstrip("\n") + "\n"
    return _write(target, org_root, "property", updated, apply=apply, state_dir=state_dir)


def status(path: Path, org_root: Path) -> dict[str, object]:
    """Return a small read-only status shape for the cockpit and CLI."""
    target = _inside_org_root(path, org_root)
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = _headings(lines)
    dated = [h for h in headings if DATE_RE.search(h.title)]
    last = dated[0] if dated else None
    milestone = next((h for h in headings if h.title.casefold() == "milestones"), None)
    milestone_lines: list[str] = []
    if milestone:
        milestone_lines = lines[milestone.line + 1 : _subtree_end(lines, milestone)]
    return {
        "file": str(target),
        "action": "status",
        "last_dated_heading": _dated_heading(last),
        "open_items": [line.strip() for line in lines if re.match(r"^\s*[-+*]\s+\[ \]", line)],
        "milestones": milestone_lines,
    }


def _dated_heading(heading: Heading | None) -> dict[str, object] | None:
    if heading is None:
        return None
    match = DATE_RE.search(heading.title)
    if match is None:
        return None
    return {"title": heading.title, "line": heading.line + 1, "date": match.group(1)}


__all__ = [
    "OrgWriteError",
    "OrgWriteResult",
    "append_dated",
    "set_property",
    "status",
    "toggle_todo",
]
