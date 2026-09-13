#!/usr/bin/env python3
# ruff: noqa: E501
"""Verify a BibTeX bibliography: internal consistency offline, Crossref and PubMed online.

Offline checks (always run):

* duplicate keys, duplicate DOIs, duplicate normalised titles;
* required fields per entry type (article: author, title, journal, year;
  inproceedings/incollection: author, title, booktitle, year; book: author or
  editor, title, publisher, year; phdthesis/mastersthesis: author, title,
  school, year; misc/online/software: title plus doi, url or howpublished);
* malformed DOI, DOI hidden in the url field, malformed PMID, malformed year
  or a year in the future, ``et al.`` or ``others`` in the author list,
  empty title, ``\\url`` in the note without an access date for web sources.

Online checks (default; disabled by ``--offline``):

* every DOI is resolved through the Crossref REST API; unresolvable DOIs are
  errors; title, year and first author family name are compared with the
  entry (title similarity below ``--title-threshold`` is a mismatch);
* Crossref is asked for retraction or correction notices that update the DOI
  and the Crossref title is checked for a RETRACTED marker;
* entries with a ``pmid`` field are checked against PubMed esummary (title,
  year, DOI agreement).

Findings are ``file:line: severity: code: message. fix: ...``; ``--json`` for
machine reading; exit 1 when any error remains, 0 otherwise, 2 on usage
problems. ``--cache PATH`` stores API responses as JSON so a rerun is free;
``--only-cited MANUSCRIPT`` restricts checks to the keys a .tex or .md file
cites. Nothing is written except the cache file.

Example:
  cite_check.py refs.bib --offline
  cite_check.py refs.bib --only-cited main.tex --cache runs/paper/cites.json --mailto you@example.org
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CROSSREF = "https://api.crossref.org/works/"
PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_IN_URL_RE = re.compile(r"doi\.org/(10\.\d{4,9}/[^\s}]+)", re.IGNORECASE)
PMID_RE = re.compile(r"^\d{1,9}$")
YEAR_RE = re.compile(r"^\d{4}$")

REQUIRED: dict[str, list[list[str]]] = {
    "article": [["author"], ["title"], ["journal", "journaltitle"], ["year", "date"]],
    "inproceedings": [["author"], ["title"], ["booktitle"], ["year", "date"]],
    "conference": [["author"], ["title"], ["booktitle"], ["year", "date"]],
    "incollection": [["author"], ["title"], ["booktitle"], ["year", "date"]],
    "book": [["author", "editor"], ["title"], ["publisher"], ["year", "date"]],
    "phdthesis": [["author"], ["title"], ["school", "institution"], ["year", "date"]],
    "mastersthesis": [["author"], ["title"], ["school", "institution"], ["year", "date"]],
    "thesis": [["author"], ["title"], ["school", "institution"], ["year", "date"]],
    "techreport": [["author", "institution"], ["title"], ["year", "date"]],
    "misc": [["title"], ["doi", "url", "howpublished", "eprint"]],
    "online": [["title"], ["url", "doi"]],
    "software": [["title"], ["doi", "url"]],
    "dataset": [["title"], ["doi", "url"]],
    "unpublished": [["author"], ["title"], ["note", "year", "date"]],
}


@dataclass
class Finding:
    path: str
    line: int
    severity: str
    code: str
    message: str
    fix: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.severity}: {self.code}: {self.message}. fix: {self.fix}"


@dataclass
class Entry:
    key: str
    type: str
    fields: dict[str, str]
    path: str
    line: int


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checked_online: int = 0
    skipped_online: int = 0


# --------------------------------------------------------------------------- bibtex


def parse_bibtex(path: Path) -> tuple[list[Entry], list[Finding]]:
    """Minimal BibTeX parser: entries, keys, fields with brace or quote values, line numbers."""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: list[Entry] = []
    problems: list[Finding] = []
    strings: dict[str, str] = {}
    i = 0
    n = len(text)
    while i < n:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@\s*(\w+)\s*([{(])", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        open_ch = m.group(2)
        close_ch = "}" if open_ch == "{" else ")"
        body_start = at + m.end()
        depth = 1
        j = body_start
        while j < n and depth > 0:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == close_ch and close_ch == ")" and depth == 1:
                depth = 0
                break
            j += 1
        body = text[body_start : j - 1] if depth == 0 or j >= n else text[body_start:j]
        line = text.count("\n", 0, at) + 1
        i = j + 1
        if etype in ("comment", "preamble"):
            continue
        if etype == "string":
            sm = re.match(r"\s*(\w+)\s*=\s*(.*)", body, re.DOTALL)
            if sm:
                strings[sm.group(1).lower()] = strip_value(sm.group(2).strip(), strings)
            continue
        km = re.match(r"\s*([^,\s]+)\s*,", body)
        if not km:
            problems.append(
                Finding(
                    str(path),
                    line,
                    "error",
                    "bib.syntax",
                    f"@{etype} entry without a key",
                    "add a citation key after the brace",
                )
            )
            continue
        key = km.group(1)
        fields = parse_fields(body[km.end() :], strings)
        entries.append(Entry(key, etype, fields, str(path), line))
    return entries, problems


def parse_fields(body: str, strings: dict[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        m = re.match(r"\s*,?\s*([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*", body[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        parts: list[str] = []
        while i < n:
            ch = body[i]
            if ch == "{":
                depth = 0
                j = i
                while j < n:
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                parts.append(body[i + 1 : j])
                i = j + 1
            elif ch == '"':
                j = i + 1
                depth = 0
                while j < n:
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                    elif body[j] == '"' and depth == 0:
                        break
                    j += 1
                parts.append(body[i + 1 : j])
                i = j + 1
            else:
                wm = re.match(r"\s*([A-Za-z0-9_\-]+)", body[i:])
                if not wm:
                    break
                tok = wm.group(1)
                parts.append(strings.get(tok.lower(), tok))
                i += wm.end()
            cm = re.match(r"\s*#\s*", body[i:])
            if cm:
                i += cm.end()
                continue
            break
        fields[name] = re.sub(r"\s+", " ", "".join(parts)).strip()
        cm2 = re.match(r"\s*,", body[i:])
        if cm2:
            i += cm2.end()
        else:
            tail = body[i:].strip()
            if not tail:
                break
    return fields


def strip_value(v: str, strings: dict[str, str]) -> str:
    v = v.strip().rstrip(",").strip()
    if v[:1] in '{"' and v[-1:] in '}"':
        return v[1:-1]
    return strings.get(v.lower(), v)


def normalise_title(t: str) -> str:
    t = re.sub(r"\\[a-zA-Z]+", " ", t)
    t = re.sub(r"[{}$\\]", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def first_author_family(author: str) -> str:
    first = re.split(r"\s+and\s+", author, maxsplit=1)[0].strip()
    first = re.sub(r"[{}]", "", first)
    if "," in first:
        return first.split(",", 1)[0].strip().lower()
    parts = first.split()
    return parts[-1].lower() if parts else ""


def entry_year(e: Entry) -> str | None:
    y = e.fields.get("year")
    if y and YEAR_RE.match(y.strip()):
        return y.strip()
    d = e.fields.get("date")
    if d:
        m = re.match(r"(\d{4})", d)
        if m:
            return m.group(1)
    return None


# --------------------------------------------------------------------------- offline checks


def offline_checks(entries: list[Entry], today: dt.date) -> list[Finding]:
    out: list[Finding] = []
    seen_keys: dict[str, Entry] = {}
    seen_dois: dict[str, Entry] = {}
    seen_titles: dict[str, Entry] = {}
    for e in entries:
        if e.key in seen_keys:
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "error",
                    "bib.duplicate-key",
                    f"key {e.key!r} already defined at line {seen_keys[e.key].line}",
                    "merge or rename",
                )
            )
        else:
            seen_keys[e.key] = e
        req = REQUIRED.get(e.type)
        if req is None:
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "info",
                    "bib.type",
                    f"{e.key}: entry type @{e.type} has no field rule",
                    "no action",
                )
            )
        else:
            for alternatives in req:
                if not any(e.fields.get(a) for a in alternatives):
                    out.append(
                        Finding(
                            e.path,
                            e.line,
                            "error",
                            "bib.missing-field",
                            f"{e.key}: @{e.type} lacks {' or '.join(alternatives)}",
                            "complete the entry from the publisher record",
                        )
                    )
        title = e.fields.get("title", "")
        if title and not normalise_title(title):
            out.append(
                Finding(
                    e.path, e.line, "error", "bib.title", f"{e.key}: empty title", "add the title"
                )
            )
        if title:
            nt = normalise_title(title)
            if nt in seen_titles and seen_titles[nt].key != e.key:
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "warning",
                        "bib.duplicate-title",
                        f"{e.key}: same title as {seen_titles[nt].key!r} (line {seen_titles[nt].line})",
                        "keep one entry and repoint the citations",
                    )
                )
            else:
                seen_titles.setdefault(nt, e)
        doi = e.fields.get("doi", "").strip()
        if doi:
            doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
            if not DOI_RE.match(doi):
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "error",
                        "bib.doi-format",
                        f"{e.key}: malformed DOI {doi!r}",
                        "DOIs look like 10.1371/journal.pcbi.1005619; drop the URL prefix",
                    )
                )
            else:
                low = doi.lower()
                if low in seen_dois:
                    out.append(
                        Finding(
                            e.path,
                            e.line,
                            "error",
                            "bib.duplicate-doi",
                            f"{e.key}: DOI also used by {seen_dois[low].key!r} (line {seen_dois[low].line})",
                            "keep one entry and repoint the citations",
                        )
                    )
                else:
                    seen_dois[low] = e
        else:
            url = (
                e.fields.get("url", "")
                + " "
                + e.fields.get("howpublished", "")
                + " "
                + e.fields.get("note", "")
            )
            m = DOI_IN_URL_RE.search(url)
            if m:
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "warning",
                        "bib.doi-in-url",
                        f"{e.key}: DOI {m.group(1)} given as URL, not in the doi field",
                        "move it to doi = {...} so it can be verified",
                    )
                )
            elif e.type in ("article", "inproceedings", "incollection", "conference"):
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "warning",
                        "bib.no-doi",
                        f"{e.key}: no DOI",
                        "add the DOI (Crossref search by title) so the entry can be verified",
                    )
                )
        pmid = e.fields.get("pmid", "").strip()
        if pmid and not PMID_RE.match(pmid):
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "error",
                    "bib.pmid-format",
                    f"{e.key}: malformed PMID {pmid!r}",
                    "PMIDs are plain integers",
                )
            )
        y = e.fields.get("year")
        if y is not None and not YEAR_RE.match(y.strip()):
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "error",
                    "bib.year-format",
                    f"{e.key}: year {y!r} is not a four-digit year",
                    "fix the year field",
                )
            )
        ey = entry_year(e)
        if ey and int(ey) > today.year + 1:
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "error",
                    "bib.year-future",
                    f"{e.key}: year {ey} is in the future",
                    "fix the year field",
                )
            )
        if ey and int(ey) < 1600:
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "warning",
                    "bib.year-odd",
                    f"{e.key}: year {ey} looks wrong",
                    "check the year field",
                )
            )
        author = e.fields.get("author", "")
        if re.search(r"\bet al\.?\b", author, re.IGNORECASE) or re.search(
            r"\band others\b", author
        ):
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "warning",
                    "bib.author-truncated",
                    f"{e.key}: author list truncated ({'et al.' if 'et al' in author.lower() else 'and others'})",
                    "list all authors; the style file truncates as the venue wants",
                )
            )
        if (
            e.type in ("misc", "online")
            and e.fields.get("url")
            and not any(k in e.fields for k in ("urldate", "note", "lastaccessed", "accessed"))
        ):
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "warning",
                    "bib.url-no-date",
                    f"{e.key}: web source without access date",
                    "add urldate = {YYYY-MM-DD}",
                )
            )
    return out


# --------------------------------------------------------------------------- online checks


class Client:
    def __init__(
        self, cache_path: Path | None, mailto: str | None, timeout: float, pause: float
    ) -> None:
        self.cache_path = cache_path
        self.cache: dict[str, Any] = {}
        if cache_path and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}
        self.mailto = mailto
        self.timeout = timeout
        self.pause = pause
        self.dirty = False

    def get(self, url: str) -> tuple[int, Any]:
        if url in self.cache:
            return self.cache[url]["status"], self.cache[url]["body"]
        headers = {
            "User-Agent": f"borg-cube cite_check/1.0 (mailto:{self.mailto})"
            if self.mailto
            else "borg-cube cite_check/1.0"
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            status, body = exc.code, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            status, body = 0, {"error": str(exc)}
        self.cache[url] = {"status": status, "body": body}
        self.dirty = True
        time.sleep(self.pause)
        return status, body

    def save(self) -> None:
        if self.cache_path and self.dirty:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")


def crossref_year(msg: dict[str, Any]) -> str | None:
    for k in ("published-print", "published-online", "issued", "created"):
        parts = msg.get(k, {}).get("date-parts", [[None]])
        if parts and parts[0] and parts[0][0]:
            return str(parts[0][0])
    return None


def compare_record(
    e: Entry,
    title_online: str,
    year_online: str | None,
    family_online: str | None,
    source: str,
    threshold: float,
) -> list[Finding]:
    out: list[Finding] = []
    bt = normalise_title(e.fields.get("title", ""))
    ot = normalise_title(title_online)
    if bt and ot:
        ratio = difflib.SequenceMatcher(None, bt, ot).ratio()
        if ratio < threshold and not (bt in ot or ot in bt):
            out.append(
                Finding(
                    e.path,
                    e.line,
                    "error",
                    f"{source}.title-mismatch",
                    f"{e.key}: title differs from {source} record (similarity {ratio:.2f}): {title_online[:90]!r}",
                    "the DOI or PMID points to another work; fix the identifier or the entry",
                )
            )
    ey = entry_year(e)
    if ey and year_online and ey != year_online:
        sev = "warning" if abs(int(ey) - int(year_online)) == 1 else "error"
        out.append(
            Finding(
                e.path,
                e.line,
                sev,
                f"{source}.year-mismatch",
                f"{e.key}: year {ey} but {source} says {year_online}",
                "use the publication year of the version you cite (print vs online may differ by one)",
            )
        )
    fam = first_author_family(e.fields.get("author", ""))
    if (
        fam
        and family_online
        and fam != family_online.lower()
        and difflib.SequenceMatcher(None, fam, family_online.lower()).ratio() < 0.8
    ):
        out.append(
            Finding(
                e.path,
                e.line,
                "warning",
                f"{source}.author-mismatch",
                f"{e.key}: first author {fam!r} but {source} says {family_online!r}",
                "check the author list and order",
            )
        )
    return out


def online_checks(
    entries: list[Entry], client: Client, threshold: float, report: Report
) -> list[Finding]:
    out: list[Finding] = []
    for e in entries:
        doi = re.sub(
            r"^(https?://)?(dx\.)?doi\.org/",
            "",
            e.fields.get("doi", "").strip(),
            flags=re.IGNORECASE,
        )
        pmid = e.fields.get("pmid", "").strip()
        if not doi and not pmid:
            report.skipped_online += 1
            continue
        if doi and DOI_RE.match(doi):
            report.checked_online += 1
            status, body = client.get(CROSSREF + urllib.parse.quote(doi, safe=""))
            if status == 404:
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "error",
                        "crossref.unresolvable",
                        f"{e.key}: DOI {doi} not found in Crossref",
                        "check the DOI on the publisher page; DataCite DOIs (Zenodo) are not in Crossref, mark them with note = {DataCite}",
                    )
                )
            elif status != 200 or not isinstance(body, dict):
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "warning",
                        "crossref.unavailable",
                        f"{e.key}: Crossref returned {status}",
                        "rerun later; the entry was not verified",
                    )
                )
            else:
                msg = body.get("message", {})
                title = " ".join(msg.get("title", []) or [])
                fam = None
                for a in msg.get("author", []) or []:
                    if a.get("sequence") == "first" or fam is None:
                        fam = a.get("family")
                        if a.get("sequence") == "first":
                            break
                out.extend(compare_record(e, title, crossref_year(msg), fam, "crossref", threshold))
                if re.search(r"\bretract", title, re.IGNORECASE) or re.search(
                    r"\bwithdrawn\b", title, re.IGNORECASE
                ):
                    out.append(
                        Finding(
                            e.path,
                            e.line,
                            "error",
                            "crossref.retracted",
                            f"{e.key}: Crossref title carries a retraction or withdrawal marker",
                            "do not cite a retracted work as evidence; cite the retraction notice if the history matters",
                        )
                    )
                for upd in msg.get("update-to", []) or []:
                    if str(upd.get("type", "")).lower().startswith("retract"):
                        out.append(
                            Finding(
                                e.path,
                                e.line,
                                "warning",
                                "crossref.is-retraction-notice",
                                f"{e.key}: this DOI is itself a retraction notice for {upd.get('DOI')}",
                                "cite the original only if the retraction is the point",
                            )
                        )
                q = (
                    "https://api.crossref.org/works?filter=updates:"
                    + urllib.parse.quote(doi, safe="")
                    + "&rows=5&select=DOI,update-to,type,title"
                )
                st2, body2 = client.get(q)
                if st2 == 200 and isinstance(body2, dict):
                    for item in body2.get("message", {}).get("items", []) or []:
                        for upd in item.get("update-to", []) or []:
                            utype = str(upd.get("type", "")).lower()
                            if utype.startswith("retract"):
                                out.append(
                                    Finding(
                                        e.path,
                                        e.line,
                                        "error",
                                        "crossref.retracted",
                                        f"{e.key}: retracted by {item.get('DOI')}",
                                        "do not cite a retracted work as evidence",
                                    )
                                )
                            elif utype in (
                                "correction",
                                "corrigendum",
                                "erratum",
                                "expression_of_concern",
                            ):
                                out.append(
                                    Finding(
                                        e.path,
                                        e.line,
                                        "warning",
                                        f"crossref.{utype}",
                                        f"{e.key}: {utype} published as {item.get('DOI')}",
                                        "read the notice and check whether it touches what you cite",
                                    )
                                )
        if pmid and PMID_RE.match(pmid):
            report.checked_online += 1
            status, body = client.get(f"{PUBMED}?db=pubmed&id={pmid}&retmode=json")
            rec = None
            if status == 200 and isinstance(body, dict):
                rec = body.get("result", {}).get(pmid)
            if not rec or "error" in rec:
                out.append(
                    Finding(
                        e.path,
                        e.line,
                        "error",
                        "pubmed.unresolvable",
                        f"{e.key}: PMID {pmid} not found in PubMed",
                        "check the PMID",
                    )
                )
            else:
                year = None
                m = re.match(r"(\d{4})", rec.get("pubdate", "") or rec.get("epubdate", ""))
                if m:
                    year = m.group(1)
                fam = None
                authors = rec.get("authors") or []
                if authors:
                    fam = (authors[0].get("name") or "").split(" ")[0]
                out.extend(compare_record(e, rec.get("title", ""), year, fam, "pubmed", threshold))
                pm_doi = next(
                    (a.get("value") for a in rec.get("articleids", []) if a.get("idtype") == "doi"),
                    None,
                )
                if doi and pm_doi and pm_doi.lower() != doi.lower():
                    out.append(
                        Finding(
                            e.path,
                            e.line,
                            "error",
                            "pubmed.doi-mismatch",
                            f"{e.key}: PubMed lists DOI {pm_doi} for PMID {pmid}, entry has {doi}",
                            "one of the identifiers points elsewhere",
                        )
                    )
                if any("retract" in (t or "").lower() for t in rec.get("pubtype", [])):
                    out.append(
                        Finding(
                            e.path,
                            e.line,
                            "error",
                            "pubmed.retracted",
                            f"{e.key}: PubMed marks this record as retracted",
                            "do not cite a retracted work as evidence",
                        )
                    )
    return out


# --------------------------------------------------------------------------- cited keys


def cited_keys(manuscript: Path) -> set[str]:
    text = manuscript.read_text(encoding="utf-8", errors="replace")
    keys: set[str] = set()
    if manuscript.suffix.lower() in (".tex", ".ltx", ".latex"):
        text = "\n".join(re.sub(r"(?<!\\)%.*$", "", ln) for ln in text.splitlines())
        for m in re.finditer(
            r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}", text
        ):
            keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    else:
        for m in re.finditer(
            r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*[A-Za-z0-9_])", text
        ):
            if not re.match(r"^(fig|tbl|tab|eq|sec|lst)[:\-]", m.group(1)):
                keys.add(m.group(1))
    return keys


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("bib", type=Path, nargs="+", help="BibTeX file(s)")
    p.add_argument("--offline", action="store_true", help="internal consistency only; no network")
    p.add_argument(
        "--only-cited", type=Path, help="restrict to keys cited in this .tex or .md file"
    )
    p.add_argument("--cache", type=Path, help="JSON cache of API responses (read and written)")
    p.add_argument("--mailto", help="contact address for the Crossref polite pool")
    p.add_argument("--timeout", type=float, default=20.0, help="seconds per request")
    p.add_argument("--pause", type=float, default=0.2, help="seconds between requests")
    p.add_argument(
        "--title-threshold",
        type=float,
        default=0.8,
        help="title similarity below which a record mismatches",
    )
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    p.add_argument("--quiet", action="store_true", help="hide info findings")
    args = p.parse_args(argv)

    entries: list[Entry] = []
    findings: list[Finding] = []
    for bp in args.bib:
        if not bp.exists():
            print(f"error: {bp} not found", file=sys.stderr)
            return 2
        ents, probs = parse_bibtex(bp)
        entries.extend(ents)
        findings.extend(probs)
    if args.only_cited:
        if not args.only_cited.exists():
            print(f"error: {args.only_cited} not found", file=sys.stderr)
            return 2
        wanted = cited_keys(args.only_cited)
        entries = [e for e in entries if e.key in wanted]
    report = Report()
    findings.extend(offline_checks(entries, dt.date.today()))
    if not args.offline:
        client = Client(args.cache, args.mailto, args.timeout, args.pause)
        findings.extend(online_checks(entries, client, args.title_threshold, report))
        client.save()
    if args.strict:
        for f in findings:
            if f.severity == "warning":
                f.severity = "error"
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.path, f.line, f.code))
    shown = [f for f in findings if not (args.quiet and f.severity == "info")]
    if args.json:
        print(
            json.dumps(
                {
                    "entries": len(entries),
                    "checked_online": report.checked_online,
                    "skipped_online": report.skipped_online,
                    "offline": args.offline,
                    "findings": [asdict(f) for f in shown],
                },
                indent=2,
            )
        )
    else:
        for f in shown:
            print(f.render())
        counts = {
            s: sum(1 for f in findings if f.severity == s) for s in ("error", "warning", "info")
        }
        mode = (
            "offline"
            if args.offline
            else f"online, {report.checked_online} identifiers checked, {report.skipped_online} entries without DOI or PMID"
        )
        print(
            f"{len(entries)} entries ({mode}): {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info"
        )
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
