"""Fixtures for the skill and corpus tool tests: a tiny synthetic repo."""

# ruff: noqa: E501

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

MANIFEST = """\
# test manifest
sources:
  - id: marino2014
    type: article
    citation: "Marino J, Stefan MI, Blackford S (2014) Ten simple rules for finishing your PhD. PLoS Comput Biol 10(12): e1003954"
    doi: 10.1371/journal.pcbi.1003954
    license: CC-BY-4.0
    oa: true
    excerpt_ok: true
    topics: [doctoral-process]
    verified_by: memory
    fetched: null
    sha256: null
  - id: gu2007
    type: article
    citation: "Gu J, Bourne PE (2007) Ten simple rules for graduate students. PLoS Comput Biol 3(11): e229"
    doi: 10.1371/journal.pcbi.0030229
    license: CC-BY-4.0
    oa: true
    excerpt_ok: true
    topics: [doctoral-process]
    verified_by: memory
    fetched: null
    sha256: null
  - id: turing-way
    type: web
    citation: "The Turing Way Community, The Turing Way handbook"
    url: https://book.the-turing-way.org/
    license: CC-BY-4.0
    oa: web
    excerpt_ok: true
    topics: [reproducibility]
    verified_by: memory
    fetched: null
    sha256: null
  - id: lovitts2001
    type: book
    citation: "Lovitts BE (2001) Leaving the Ivory Tower. Rowman & Littlefield"
    license: proprietary
    oa: false
    excerpt_ok: false
    topics: [doctoral-process]
    verified_by: memory
    fetched: null
    sha256: null
    notes: corpus/notes/lovitts2001.md
  - id: nap2019-mentorship
    type: report
    citation: "National Academies (2019) The Science of Effective Mentorship in STEMM"
    doi: 10.17226/25568
    url: https://nap.nationalacademies.org/catalog/25568
    license: proprietary
    oa: true
    excerpt_ok: false
    topics: [mentoring]
    verified_by: memory
    fetched: null
    sha256: null
  - id: pineau2021
    type: article
    citation: "Pineau J et al. (2021) Improving reproducibility in machine learning research. JMLR 22"
    doi: null
    url: https://arxiv.org/abs/2003.12206
    license: CC-BY-4.0
    oa: true
    excerpt_ok: true
    topics: [reproducibility]
    verified_by: memory
    fetched: null
    sha256: null
"""

DISTILLED = """\
---
topic: doctoral-process
reviewed_by: Robert Hoehndorf
reviewed_on: 2026-09-01
---

# Doctoral process

Sources
- marino2014 (CC-BY-4.0)
- gu2007 (CC-BY-4.0)

## What the evidence says

- Finishing needs a written plan with dates [marino2014].
- Students should own their project early [gu2007].

## Rules we adopt

1. Every student has a dated milestone plan (from [marino2014]).
"""

HAND_REFERENCE = """\
# Reproducible practice

Sources
- turing-way (CC-BY-4.0; short excerpts allowed)

## What the evidence says

- Record environments and seeds [turing-way].
"""

SKILL_MD = """\
---
name: demo-skill
description: Demonstrates the fixture skill. Use when asked to "run the demo".
license: CC-BY-4.0
metadata:
  borg-role: infra           # keep this comment; sync must preserve it
  grounding: gu2007, marino2014, turing-way
  hermes:
    category: infra
    tags: demo
allowed-tools: Read
---

# Demo skill

## Procedure

1. Run `scripts/hello.py --help`.

## Grounding

- `references/doctoral-process.md`: synced topic.
- `references/reproducible.md`: hand-written reference.
"""

HELLO_PY = """\
#!/usr/bin/env python3
\"\"\"Print a greeting.\"\"\"

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", default="world")
    args = p.parse_args(argv)
    print(f"hello {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""

HELLO_TEST = """\
def test_hello_runs():
    # covers demo-skill scripts/hello.py
    assert True
"""


class SkillRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = root / "corpus" / "sources.yaml"
        self.distilled = root / "corpus" / "distilled"
        self.skills = root / "skills"
        self.tests = root / "tests" / "skills"
        self.skill = self.skills / "demo-skill"

    def write_skill_md(self, text: str) -> None:
        (self.skill / "SKILL.md").write_text(text, encoding="utf-8")

    def skill_md(self) -> str:
        return (self.skill / "SKILL.md").read_text(encoding="utf-8")


@pytest.fixture
def skill_repo(tmp_path: Path) -> SkillRepo:
    repo = SkillRepo(tmp_path)
    repo.distilled.mkdir(parents=True)
    repo.manifest.write_text(MANIFEST, encoding="utf-8")
    (repo.distilled / "doctoral-process.md").write_text(DISTILLED, encoding="utf-8")
    (repo.skill / "references").mkdir(parents=True)
    (repo.skill / "scripts").mkdir()
    repo.write_skill_md(SKILL_MD)
    (repo.skill / "references" / "manifest.txt").write_text(
        "# synced topics\ndoctoral-process\n", encoding="utf-8"
    )
    (repo.skill / "references" / "doctoral-process.md").write_text(DISTILLED, encoding="utf-8")
    (repo.skill / "references" / "reproducible.md").write_text(HAND_REFERENCE, encoding="utf-8")
    (repo.skill / "scripts" / "hello.py").write_text(HELLO_PY, encoding="utf-8")
    repo.tests.mkdir(parents=True)
    (repo.tests / "test_hello.py").write_text(HELLO_TEST, encoding="utf-8")
    return repo
