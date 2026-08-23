"""LIVE: one trivial task end-to-end through the real Claude engine.

Costs real money (~$0.05) and needs the Claude Code login. Run with:
    pytest -m live tests/live/test_live_agent.py
"""

from pathlib import Path

import pytest

from todo_engine.agent import TaskContext, run_task
from todo_engine.parser import Task

pytestmark = pytest.mark.live


async def test_single_task_end_to_end(tmp_path: Path) -> None:
    task = Task(line_no=0, number=1, done=False,
                text="Create a file named proof.txt containing the single line: agent was here")
    result = await run_task(task, TaskContext(workdir=tmp_path, on_event=lambda s: print(f"  | {s[:120]}")))
    print(f"status: {result.status_line}  cost: {result.cost_usd}  duration: {result.duration_s:.1f}s")
    assert result.success, result.status_line
    assert (tmp_path / "proof.txt").read_text(encoding="utf-8").strip() == "agent was here"
