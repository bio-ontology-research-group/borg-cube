"""Critique checks accept real model output: wrapped items and mid-sentence sources."""

from __future__ import annotations

from cube.pipeline import _critique_errors, _critique_items

WRAPPED = """# Critique

## Agree
- The staged solver is the right first experiment (plan lines 286,
  294 to 310).

## Disagree
- Effort for e3 and e4 does not fit the window between 2026-10-30 and
  2026-11-15 (OPEN_ITEMS.md C2). opinion

## Missing
1. No owner for the B3 soundness sketch. Opinion.

## Risks
- Licensing before benchmark files land in the physiomap checkout (source: OPEN_ITEMS A3)
- This one has nothing behind it at all
"""


def test_wrapped_items_are_joined_and_sources_found_anywhere() -> None:
    items = _critique_items(WRAPPED)
    assert len(items) == 5
    assert items[0].endswith("294 to 310).")
    errors = _critique_errors(WRAPPED)
    assert len(errors) == 1
    assert "nothing behind it" in errors[0]


def test_missing_sections_are_reported() -> None:
    errors = _critique_errors("## Agree\n- fine (source: x)\n")
    assert {e for e in errors if "missing" in e} == {
        "critique is missing the Disagree section",
        "critique is missing the Missing section",
        "critique is missing the Risks section",
    }
