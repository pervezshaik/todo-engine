"""Cross-run memory: retrieve lessons distilled from completed tasks.

After each *verified* success the memo role (:mod:`todo_engine.roles.memo`)
stores a short memo under ``memory/lessons/``, indexed in ``memory/MEMORY.md``.
Before each task, the top-k keyword-relevant memos are injected into the
agent's prompt so related tasks don't start cold.
"""

from __future__ import annotations

import re
from pathlib import Path

from .roles.memo import DISTILL_SYSTEM_PROMPT, MEMO, MEMO_MODEL, Memo, distill, memory_dir

__all__ = [
    "DISTILL_SYSTEM_PROMPT",
    "MEMO",
    "MEMO_MODEL",
    "Memo",
    "distill",
    "memory_dir",
    "relevant_memos",
]

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")
_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "has",
        "have",
        "was",
        "were",
        "are",
        "will",
        "file",
        "files",
        "create",
        "write",
        "task",
        "using",
        "use",
        "used",
        "new",
        "all",
        "one",
        "two",
        "out",
    ]
)


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)} - _STOPWORDS


def relevant_memos(task_text: str, project_root: Path, k: int = 3, max_chars: int = 2500) -> str:
    """Return the top-k keyword-relevant memos, concatenated for the prompt."""
    lessons_dir = memory_dir(project_root)
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
