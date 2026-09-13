"""Small, non-extensible tool surface for the two restricted fleet roles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.config import ALWAYS_UNREADABLE, Settings
from cube.disclosure import release_text
from cube.lookup import LookupError, Roots, op_grep, op_head, op_ls, readable_roots, resolve_within


def laptop_roots(settings: Settings, beads: Beads | None = None) -> Roots:
    if settings.host != "laptop":
        raise LookupError("laptop tools run on the laptop only; use the liaison request channel")
    roots = readable_roots(settings)
    return roots


def approved_paths(beads: Beads | None) -> list[Path]:
    bead_id = os.environ.get("CUBE_BEAD")
    if beads is not None and bead_id:
        from cube.agents.liaison import request_paths, request_text

        bead = beads.show(bead_id)
        labels = bead.get("labels") or []
        if "approved:robert" in labels and "agent:liaison" in labels:
            # Approval extends only the paths in this request, never the whole home.
            return [Path(p).expanduser().resolve() for p in request_paths(request_text(bead))]
    return []


def request_access(settings: Settings, beads: Beads, text: str, *, dry_run: bool) -> dict[str, Any]:
    """One durable, scoped directory request, handled by the normal MM decision path."""
    from cube.agents.liaison import request_paths
    from cube.model import BeadHeader, Privacy, Provenance

    if not request_paths(text):
        raise LookupError(
            "directory requests must name absolute paths; tool changes need a policy review"
        )
    if release_text(text, personal_source=True) != text:
        raise LookupError("permission requests must not contain private data or credentials")
    xid = "liaison-access:" + hashlib.sha256(text.strip().encode()).hexdigest()
    existing = beads.find_by_xid(xid)
    if existing:
        return {"bead": existing["id"], "status": existing.get("status"), "existing": True}
    if dry_run:
        return {
            "bead": None,
            "dry_run": True,
            "status": "awaiting-approval",
            "paths": request_paths(text),
        }
    bead_id = beads.create(
        "Liaison: scoped laptop read",
        header=BeadHeader(
            xid=xid,
            provenance=[
                Provenance(
                    source="liaison", locator=os.environ.get("CUBE_BEAD") or "boundary request"
                )
            ],
            deadline=None,
            privacy=Privacy.internal,
        ),
        body=f"Question: {text.strip()}",
        labels=[
            "kind:request",
            "agent:liaison",
            "host:laptop",
            "privacy:internal",
            "laptop-read:approval",
            "needs:robert",
        ],
        acceptance=(
            "Robert approves the named paths; liaison answers with a source-backed, "
            "privacy-screened result."
        ),
    )
    return {"bead": bead_id, "dry_run": dry_run, "status": "awaiting-approval"}


def lookup(
    settings: Settings, operation: str, path: str, *, pattern: str = "", beads: Beads | None = None
) -> dict[str, Any]:
    roots = laptop_roots(settings, beads)
    try:
        bounded = resolve_within(path, roots)
    except LookupError:
        # Use ONLY approved roots here: dropping a configured deny from the
        # standing root set would accidentally open sibling private directories.
        scoped = Roots(
            tuple(approved_paths(beads)), tuple(p.expanduser().resolve() for p in ALWAYS_UNREADABLE)
        )
        bounded = resolve_within(path, scoped)
    if operation == "ls":
        return op_ls(bounded)
    if operation == "grep":
        return op_grep(bounded, pattern)
    if operation == "head":
        return op_head(bounded, lines=200)
    raise LookupError("unsupported lookup operation")


def mail(settings: Settings, operation: str, query: str) -> Any:
    """Gnus socket only; fixed notmuch operations, no caller-supplied Lisp or shell."""
    laptop_roots(settings)
    if not settings.hosts["laptop"].mail_read:
        raise LookupError("mail access needs a standing permission through Mattermost")
    if not query.strip() or len(query) > 2000:
        raise LookupError("give a bounded mail query")
    if operation == "search":
        args = ["search", "--format=json", "--limit=20", "--", query]
    elif operation == "show" and re.fullmatch(r"id:[A-Za-z0-9_.+@%=/~-]{1,500}", query):
        args = [
            "show",
            "--format=json",
            "--entire-thread=false",
            "--include-html=false",
            "--body=true",
            "--",
            query,
        ]
    else:
        raise LookupError("mail show requires an exact id:Message-ID")
    lisp_args = " ".join(json.dumps(a) for a in args)
    expression = (
        '(with-temp-buffer (let ((status (call-process "notmuch" nil t nil '
        + lisp_args
        + '))) (unless (equal status 0) (error "mail lookup failed")) '
        "(buffer-string)))"
    )
    proc = subprocess.run(
        ["emacsclient", "-s", "gnus", "--eval", expression],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode:
        raise LookupError("Gnus lookup failed; dedicated gnus socket must already be running")
    try:
        raw = json.loads(proc.stdout)
        if not isinstance(raw, str) or len(raw) > 200_000:
            raise ValueError("oversize response")
        # Refuse sensitive mail before any of it enters model context.
        decoded = json.loads(raw)
        visible = json.dumps(decoded, ensure_ascii=False)
        safe = release_text(visible, personal_source=True)
        return {"withheld": safe} if safe != visible else decoded
    except (ValueError, TypeError) as exc:
        raise LookupError("Gnus returned an invalid or oversized response") from exc
