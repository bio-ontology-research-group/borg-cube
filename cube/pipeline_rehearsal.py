"""Complete offline research pipeline rehearsal using only deterministic fixtures."""

from __future__ import annotations

import io
import json
import shlex
import shutil
import stat
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads
from cube.cli import main
from cube.config import load_settings
from cube.engine.context import bead_labels, label_value
from cube.engine.marshal import tick
from cube.engine.run import execute
from cube.model import Provenance, RunResult
from cube.pipeline import (
    advance,
    ask,
    is_pipeline_epic,
    new_pipeline,
    pipeline_status,
    stage_prompt,
    write_rehearsal_search_log,
)
from cube.runners import StubRunner
from cube.testing.fakebd import FakeBd


def _copy_rehearsal_files(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "roles", target / "roles")
    (target / "agents").mkdir()
    for name in ("coordinator", "liaison", "ontology", "protein-function"):
        # The rehearsal repo is its own orchestration host ("laptop"); every
        # agent lives there, because the marshal runs an agent only where it lives.
        text = (source / "agents" / f"{name}.yaml").read_text(encoding="utf-8")
        lines = ["host: laptop" if line.startswith("host:") else line for line in text.splitlines()]
        (target / "agents" / f"{name}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (target / "agents" / name).mkdir()
        shutil.copy2(
            source / "agents" / name / "charter.md", target / "agents" / name / "charter.md"
        )
    (target / "brain").mkdir()
    shutil.copy2(source / "brain" / "doctrine.md", target / "brain" / "doctrine.md")
    # The roster is site data (gitignored); a clean checkout rehearses on the example.
    people = source / "people.yaml"
    if not people.exists():
        people = source / "people.yaml.example"
    shutil.copy2(people, target / "people.yaml")
    (target / "contacts.yaml").write_text("grants: {}\n", encoding="utf-8")
    (target / ".gitignore").write_text("runs/\nstate/\n", encoding="utf-8")
    for directory in ("runs", "state", "pa", "org", "rkg", "skills-lib", "software"):
        (target / directory).mkdir(parents=True, exist_ok=True)
    config = {
        "host": "laptop",
        "paths": {
            "pa": "pa",
            "org": "org",
            "rkg": "rkg",
            "runs": "runs",
            "state": "state",
            "skills_library": "skills-lib",
        },
        "hosts": {
            "ws": {"role": "orchestration", "ssh": "ws"},
            "laptop": {
                "role": "personal",
                "hostname": "fixture-laptop",
                "ssh": None,
                "software_dirs": [str(target / "software")],
            },
        },
        "slots": {"plan": 2, "implement": 2, "bulk": 2, "local": 1},
        "tiers": {
            "plan": [{"runner": "stub"}],
            "implement": [{"runner": "stub"}],
            "bulk": [{"runner": "stub"}],
            "local": [{"runner": "stub"}],
        },
        "budget": {
            "plan_runs_per_day": None,
            "implement_runs_per_day": None,
            "bulk_runs_per_day": None,
            "local_runs_per_day": None,
        },
        "pipeline": {
            "max_iterations": 3,
            "max_team": 6,
            "stale_hours": 24,
            "autonomy": {"recruit": "coordinator"},
        },
    }
    (target / "cube.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _install_external_fixtures(fake: FakeBd, root: Path) -> None:
    body = (
        "Compare PhysioMap with mOWL using https://github.com/borg/PhysioMap.\n\n"
        "The starting paper has DOI 10.1234/fixture and PMID at "
        "https://pubmed.ncbi.nlm.nih.gov/12345678/."
    )
    search = json.dumps([{"id": "pipeline-fixture"}])
    shown = json.dumps(
        [
            [
                [
                    {
                        "id": "pipeline-fixture",
                        "headers": {
                            "From": "Robert Hoehndorf <robert.hoehndorf@kaust.edu.sa>",
                            "Message-ID": "<pipeline-fixture@local>",
                        },
                        "body": [{"content-type": "text/plain", "content": body}],
                    },
                    [],
                ]
            ]
        ]
    )
    _script(
        fake.dir / "notmuch",
        'if [ "$1" = search ]; then\n'
        f"  printf '%s\\n' {shlex.quote(search)}\n"
        "else\n"
        f"  printf '%s\\n' {shlex.quote(shown)}\n"
        "fi\n",
    )
    _script(fake.dir / "ssh", "printf '%s\\n' '{\"delivered\": true}'\n")
    for name in ("PhysioMap", "mOWL", "time"):
        (root / "software" / name).mkdir()
    git = root / "software" / "PhysioMap" / ".git"
    git.mkdir()
    (git / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/borg/PhysioMap.git\n',
        encoding="utf-8",
    )


def _plan(path: Path, *, version: int) -> None:
    payload = {
        "plan": "pipeline-rehearsal",
        "question": "Does the fixture implementation pass its deterministic checks?",
        "provenance": [f"fixture::plan version {version}"],
        "privacy": "internal",
        "owner": "programmer",
        "deadline": "2026-12-31",
        "hypotheses": [
            {"id": "h1", "statement": "the implementation works", "predicts": "checks pass"},
            {"id": "h0", "statement": "the implementation fails", "predicts": "checks fail"},
        ],
        "experiments": [
            {
                "id": "prepare",
                "title": "Prepare the fixture",
                "baselines": ["unchanged fixture"],
                "success_threshold": "100% of fixture rows load",
                "kill_criterion": "stop if any fixture row is corrupt",
                "metric": "loaded row percentage",
                "tests": ["h1"],
                "depends_on": [],
                "acceptance": ["the fixture file exists"],
            },
            {
                "id": "evaluate",
                "title": "Evaluate the fixture",
                "baselines": ["unchanged fixture"],
                "success_threshold": "fixture score is at least 0.8",
                "kill_criterion": "stop if fixture score is below 0.2",
                "metric": "fixture score",
                "tests": ["h1", "h0"],
                "depends_on": ["prepare"],
                "acceptance": ["the result contains a score table"],
            },
        ],
        "risks": [],
        "checkpoints": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _reading_list(path: Path) -> None:
    path.write_text(
        "@article{fixture, author={Researcher, A}, title={Fixture evidence}, "
        "journal={Fixture Journal}, year={2025}, doi={10.1234/fixture}}\n",
        encoding="utf-8",
    )


def _student_for_team(root: Path) -> str:
    """First current student in the rehearsal roster, so the team names a real member."""
    from cube.sync.context import load_people

    people, _ = load_people(root / "people.yaml")
    for person in people:
        if person.is_student and not person.extra.get("pending") and person.role != "former":
            return person.id
    return "alex-example"


def _team(path: Path, student: str = "alex-example") -> None:
    payload = {
        "team": [
            {
                "member": "agent:ontology",
                "role": "senior",
                "why": "applied-ontology topic (source: agents/ontology.yaml)",
            },
            {
                "member": "role:programmer",
                "why": "implements experiments (source: roles/programmer.yaml)",
            },
            {
                "member": f"person:{student}",
                "role": "student",
                "why": "current student roster entry (source: people.yaml)",
            },
        ],
        "lead": "agent:coordinator",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _critique(path: Path, *, member: str, round_number: int) -> None:
    disagreement = (
        "Raise the success threshold to 0.9 opinion"
        if member == "ontology" and round_number == 1
        else "No threshold disagreement opinion"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "## Agree",
                "- Keep the deterministic baseline (source: plan draft)",
                "## Disagree",
                f"- {disagreement}",
                "## Missing",
                "- Add a sensitivity check (source: DOI:10.1234/fixture)",
                "## Risks",
                "- Fixture drift opinion",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _decisions(path: Path, *, round_number: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan {round_number} decisions\n\n"
        "- Accepted: add the sensitivity check because DOI:10.1234/fixture supports it.\n"
        "- Rejected: raise the threshold because it is opinion without fixture evidence.\n",
        encoding="utf-8",
    )


def _command(root: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(["--root", str(root), *argv])
    if code:
        raise RuntimeError(stderr.getvalue().strip() or stdout.getvalue().strip())
    output = stdout.getvalue().strip()
    return code, json.loads(output) if output else {}


def _answer(bead: dict[str, Any]) -> dict[str, Any]:
    description = str(bead.get("description") or "")
    marker = "\nanswer:\n"
    if marker not in description:
        return {}
    payload = yaml.safe_load("answer:\n" + description.split(marker, 1)[1])
    return dict(payload.get("answer") or {}) if isinstance(payload, dict) else {}


def run_rehearsal(source_root: Path, directory: Path) -> dict[str, Any]:
    """Run the complete fixture pipeline and return its inspectable transcript."""
    root = directory.resolve()
    _copy_rehearsal_files(source_root.resolve(), root)
    fake = FakeBd(root)
    _install_external_fixtures(fake, root)
    settings = load_settings(root)
    ledger = Beads(bin="bd", cwd=root)
    today = date(2026, 9, 3)
    transitions: list[str] = []
    dispatches: list[dict[str, Any]] = []
    ready_trace: list[dict[str, Any]] = []
    gate_verdicts: list[str] = []
    recruit_request: str | None = None

    with fake.installed():
        created = new_pipeline(
            settings,
            ledger,
            title="Pipeline rehearsal",
            target=date(2026, 12, 31),
            success=["the second pipeline gate passes"],
            question=(
                "Collect the email I sent about the fixture pipeline: extract the ideas, "
                "list the papers and the code I already have (links, DOIs, local repositories)"
            ),
            person="robert",
            provenance=[Provenance(source="fixture", locator="pipeline rehearsal instruction")],
        )
        epic_id = created["epic"]

        def dispatch(role: str, bead_id: str, tier: str) -> int:
            bead = fake.bead(bead_id)
            labels = bead_labels(bead)
            stage = label_value(labels, "pipeline-stage:") or (
                "review" if "kind:review" in labels else "work"
            )
            command = ["cube", "run", role, "--bead", bead_id, "--runner", "stub"]
            before = pipeline_status(settings, ledger, epic_id, today=today)["stage"]
            agent_name = label_value(labels, "agent:")
            actor = agent_name or role
            if agent_name:
                command = ["cube", "agent", "workday", agent_name, "--bead", bead_id]
            prompt = (
                stage_prompt(settings, fake.bead(epic_id), bead, beads=ledger)
                if stage not in {"review", "work"}
                else None
            )
            if stage == "collect":
                actor = "liaison"
                command = ["cube", "agent", "workday", "liaison", "--bead", bead_id]
                workday = [
                    "agent",
                    "workday",
                    "liaison",
                    "--now",
                    "--bead",
                    bead_id,
                    "--apply",
                    "--json",
                ]
                _command(root, *workday)
                why = "liaison collected the sent mail after Robert's yes"
            elif stage == "team":
                artifact = root / "artifacts" / "team.yaml"
                _team(artifact, _student_for_team(root))
                result = RunResult(
                    summary="fixture source-backed project team",
                    artifacts=[{"kind": "team", "path": str(artifact)}],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                    prompt_text=prompt,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = "coordinator recruited the project team"
            elif stage == "draft":
                round_number = int(label_value(labels, "planning-round:") or 1)
                artifact = root / "artifacts" / f"plan-v{round_number}-draft.yaml"
                _plan(artifact, version=round_number)
                result = RunResult(
                    summary=f"fixture plan {round_number} draft",
                    artifacts=[{"kind": "plan", "path": str(artifact)}],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                    prompt_text=prompt,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = f"validated plan {round_number} draft"
            elif stage == "critique":
                round_number = int(label_value(labels, "planning-round:") or 1)
                member = label_value(labels, "pipeline-member:") or "member"
                artifact = root / "artifacts" / f"critique-{round_number}-{member}.md"
                _critique(artifact, member=member, round_number=round_number)
                result = RunResult(
                    summary=f"fixture critique from {member}",
                    artifacts=[{"kind": "critique", "path": str(artifact)}],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                    prompt_text=prompt,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = f"recorded critique from {member}"
            elif stage == "final":
                round_number = int(label_value(labels, "planning-round:") or 1)
                plan_artifact = root / "artifacts" / f"plan-v{round_number}-final.yaml"
                decisions = root / "artifacts" / f"plan-v{round_number}-decisions.md"
                _plan(plan_artifact, version=round_number)
                _decisions(decisions, round_number=round_number)
                result = RunResult(
                    summary=f"fixture plan {round_number} final",
                    artifacts=[
                        {"kind": "plan", "path": str(plan_artifact)},
                        {"kind": "decision-log", "path": str(decisions)},
                    ],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                    prompt_text=prompt,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = f"resolved plan {round_number} discussion"
            elif stage == "recruit":
                command = [
                    "cube",
                    "pipeline",
                    "recruit",
                    epic_id,
                    "--member",
                    "agent:protein-function",
                    "--role",
                    "senior",
                    "--apply",
                ]
                _command(
                    root,
                    "pipeline",
                    "recruit",
                    epic_id,
                    "--member",
                    "agent:protein-function",
                    "--role",
                    "senior",
                    "--why",
                    "protein-function topic (source: agents/protein-function.yaml)",
                    "--apply",
                    "--json",
                )
                why = "coordinator recruited the requested expert"
            elif stage == "survey":
                artifact_dir = root / "artifacts"
                search = artifact_dir / "search-log.jsonl"
                reading = artifact_dir / "reading-list.bib"
                write_rehearsal_search_log(search, today=today)
                _reading_list(reading)
                result = RunResult(
                    summary="fixture literature survey",
                    artifacts=[
                        {"kind": "search-log", "path": str(search)},
                        {"kind": "reading-list", "path": str(reading)},
                    ],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                    prompt_text=prompt,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = "literature artifacts passed offline checks"
            elif stage == "experiments":
                result = RunResult(
                    summary="fixture implementation and checks passed",
                    bead_updates=[{"bead": bead_id, "close": True}],
                )
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(result=result),
                    beads=ledger,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = "programmer returned implementation for review"
            elif stage == "gate":
                number = int(label_value(labels, "gate:") or 1)
                verdict = "revise" if number == 1 else "approve"
                gate_verdicts.append(verdict)
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(
                        result=RunResult(
                            summary=f"fixture gate {number} verdict {verdict}", verdict=verdict
                        )
                    ),
                    beads=ledger,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = f"gate {number} returned {verdict}"
            elif "kind:review" in labels:
                report = execute(
                    settings,
                    role,
                    bead=bead_id,
                    runner_name="stub",
                    runner=StubRunner(
                        result=RunResult(summary="fixture review approved", verdict="approve")
                    ),
                    beads=ledger,
                )
                if not report.ok:
                    raise RuntimeError(report.error or report.state)
                why = "senior approved the implementation"
            else:
                raise RuntimeError(f"unexpected rehearsal bead {bead_id}: {sorted(labels)}")
            after = pipeline_status(settings, ledger, epic_id, today=today)["stage"]
            dispatches.append(
                {
                    "bead": bead_id,
                    "role": role,
                    "tier": tier,
                    "stage": stage,
                    "command": command,
                    "via": "marshal.tick",
                }
            )
            transitions.append(f"{before} -> {after} ({actor}, {why})")
            return len(dispatches) + 1000

        for _pass in range(60):
            status_before = pipeline_status(settings, ledger, epic_id, today=today)
            if status_before["status"] == "done":
                break
            # Robert, 2026-09-08 (ADR-0027): the mail read waits for his yes; the
            # rehearsal answers it the way his Mattermost reply would.
            for item in ledger.list_issues("--all"):
                item_labels = bead_labels(item)
                if (
                    "laptop-read:approval" in item_labels
                    and "needs:robert" in item_labels
                    and str(item.get("status") or "open") not in {"closed", "done"}
                ):
                    _command(
                        root, "decide", str(item["id"]), "--choice", "yes", "--apply", "--json"
                    )
                    transitions.append(f"collect: Robert approved the laptop read ({item['id']})")
            ready = ledger.ready()
            ready_trace.append(
                {
                    "pass": _pass + 1,
                    "ready": [str(item.get("id")) for item in ready],
                    "ready_stages": [
                        label_value(bead_labels(item), "pipeline-stage:")
                        or ("review" if "kind:review" in bead_labels(item) else "work")
                        for item in ready
                        if not is_pipeline_epic(item)
                    ],
                }
            )
            dispatched = tick(
                settings,
                ledger,
                slots={"plan": 2, "implement": 2, "bulk": 2, "local": 1},
                dry_run=False,
                dispatch=dispatch,
                host="laptop",
            )
            before_advance = pipeline_status(settings, ledger, epic_id, today=today)
            moved = advance(settings, ledger, epic_id, today=today, dry_run=False)
            after_advance = pipeline_status(settings, ledger, epic_id, today=today)
            if (
                recruit_request is None
                and after_advance["stage"] == "plan2:draft"
                and any(
                    "planning-round:2" in bead_labels(item) for item in ledger.list_issues("--all")
                )
            ):
                requested = ask(
                    settings,
                    ledger,
                    epic_id,
                    from_member="agent:ontology",
                    to_member="agent:protein-function",
                    text="Help assess the protein-function interpretation",
                    dry_run=False,
                )
                recruit_request = requested["recruit_request"]
                transitions.append(
                    "plan2:draft -> plan2:draft (ontology, requested recruitment of "
                    "protein-function)"
                )
            if before_advance["stage"] != after_advance["stage"]:
                reason = (
                    "gate passed"
                    if after_advance["stage"] == "done"
                    else "deterministic stage transition"
                )
                transitions.append(
                    f"{before_advance['stage']} -> {after_advance['stage']} "
                    f"(pipeline patrol, {reason})"
                )
            if not dispatched.dispatched and not any(
                moved[key] for key in ("created", "closed", "flagged")
            ):
                raise RuntimeError(f"pipeline rehearsal stalled at {after_advance['stage']}")
        final = pipeline_status(settings, ledger, epic_id, today=today)
        collect = fake.bead(created["stages"]["collect"])
        liaison_answer = _answer(collect)
        followups = [
            str(item.get("id"))
            for item in fake.beads().values()
            if any(label.startswith("revises:") for label in bead_labels(item))
        ]

    exit_code = 0 if final["status"] == "done" and final["gate"]["n"] == 2 else 1
    return {
        "exit_code": exit_code,
        "epic": epic_id,
        "transitions": transitions,
        "status": final,
        "dispatches": dispatches,
        "ready_trace": ready_trace,
        "gate_verdicts": gate_verdicts,
        "follow_ups": followups,
        "liaison_answer": liaison_answer,
        "recruit_request": recruit_request,
    }
