"""Cross-run memory: distill lessons from completed tasks, retrieve them later.

After each *verified* success, a short memo (what worked, reusable commands,
gotchas) is distilled by a cheap model and stored under ``memory/lessons/``,
indexed in ``memory/MEMORY.md``. Before each task, the top-k keyword-relevant
memos are injected into the agent's prompt so related tasks don't start cold.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .parser import Task

MEMO_MODEL = "haiku"

DISTILL_SYSTEM_PROMPT = """You distill lessons from completed agent tasks.
Given a task and the agent's transcript summary, write a memo of AT MOST 8
lines that would help a future agent doing a similar task. Include only
transferable knowledge: working commands/recipes, discovered paths or IDs,
gotchas, decisions made. NO narration, NO praise, NO restating the task.
If there is nothing transferable, reply with exactly: NOTHING
"""

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")
_STOPWORDS = frozenset(
    "the and for with that this from into your has have was were are will "
    "file files create write task using use used new all one two out".split())


def _memory_dir(project_root: Path) -> Path:
    return project_root / "memory" / "lessons"


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)} - _STOPWORDS


async def distill(task: Task, final_text: str, transcript_tail: str,
                  project_root: Path) -> Path | None:
    """Distill a lesson memo from a verified-successful task. Returns the memo
    path, or None if the model judged there was nothing transferable."""
    options = ClaudeAgentOptions(
        model=MEMO_MODEL,
        max_turns=1,
        allowed_tools=[],
        system_prompt=DISTILL_SYSTEM_PROMPT,
    )
    prompt = (f"TASK: {task.text}\n\nAGENT FINAL REPORT:\n{final_text[:1500]}\n\n"
              f"TOOL-CALL TRAIL (tail):\n{transcript_tail[:1000]}")
    memo_text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    memo_text = block.text.strip()
        elif isinstance(message, ResultMessage):
            if message.is_error:
                return None

    if not memo_text or memo_text.strip().upper() == "NOTHING":
        return None

    lessons_dir = _memory_dir(project_root)
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
    return memo_path


def relevant_memos(task_text: str, project_root: Path, k: int = 3,
                   max_chars: int = 2500) -> str:
    """Return the top-k keyword-relevant memos, concatenated for the prompt."""
    lessons_dir = _memory_dir(project_root)
    if not lessons_dir.is_dir():
        return ""
    task_words = _keywords(task_text)
    if not task_words:
        return ""
    scored: list[tuple[float, Path, str]] = []
    for memo in lessons_dir.glob("*.md"):
        try:
            content = memo.read_text(encoding="utf-8")
        except OSError:
            continue
        memo_words = _keywords(content)
        if not memo_words:
            continue
        overlap = len(task_words & memo_words)
        if overlap == 0:
            continue
        scored.append((overlap / len(task_words), memo, content))
    scored.sort(key=lambda s: s[0], reverse=True)

    parts: list[str] = []
    used = 0
    for _score, _path, content in scored[:k]:
        chunk = content.strip()[:1000]
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n\n---\n\n".join(parts)
