"""Auto-discovered CLI command modules.

Every module in this package may define ``register(sub, helpers)`` where ``sub`` is the
top-level ``argparse`` subparsers object and ``helpers`` offers ``add_json``, ``add_dry``,
``emit`` and ``beads``. Modules are imported in name order; a module that fails to import
is reported on stderr and skipped so one broken command never takes down the CLI.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cube.beads import Beads
from cube.config import Settings


@dataclass
class Helpers:
    add_json: Callable[[argparse.ArgumentParser], None]
    add_dry: Callable[[argparse.ArgumentParser], None]
    emit: Callable[[argparse.Namespace, Any, str | None], None]
    beads: Callable[[Settings, bool], Beads]
    command_names: Callable[[], list[str]]


def register_all(sub: Any, helpers: Helpers) -> list[str]:
    loaded: list[str] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # noqa: BLE001 - keep the CLI alive
            print(f"cube: could not load command module {info.name}: {exc}", file=sys.stderr)
            continue
        reg = getattr(mod, "register", None)
        if callable(reg):
            reg(sub, helpers)
            loaded.append(info.name)
    return loaded
