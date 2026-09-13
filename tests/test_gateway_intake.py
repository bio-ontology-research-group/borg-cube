import asyncio
import importlib.util
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cube.agents import load_agent, read_inbox
from cube.gateway_intake import accept, dispatch
from tests.helpers_engine import REPO_ROOT, fixtures
from tools.configure_gateway_intake import configured

globals().update(fixtures())


def test_gateway_settings_preserve_other_configuration():
    original = {
        "plugins": {"enabled": ["other"]},
        "agent": {},
        "model": {"default": "existing"},
        "display": {"tool_progress": "off"},
    }
    changed = configured(original)
    assert changed["plugins"]["enabled"] == ["other", "cube-intake"]
    assert changed["agent"]["max_turns"] == 8
    assert changed["model"] == original["model"]
    assert changed["display"] == original["display"]
    assert configured(changed) == changed
    assert original["agent"] == {}


def test_dispatch_bounded_goal_and_local_model(engine_settings, monkeypatch):
    import cube.gateway_intake as intake
    from cube.config import TierEntry

    engine_settings.tiers["local"] = [TierEntry(runner="hermes", provider="local", model="qwen")]
    monkeypatch.setattr(intake, "load_agent", lambda *args: SimpleNamespace(name="coordinator"))
    rows = [{"id": "mail-1", "from": "robert", "text": "New goal intake cube-abc; request"}]
    monkeypatch.setattr(intake, "read_inbox", lambda *args, **kwargs: rows)
    run = MagicMock(
        return_value=SimpleNamespace(
            ok=True, message="Plan saved", run_id="run-1", state="finished", error=None
        )
    )
    ack = MagicMock()
    monkeypatch.setattr(intake, "execute", run)
    monkeypatch.setattr(intake, "append_journal", MagicMock())
    monkeypatch.setattr(intake, "mark_inbox_read", ack)
    assert dispatch(engine_settings)["state"] == "finished"
    args = run.call_args.kwargs
    assert args["model"] == "qwen" and args["runner_name"] == "hermes@local"
    assert args["bead"] == "cube-abc" and len(args["prompt_text"]) < 1500
    assert ack.call_args.args[2] == ["mail-1"]
    run.return_value.ok = False
    ack.reset_mock()
    dispatch(engine_settings)
    ack.assert_not_called()


def test_intake_verbatim_receipt_and_retry(engine_settings, fake_bd):
    root = engine_settings.root
    (root / "agents/coordinator").mkdir(parents=True)
    for name in ("coordinator.yaml", "coordinator/charter.md"):
        shutil.copy(REPO_ROOT / "agents" / name, root / "agents" / name)
    post = "a" * 26
    text = "New goal: Extend FLOPO; validate OWL and SHACL. Laptop files use the liaison."
    bead = accept(engine_settings, post, text)
    assert text in fake_bd.bead(bead)["description"]
    assert fake_bd.bead(bead)["labels"] == [
        "kind:request",
        "agent:coordinator",
        "intake:goal",
        "privacy:internal",
    ]
    assert accept(engine_settings, post, text) == bead
    assert len(fake_bd.beads()) == 1
    assert len(read_inbox(root, load_agent(root, "coordinator"))) == 1
    with pytest.raises(ValueError, match="Edited"):
        accept(engine_settings, post, text + " Changed.")


@pytest.mark.parametrize("text", ["New goal:", "hello", "New goal: grades for students"])
def test_invalid_intake_never_writes(engine_settings, fake_bd, text):
    with pytest.raises(ValueError):
        accept(engine_settings, "a" * 26, text)
    assert not fake_bd.beads()


def plugin():
    spec = importlib.util.spec_from_file_location(
        "intake_plugin", REPO_ROOT / "hermes/plugins/cube-intake/__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = MagicMock()
    module.register(ctx)
    return module, ctx.register_hook.call_args.args[1], ctx.register_command.call_args.args[1]


def event(module, **overrides):
    source = dict(platform="mattermost", user_id=module.ROBERT, chat_id=module.DM, chat_type="dm")
    source.update(overrides)
    return SimpleNamespace(
        source=SimpleNamespace(**source),
        message_id="a" * 26,
        text="New goal: Extend FLOPO with OWL and SHACL validation",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": "someone-else"},
        {"chat_id": "another-channel"},
        {"platform": "telegram"},
        {"chat_type": "group"},
    ],
)
def test_plugin_identity_boundary(overrides):
    module, before, _ = plugin()
    assert before(event(module, **overrides)) is None


def test_fast_path_no_model_and_single_use(monkeypatch):
    module, before, handler = plugin()
    proc = SimpleNamespace(
        returncode=0, communicate=AsyncMock(return_value=(b'{"bead":"cube-test"}', b""))
    )
    wake = SimpleNamespace(wait=AsyncMock(return_value=0))
    spawn = AsyncMock(side_effect=[proc, wake])
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    incoming = event(module)
    routed = before(incoming)
    ticket = routed["text"].split()[1]
    assert "Recorded as cube-test" in asyncio.run(handler(ticket))
    assert spawn.call_count == 2
    assert spawn.call_args_list[0].args[1:] == ("-m", "cube.gateway_intake")
    sent = json.loads(proc.communicate.call_args.args[0])
    assert sent == {"post": incoming.message_id, "text": incoming.text}
    assert "Send New goal:" in asyncio.run(handler(ticket))
    assert spawn.call_count == 2


def test_intake_failure_never_wakes_research(monkeypatch):
    module, before, handler = plugin()
    proc = SimpleNamespace(
        returncode=1, communicate=AsyncMock(return_value=(b"", b"private error"))
    )
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    ticket = before(event(module))["text"].split()[1]
    answer = asyncio.run(handler(ticket))
    assert "failed" in answer and "private error" not in answer
    assert spawn.call_count == 1
