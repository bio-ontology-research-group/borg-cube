"""`cube` command-line entry point.

Read commands support --json; write commands default to --dry-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from cube import __version__
from cube.beads import Beads
from cube.config import HermesProfile, Settings, load_settings
from cube.contact import ContactPolicy


def _emit(args: argparse.Namespace, data: Any, text: str | None = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    else:
        print(
            text
            if text is not None
            else json.dumps(data, ensure_ascii=False, indent=1, default=str)
        )


def _beads(settings: Settings, dry_run: bool) -> Beads:
    return Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run, actor="cube")


# --- commands ----------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    from cube.doctor import run_all, summarize

    checks = run_all(settings)
    if args.cockpit:
        from cube.commands.doctor_cockpit import cockpit_check

        checks.append(cockpit_check(settings.root, args.host or settings.host))
    errors, warns = summarize(checks)
    if args.json:
        _emit(args, {"checks": [c.as_dict() for c in checks], "errors": errors, "warnings": warns})
    else:
        for c in checks:
            mark = (
                "ok "
                if c.ok
                else (
                    "WARN" if c.severity == "warn" else ("info" if c.severity == "info" else "FAIL")
                )
            )
            print(f"[{mark}] {c.name}: {c.detail}")
        print(f"\n{errors} error(s), {warns} warning(s)")
    return 1 if errors else 0


def cmd_contact(args: argparse.Namespace, settings: Settings) -> int:
    policy = ContactPolicy(settings.root / "contacts.yaml")
    if args.contact_cmd == "check":
        decision = policy.check(args.person, args.channel, args.action)
        _emit(
            args,
            decision.as_dict(),
            f"{'ALLOW' if decision.allowed else 'DENY'}: {decision.reason}",
        )
        return 0 if decision.allowed else 3
    if args.contact_cmd == "list":
        _emit(
            args,
            {"grants": policy.grants},
            "\n".join(f"{p}: {list(c)}" for p, c in policy.grants.items())
            or "no grants (default deny)",
        )
        return 0
    if args.contact_cmd == "grant":
        expires = date.fromisoformat(args.expires) if args.expires else None
        entry = policy.grant(
            args.person, args.channel, args.scope, expires=expires, evidence=args.evidence
        )
        if args.dry_run:
            _emit(
                args,
                {"dry_run": True, "person": args.person, "channel": args.channel, "grant": entry},
                f"DRY-RUN would grant {args.person}/{args.channel}: {entry}",
            )
        else:
            policy.save()
            _emit(
                args,
                {"person": args.person, "channel": args.channel, "grant": entry},
                f"granted {args.person}/{args.channel}: {entry}",
            )
        return 0
    if args.contact_cmd == "revoke":
        removed = policy.revoke(args.person, args.channel)
        if not args.dry_run and removed:
            policy.save()
        _emit(
            args,
            {"removed": removed, "dry_run": args.dry_run},
            f"{'DRY-RUN ' if args.dry_run else ''}revoked={removed}",
        )
        return 0 if removed else 3
    if args.contact_cmd == "allowlist":
        users = policy.allowed_users(args.channel)
        _emit(args, {"channel": args.channel, "people": users}, ",".join(users))
        return 0
    return 2


def cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    from cube.seed import discover, write_index

    sources = discover(settings)
    missing = [s for s in sources if not s.exists]
    out = settings.root / "skills" / "seeded" / "discovered.yaml"
    if not args.dry_run:
        write_index(sources, out)
    if args.json:
        _emit(
            args,
            {
                "sources": [s.as_dict() for s in sources],
                "written": None if args.dry_run else str(out),
            },
        )
    else:
        for s in sources:
            flag = "" if s.exists else " (MISSING)"
            print(f"{s.kind:9} {s.name:32} {s.path}{flag}")
        print(
            f"\n{len(sources)} sources, {len(missing)} missing; {'dry-run, nothing written' if args.dry_run else f'index written to {out}'}"  # noqa: E501
        )
    return 0


def cmd_brain(args: argparse.Namespace, settings: Settings) -> int:
    from cube.brain import load_facts, push

    brain_dir = settings.root / "brain"
    if args.brain_cmd == "list":
        facts = load_facts(brain_dir)
        _emit(args, {"facts": facts}, "\n".join(f"{f['key']}: {f['text'][:100]}" for f in facts))
        return 0
    if args.brain_cmd == "push":
        beads = _beads(settings, dry_run=args.dry_run)
        pushed = push(beads, brain_dir)
        _emit(
            args,
            {"pushed": pushed, "dry_run": args.dry_run, "commands": beads.log},
            f"{'DRY-RUN ' if args.dry_run else ''}pushed {len(pushed)} fact(s)",
        )
        return 0
    return 2


def cmd_hermes(args: argparse.Namespace, settings: Settings) -> int:
    from cube.hermes import allowlist, render_profile

    if args.hermes_cmd == "render":
        profile_dir = settings.root / "hermes" / "profiles" / args.profile
        if not profile_dir.exists():
            print(f"no such profile template: {profile_dir}", file=sys.stderr)
            return 2
        policy = ContactPolicy(settings.root / "contacts.yaml")
        people_path = settings.root / "people.yaml"
        mm_users: dict[str, str] = {}
        if people_path.exists():
            import yaml

            people = yaml.safe_load(people_path.read_text(encoding="utf-8")) or {}
            for pid, rec in (people.get("people") or people or {}).items():
                if isinstance(rec, dict) and rec.get("mattermost_id"):
                    mm_users[pid] = str(rec["mattermost_id"])
        values = {
            "PROFILE": args.profile,
            "CUBE_ROOT": str(settings.root),
            "VLLM_BASE_URL": settings.env.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
            "MATTERMOST_URL": settings.env.get("MATTERMOST_URL", "https://borg.bio2vec.net"),
            "MATTERMOST_ALLOWED_USERS": ",".join(allowlist(policy, mm_users)),
            "MATTERMOST_HOME_CHANNEL": (
                settings.hermes.profiles.get(args.profile, HermesProfile()).home_channel or ""
            ),
        }
        out_dir = (
            Path(args.out).expanduser()
            if args.out
            else settings.dirs["hermes_home"] / "profiles" / args.profile
        )
        written = render_profile(profile_dir, values, out_dir, dry_run=args.dry_run)
        _emit(
            args,
            {
                "profile": args.profile,
                "out_dir": str(out_dir),
                "files": [str(w) for w in written],
                "dry_run": args.dry_run,
                "allowed_users": values["MATTERMOST_ALLOWED_USERS"],
            },
            f"{'DRY-RUN ' if args.dry_run else ''}render {args.profile} -> {out_dir}: {[w.name for w in written]}; allowed users: {values['MATTERMOST_ALLOWED_USERS'] or '(none)'}",  # noqa: E501
        )
        return 0
    return 2


def cmd_systemd(args: argparse.Namespace, settings: Settings) -> int:
    from cube.systemd_units import install

    target = Path("~/.config/systemd/user").expanduser()
    actions = install(
        settings.root / "systemd", target, apply=not args.dry_run, enable_timers=args.enable
    )
    _emit(args, {"actions": actions, "dry_run": args.dry_run}, "\n".join(actions))
    return 0


def cmd_notify(args: argparse.Namespace, settings: Settings) -> int:
    from cube.notify import append_event, event_from_claude_hook, make_event, read_hook_stdin

    if args.hook:
        event = event_from_claude_hook(read_hook_stdin(), session=args.session)
    else:
        event = make_event(
            args.kind,
            source="cube",
            session=args.session or "cube",
            title=args.title or args.kind,
            body=args.body or None,
        )
    written = append_event(settings.state_dir(), event)
    if args.json:
        _emit(args, written)
    return 0


def _sessions(settings: Settings) -> list[dict[str, Any]]:
    try:
        from cube.engine.fleet import fleet

        return list(fleet(settings).get("sessions", []))
    except Exception:  # noqa: BLE001 - status must never fail because of fleet probing
        return []


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    beads = _beads(settings, dry_run=True)
    data = {
        "version": __version__,
        "host": settings.host,
        "root": str(settings.root),
        "beads": beads.available(),
        "sessions": _sessions(settings),
        "kill": (settings.state_dir() / "KILL").exists(),
    }
    _emit(
        args,
        data,
        f"cube {__version__} on {settings.host}; beads={'yes' if data['beads'] else 'no'}; kill={'ON' if data['kill'] else 'off'}",  # noqa: E501
    )
    return 0


def cmd_kill(args: argparse.Namespace, settings: Settings) -> int:
    kill = settings.state_dir() / "KILL"
    if args.kill_cmd == "on":
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text(f"paused by cube kill on {date.today().isoformat()}\n", encoding="utf-8")
        print("KILL set: patrols, workers and gateways stop at next tick")
    elif args.kill_cmd == "off":
        if kill.exists():
            kill.unlink()
        print("KILL cleared")
    else:
        print("ON" if kill.exists() else "off")
    return 0


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cube", description="borg-cube orchestration CLI")
    p.add_argument("--root", type=Path, help="repo root (default: $CUBE_ROOT or discovered)")
    p.add_argument("--version", action="version", version=f"cube {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_json(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--json", action="store_true", help="machine-readable output")

    def add_dry(sp: argparse.ArgumentParser) -> None:
        g = sp.add_mutually_exclusive_group()
        g.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=True,
            help="(default) show what would change",
        )
        g.add_argument("--apply", dest="dry_run", action="store_false", help="actually write")

    sp = sub.add_parser("doctor", help="check environment, auth, paths, policy")
    sp.add_argument(
        "--cockpit", action="store_true", help="compare this checkout with cockpit host"
    )
    sp.add_argument("--host", help="cockpit backend host (defaults to cube.yaml host)")
    add_json(sp)
    sp.set_defaults(fn=cmd_doctor)
    sp = sub.add_parser("status", help="orchestrator status")
    add_json(sp)
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("contact", help="outbound-contact grants (default deny)")
    cs = sp.add_subparsers(dest="contact_cmd", required=True)
    c = cs.add_parser("check")
    c.add_argument("person")
    c.add_argument("channel")
    c.add_argument("action")
    add_json(c)
    c = cs.add_parser("list")
    add_json(c)
    c = cs.add_parser("grant")
    c.add_argument("person")
    c.add_argument("channel")
    c.add_argument("--scope", nargs="+", required=True)
    c.add_argument("--expires")
    c.add_argument("--evidence")
    add_json(c)
    add_dry(c)
    c = cs.add_parser("revoke")
    c.add_argument("person")
    c.add_argument("--channel")
    add_json(c)
    add_dry(c)
    c = cs.add_parser("allowlist")
    c.add_argument("--channel", default="mattermost_dm")
    add_json(c)
    sp.set_defaults(fn=cmd_contact)

    sp = sub.add_parser("seed", help="index existing skills, doctrine and memory (no copies)")
    add_json(sp)
    add_dry(sp)
    sp.set_defaults(fn=cmd_seed)

    sp = sub.add_parser("brain", help="doctrine facts")
    bs = sp.add_subparsers(dest="brain_cmd", required=True)
    b = bs.add_parser("list")
    add_json(b)
    b = bs.add_parser("push")
    add_json(b)
    add_dry(b)
    sp.set_defaults(fn=cmd_brain)

    sp = sub.add_parser("hermes", help="Hermes profile rendering")
    hs = sp.add_subparsers(dest="hermes_cmd", required=True)
    h = hs.add_parser("render")
    h.add_argument("profile")
    h.add_argument("--out")
    add_json(h)
    add_dry(h)
    sp.set_defaults(fn=cmd_hermes)

    sp = sub.add_parser("systemd", help="systemd user units")
    ss = sp.add_subparsers(dest="systemd_cmd", required=True)
    s = ss.add_parser("install")
    s.add_argument("--enable", action="store_true")
    add_json(s)
    add_dry(s)
    sp.set_defaults(fn=cmd_systemd)

    sp = sub.add_parser("notify", help="append an event for the cockpit")
    sp.add_argument(
        "--hook", action="store_true", help="read a Claude Code hook payload from stdin"
    )
    sp.add_argument(
        "--kind",
        default="notification",
        help="start|prompt|stop|notification|end|attention|finished|error|approval",
    )
    sp.add_argument("--session")
    sp.add_argument("--title")
    sp.add_argument("--body")
    add_json(sp)
    sp.set_defaults(fn=cmd_notify)

    sp = sub.add_parser("kill", help="kill switch")
    sp.add_argument("kill_cmd", nargs="?", choices=["on", "off", "status"], default="status")
    sp.set_defaults(fn=cmd_kill)

    from cube.commands import Helpers, register_all

    register_all(
        sub,
        Helpers(
            add_json=add_json,
            add_dry=add_dry,
            emit=_emit,
            beads=_beads,
            command_names=lambda: sorted(sub.choices),
        ),
    )
    return p


SHOW_ALIASES = {
    ("runs", "show"): "run-show",
    ("approvals", "show"): "approval-show",
    ("beads", "show"): "bead-show",
}


def _rewrite_show(argv: list[str]) -> list[str]:
    """Map `cube runs show ID` style invocations onto the flat show commands."""
    for i in range(len(argv) - 1):
        key = (argv[i], argv[i + 1])
        if key in SHOW_ALIASES:
            return argv[:i] + [SHOW_ALIASES[key]] + argv[i + 2 :]
    return argv


USER_BIN_DIRS = (".local/bin", ".cargo/bin")


def ensure_user_bin_on_path(environ: dict[str, str] | None = None) -> str:
    """Prepend the user's bin directories to PATH when they are missing.

    The cockpit reaches ws through a non-login ssh shell whose PATH has no
    ~/.local/bin, so ``bd`` (and claude, codex, uv) were not found and every
    ledger read came back empty: no goals, no ready beads, "host lacks: beads".
    """
    env = os.environ if environ is None else environ
    current = env.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    missing = [
        str(Path.home() / rel)
        for rel in USER_BIN_DIRS
        if (Path.home() / rel).is_dir() and str(Path.home() / rel) not in parts
    ]
    if missing:
        env["PATH"] = os.pathsep.join(missing + parts)
    return env.get("PATH", "")


def main(argv: list[str] | None = None) -> int:
    from cube.config import clean_github_environment

    environment = dict(os.environ)
    clean_github_environment(environment)
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if key not in environment:
            os.environ.pop(key, None)
    ensure_user_bin_on_path()
    parser = build_parser()
    args = parser.parse_args(_rewrite_show(list(argv if argv is not None else sys.argv[1:])))
    settings = load_settings(args.root.expanduser().resolve() if args.root else None)
    return int(args.fn(args, settings))


if __name__ == "__main__":
    sys.exit(main())
