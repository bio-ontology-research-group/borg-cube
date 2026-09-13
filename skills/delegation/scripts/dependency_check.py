#!/usr/bin/env python3
"""Check the dependency graph of a beads JSON file and print an execution order.

Reports unknown dependencies, self-dependencies and cycles (exit 1), then a
topological order and the parallel waves (beads whose dependencies are all in
earlier waves), the longest chain, and beads that share an owner role within a
wave (a hint that the wave will serialise on that role).

Example:
  dependency_check.py --beads runs/7/beads.json
  dependency_check.py --beads runs/7/beads.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def analyse(beads: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [b["id"] for b in beads]
    known = set(ids)
    deps = {b["id"]: list(b.get("depends_on") or []) for b in beads}
    errors: list[str] = []
    for bid, ds in deps.items():
        for d in ds:
            if d == bid:
                errors.append(f"{bid} depends on itself")
            elif d not in known:
                errors.append(f"{bid} depends on unknown bead {d!r}")
    dup = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dup):
        errors.append(f"duplicate bead id {d!r}")

    # cycle detection (DFS with colours)
    colour = {i: 0 for i in ids}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        colour[node] = 1
        stack.append(node)
        for d in deps.get(node, []):
            if d not in known:
                continue
            if colour[d] == 1:
                cycles.append(stack[stack.index(d) :] + [d])
            elif colour[d] == 0:
                visit(d)
        stack.pop()
        colour[node] = 2

    for i in ids:
        if colour[i] == 0:
            visit(i)
    for c in cycles:
        errors.append("cycle: " + " -> ".join(c))

    order: list[str] = []
    waves: list[list[str]] = []
    depth: dict[str, int] = {}
    if not cycles:
        remaining = {i: {d for d in deps[i] if d in known} for i in ids}
        placed: set[str] = set()
        while remaining:
            ready = sorted(i for i, ds in remaining.items() if ds <= placed)
            if not ready:
                break
            waves.append(ready)
            for r in ready:
                depth[r] = len(waves)
                placed.add(r)
                del remaining[r]
            order += ready
    by_id = {b["id"]: b for b in beads}
    role_clashes: list[str] = []
    for n, wave in enumerate(waves, 1):
        roles: dict[str, list[str]] = {}
        for bid in wave:
            roles.setdefault(str(by_id[bid].get("owner_role")), []).append(bid)
        for role, members in roles.items():
            if len(members) > 1:
                role_clashes.append(
                    f"wave {n}: {len(members)} beads for role {role}: {', '.join(members)}"
                )
    return {
        "ok": not errors,
        "errors": errors,
        "order": order,
        "waves": waves,
        "longest_chain": max(depth.values()) if depth else 0,
        "role_clashes": role_clashes,
        "roots": [i for i in ids if not deps[i]],
        "leaves": [i for i in ids if not any(i in ds for ds in deps.values())],
    }


def render(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for e in result["errors"]:
        lines.append(f"error: {e}")
    if result["ok"]:
        lines.append(f"order: {' -> '.join(result['order'])}")
        for n, wave in enumerate(result["waves"], 1):
            lines.append(f"wave {n}: {', '.join(wave)}")
        lines.append(f"longest chain: {result['longest_chain']} wave(s)")
        for clash in result["role_clashes"]:
            lines.append(f"note: {clash}")
    lines.append("dependency-check: " + ("ok" if result["ok"] else "FAILED"))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--beads", required=True, type=Path, help="beads JSON from beads_from_plan.py")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = json.loads(args.beads.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"dependency-check: {exc}", file=sys.stderr)
        return 1
    beads = data["beads"] if isinstance(data, dict) else data
    result = analyse(beads)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result), end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
