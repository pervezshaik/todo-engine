"""Compatibility shim — the executor now lives in :mod:`todo_engine.roles.executor`."""

from __future__ import annotations

from .roles.executor import (
    BUILTIN_TOOLS,
    EXECUTOR,
    SYSTEM_PROMPT,
    TaskContext,
    TaskOutcome,
    TaskResult,
    _classify,
    _extract_status,
    build_prompt,
    is_transient,
    run_task,
)

__all__ = [
    "BUILTIN_TOOLS",
    "EXECUTOR",
    "SYSTEM_PROMPT",
    "TaskContext",
    "TaskOutcome",
    "TaskResult",
    "_classify",
    "_extract_status",
    "build_prompt",
    "is_transient",
    "run_task",
]
