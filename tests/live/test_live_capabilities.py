"""LIVE: registry scan of this repo + the real agent calling mcp__local__example.

Costs real money (~$0.05). Run with:  pytest -m live tests/live/test_live_capabilities.py
"""

import hashlib
from pathlib import Path

import pytest

from todo_engine.agent import TaskContext, run_task
from todo_engine.capabilities import scan
from todo_engine.parser import Task

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


async def test_agent_uses_registered_custom_tool(tmp_path: Path) -> None:
    caps = scan(ROOT)
    for w in caps.warnings:
        print(f"  ! {w}")
    assert any(name == "weekly-report" for name, _, _ in caps.skills), "skill not found"
    assert "mcp__local__example" in caps.allowed_tools, "example tool not registered"
    assert "local" in caps.mcp_servers

    expected = "TOKEN-" + hashlib.sha256(b"hello-engine").hexdigest()[:12]
    task = Task(
        line_no=0,
        number=1,
        done=False,
        hints=["example"],
        text="Get the official TOKEN for the text 'hello-engine' and write it, "
        "and nothing else, into token.txt",
    )
    ctx = TaskContext(
        workdir=tmp_path,
        capability_manifest=caps.manifest,
        mcp_servers=caps.mcp_servers,
        extra_allowed_tools=caps.allowed_tools,
        on_event=lambda s: print(f"  | {s[:120]}"),
    )
    result = await run_task(task, ctx)
    print(f"status: {result.status_line}")
    assert result.success, result.status_line
    assert (tmp_path / "token.txt").read_text(encoding="utf-8").strip() == expected, (
        "token mismatch — tool was not actually used"
    )
    assert any("mcp__local__example" in line for line in result.transcript)
