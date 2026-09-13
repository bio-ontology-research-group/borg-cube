"""brain/: doctrine and facts. `cube brain push` loads brain/facts/*.yaml into `bd remember`."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads


def load_facts(brain_dir: Path) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    facts_dir = brain_dir / "facts"
    if not facts_dir.exists():
        return facts
    for path in sorted(facts_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if isinstance(data, dict):
            data = data.get("facts", [])
        for item in data:
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict) or not item.get("text"):
                raise ValueError(f"{path}: every fact needs a 'text' field")
            item.setdefault("source", str(path.relative_to(brain_dir)))
            item.setdefault("key", fact_key(item["text"]))
            facts.append(item)
    return facts


def fact_key(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return f"{slug}-{digest}"


def push(beads: Beads, brain_dir: Path) -> list[dict[str, Any]]:
    """Store every fact (idempotent by key). Returns the facts pushed."""
    existing = {m.get("key") for m in beads.memories()} if not beads.dry_run else set()
    pushed: list[dict[str, Any]] = []
    for fact in load_facts(brain_dir):
        if fact["key"] in existing:
            continue
        content = f"{fact['text']} (source: {fact['source']})"
        beads.remember(content, key=fact["key"])
        pushed.append(fact)
    return pushed
