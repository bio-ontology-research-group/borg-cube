"""``cube literature --json``: today's literature digest for the cockpit."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, now_iso, today_from
from cube.config import Settings
from cube.literature import literature_payload, literature_text


def cmd_literature(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    today = today_from(args) or date.today()
    payload = literature_payload(settings, today)
    payload["generated"] = now_iso()
    helpers.emit(args, payload, literature_text(payload))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("literature", help="today's arXiv and bioRxiv digest for the group")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_literature(a, s, helpers))
