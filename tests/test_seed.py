from pathlib import Path

from cube.config import load_settings
from cube.seed import discover, read_frontmatter, write_index


def test_discover_and_index(repo: Path) -> None:
    lib = repo / "skills-lib" / "local" / "demo"
    lib.mkdir(parents=True)
    (lib / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill.\n---\nbody\n", encoding="utf-8"
    )
    (repo / "cube.yaml").write_text(
        "host: t\npaths:\n  pa: pa\n  org: org\n  skills_library: skills-lib\n  infra: infra\n",
        encoding="utf-8",
    )
    s = load_settings(repo)
    sources = discover(s)
    skills = [x for x in sources if x.kind == "skill"]
    assert any(x.name == "demo" and x.description == "Demo skill." for x in skills)
    assert any(x.kind == "skill-dir" and not x.exists for x in sources)
    out = repo / "skills" / "seeded" / "discovered.yaml"
    write_index(sources, out)
    assert "demo" in out.read_text(encoding="utf-8")


def test_read_frontmatter_bad(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text("no frontmatter", encoding="utf-8")
    assert read_frontmatter(f) == {}
    assert read_frontmatter(tmp_path / "missing.md") == {}
