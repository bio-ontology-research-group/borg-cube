#!/usr/bin/env python3
"""Verify corpus/sources.yaml against Crossref.

Every entry with a ``doi`` is looked up at ``https://api.crossref.org/works/<doi>``
and the returned title is matched against the manifest citation. Responses are
cached as JSON under ``--cache-dir`` (default ``corpus/raw/crossref/``, gitignored);
``--offline`` uses the cache only. ``--urls`` additionally checks that ``url``
entries answer an HTTP request. ``--mark-verified`` upgrades ``verified_by:
memory`` to ``fetch`` for entries whose title matched.

Exit status is 1 when any DOI is missing, mismatched, or (offline) uncached.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillslib import (  # noqa: E402
    DEFAULT_MANIFEST,
    REPO_ROOT,
    Source,
    ToolError,
    load_manifest,
    update_manifest_fields,
    validate_manifest,
)

DEFAULT_CACHE = REPO_ROOT / "corpus" / "raw" / "crossref"
USER_AGENT = "borg-cube-corpus-verify/0.1"
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "are",
    "how",
    "you",
    "your",
}

Getter = Callable[[str], bytes]


@dataclass
class VerifyResult:
    id: str
    status: str  # ok | mismatch | not-found | no-cache | error | no-doi | url-ok | url-fail
    detail: str
    doi: str | None = None
    crossref_title: str | None = None
    score: float | None = None


def normalise(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text).lower())
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def title_tokens(title: str) -> set[str]:
    return {t for t in normalise(title).split() if len(t) >= 3 and t not in STOPWORDS}


def title_score(crossref_title: str, citation: str) -> float:
    """Fraction of informative Crossref title tokens found in the citation."""
    tokens = title_tokens(crossref_title)
    if not tokens:
        return 0.0
    cite = set(normalise(citation).split())
    return sum(1 for t in tokens if t in cite) / len(tokens)


def cache_path(cache_dir: Path, doi: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", doi)
    return cache_dir / f"{safe}.json"


def default_getter(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - https only
        return resp.read()


def crossref_lookup(
    doi: str, cache_dir: Path, offline: bool, getter: Getter
) -> dict[str, Any] | None:
    """Return the Crossref ``message`` dict, ``{}`` for a 404, or None when uncached offline."""
    path = cache_path(cache_dir, doi)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if offline:
        return None
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    try:
        payload = json.loads(getter(url).decode("utf-8"))
        message = payload.get("message", {})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            message = {}
        else:
            raise
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(message, indent=1), encoding="utf-8")
    return message


def verify_source(
    source: Source,
    cache_dir: Path,
    offline: bool,
    getter: Getter,
    threshold: float,
) -> VerifyResult:
    if not source.doi:
        return VerifyResult(source.id, "no-doi", "no DOI to check")
    if source.doi_registry != "crossref":
        return VerifyResult(
            source.id, "no-doi", f"{source.doi_registry} DOI, not checked", source.doi
        )
    try:
        message = crossref_lookup(source.doi, cache_dir, offline, getter)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return VerifyResult(source.id, "error", str(exc), source.doi)
    if message is None:
        return VerifyResult(source.id, "no-cache", "offline and not cached", source.doi)
    if not message:
        return VerifyResult(source.id, "not-found", "Crossref returned 404", source.doi)
    titles = list(message.get("title") or []) + list(message.get("subtitle") or [])
    if not titles:
        titles = [message.get("container-title", [""])[0]] if message.get("container-title") else []
    title = " ".join(titles)
    score = title_score(title, source.citation)
    status = "ok" if score >= threshold else "mismatch"
    return VerifyResult(source.id, status, f"score {score:.2f}", source.doi, title, round(score, 2))


def check_url(source: Source, getter: Getter) -> VerifyResult:
    if not source.url:
        return VerifyResult(source.id, "no-doi", "no url")
    try:
        getter(source.url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return VerifyResult(source.id, "url-fail", f"{source.url}: {exc}")
    return VerifyResult(source.id, "url-ok", source.url)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--offline", action="store_true", help="use cached Crossref JSON only")
    p.add_argument("--id", action="append", default=[], help="only this manifest id (repeatable)")
    p.add_argument("--urls", action="store_true", help="also check url entries answer")
    p.add_argument("--threshold", type=float, default=0.8, help="title token match threshold")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    p.add_argument("--mark-verified", action="store_true", help="set verified_by: fetch on matches")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None, getter: Getter = default_getter) -> int:
    args = build_parser().parse_args(argv)
    try:
        sources = load_manifest(args.manifest)
    except ToolError as exc:
        print(f"corpus-verify: {exc}", file=sys.stderr)
        return 1
    problems = validate_manifest(sources)
    if args.id:
        wanted = set(args.id)
        sources = [s for s in sources if s.id in wanted]
    results: list[VerifyResult] = []
    for source in sources:
        cached = source.doi is not None and cache_path(args.cache_dir, source.doi).exists()
        result = verify_source(source, args.cache_dir, args.offline, getter, args.threshold)
        results.append(result)
        if result.status == "ok" and args.mark_verified and source.verified_by == "memory":
            update_manifest_fields(args.manifest, source.id, {"verified_by": "fetch"})
        if not cached and not args.offline and source.doi:
            time.sleep(args.delay)
        if args.urls and not source.doi and source.url and not args.offline:
            results.append(check_url(source, getter))
            time.sleep(args.delay)
    failures = [
        r for r in results if r.status in {"mismatch", "not-found", "no-cache", "error", "url-fail"}
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not failures and not problems,
                    "manifest_problems": problems,
                    "results": [asdict(r) for r in results],
                },
                indent=2,
            )
        )
    else:
        for problem in problems:
            print(f"SCHEMA   {problem}")
        for r in results:
            if r.status == "no-doi":
                continue
            extra = f" [{r.crossref_title}]" if r.status == "mismatch" and r.crossref_title else ""
            print(f"{r.status:9} {r.id}: {r.detail}{extra}")
        checked = sum(1 for r in results if r.doi)
        print(
            f"corpus-verify: {checked} DOI(s) checked, {len(failures)} failure(s), "
            f"{len(problems)} schema problem(s)"
        )
    return 1 if failures or problems else 0


if __name__ == "__main__":
    sys.exit(main())
