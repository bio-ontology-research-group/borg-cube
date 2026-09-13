"""`cube lookup`: read-only lookups inside the host's readable directories (ADR-0027)."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.lookup import (
    LookupError,
    op_find,
    op_git_log,
    op_grep,
    op_head,
    op_ls,
    readable_roots,
    resolve_within,
)


def _text(op: str, data: dict[str, Any]) -> str:
    if op == "ls":
        lines = [f"{e['kind']:<4} {e['size']:>9} {e['name']}" for e in data["entries"]]
    elif op == "find":
        lines = list(data["files"])
    elif op == "grep":
        lines = [f"{m['file']}:{m['line']}: {m['text']}" for m in data["matches"]]
    elif op == "head":
        lines = list(data["lines"])
    else:
        lines = list(data["commits"])
    if data.get("truncated"):
        lines.append("... (truncated; narrow the lookup)")
    return "\n".join(lines) if lines else "(nothing)"


def cmd_lookup(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    roots = readable_roots(settings)
    try:
        bounded = resolve_within(args.path, roots)
        if args.op == "ls":
            data = op_ls(bounded, limit=args.max)
        elif args.op == "find":
            data = op_find(bounded, name=args.name, limit=args.max)
        elif args.op == "grep":
            data = op_grep(
                bounded,
                args.pattern,
                include=args.include,
                ignore_case=args.ignore_case,
                limit=args.max,
            )
        elif args.op == "head":
            data = op_head(bounded, start=args.start, lines=args.lines)
        else:
            data = op_git_log(bounded, count=args.count)
    except LookupError as exc:
        print(f"cube lookup {args.op}: {exc}", file=sys.stderr)
        return 2
    data["roots"] = [str(root) for root in roots.readable]
    data["closed"] = [str(root) for root in roots.denied]
    helpers.emit(args, data, _text(args.op, data))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser(
        "lookup", help="read-only ls, find, grep, head and git-log inside the readable directories"
    )
    ops = sp.add_subparsers(dest="op", required=True)

    ls = ops.add_parser("ls", help="list one directory")
    ls.add_argument("path")
    ls.add_argument("--max", type=int, default=200)

    find = ops.add_parser("find", help="files under a directory, optionally by name glob")
    find.add_argument("path")
    find.add_argument("--name", help="fnmatch glob on the file name, e.g. '*.tex'")
    find.add_argument("--max", type=int, default=200)

    grep = ops.add_parser("grep", help="regex search in text files under a path")
    grep.add_argument("pattern")
    grep.add_argument("path")
    grep.add_argument("--include", help="fnmatch glob on the file name")
    grep.add_argument("-i", "--ignore-case", action="store_true")
    grep.add_argument("--max", type=int, default=200)

    head = ops.add_parser("head", help="numbered lines of one text file")
    head.add_argument("path")
    head.add_argument("--start", type=int, default=1)
    head.add_argument("--lines", type=int, default=60)

    log = ops.add_parser("git-log", help="recent commits of a checkout")
    log.add_argument("path")
    log.add_argument("-n", "--count", type=int, default=20)

    for parser in (ls, find, grep, head, log):
        helpers.add_json(parser)
        parser.set_defaults(fn=lambda a, s: cmd_lookup(a, s, helpers))
