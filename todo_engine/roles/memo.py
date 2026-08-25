"""Memo role: distill a reusable lesson from a verified-successful task.

The memo is stored under ``memory/lessons/`` and indexed in
``memory/MEMORY.md``; retrieval lives in :mod:`todo_engine.memory`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import query

from ..parser import Task
from .base import RoleContext, RoleSpec, run_role

MEMO_MODEL = "haiku"

DISTILL_SYSTEM_PROMPT = """You distill lessons from completed agent tasks.
Given a task and the agent's transcript summary, write a memo of AT MOST 8
lines that would help a future agent doing a similar task. Include only
transferable knowledge: working commands/recipes, discovered paths or IDs,
gotchas, decisions made. NO narration, NO praise, NO restating the task.
If there is nothing transferable, reply with exactly: NOTHING
"""

MEMO = RoleSpec(
    name="memo",
    system_prompt=DISTILL_SYSTEM_PROMPT,
    model=MEMO_MODEL,
    allowed_tools=(),
    max_turns=1,
)


def memory_dir(project_root: Path) -> Path:
    return project_root / "memory" / "lessons"


@dataclass
class Memo:
    path: Path | None  # None when the model judged there was nothing transferable
    cost_usd: float | None


async def distill(task: Task, final_text: str, transcript_tail: str, project_root: Path) -> Memo:
    """Distill a lesson memo from a verified-successful task."""
    prompt = (
        f"TASK: {task.text}\n\nAGENT FINAL REPORT:\n{final_text[:1500]}\n\n"
        f"TOOL-CALL TRAIL (tail):\n{transcript_tail[:1000]}"
    )
    run = await run_role(MEMO, prompt, RoleContext(), query_fn=query)
    memo_text = run.final_text.strip()
    if run.is_error or not memo_text or memo_text.upper() == "NOTHING":
        return Memo(path=None, cost_usd=run.cost_usd)

    lessons_dir = memory_dir(project_root)
    lessons_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    memo_path = lessons_dir / f"{stamp}-task-{task.number}.md"
    memo_path.write_text(f"# {task.text}\n\n{memo_text}\n", encoding="utf-8")

    index = project_root / "memory" / "MEMORY.md"
    line = f"- [{task.text[:80]}](lessons/{memo_path.name})\n"
    if index.is_file():
        index.write_text(index.read_text(encoding="utf-8") + line, encoding="utf-8")
    else:
        index.write_text(f"# Task lessons index\n\n{line}", encoding="utf-8")
    return Memo(path=memo_path, cost_usd=run.cost_usd)
