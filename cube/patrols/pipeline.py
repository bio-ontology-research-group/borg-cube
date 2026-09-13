"""Patrol that advances every open deterministic research pipeline once."""

from __future__ import annotations

from datetime import date

from cube.beads import Beads
from cube.config import Settings
from cube.patrols.base import PatrolReport, attention_event, register
from cube.pipeline import advance, list_pipeline_epics


class PipelinePatrol:
    name = "pipeline"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ledger = beads or Beads(
            bin=settings.beads.bin,
            cwd=settings.root,
            dry_run=dry_run,
            actor="cube/pipeline",
        )
        if dry_run:
            ledger.dry_run = True
        report = PatrolReport(self.name, today, dry_run)
        epics = list_pipeline_epics(ledger, open_only=True)
        transitions: dict[str, dict[str, object]] = {}
        for epic in epics:
            epic_id = str(epic.get("id") or "")
            result = advance(settings, ledger, epic_id, today=today, dry_run=dry_run)
            transitions[epic_id] = result
            if result["flagged"]:
                report.events.append(
                    attention_event(
                        self.name,
                        f"Research pipeline {epic_id} needs Robert",
                        body=f"stage {result['stage']}, iteration {result['iteration']}",
                        xid=f"pipeline-attention:{epic_id}",
                        data={"epic": epic_id, "flagged": result["flagged"]},
                    )
                )
        report.data["pipelines"] = transitions
        report.summary = f"advanced {len(epics)} open research pipeline(s)"
        return report


register(PipelinePatrol, "pipeline")
