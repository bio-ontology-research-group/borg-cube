"""Which running system a text names (ADR-0027).

Robert, 2026-09-08: he approves a change to a running system and a laptop read
outside the readable directories, nothing else. ``decisions.systems`` in
``cube.yaml`` lists those systems by host name or domain; a bead, approval or
escalation that names one of them, as a whole word, is his.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_CACHE: dict[tuple[str, ...], re.Pattern[str]] = {}


def _pattern(systems: tuple[str, ...]) -> re.Pattern[str]:
    if systems not in _CACHE:
        alternatives = "|".join(re.escape(name) for name in systems)
        # Word boundaries fail on names that start or end with a dot; the lookarounds
        # accept any non-word neighbour, so `leechuck.de.` and `(ws)` match.
        _CACHE[systems] = re.compile(
            rf"(?<![A-Za-z0-9_-])(?:{alternatives})(?![A-Za-z0-9_-])", re.IGNORECASE
        )
    return _CACHE[systems]


def names_system(systems: Iterable[str], *texts: str | None) -> str | None:
    """The first configured system one of TEXTS names, or None."""
    names = tuple(name for name in systems if name)
    if not names:
        return None
    pattern = _pattern(names)
    lowered = {name.lower(): name for name in names}
    for text in texts:
        if not text:
            continue
        match = pattern.search(text)
        if match:
            return lowered.get(match.group(0).lower(), match.group(0))
    return None
