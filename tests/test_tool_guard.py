"""Exercise the actual standalone hook without a live model or tool execution."""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "cube" / "tool_guard.py"


def invoke(command, *, role="liaison", tool="Bash", raw=None):
    result = subprocess.run(
        [sys.executable, "-I", str(GUARD), "--role", role],
        input=raw
        if raw is not None
        else json.dumps(
            {
                "tool_name": tool,
                "tool_input": {"command": command},
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    return result.returncode, output["permissionDecision"]


@pytest.mark.parametrize(
    "command",
    [
        "cube boundary head '/home/user/org/a file.org' --json",
        "cube boundary grep '/home/user/org' --pattern 'research goals'",
        "cube boundary mail-search 'from:alice@example.org' --json",
        "cube boundary mail-show 'id:abc@example.org'",
        "cube boundary mail-search 'subject:research*'",
        "cube boundary request 'Please grant access to /home/user/notes' --apply",
    ],
)
def test_liaison_commands(command):
    assert invoke(command) == (0, "allow")


def test_proposal_json_is_data():
    value = json.dumps({"host": "ws", "commands": [["df", "-h"]], "rationale": "Check disk"})
    assert invoke("cube boundary propose " + shlex.quote(value) + " --apply", role="sysadmin") == (
        0,
        "allow",
    )
    assert invoke("cube boundary inspect ws --check disk", role="sysadmin") == (0, "allow")


@pytest.mark.parametrize(
    "command",
    [
        "cube boundary head /tmp/file > /tmp/output",
        "cube boundary head /tmp/file >> /tmp/output",
        "cube boundary head /tmp/file < /tmp/input",
        "cube boundary head /tmp/file; touch /tmp/x",
        "cube boundary head /tmp/file && true",
        "cube boundary head /tmp/file | true",
        "cube boundary head /tmp/file &",
        "cube boundary head /tmp/file\ntouch /tmp/x",
        "cube boundary head /tmp/file\rtrue",
        "cube boundary head $(whoami)",
        "cube boundary head `whoami`",
        "cube boundary head ${HOME}/file",
        "cube boundary head /tmp/*",
        "cube boundary head ~/org/file.org",
        "cube boundary head /tmp/{a,b}",
        "CUBE_ROLE=sysadmin cube boundary inspect ws",
        "env CUBE_ROLE=sysadmin cube boundary inspect ws",
        "cube boundary head /tmp/file # comment",
        "cube boundary head /tmp/file --root /tmp/other",
        "cube boundary head /tmp/file --apply --dry-run",
        "cube boundary head /tmp/file --json --json",
        "cube boundary head /tmp/file other",
        "cube boundary head /tmp/file --pattern x",
        "cube boundary head /tmp/file --check disk",
        "cube boundary grep /tmp/file --pattern",
        "cube boundary grep /tmp/file --pattern --apply",
        "cube boundary request 'Quoted ; shell syntax still forbidden'",
        "cube boundary head '/tmp/unterminated",
        "cube boundary head",
        "cube boundary head ''",
        "cube boundary inspect ws",
        "cube approve anything --apply",
    ],
)
def test_shell_and_parser_bypasses_denied(command):
    assert invoke(command) == (0, "deny")


@pytest.mark.parametrize(
    "command",
    [
        "cube boundary head /tmp/file",
        "cube boundary inspect ws --check arbitrary",
        "cube boundary inspect ws --check disk --unknown",
        "cube boundary execute anything --apply",
    ],
)
def test_sysadmin_restrictions(command):
    assert invoke(command, role="sysadmin") == (0, "deny")


def test_other_tool_and_malformed_input_fail_closed():
    assert invoke("cube boundary head /tmp/file", tool="Read") == (0, "deny")
    for raw in ("{", "null", "[]", "{}", "x" * 200_001):
        assert invoke(None, raw=raw) == (2, "deny")
