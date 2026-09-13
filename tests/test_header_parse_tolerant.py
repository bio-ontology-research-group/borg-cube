"""A malformed header on one bead must not break xid lookups over the ledger."""

from __future__ import annotations

from cube.model import BeadHeader


def test_parse_returns_none_for_malformed_provenance_and_bad_yaml() -> None:
    malformed = (
        "---\nxid: feature:x\nprovenance:\n  - user::conversation goal\ndeadline: null\n---\nbody"
    )
    assert BeadHeader.parse(malformed) is None
    assert BeadHeader.parse("---\nxid: [unclosed\n---\n") is None
    good = (
        "---\nxid: feature:y\nprovenance:\n  - source: cli\n    locator: test\n"
        "deadline: null\n---\n"
    )
    header = BeadHeader.parse(good)
    assert header is not None and header.xid == "feature:y"
