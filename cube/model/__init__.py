"""Shared data models: work kinds, labels, provenance, run results."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


class WorkKind(StrEnum):
    program = "program"
    milestone = "milestone"
    paper = "paper"
    experiment = "experiment"
    review = "review"
    audit = "audit"
    lecture = "lecture"
    course = "course"
    mentoring = "mentoring"
    meeting_note = "meeting-note"
    service = "service"
    finding = "finding"
    conflict = "conflict"
    incident = "incident"
    outbound = "outbound"


class Privacy(StrEnum):
    public = "public"
    internal = "internal"
    local_only = "local-only"


class Tier(StrEnum):
    plan = "plan"
    implement = "implement"
    bulk = "bulk"
    local = "local"
    none = "none"


class Provenance(BaseModel):
    source: str
    locator: str | None = None
    permalink: str | None = None
    message_id: str | None = None
    seen: date | None = None


class BeadHeader(BaseModel):
    """The fenced YAML header every bead description starts with."""

    xid: str
    provenance: list[Provenance] = Field(default_factory=list)
    deadline: date | None = None
    privacy: Privacy = Privacy.internal

    def render(self) -> str:
        import yaml

        payload: dict[str, Any] = self.model_dump(mode="json", exclude_none=True)
        return "---\n" + yaml.safe_dump(payload, sort_keys=False).rstrip() + "\n---\n"

    @classmethod
    def parse(cls, description: str) -> BeadHeader | None:
        import yaml

        text = description.lstrip()
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---", 4)
        if end < 0:
            return None
        try:
            data = yaml.safe_load(text[4:end])
        except yaml.YAMLError:
            return None
        if not isinstance(data, dict) or "xid" not in data:
            return None
        try:
            return cls.model_validate(data)
        except ValidationError:
            # A bead written by hand or by another tool with a malformed header
            # is treated as having no header; it must never break a ledger scan.
            return None


ESCALATION_KINDS = (
    "decision",
    "permission",
    "integrity",
    "people",
    "conflict",
    "blocked",
    "note",
)
EscalationKind = Literal[
    "decision", "permission", "integrity", "people", "conflict", "blocked", "note"
]
CRITICAL_CLASSES = ("security", "privacy")
CriticalClass = Literal["security", "privacy"]


class Escalation(BaseModel):
    """One item a run hands back. ``kind`` decides who sees it, not just Robert.

    ``decision`` is a choice that changes scope, money, people or the plan;
    ``permission`` asks for a resource; ``integrity`` reports suspected
    fabrication; ``people`` covers anything about a person; ``conflict`` a
    source conflict; ``blocked`` a tooling or input gap the group fixes; and
    ``note`` is information that closes itself.
    """

    condition: str
    to: str = "robert"
    summary: str
    kind: EscalationKind = "decision"
    options: list[str] = Field(default_factory=list)
    # Robert, 2026-09-07: he decides only what is security-critical (a change to a
    # running system, spend over budget, contact) or privacy-critical (a person's
    # data, secrets, local-only data leaving the local tier). An escalation that
    # names neither goes to the coordinator, whatever its kind.
    critical: CriticalClass | None = None


class BeadUpdate(BaseModel):
    bead: str
    comment: str | None = None
    close: bool = False
    labels_add: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    kind: str
    path: str
    summary: str | None = None
    # Full text of the artifact, for runs whose role has no Write tool. The engine
    # saves it under the run directory at ``path`` before anything reads it.
    content: str | None = None


class RunResult(BaseModel):
    """What a role run must return (validated before anything is applied)."""

    summary: str
    artifacts: list[Artifact] = Field(default_factory=list)
    bead_updates: list[BeadUpdate] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    verdict: str | None = None
    next_actions: list[str] = Field(default_factory=list)
    finished_at: datetime | None = None

    @field_validator("finished_at", mode="before")
    @classmethod
    def _lenient_finished_at(cls, value: Any) -> Any:
        # A model that writes "null" or a bare date for the timestamp has still
        # finished; two group-leader runs were discarded as invalid over this
        # field on 2026-09-08 (cube-tj0h, cube-qt48). Nothing reads it.
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.lower() in {"", "null", "none"}:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
