from __future__ import annotations

import json

import yaml

from cube.cli import main
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())


def test_kg_propose_writes_patch_and_approval_bead_without_touching_kg(
    engine_repo, fake_bd: FakeBd, capsys
) -> None:
    kg = engine_repo / "rkg" / "projects.jsonld"
    before = kg.read_bytes()

    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "kg",
                "propose",
                "test-project",
                "--set",
                "borg:status=active",
                "--add-member",
                "alex-example",
                "--note",
                "Review at the next project meeting",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    patch = engine_repo / payload["patch"]
    assert kg.read_bytes() == before
    assert patch.exists() and "borg:status" in patch.read_text(encoding="utf-8")
    assert payload["bead"]
    approval = fake_bd.bead(payload["bead"])
    assert {"kind:outbound", "needs:robert", "project:test-project"} <= set(approval["labels"])
    header = yaml.safe_load(approval["description"].split("---", 2)[1])
    assert header["provenance"][0]["source"] == str(kg)
    assert "Evidence: runs/kg/" in approval["description"]
