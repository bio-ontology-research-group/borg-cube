from datetime import date
from pathlib import Path

from cube.beads import Beads, _as_list
from cube.model import BeadHeader, Provenance


def test_header_roundtrip() -> None:
    h = BeadHeader(
        xid="milestone:alex-example:phd-defense",
        deadline=date(2026, 12, 31),
        provenance=[
            Provenance(
                source="~/org/staff.org", locator="** Alex / Graduates", seen=date(2026, 9, 2)
            )
        ],
    )
    text = h.render() + "\nbody text"
    parsed = BeadHeader.parse(text)
    assert parsed is not None
    assert parsed.xid == h.xid and parsed.deadline == h.deadline
    assert parsed.provenance[0].locator == "** Alex / Graduates"
    assert BeadHeader.parse("no header") is None


def test_create_dry_run_builds_command(tmp_path: Path) -> None:
    b = Beads(bin="bd", cwd=tmp_path, dry_run=True, actor="cube")
    h = BeadHeader(xid="paper:test", deadline=date(2026, 10, 1))
    assert (
        b.create(
            "Title",
            header=h,
            labels=["kind:paper", "person:x"],
            parent="cube-1",
            deps=["blocks:cube-2"],
        )
        is None
    )
    cmd = b.log[-1]
    assert cmd[:2] == ["bd", "create"]
    assert "--external-ref" in cmd and cmd[cmd.index("--external-ref") + 1] == "paper:test"
    assert cmd[cmd.index("--labels") + 1] == "kind:paper,person:x"
    assert cmd[cmd.index("--due") + 1] == "2026-10-01"
    assert cmd[cmd.index("--parent") + 1] == "cube-1"
    assert cmd[-2:] == ["--actor", "cube"]


def test_as_list_shapes() -> None:
    assert _as_list(None) == []
    assert _as_list({"issues": [{"id": 1}]}) == [{"id": 1}]
    assert _as_list([{"id": 2}]) == [{"id": 2}]
    assert _as_list({"id": 3}) == [{"id": 3}]
