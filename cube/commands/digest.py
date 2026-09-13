"""`cube digest`: the daily Robert briefing, deterministic, zero tokens.

Composes today's attention items (approvals, needs:robert, errors, dead sessions) with
the latest patrol cursors and the most recent events into ``briefings/digest-<date>.md``
(dry-run by default; ``--apply`` writes the file). The cockpit and the concierge brief
read the same file.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, now_iso, today_from
from cube.config import Settings
from cube.decisions import policy_digest_lines
from cube.engine.attention import build_attention
from cube.literature import brief_block
from cube.patrols.cursors import load_cursors

MAX_EVENTS_IN_DIGEST = 15


def recent_events(state: Path, limit: int = MAX_EVENTS_IN_DIGEST) -> list[dict[str, Any]]:
    path = state / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit * 3 :]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-limit:]


def _policy_lines(settings: Settings, today: date) -> list[str]:
    """The policy digest line, unless `decisions.digest` turns it off."""
    if settings.decisions.digest != "daily":
        return []
    return policy_digest_lines(settings.state_dir(), today)


def render_digest(
    today: date,
    attention: list[dict[str, Any]],
    cursors: dict[str, Any],
    events: list[dict[str, Any]],
    literature: list[str] | None = None,
    policy: list[str] | None = None,
) -> str:
    lines = [f"# Digest {today.isoformat()}", "", f"Generated {now_iso()}.", ""]
    lines.append("## Attention")
    if attention:
        for item in attention:
            lines.append(f"- [{item['severity']}] {item['kind']}: {item['title']}")
    else:
        lines.append("- nothing needs attention")
    lines += ["", "## Patrols (last runs)"]
    if cursors:
        for name in sorted(cursors):
            c = cursors[name]
            when = str(c.get("last_run") or "?")[:19]
            lines.append(f"- {name}: {when} - {c.get('summary') or '(no summary)'}")
    else:
        lines.append("- no patrol has run yet")
    if policy:
        lines += ["", *policy]
    if literature:
        lines += ["", *literature]
    lines += ["", "## Recent events"]
    if events:
        for ev in events:
            lines.append(f"- {str(ev.get('ts') or '?')[:19]} {ev.get('event')}: {ev.get('title')}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def cmd_digest(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    today = today_from(args) or date.today()
    state = settings.state_dir()
    beads = helpers.beads(settings, True)
    attention = build_attention(settings, beads)
    cursors = load_cursors(state)
    events = recent_events(state)
    md = render_digest(
        today,
        attention,
        cursors,
        events,
        brief_block(settings, today),
        _policy_lines(settings, today),
    )
    out_dir = settings.root / "briefings"
    path = out_dir / f"digest-{today.isoformat()}.md"
    if args.dry_run:
        print(md, end="")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
    data = {
        "generated": now_iso(),
        "written": None if args.dry_run else str(path),
        "attention_count": len(attention),
        "patrols": len(cursors),
        "events": len(events),
    }
    text = None if args.dry_run else f"{path} ({len(attention)} attention item(s))"
    helpers.emit(args, data, text)
    return 0


def cmd_brief(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """`cube brief`: today's digest as markdown for the cockpit, never written to disk."""
    today = today_from(args) or date.today()
    state = settings.state_dir()
    beads = helpers.beads(settings, True)
    attention = build_attention(settings, beads)
    cursors = load_cursors(state)
    events = recent_events(state)
    md = render_digest(
        today,
        attention,
        cursors,
        events,
        brief_block(settings, today),
        _policy_lines(settings, today),
    )
    data = {
        "generated": now_iso(),
        "date": today.isoformat(),
        "markdown": md,
        "attention_count": len(attention),
    }
    helpers.emit(args, data, md)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("brief", help="today's digest as markdown (read-only, for the cockpit)")
    helpers.add_json(sp)
    add_today(sp)
    sp.set_defaults(fn=lambda a, s: cmd_brief(a, s, helpers))

    sp = sub.add_parser("digest", help="render the daily digest briefing (briefings/digest-*.md)")
    add_today(sp)
    helpers.add_dry(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_digest(a, s, helpers))
