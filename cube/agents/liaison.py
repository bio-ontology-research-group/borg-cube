"""Deterministic, laptop-local handling of liaison requests.

Robert, 2026-09-08 (ADR-0027): a request the liaison answers on its own reads
only the directories ``hosts.laptop.readable`` lists (``~/Documents/papers``,
``~/Public/software``); every other laptop read (mail, ``~/pa``, ``~/org``, any
other path) waits for his approval first. ``classify_request`` decides which
from the question text alone, so ws and the laptop agree.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from configparser import ConfigParser
from configparser import Error as ConfigError
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import yaml

from cube.agents import AgentError, load_agent
from cube.beads import Beads
from cube.config import Settings
from cube.engine.context import FORBIDDEN_WORDS, bead_labels
from cube.hosts import RelayResult, relay
from cube.model import BeadHeader, Privacy, Provenance
from cube.notify import append_event, make_event

ROBERT_EMAIL = "robert.hoehndorf@kaust.edu.sa"
_SUBJECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "already",
    "about",
    "check",
    "code",
    "collect",
    "doi",
    "dois",
    "email",
    "extract",
    "from",
    "have",
    "ideas",
    "in",
    "i",
    "just",
    "links",
    "list",
    "local",
    "mail",
    "my",
    "of",
    "paper",
    "papers",
    "please",
    "repositories",
    "repository",
    "sent",
    "that",
    "the",
    "this",
    "to",
}
# Personal categories that keep an answer on the laptop (CLAUDE.md privacy
# classes). Research vocabulary of a biomedical group (health, medical, cancer,
# diagnosis, performance) is deliberately absent: it appears in nearly every
# scientific mail and says nothing about a person. Person-directed health
# wording is caught by the phrases below and by FORBIDDEN_WORDS.
_PERSONAL_CATEGORY = re.compile(
    r"\b(?:assessment|assessments|grade|grades|grading|gpa|contract|contracts|"
    r"visa|visas|passport|passports|iqama|personnel|disciplinary|salary|salaries|"
    r"sick leave|medical leave|maternity leave|paternity leave|illness|surgery|"
    r"diagnosed with|performance review|probation)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_DOI_RE = re.compile(r"(?<![\w/])(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>"
_REPO_NAME_STOPWORDS = {"prov", "time"}


class LiaisonError(AgentError):
    """A local request could not be answered without guessing."""


# --- request scope (ADR-0027) --------------------------------------------------

SCOPE_MAIL = "mail"
SCOPE_READABLE = "readable"
SCOPE_PERSONAL = "personal"
NEEDS_ROBERT = "needs:robert"
APPROVED = "approved:robert"
LAPTOP_READ = "laptop-read:approval"
_PATH_RE = re.compile(
    r"(?<![\w/:])(~/[^\s'\"`,;:)\]]+|/(?!/)[^\s'\"`,;:)\]]+|~(?=[\s'\"`,;:)\]]|$))"
)
# Sources that are personal by nature, whatever path the question names.
_PERSONAL_SOURCE = re.compile(
    r"\b(?:e-?mails?|mail|notmuch|gnus|inbox|calendar|contacts?|bbdb|memor(?:y|ies)|"
    r"journal|~/pa|~/org)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RequestScope:
    """What a request may read: mail, the readable directories, or more."""

    scope: str
    paths: list[str]
    roots: list[str]
    reason: str
    standing_grant: bool = False

    @property
    def needs_approval(self) -> bool:
        return self.scope != SCOPE_READABLE and not self.standing_grant

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"needs_approval": self.needs_approval}


def request_paths(question: str) -> list[str]:
    """Home-relative and absolute home paths the question names, in order."""
    paths: list[str] = []
    for match in _PATH_RE.finditer(question):
        value = match.group(1).rstrip(".")
        if value and value not in paths:
            paths.append(value)
    return paths


def _normalised(path: str, home: Path) -> Path:
    raw = Path(path)
    if path == "~" or path.startswith("~/"):
        raw = home / path[2:] if len(path) > 1 else home
    parts: list[str] = []
    for part in raw.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return Path(*parts) if parts else Path("/")


def path_within(path: str, roots: list[Path], *, home: Path | None = None) -> bool:
    """True when PATH (textual, `~` allowed) lies under one of ROOTS."""
    home = home or Path.home()
    candidate = _normalised(path, home)
    for root in roots:
        base = _normalised(str(root), home)
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        return True
    return False


def classify_request(
    question: str, settings: Settings, *, host: str = "laptop", home: Path | None = None
) -> RequestScope:
    """Decide from the text what the request reads (the same answer on ws and laptop)."""
    roots = settings.readable_dirs(host)
    closed = settings.unreadable_dirs(host)
    paths = request_paths(question)
    root_texts = [str(root) for root in roots]
    inside_closed = [path for path in paths if path_within(path, closed, home=home)]
    if inside_closed:
        return RequestScope(
            SCOPE_PERSONAL, paths, root_texts, f"names a closed directory: {inside_closed[0]}"
        )
    if is_mail_request(question):
        if settings.hosts.get(host) and settings.hosts[host].mail_read:
            return RequestScope(
                SCOPE_MAIL, paths, root_texts, "standing read-only mail grant", True
            )
        return RequestScope(SCOPE_MAIL, paths, root_texts, "reads Robert's mail")
    personal = _PERSONAL_SOURCE.search(question)
    if personal and paths and all(path_within(path, roots, home=home) for path in paths):
        if personal.group(0).lower() in {"calendar", "~/org"}:
            personal = None
    if personal:
        return RequestScope(
            SCOPE_PERSONAL, paths, root_texts, f"names a personal source ({personal.group(0)})"
        )
    if not roots:
        return RequestScope(SCOPE_PERSONAL, paths, root_texts, "no readable directories")
    if not paths:
        return RequestScope(
            SCOPE_PERSONAL, paths, root_texts, "names no path under a readable directory"
        )
    outside = [path for path in paths if not path_within(path, roots, home=home)]
    if outside:
        return RequestScope(
            SCOPE_PERSONAL,
            paths,
            root_texts,
            f"reaches outside the readable directories: {outside[0]}",
        )
    return RequestScope(
        SCOPE_READABLE, paths, root_texts, "every path is under a readable directory"
    )


def approval_labels(scope: RequestScope) -> list[str]:
    """Labels a new request carries when it must wait for Robert."""
    return [NEEDS_ROBERT, LAPTOP_READ] if scope.needs_approval else []


def gate_request(
    settings: Settings,
    ledger: Beads,
    bead: dict[str, Any],
    *,
    dry_run: bool,
    home: Path | None = None,
) -> dict[str, Any]:
    """Where a request stands: approved, readable on its own, or waiting for Robert."""
    bead_id = str(bead.get("id") or "")
    labels = bead_labels(bead)
    question = request_text(bead)
    scope = (
        classify_request(question, settings, home=home)
        if question
        else RequestScope(
            SCOPE_PERSONAL, [], [str(r) for r in settings.readable_dirs("laptop")], "empty request"
        )
    )
    out: dict[str, Any] = {"bead": bead_id, "scope": scope.as_dict(), "waiting": False}
    if APPROVED in labels:
        out["approved"] = True
        return out
    if not scope.needs_approval or (
        scope.scope == SCOPE_MAIL
        and settings.hosts.get("laptop")
        and settings.hosts["laptop"].mail_read
    ):
        return out
    out["waiting"] = True
    if NEEDS_ROBERT not in labels:
        ledger.add_labels(
            bead_id, [label for label in (NEEDS_ROBERT, LAPTOP_READ) if label not in labels]
        )
        ledger.comment(
            bead_id,
            "[liaison] this request reads beyond the readable directories "
            f"({', '.join(scope.roots) or 'none configured'}): {scope.reason}. It waits for "
            f'Robert\'s approval (ADR-0027); he answers "{bead_id} yes" or "{bead_id} no".',
        )
        out["labelled"] = True
    return out


@dataclass(frozen=True)
class Idea:
    text: str
    message_id: str
    paragraph: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiaisonAnswer:
    bead: str
    privacy: Privacy
    message_id: str
    paragraphs: list[int]
    pointer: str | None
    ideas: list[Idea]
    links: list[dict[str, str]]
    local_repos: list[dict[str, str | None]]
    identifiers: dict[str, list[str]]
    relay: RelayResult

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "bead": self.bead,
            "privacy": self.privacy.value,
            "message_id": self.message_id,
            "paragraphs": self.paragraphs,
            "pointer": self.pointer,
            "relay": self.relay.as_dict(),
        }
        if self.privacy == Privacy.internal:
            data["ideas"] = [idea.as_dict() for idea in self.ideas]
            data["links"] = self.links
            data["local_repos"] = self.local_repos
            data["identifiers"] = self.identifiers
        else:
            data["counts"] = _answer_counts(
                self.ideas, self.links, self.local_repos, self.identifiers
            )
        return data


def contains_personal_category(text: str) -> bool:
    """Conservatively identify categories that must stay on the laptop."""
    return bool(FORBIDDEN_WORDS.search(text) or _PERSONAL_CATEGORY.search(text))


def request_question(bead: dict[str, Any]) -> str:
    description = str(bead.get("description") or "")
    marker = "Question:"
    if marker not in description:
        raise LiaisonError(f"request {bead.get('id')}: missing Question field")
    question = description.split(marker, 1)[1].split("\nanswer:", 1)[0].strip()
    if not question:
        raise LiaisonError(f"request {bead.get('id')}: empty Question field")
    return question


def request_text(bead: dict[str, Any]) -> str:
    """The Question line, or the plain ask after the header (ADR-0025 accepts both)."""
    try:
        return request_question(bead)
    except LiaisonError:
        body = _description_body(str(bead.get("description") or ""))
        return body.split("\nanswer:", 1)[0].strip()


def is_mail_request(question: str) -> bool:
    lowered = question.lower()
    return "email" in lowered or "mail" in lowered


def subject_words(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", question.lower())
    return list(dict.fromkeys(word for word in words if word not in _SUBJECT_STOPWORDS))[:8]


def _notmuch(command: list[str]) -> Any:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiaisonError(f"notmuch failed: {exc}") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise LiaisonError(detail or f"notmuch exited {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LiaisonError("notmuch returned invalid JSON") from exc


def _search_queries(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    queries: list[str] = []
    for item in payload:
        if isinstance(item, str):
            queries.append(item if ":" in item else f"id:{item}")
        elif isinstance(item, dict):
            message_id = item.get("message_id") or item.get("id")
            thread = item.get("thread")
            if message_id:
                value = str(message_id)
                queries.append(value if value.startswith("id:") else f"id:{value}")
            elif thread:
                value = str(thread)
                queries.append(value if value.startswith("thread:") else f"thread:{value}")
    return queries


def _message_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if "headers" in value or "body" in value:
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _message_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _message_dicts(child)


def _header(headers: Any, name: str) -> str:
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _plain_parts(value: Any, *, in_body: bool = False) -> Iterator[str]:
    if isinstance(value, str):
        if in_body:
            yield value
        return
    if isinstance(value, list):
        for child in value:
            yield from _plain_parts(child, in_body=in_body)
        return
    if not isinstance(value, dict):
        return
    disposition = str(value.get("content-disposition") or value.get("content_disposition") or "")
    if value.get("filename") or disposition.lower().startswith("attachment"):
        return
    content_type = str(value.get("content-type") or value.get("content_type") or "")
    content = value.get("content")
    if isinstance(content, str) and (not content_type or content_type.startswith("text/plain")):
        yield content
    body = value.get("body")
    if body is not None:
        yield from _plain_parts(body, in_body=True)
    if isinstance(content, (dict, list)):
        yield from _plain_parts(content, in_body=True)


def _message(payload: Any) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []
    for order, message in enumerate(_message_dicts(payload)):
        sender = _header(message.get("headers"), "From")
        if sender and ROBERT_EMAIL not in sender.lower():
            continue
        message_id = (
            _header(message.get("headers"), "Message-ID")
            or str(message.get("message_id") or message.get("id") or "")
        ).strip()
        bodies = [part.strip() for part in _plain_parts(message.get("body"), in_body=True)]
        body = "\n\n".join(part for part in bodies if part)
        if message_id and body:
            try:
                timestamp = int(message.get("timestamp") or 0)
            except (TypeError, ValueError):
                timestamp = 0
            candidates.append((timestamp, -order, message_id, body))
    if candidates:
        _timestamp, _order, message_id, body = max(candidates)
        return message_id, body
    raise LiaisonError("notmuch show returned no matching plain-text message")


def find_sent_message(question: str) -> tuple[str, str]:
    query = [f"from:{ROBERT_EMAIL}"]
    query.extend(f"subject:{word}" for word in subject_words(question))
    matches = _notmuch(["notmuch", "search", "--format=json", "--sort=newest-first", *query])
    candidates = _search_queries(matches)
    if not candidates:
        raise LiaisonError("no sent message matched the request")
    for candidate in candidates:
        shown = _notmuch(["notmuch", "show", "--format=json", "--body=true", candidate])
        try:
            return _message(shown)
        except LiaisonError:
            continue
    raise LiaisonError("no matching sent message had a plain-text body")


def _skip_paragraph(text: str) -> bool:
    lowered = text.strip().lower()
    return bool(
        not lowered
        or lowered.startswith(">")
        or lowered.startswith("on ")
        and " wrote:" in lowered
        or lowered.startswith(("hi ", "hello ", "dear ", "best,", "regards,", "thanks,"))
        or lowered.startswith("-- ")
        or lowered in {"hi", "hello", "dear all", "best", "best regards", "regards", "thanks"}
        or re.fullmatch(r"(?:here are|these are|some) (?:my )?ideas?:?", lowered)
    )


def extract_ideas(body: str, message_id: str) -> list[Idea]:
    ideas: list[Idea] = []
    for number, raw in enumerate(re.split(r"\n\s*\n", body.replace("\r\n", "\n")), start=1):
        paragraph = " ".join(line.strip() for line in raw.splitlines()).strip()
        if _skip_paragraph(paragraph) or paragraph == "--":
            continue
        bullet_lines = [
            re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line.strip())
            for line in raw.splitlines()
            if re.match(r"^(?:[-*•]|\d+[.)])\s+", line.strip())
        ]
        candidates = bullet_lines or [paragraph]
        for text in candidates:
            if text:
                ideas.append(Idea(text=text, message_id=message_id, paragraph=number))
    if not ideas:
        raise LiaisonError("the matching message contained no extractable idea paragraphs")
    return ideas


def _trim_link(value: str) -> str:
    return value.rstrip(_TRAILING_URL_PUNCTUATION)


def _doi(value: str) -> str | None:
    parsed = urlparse(value)
    candidate = parsed.path.lstrip("/") if "doi.org" in parsed.netloc.lower() else value
    match = _DOI_RE.search(candidate)
    return _trim_link(match.group(1)) if match else None


def _link_kind(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if host == "doi.org" or host.endswith(".doi.org"):
        return "doi"
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        return "arxiv"
    if "pubmed" in host or host == "ncbi.nlm.nih.gov" or host.endswith(".ncbi.nlm.nih.gov"):
        return "pubmed"
    return "web"


def extract_links(body: str) -> list[dict[str, str]]:
    """Extract and classify HTTP links and bare DOIs in first-seen order."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, kind: str) -> None:
        if kind == "doi":
            doi = _doi(url)
            if not doi:
                return
            url = f"https://doi.org/{doi}"
        key = url.lower()
        if key not in seen:
            seen.add(key)
            links.append({"url": url, "kind": kind})

    for match in _URL_RE.finditer(body):
        url = _trim_link(match.group(0))
        add(url, _link_kind(url))
    for match in _DOI_RE.finditer(body):
        add(match.group(1), "doi")
    return links


def _origin_remote(repo: Path) -> str | None:
    config_path = repo / ".git" / "config"
    if not config_path.is_file():
        return None
    parser = ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
        value = parser.get('remote "origin"', "url", fallback="").strip()
    except (ConfigError, OSError):
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.username:
        hostname = parsed.hostname or ""
        netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
        value = urlunsplit(parsed._replace(netloc=netloc))
    return value or None


def match_local_repos(body: str, settings: Settings) -> list[dict[str, str | None]]:
    """Match immediate software-root directories named as words in the mail body."""
    normalised_body = re.sub(r"[-_]", "", body).lower()
    matches: list[dict[str, str | None]] = []
    seen_paths: set[Path] = set()
    for configured in settings.software_dirs():
        try:
            root = configured.resolve(strict=True)
        except OSError:
            continue
        if not root.is_dir():
            continue
        try:
            candidates = sorted(root.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for candidate in candidates:
            compact = re.sub(r"[-_]", "", candidate.name).lower()
            if len(compact) < 4 or compact in _REPO_NAME_STOPWORDS:
                continue
            if not re.search(rf"(?<![a-z0-9]){re.escape(compact)}(?![a-z0-9])", normalised_body):
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if not resolved.is_dir() or resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            matches.append(
                {"name": candidate.name, "path": str(resolved), "remote": _origin_remote(resolved)}
            )
    return matches


def extract_identifiers(body: str, links: list[dict[str, str]]) -> dict[str, list[str]]:
    """Derive stable publication identifiers without resolving anything online."""
    dois: list[str] = []
    arxiv: list[str] = []
    pmids: list[str] = []
    for match in _DOI_RE.finditer(body):
        value = _trim_link(match.group(1))
        if value.lower() not in {item.lower() for item in dois}:
            dois.append(value)
    for link in links:
        parsed = urlparse(link["url"])
        if link["kind"] == "arxiv":
            arxiv_match = re.search(r"/(?:abs|pdf)/([^/?#]+)", parsed.path, re.IGNORECASE)
            if arxiv_match:
                value = arxiv_match.group(1).removesuffix(".pdf")
                if value not in arxiv:
                    arxiv.append(value)
        elif link["kind"] == "pubmed":
            pubmed_match = re.search(r"/(\d{1,9})(?:/|$)", parsed.path)
            if pubmed_match and pubmed_match.group(1) not in pmids:
                pmids.append(pubmed_match.group(1))
    return {"dois": dois, "arxiv": arxiv, "pmids": pmids}


def _description_body(description: str) -> str:
    text = description.lstrip()
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip("\n")


def _answer_text(
    ideas: list[Idea],
    links: list[dict[str, str]],
    local_repos: list[dict[str, str | None]],
    identifiers: dict[str, list[str]],
) -> str:
    lines = ["# Liaison answer", ""]
    for index, idea in enumerate(ideas, start=1):
        lines.append(
            f"{index}. {idea.text} (Message-ID: {idea.message_id}; paragraph {idea.paragraph})"
        )
    lines.extend(["", "## Collected material", ""])
    lines.append(
        yaml.safe_dump(
            {"links": links, "local_repos": local_repos, "identifiers": identifiers},
            sort_keys=False,
        ).rstrip()
    )
    return "\n".join(lines) + "\n"


def _answer_counts(
    ideas: list[Idea],
    links: list[dict[str, str]],
    local_repos: list[dict[str, str | None]],
    identifiers: dict[str, list[str]],
) -> dict[str, int]:
    return {
        "ideas": len(ideas),
        "links": len(links),
        "local_repos": len(local_repos),
        "dois": len(identifiers["dois"]),
        "arxiv": len(identifiers["arxiv"]),
        "pmids": len(identifiers["pmids"]),
    }


def _answer_path(settings: Settings, bead_id: str) -> tuple[Path, str]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", bead_id):
        raise LiaisonError(f"unsafe bead id for local answer path: {bead_id!r}")
    path = settings.state_dir() / "agents" / "liaison" / "answers" / f"{bead_id}.md"
    try:
        pointer = str(path.relative_to(settings.root))
    except ValueError:
        pointer = str(path)
    return path, pointer


def _coordinator_relay(settings: Settings, bead_id: str, *, dry_run: bool) -> RelayResult:
    try:
        coordinator_host = load_agent(settings.root, "coordinator").host
    except AgentError:
        coordinator_host = "ws"
    return relay(
        settings,
        coordinator_host,
        [
            "agent",
            "tell",
            "coordinator",
            f"Liaison answered request {bead_id}; read the closed answer bead after Beads sync.",
            "--from",
            "liaison",
            "--apply",
        ],
        dry_run=dry_run,
    )


def answer_mail_request(
    settings: Settings,
    ledger: Beads,
    bead: dict[str, Any],
    *,
    dry_run: bool,
) -> LiaisonAnswer:
    bead_id = str(bead.get("id") or "")
    if not bead_id:
        raise LiaisonError("request has no bead id")
    description = str(bead.get("description") or "")
    header = BeadHeader.parse(description)
    if header is None:
        raise LiaisonError(f"request {bead_id}: missing valid provenance header")
    question = request_question(bead)
    message_id, body = find_sent_message(question)
    ideas = extract_ideas(body, message_id)
    links = extract_links(body)
    local_repos = match_local_repos(body, settings)
    identifiers = extract_identifiers(body, links)
    privacy = (
        Privacy.local_only
        if header.privacy == Privacy.local_only or contains_personal_category(body)
        else Privacy.internal
    )
    pointer: str | None = None
    answer_payload: dict[str, Any]
    if privacy == Privacy.local_only:
        answer_path, pointer = _answer_path(settings, bead_id)
        if not dry_run:
            answer_path.parent.mkdir(parents=True, exist_ok=True)
            answer_path.write_text(
                _answer_text(ideas, links, local_repos, identifiers), encoding="utf-8"
            )
        answer_payload = {
            "privacy": privacy.value,
            "pointer": pointer,
            "counts": _answer_counts(ideas, links, local_repos, identifiers),
            "provenance": [
                {"message_id": idea.message_id, "paragraph": idea.paragraph} for idea in ideas
            ],
        }
    else:
        answer_payload = {
            "privacy": privacy.value,
            "ideas": [
                {"number": number, **idea.as_dict()} for number, idea in enumerate(ideas, start=1)
            ],
            "links": links,
            "local_repos": local_repos,
            "identifiers": identifiers,
        }
    provenance = list(header.provenance)
    seen = {(item.message_id, item.locator) for item in provenance}
    for idea in ideas:
        key = (idea.message_id, f"paragraph {idea.paragraph}")
        if key not in seen:
            provenance.append(
                Provenance(
                    source="notmuch",
                    locator=f"paragraph {idea.paragraph}",
                    message_id=idea.message_id,
                )
            )
            seen.add(key)
    updated_header = header.model_copy(update={"privacy": privacy, "provenance": provenance})
    original_body = _description_body(description).split("\nanswer:\n", 1)[0].rstrip()
    answer_yaml = yaml.safe_dump({"answer": answer_payload}, sort_keys=False).rstrip()
    ledger.update_description(
        bead_id,
        updated_header.render() + "\n" + original_body + "\n\n" + answer_yaml + "\n",
    )
    desired_label = f"privacy:{privacy.value}"
    current_labels = bead_labels(bead)
    ledger.remove_labels(
        bead_id,
        [
            label
            for label in current_labels
            if label.startswith("privacy:") and label != desired_label
        ],
    )
    if desired_label not in current_labels:
        ledger.add_labels(bead_id, [desired_label])
    ledger.close(bead_id, "Liaison recorded a source-backed answer.")
    relayed = _coordinator_relay(settings, bead_id, dry_run=dry_run)
    answer = LiaisonAnswer(
        bead=bead_id,
        privacy=privacy,
        message_id=message_id,
        paragraphs=[idea.paragraph for idea in ideas],
        pointer=pointer,
        ideas=ideas,
        links=links,
        local_repos=local_repos,
        identifiers=identifiers,
        relay=relayed,
    )
    if not dry_run:
        append_event(
            settings.state_dir(),
            make_event(
                "finished",
                source="liaison",
                session="agent-liaison",
                title=f"Liaison answered request {bead_id}",
                bead=bead_id,
                data={
                    "privacy": privacy.value,
                    "message_id": message_id,
                    "paragraphs": answer.paragraphs,
                    "pointer": pointer,
                    "counts": _answer_counts(ideas, links, local_repos, identifiers),
                },
            ),
        )
    return answer
