"""Deterministic sentinel patrols. Importing this package registers every patrol.

Each module below calls ``cube.patrols.base.register`` at import time, so the CLI
(``cube patrol``) and ``run_many`` only need one import to see the full registry.
Module-level options (``--only``, ``--refresh-context``) are passed through
``cube.patrols.base.make`` by the command layer.
"""

from __future__ import annotations

from cube.patrols import (  # noqa: F401 - import for registration side effects
    agent_workdays,
    budget,
    calendar,
    cursors,
    data_pull,
    deadlines,
    decisions,
    deliveries,
    goals,
    infra,
    infra_hygiene,
    infra_incidents,
    leases,
    literature_watch,
    mattermost_events,
    milestones,
    papers,
    pipeline,
    repos,
    student_digest,
    triage,
)
from cube.patrols.base import Finding as Finding
from cube.patrols.base import Patrol as Patrol
from cube.patrols.base import PatrolReport as PatrolReport
from cube.patrols.base import killed as killed
from cube.patrols.base import make as make
from cube.patrols.base import names as names
from cube.patrols.base import run_many as run_many
from cube.patrols.base import run_patrol as run_patrol
