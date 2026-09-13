#!/usr/bin/env python3
"""Download open-access corpus items listed in corpus/sources.yaml into corpus/raw/.

* Entries with ``oa: false`` are skipped (books, paywalled articles: cite only).
* PLOS DOIs resolve to the journal's printable PDF; arXiv URLs to the PDF;
  anything else is fetched from ``url`` (or ``https://doi.org/<doi>``).
* NAP reports need a manual download click: place the PDF at
  ``corpus/raw/<id>.pdf`` and rerun; the hash is then recorded.
* One request per second. ``sha256`` and ``fetched`` are written back into the
  manifest entry in place (comments preserved).
"""

from __future__ import annotations

import argparse
import datetime as dt
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillslib import (  # noqa: E402
    DEFAULT_MANIFEST,
    REPO_ROOT,
    Source,
    ToolError,
    load_manifest,
    sha256_file,
    update_manifest_fields,
)

DEFAULT_RAW = REPO_ROOT / "corpus" / "raw"
USER_AGENT = "borg-cube-corpus-fetch/0.1 (+https://github.com/bio-ontology-research-group)"
PLOS_JOURNALS = {
    "pcbi": "ploscompbiol",
    "pbio": "plosbiology",
    "pmed": "plosmedicine",
    "pone": "plosone",
    "pgen": "plosgenetics",
    "ppat": "plospathogens",
}
MANUAL_HOSTS = {"nap.nationalacademies.org", "www.nap.edu", "nap.edu"}

Fetcher = Callable[[str], tuple[bytes, str]]


@dataclass
class FetchResult:
    id: str
    status: str  # fetched | recorded | skipped | manual | error | dry-run
    detail: str
    path: str | None = None


def plos_pdf_url(doi: str) -> str | None:
    m = re.match(r"^10\.1371/journal\.(p[a-z]+)\.\d+$", doi)
    if not m:
        return None
    journal = PLOS_JOURNALS.get(m.group(1))
    if not journal:
        return None
    return f"https://journals.plos.org/{journal}/article/file?id={doi}&type=printable"


def arxiv_pdf_url(url: str) -> str | None:
    m = re.match(r"^https?://arxiv\.org/(?:abs|pdf)/([0-9.]+(?:v\d+)?|[a-z-]+/\d+)", url)
    if not m:
        return None
    return f"https://arxiv.org/pdf/{m.group(1)}"


def resolve_download(source: Source) -> tuple[str, str] | None:
    """Return ``(url, extension_hint)`` or None when nothing can be downloaded."""
    if source.doi:
        plos = plos_pdf_url(source.doi)
        if plos:
            return plos, "pdf"
    if source.url:
        arxiv = arxiv_pdf_url(source.url)
        if arxiv:
            return arxiv, "pdf"
        return source.url, ""
    if source.doi:
        return f"https://doi.org/{source.doi}", ""
    return None


def is_manual(url: str) -> bool:
    return urllib.parse.urlparse(url).netloc.lower() in MANUAL_HOSTS


def extension_for(url: str, content_type: str, hint: str) -> str:
    if hint:
        return hint
    ct = content_type.split(";")[0].strip().lower()
    if ct == "application/pdf":
        return "pdf"
    if ct in {"text/html", "application/xhtml+xml"}:
        return "html"
    if ct in {"text/plain"}:
        return "txt"
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower()
    return suffix or "bin"


def default_fetcher(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - http(s) only
        return resp.read(), resp.headers.get("Content-Type", "")


def existing_raw(raw_dir: Path, entry_id: str) -> Path | None:
    matches = sorted(raw_dir.glob(f"{entry_id}.*"))
    return matches[0] if matches else None


def fetch_one(
    source: Source,
    manifest: Path,
    raw_dir: Path,
    fetcher: Fetcher,
    force: bool,
    dry_run: bool,
) -> tuple[FetchResult, bool]:
    """Fetch one entry. Returns the result and whether a network request was made."""
    if source.oa is False:
        return FetchResult(source.id, "skipped", "oa: false (cite only)"), False
    existing = existing_raw(raw_dir, source.id)
    if existing and not force:
        if source.sha256 and source.fetched:
            return FetchResult(source.id, "skipped", "already fetched", str(existing)), False
        digest = sha256_file(existing)
        if not dry_run:
            update_manifest_fields(manifest, source.id, {"sha256": digest, "fetched": _today()})
        return FetchResult(
            source.id, "recorded", f"hash of existing file {existing.name}", str(existing)
        ), False
    target = resolve_download(source)
    if target is None:
        return FetchResult(source.id, "skipped", "no doi or url to fetch"), False
    url, hint = target
    if is_manual(url):
        return (
            FetchResult(
                source.id, "manual", f"download by hand from {url} to {raw_dir}/{source.id}.pdf"
            ),
            False,
        )
    if dry_run:
        return FetchResult(source.id, "dry-run", f"would GET {url}"), False
    try:
        data, content_type = fetcher(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return FetchResult(source.id, "error", f"{url}: {exc}"), True
    ext = extension_for(url, content_type, hint)
    if ext == "pdf" and not data.startswith(b"%PDF"):
        return FetchResult(
            source.id, "error", f"{url}: response is not a PDF (got {content_type!r})"
        ), True
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{source.id}.{ext}"
    path.write_bytes(data)
    digest = sha256_file(path)
    update_manifest_fields(manifest, source.id, {"sha256": digest, "fetched": _today()})
    return FetchResult(source.id, "fetched", f"{len(data)} bytes from {url}", str(path)), True


def _today() -> str:
    return dt.date.today().isoformat()


def select_sources(sources: list[Source], ids: list[str], topics: list[str]) -> list[Source]:
    out = sources
    if ids:
        wanted = set(ids)
        unknown = wanted - {s.id for s in sources}
        if unknown:
            raise ToolError(f"unknown ids: {sorted(unknown)}")
        out = [s for s in out if s.id in wanted]
    if topics:
        t = set(topics)
        out = [s for s in out if t & set(s.topics)]
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument(
        "--raw-dir", type=Path, default=DEFAULT_RAW, help="download directory (gitignored)"
    )
    p.add_argument("--id", action="append", default=[], help="only this manifest id (repeatable)")
    p.add_argument(
        "--topic", action="append", default=[], help="only entries with this topic (repeatable)"
    )
    p.add_argument("--force", action="store_true", help="re-download even if fetched")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    p.add_argument("--dry-run", action="store_true", help="print what would be fetched")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None, fetcher: Fetcher = default_fetcher) -> int:
    args = build_parser().parse_args(argv)
    try:
        sources = select_sources(load_manifest(args.manifest), args.id, args.topic)
    except ToolError as exc:
        print(f"corpus-fetch: {exc}", file=sys.stderr)
        return 1
    results: list[FetchResult] = []
    last_request = 0.0
    for source in sources:
        wait = args.delay - (time.monotonic() - last_request)
        if last_request and wait > 0:
            time.sleep(wait)
        result, requested = fetch_one(
            source, args.manifest, args.raw_dir, fetcher, args.force, args.dry_run
        )
        if requested:
            last_request = time.monotonic()
        results.append(result)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(f"{r.status:8} {r.id}: {r.detail}")
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        print("corpus-fetch: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
