"""Render Hermes profile templates and the Mattermost allowlist from contacts.yaml."""

from __future__ import annotations

import re
from pathlib import Path

from cube.contact import ContactPolicy

PLACEHOLDER = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def render_template(text: str, values: dict[str, str]) -> str:
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return values[key]

    out = PLACEHOLDER.sub(repl, text)
    if missing:
        raise KeyError(f"unresolved placeholders: {sorted(set(missing))}")
    return out


def render_profile(
    profile_dir: Path, values: dict[str, str], out_dir: Path, dry_run: bool = True
) -> list[Path]:
    written: list[Path] = []
    for tmpl in sorted(profile_dir.glob("*.tmpl")):
        rendered = render_template(tmpl.read_text(encoding="utf-8"), values)
        target = out_dir / tmpl.name.removesuffix(".tmpl")
        written.append(target)
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
    return written


def allowlist(policy: ContactPolicy, mm_users: dict[str, str]) -> list[str]:
    """Map granted people (cube ids) to Mattermost user ids via people.yaml's mapping."""
    ids: list[str] = []
    for person in policy.allowed_users("mattermost_dm"):
        mm = mm_users.get(person)
        if mm:
            ids.append(mm)
    return ids
