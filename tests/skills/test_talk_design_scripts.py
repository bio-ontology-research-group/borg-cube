"""Tests for the talk-design deck linter and selected-frame renderer."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "talk-design"
LINTER = SKILL / "scripts" / "slide_lint.py"
RENDERER = SKILL / "scripts" / "frames_to_png.sh"


def load_linter():
    spec = importlib.util.spec_from_file_location("talk_design_slide_lint", LINTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_slide_lint_accepts_a_credited_markdown_deck(tmp_path: Path, capsys) -> None:
    slide_lint = load_linter()
    deck = tmp_path / "talk.md"
    deck.write_text(
        "<!-- slide: 1 -->\n"
        "# The treatment reduces mortality in the test cohort\n\n"
        "![Kaplan-Meier curves compare treated and control cohorts.](survival.png)\n"
        "Source: Doe et al. (2026), Figure 2.\n\n"
        "---\n\n"
        "<!-- slide: 2 -->\n"
        "# The effect remains after adjustment for baseline risk\n\n"
        "![Adjusted model estimates remain below one.](model.png)\n"
        "Source: Doe et al. (2026), Figure 3.\n",
        encoding="utf-8",
    )

    assert slide_lint.main([str(deck)]) == 0
    assert "slide-lint: 0 error(s), 0 warning(s)" in capsys.readouterr().out

    assert slide_lint.main([str(deck), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == {"errors": 0, "warnings": 0}
    assert report["thresholds"]["max_slide_words"] == 40


def test_slide_lint_reports_errors_and_density_warnings(tmp_path: Path) -> None:
    slide_lint = load_linter()
    deck = tmp_path / "bad.md"
    deck.write_text(
        "<!-- slide: 1 -->\n"
        "# Results\n\n"
        "- this bullet contains far too many words to fit on a focused evidence slide today\n"
        "- two\n- three\n- four\n- five\n"
        "![ ](plot.png)\n"
        "This line contains an em" + "\u2014" + "dash.\n\n"
        "---\n\n"
        "# The Model Shows A Large Effect\n"
        "Body words stay brief.\n",
        encoding="utf-8",
    )

    issues = slide_lint.lint(deck, max_bullets=4, max_bullet_words=12, max_slide_words=40)
    rules = {issue.rule for issue in issues}
    assert {
        "assertion-title",
        "figure-caption",
        "figure-source",
        "em-dash",
        "slide-number",
    } <= rules
    assert {"bullet-count", "bullet-words", "sentence-case"} <= rules
    assert all(issue.path == str(deck) and issue.line > 0 and issue.fix for issue in issues)
    assert slide_lint.main([str(deck)]) == 1


def test_slide_lint_accepts_a_credited_beamer_deck(tmp_path: Path) -> None:
    slide_lint = load_linter()
    deck = tmp_path / "talk.tex"
    deck.write_text(
        "\\documentclass{beamer}\n"
        "\\setbeamertemplate{footline}{\\hfill\\insertframenumber}\n"
        "\\begin{document}\n"
        "\\begin{frame}{The treatment reduces mortality in the test cohort}\n"
        "\\includegraphics{survival.pdf}\n"
        "\\caption{Kaplan-Meier curves compare treated and control cohorts.}\n"
        "{\\tiny Source: Doe et al. (2026), Figure 2.}\n"
        "\\end{frame}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    assert slide_lint.main([str(deck)]) == 0


def write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_frames_to_png_is_dry_by_default_and_renders_with_tools(tmp_path: Path) -> None:
    source = tmp_path / "talk.tex"
    source.write_text("\\documentclass{beamer}\n", encoding="utf-8")
    out = tmp_path / "frames"

    help_result = subprocess.run(["bash", str(RENDERER), "--help"], capture_output=True, text=True)
    assert help_result.returncode == 0 and "--frames" in help_result.stdout

    dry_run = subprocess.run(
        ["bash", str(RENDERER), str(source), "--frames", "1,3-4", "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert dry_run.returncode == 0 and "[dry-run] latexmk" in dry_run.stdout
    assert not out.exists()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    write_executable(
        fake_bin / "latexmk",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in -outdir=*) out=${arg#-outdir=};; esac\n'
        "done\n"
        "source=${!#}\n"
        'base=$(basename "$source")\n'
        'touch "$out/${base%.*}.pdf"\n',
    )
    write_executable(
        fake_bin / "pdftoppm",
        '#!/usr/bin/env bash\nset -eu\nprefix=${!#}\ntouch "$prefix.png"\n',
    )
    environment = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    rendered = subprocess.run(
        ["bash", str(RENDERER), str(source), "--frames", "1,3", "--out", str(out), "--apply"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert (out / "frame-001.png").is_file() and (out / "frame-003.png").is_file()

    repeated = subprocess.run(
        ["bash", str(RENDERER), str(source), "--frames", "1", "--out", str(out), "--apply"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert repeated.returncode == 2 and "refusing to overwrite" in repeated.stderr
