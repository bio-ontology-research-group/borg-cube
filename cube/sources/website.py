"""Read-only adapter for the public BORG profile-group pages."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://borg.kaust.edu.sa/profiles/by-profile-group"
GROUPS = (
    "students",
    "research-scientists",
    "postdoctoral-fellows",
    "research-staff",
    "principal-investigators",
)
USER_AGENT = "borg-cube/0.1 roster reconciliation (+https://borg.kaust.edu.sa/)"
ROLE_WORDS = (
    "student",
    "scientist",
    "postdoc",
    "professor",
    "specialist",
    "engineer",
    "curator",
    "technician",
    "manager",
    "intern",
)

Fetcher = Callable[[Request], bytes]


class WebsiteParseError(ValueError):
    """The response was HTML, but no trustworthy profile list could be identified."""


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _role_for_group(group: str) -> str:
    return {
        "students": "student",
        "research-scientists": "research-scientist",
        "postdoctoral-fellows": "postdoc",
        "research-staff": "staff",
        "principal-investigators": "staff",
    }[group]


def _program(title: str) -> str | None:
    low = title.lower()
    if "student" not in low:
        return None
    degree = "PhD" if "ph.d" in low or "phd" in low else None
    if "m.s" in low or re.search(r"\bms\b", low):
        degree = "MS"
    if degree is None:
        return "visiting" if "visiting" in low else None
    if "bioengineering" in low:
        return f"{degree}-Bioeng"
    if "computer science" in low:
        return f"{degree}-CS"
    if "bioscience" in low:
        return f"{degree}-Biosci"
    return degree


@dataclass
class WebsiteProfile:
    name: str
    slug: str
    title: str
    group: str
    role: str
    program: str | None
    url: str


@dataclass
class WebsiteSnapshot:
    profiles: list[WebsiteProfile] = field(default_factory=list)
    fetched_at: str | None = None
    cached: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class _Candidate:
    name_parts: list[str] = field(default_factory=list)
    detail_parts: list[str] = field(default_factory=list)
    href: str | None = None


class _ProfileParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_heading = False
        self.ignored = 0
        self.current: _Candidate | None = None
        self.candidates: list[_Candidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
            return
        if tag == "h3":
            self._finish()
            self.current = _Candidate()
            self.in_heading = True
        if self.in_heading and tag == "a" and self.current is not None:
            self.current.href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1
        if tag == "h3":
            self.in_heading = False

    def handle_data(self, data: str) -> None:
        if self.ignored or self.current is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        target = self.current.name_parts if self.in_heading else self.current.detail_parts
        target.append(text)

    def close(self) -> None:
        super().close()
        self._finish()

    def _finish(self) -> None:
        if self.current is not None:
            self.candidates.append(self.current)
        self.current = None


def _candidate_title(parts: list[str]) -> str | None:
    for index, part in enumerate(parts):
        if not any(word in part.lower() for word in ROLE_WORDS):
            continue
        selected = [part]
        if index + 1 < len(parts) and len(parts[index + 1].split()) <= 8:
            selected.append(parts[index + 1])
        return re.sub(r"\s+,", ",", ", ".join(selected)).strip(" ,")
    return None


def parse_profile_page(html: str, group: str, url: str | None = None) -> list[WebsiteProfile]:
    """Parse a profile list, or raise rather than silently claiming an empty group."""
    if group not in GROUPS:
        raise ValueError(f"unknown website profile group: {group}")
    parser = _ProfileParser()
    parser.feed(html)
    parser.close()
    profiles: list[WebsiteProfile] = []
    page_url = url or f"{BASE_URL}/{group}"
    for candidate in parser.candidates:
        name = " ".join(candidate.name_parts).strip()
        title = _candidate_title(candidate.detail_parts)
        if not name or title is None:
            continue
        href = candidate.href or ""
        slug = Path(urlparse(href).path).name if href else _slugify(name)
        profiles.append(
            WebsiteProfile(
                name=name,
                slug=slug or _slugify(name),
                title=title,
                group=group,
                role=_role_for_group(group),
                program=_program(" ".join(candidate.detail_parts)),
                url=href or page_url,
            )
        )
    if not profiles:
        raise WebsiteParseError(f"could not parse a profile list from {page_url}")
    return profiles


# A descriptive alias for callers and fixtures that use the plural spelling.
parse_profiles = parse_profile_page


def _fetch(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS origin
        return cast(bytes, response.read())


@dataclass
class WebsiteSource:
    cache_dir: Path
    fetcher: Fetcher = _fetch
    now: datetime | None = None

    def _now(self) -> datetime:
        return self.now or datetime.now(UTC)

    def roster(self, *, offline: bool = False) -> WebsiteSnapshot:
        profiles: list[WebsiteProfile] = []
        errors: list[str] = []
        fetched: list[str] = []
        cached_flags: list[bool] = []
        for group in GROUPS:
            url = f"{BASE_URL}/{group}"
            cached = self._read_cache(group)
            html: str | None = None
            fetched_at: str | None = None
            from_cache = False
            if offline:
                if cached is None:
                    errors.append(f"offline cache missing for {url}")
                    continue
                html, fetched_at = cached
                from_cache = True
            else:
                try:
                    request = Request(url, headers={"User-Agent": USER_AGENT})
                    html = self.fetcher(request).decode("utf-8", errors="replace")
                    fetched_at = self._now().isoformat(timespec="seconds")
                    self._write_cache(group, url, fetched_at, html)
                except (OSError, TimeoutError) as exc:
                    if cached is None:
                        errors.append(f"could not fetch {url}: {exc}")
                        continue
                    html, fetched_at = cached
                    from_cache = True
                    errors.append(f"using cached {url}: {exc}")
            assert html is not None
            try:
                profiles.extend(parse_profile_page(html, group, url))
            except WebsiteParseError as exc:
                errors.append(str(exc))
                continue
            if fetched_at:
                fetched.append(fetched_at)
            cached_flags.append(from_cache)
        return WebsiteSnapshot(
            profiles=profiles,
            fetched_at=max(fetched) if fetched else None,
            cached=bool(cached_flags) and all(cached_flags),
            errors=errors,
        )

    def _cache_path(self, group: str) -> Path:
        return self.cache_dir / f"{group}.json"

    def _read_cache(self, group: str) -> tuple[str, str] | None:
        try:
            data: Any = json.loads(self._cache_path(group).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("html"), str):
            return None
        fetched = data.get("fetched")
        if not isinstance(fetched, str):
            return None
        return data["html"], fetched

    def _write_cache(self, group: str, url: str, fetched: str, html: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {"url": url, "fetched": fetched, "html": html}
        self._cache_path(group).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
