"""Executor role: run one todo task with an autonomous agent."""

from __future__ import annotations

import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher, query
from claude_agent_sdk.types import HookEvent

from ..parser import Task
from .base import Effort, RoleContext, RoleSpec, last_line_starting_with, run_role

BUILTIN_TOOLS = [
    "Bash",
    "PowerShell",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]


def _os_line() -> str:
    system = platform.system()
    if system == "Windows":
        return "You are running on Windows; prefer PowerShell for shell commands."
    if system == "Darwin":
        return "You are running on macOS; use Bash for shell commands."
    return f"You are running on {system or 'Linux'}; use Bash for shell commands."


SYSTEM_PROMPT = f"""You are a task-execution agent. You are given exactly ONE task
from a user's to-do list. Complete it autonomously.

Rules:
1. Before planning, inventory your capabilities: your built-in tools plus the
   "Available capabilities" listed in the task briefing. Choose the ones suited
   to this task.
2. Work autonomously — do not ask the user questions; make reasonable choices.
3. Verify your own work before finishing (read back files you wrote, check
   command output).
4. If the task needs a capability you do not have, do NOT improvise around it.
5. {_os_line()}
6. Your FINAL message must end with exactly one status line:
   STATUS: done
   or
   STATUS: failed — <short reason>   (use "missing capability: <what>" when that is the cause)
"""

EXECUTOR = RoleSpec(
    name="executor",
    system_prompt=SYSTEM_PROMPT,
    allowed_tools=tuple(BUILTIN_TOOLS),
    permission_mode="acceptEdits",
    max_turns=50,
    setting_sources=("user", "project"),
)


class TaskOutcome(str, Enum):
    DONE = "done"
    FAILED = "failed"  # real failure; Reflexion retry applies
    TIMEOUT = "timeout"  # hit max_turns
    MISSING_CAPABILITY = "missing_capability"  # agent lacked a capability; no retry
    DECLINED = "declined"  # user/permission denied; no retry
    ENGINE_ERROR = "engine_error"  # SDK/infrastructure error
    BLOCKED = "blocked"  # needs a human decision; line marked [!]


# substrings that mark an engine error as transient → backoff + retry
_TRANSIENT_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "overloaded",
    "529",
    "timeout",
    "timed out",
    "connection",
    "econnreset",
    "network",
    "5xx",
    "internal server error",
    "service unavailable",
)


def is_transient(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


@dataclass
class TaskContext:
    """Everything a task run needs beyond the task itself."""

    workdir: Path
    yolo: bool = False
    max_turns: int = 50
    capability_manifest: str = ""
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    extra_allowed_tools: list[str] = field(default_factory=list)
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    completed_summaries: list[str] = field(default_factory=list)
    lessons: str = ""  # cross-run memory memos (set by runner)
    failure_memo: str = ""  # set on Reflexion retry attempts
    on_event: Callable[[str], None] = lambda _line: None  # live console callback
    model: str | None = None  # None → CLI default
    effort: Effort | None = None
    max_budget_usd: float | None = None
    agents: dict[str, Any] | None = None  # SDK subagent roster


@dataclass
class TaskResult:
    success: bool
    outcome: TaskOutcome
    status_line: str  # the STATUS: line (or synthesized failure reason)
    final_text: str
    cost_usd: float | None
    duration_s: float
    transcript: list[str]  # markdown lines for the run log
    error_detail: str = ""
    model: str | None = None


def build_prompt(task: Task, ctx: TaskContext) -> str:
    parts = [f"Working directory: {ctx.workdir}", "", f"TASK: {task.text}"]
    if task.hints:
        parts += [
            "",
            "The user specifically suggested using these registered "
            f"capabilities for this task: {', '.join(task.hints)}. "
            "Favor them if applicable.",
        ]
    if ctx.capability_manifest:
        parts += [
            "",
            "Available capabilities (beyond your built-in tools):",
            ctx.capability_manifest,
        ]
    else:
        parts += ["", "Available capabilities: none registered beyond your built-in tools."]
    if ctx.lessons:
        parts += ["", "Lessons from previous related tasks (use if helpful):", ctx.lessons]
    if ctx.completed_summaries:
        parts += ["", "Tasks already completed earlier in this run:"]
        parts += [f"- {s}" for s in ctx.completed_summaries]
    if ctx.failure_memo:
        parts += [
            "",
            "IMPORTANT — a previous attempt at this task failed:",
            ctx.failure_memo,
            "Analyze what went wrong and take a DIFFERENT approach this time. "
            "Do not repeat the failed approach.",
        ]
    return "\n".join(parts)


def _extract_status(final_text: str) -> tuple[bool, str]:
    line = last_line_starting_with(final_text, "STATUS:")
    if line is None:
        return False, "STATUS: failed — agent did not report a status line"
    body = line.split(":", 1)[1].strip()
    return body.lower().startswith("done"), line


async def run_task(task: Task, ctx: TaskContext) -> TaskResult:
    role_ctx = RoleContext(
        workdir=ctx.workdir,
        mcp_servers=ctx.mcp_servers,
        extra_allowed_tools=ctx.extra_allowed_tools,
        hooks=ctx.hooks,
        on_event=ctx.on_event,
        model=ctx.model,
        max_turns=ctx.max_turns,
        permission_mode="bypassPermissions" if ctx.yolo else None,
        effort=ctx.effort,
        max_budget_usd=ctx.max_budget_usd,
        agents=ctx.agents,
    )
    header = [f"# Task {task.number}: {task.text}", ""]
    if ctx.failure_memo:
        header += ["*Retry attempt — previous failure memo was provided.*", ""]

    run = await run_role(EXECUTOR, build_prompt(task, ctx), role_ctx, query_fn=query)

    status_ok, status_line = _extract_status(run.final_text)
    outcome = _classify(run.is_error, run.subtype, status_ok, status_line)
    if outcome is TaskOutcome.ENGINE_ERROR:
        status_line = f"STATUS: failed — engine error: {run.error_detail or 'unknown'}"
    success = outcome is TaskOutcome.DONE

    transcript = header + run.transcript
    transcript += [
        "",
        "---",
        f"Result: {'success' if success else 'FAILED'} | outcome: {outcome.value} | {status_line}",
        f"Cost: ${run.cost_usd:.4f}" if run.cost_usd is not None else "Cost: n/a",
        f"Duration: {run.duration_s:.1f}s",
    ]
    if run.model:
        transcript.append(f"Model: {run.model}")
    return TaskResult(
        success=success,
        outcome=outcome,
        status_line=status_line,
        final_text=run.final_text,
        cost_usd=run.cost_usd,
        duration_s=run.duration_s,
        transcript=transcript,
        error_detail=run.error_detail,
        model=run.model,
    )


def _classify(
    is_error: bool, result_subtype: str, status_ok: bool, status_line: str
) -> TaskOutcome:
    if is_error:
        return TaskOutcome.ENGINE_ERROR
    if "max_turn" in result_subtype:
        return TaskOutcome.TIMEOUT
    if status_ok:
        return TaskOutcome.DONE
    lowered = status_line.lower()
    if "missing capability" in lowered:
        return TaskOutcome.MISSING_CAPABILITY
    if "declined" in lowered or "permission" in lowered or "denied" in lowered:
        return TaskOutcome.DECLINED
    return TaskOutcome.FAILED
