#!/usr/bin/env python3
"""Convert downloaded corpus files in corpus/raw/ to plain text in corpus/text/.

PDF -> ``pdftotext -layout``; HTML -> ``pandoc -f html -t plain``; text and
Markdown are copied. Output is ``corpus/text/<id>.txt``. Files are skipped
when the output is newer than the input unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillslib import REPO_ROOT  # noqa: E402

DEFAULT_RAW = REPO_ROOT / "corpus" / "raw"
DEFAULT_TEXT = REPO_ROOT / "corpus" / "text"
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass
class ConvertResult:
    id: str
    status: str  # converted | copied | skipped | error | dry-run
    detail: str


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def command_for(src: Path, dst: Path) -> list[str] | None:
    """Return the conversion command, or None when the file is copied verbatim."""
    ext = src.suffix.lower()
    if ext == ".pdf":
        return ["pdftotext", "-layout", str(src), str(dst)]
    if ext in {".html", ".htm", ".xhtml"}:
        return ["pandoc", "-f", "html", "-t", "plain", "--wrap=none", "-o", str(dst), str(src)]
    if ext in {".txt", ".md", ".rst", ".xml"}:
        return None
    raise ValueError(f"no converter for {src.suffix!r}")


def convert_one(
    src: Path, text_dir: Path, runner: Runner, force: bool, dry_run: bool
) -> ConvertResult:
    entry_id = src.stem
    dst = text_dir / f"{entry_id}.txt"
    if dst.exists() and not force and dst.stat().st_mtime >= src.stat().st_mtime:
        return ConvertResult(entry_id, "skipped", "up to date")
    try:
        cmd = command_for(src, dst)
    except ValueError as exc:
        return ConvertResult(entry_id, "error", str(exc))
    if dry_run:
        return ConvertResult(entry_id, "dry-run", " ".join(cmd) if cmd else f"copy {src.name}")
    text_dir.mkdir(parents=True, exist_ok=True)
    if cmd is None:
        shutil.copyfile(src, dst)
        return ConvertResult(entry_id, "copied", src.name)
    if shutil.which(cmd[0]) is None:
        return ConvertResult(entry_id, "error", f"{cmd[0]} not installed")
    proc = runner(cmd)
    if proc.returncode != 0:
        return ConvertResult(
            entry_id, "error", f"{cmd[0]} exited {proc.returncode}: {proc.stderr.strip()}"
        )
    return ConvertResult(entry_id, "converted", f"{cmd[0]} -> {dst.name}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    p.add_argument("--text-dir", type=Path, default=DEFAULT_TEXT)
    p.add_argument("--id", action="append", default=[], help="only this manifest id (repeatable)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None, runner: Runner = default_runner) -> int:
    args = build_parser().parse_args(argv)
    if not args.raw_dir.is_dir():
        print(
            f"corpus-convert: {args.raw_dir} does not exist (run corpus-fetch first)",
            file=sys.stderr,
        )
        return 1
    files = sorted(p for p in args.raw_dir.iterdir() if p.is_file())
    if args.id:
        wanted = set(args.id)
        files = [f for f in files if f.stem in wanted]
    results = [convert_one(f, args.text_dir, runner, args.force, args.dry_run) for f in files]
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(f"{r.status:9} {r.id}: {r.detail}")
        print(f"corpus-convert: {len(results)} file(s)")
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
