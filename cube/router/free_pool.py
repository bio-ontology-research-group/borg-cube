"""The free pool: OpenRouter's free endpoints, discovered daily, for open-data runs only.

Robert, 2026-09-07: almost every free endpoint trains on prompts, and OpenRouter's
public API exposes no data-policy field, so the cube cannot tell the safe ones
apart. It does not need to: the request-level ``provider.data_collection`` flag
makes OpenRouter enforce the policy (``deny`` for every private run, ``allow`` for
an open-data run), and this pool decides which models an open-data run tries
first. The budget patrol refreshes the catalogue once a day into
``state/cache/openrouter-models.json``; the router reads the ``free`` list from
there. A model that fails backs off on its own target like any other entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.config import Settings

POOL_SIZE = 6
STALE_AFTER = timedelta(days=3)


@dataclass(frozen=True)
class FreeModel:
    id: str
    context_length: int = 0
    tools: bool = False
    structured: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "context_length": self.context_length,
            "tools": self.tools,
            "structured": self.structured,
        }


def cache_path(settings: Settings) -> Path:
    return settings.state_dir() / "cache" / "openrouter-models.json"


def free_models_from_catalogue(payload: object) -> list[FreeModel]:
    """Free entries of an OpenRouter ``/api/v1/models`` payload, with what they support."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    out: list[FreeModel] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        pricing = item.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {}
        try:
            prompt = float(pricing.get("prompt") or 0)
            completion = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            prompt = completion = 1.0
        zero = prompt == 0 and completion == 0
        if not model_id.endswith(":free") or not zero:
            continue
        params = item.get("supported_parameters")
        supported = {str(x) for x in params} if isinstance(params, list) else set()
        try:
            context = int(item.get("context_length") or 0)
        except (TypeError, ValueError):
            context = 0
        out.append(
            FreeModel(
                id=model_id,
                context_length=context,
                tools="tools" in supported,
                structured=bool({"response_format", "structured_outputs"} & supported),
            )
        )
    return out


def rank(models: list[FreeModel]) -> list[FreeModel]:
    """Structured-output and tool support first, then the largest context."""
    return sorted(models, key=lambda m: (not m.structured, not m.tools, -m.context_length, m.id))


def load_pool(settings: Settings, *, now: datetime | None = None) -> list[FreeModel]:
    """The ranked free pool from the cache, empty when missing or stale."""
    try:
        raw = json.loads(cache_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("free"), list):
        return []
    checked = raw.get("checked")
    try:
        stamp = datetime.fromisoformat(str(checked))
        stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return []
    if (now or datetime.now(UTC)) - stamp > STALE_AFTER:
        return []
    models = [
        FreeModel(
            id=str(item["id"]),
            context_length=int(item.get("context_length") or 0),
            tools=bool(item.get("tools")),
            structured=bool(item.get("structured")),
        )
        for item in raw["free"]
        if isinstance(item, dict) and item.get("id")
    ]
    return rank(models)[:POOL_SIZE]
