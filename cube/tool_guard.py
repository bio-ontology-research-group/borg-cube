"""Standalone Claude PreToolUse guard for restricted roles (stdlib only)."""

from __future__ import annotations

import argparse
import json
import shlex
import sys

OPERATIONS = {
    "liaison": {"ls", "head", "grep", "mail-search", "mail-show", "request"},
    "sysadmin": {"inspect", "propose", "request"},
}
CHECKS = {"uptime", "disk", "memory", "services", "journal", "slurm"}
FORBIDDEN = set(";|&><$`\n\r#\x00")
MAX_INPUT = 200_000


def _expands(command: str) -> bool:
    """shlex does not expand globs, braces or tildes; the actual Bash would."""
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char in "*?[]~{}()":
            return True
    return False


def permitted(role: str, event: object) -> bool:
    """Accept one dispatcher command, never a shell expression."""
    if role not in OPERATIONS or not isinstance(event, dict):
        return False
    if event.get("tool_name") != "Bash":
        return False
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str) or not command or any(c in FORBIDDEN for c in command):
        return False
    if _expands(command):
        return False
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(argv) < 4 or argv[:2] != ["cube", "boundary"]:
        return False
    operation, value = argv[2:4]
    if operation not in OPERATIONS[role] or not value or value.startswith("-"):
        return False
    seen = set()
    index = 4
    while index < len(argv):
        flag = argv[index]
        if flag in seen:
            return False
        seen.add(flag)
        if flag in {"--apply", "--dry-run", "--json"}:
            index += 1
        elif flag in {"--pattern", "--check"}:
            if index + 1 >= len(argv):
                return False
            argument = argv[index + 1]
            if not argument or argument.startswith("-"):
                return False
            if flag == "--pattern" and operation != "grep":
                return False
            if flag == "--check" and (operation != "inspect" or argument not in CHECKS):
                return False
            index += 2
        else:
            return False
    return not {"--apply", "--dry-run"}.issubset(seen)


def _respond(allow: bool) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow" if allow else "deny",
                    "permissionDecisionReason": (
                        "Validated restricted dispatcher command."
                        if allow
                        else "Only a single role-scoped dispatcher command is permitted."
                    ),
                },
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=sorted(OPERATIONS))
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("oversized hook input")
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
            raise ValueError("invalid hook event")
        if not isinstance(event.get("tool_name"), str):
            raise ValueError("missing tool name")
    except (ValueError, OSError):
        _respond(False)
        return 2
    _respond(permitted(args.role, event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
