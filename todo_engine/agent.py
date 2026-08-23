"""Run one todo task with an autonomous agent (Claude Agent SDK)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .parser import Task

BUILTIN_TOOLS = [
    "Bash", "PowerShell", "Read", "Write", "Edit", "Glob", "Grep",
    "WebSearch", "WebFetch",
]

SYSTEM_PROMPT = """You are a task-execution agent. You are given exactly ONE task
from a user's to-do list. Complete it autonomously.

Rules:
1. Before planning, inventory your capabilities: your built-in tools plus the
   "Available capabilities" listed in the task briefing. Choose the ones suited
   to this task.
2. Work autonomously — do not ask the user questions; make reasonable choices.
3. Verify your own work before finishing (read back files you wrote, check
   command output).
4. If the task needs a capability you do not have, do NOT improvise around it.
5. You are running on Windows 11.
6. Your FINAL message must end with exactly one status line:
   STATUS: done
   or
   STATUS: failed — <short reason>   (use "missing capability: <what>" when that is the cause)
"""


class TaskOutcome(str, Enum):
    DONE = "done"
    FAILED = "failed"                        # real failure; Reflexion retry applies
    TIMEOUT = "timeout"                      # hit max_turns
    MISSING_CAPABILITY = "missing_capability"  # agent lacked a capability; no retry
    DECLINED = "declined"                    # user/permission denied; no retry
    ENGINE_ERROR = "engine_error"            # SDK/infrastructure error


# substrings that mark an engine error as transient → backoff + retry
_TRANSIENT_MARKERS = (
    "rate limit", "rate_limit", "429", "overloaded", "529", "timeout",
    "timed out", "connection", "econnreset", "network", "5xx",
    "internal server error", "service unavailable",
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
    hooks: dict[str, list[Any]] | None = None
    completed_summaries: list[str] = field(default_factory=list)
    lessons: str = ""             # cross-run memory memos (set by runner)
    failure_memo: str = ""        # set on Reflexion retry attempts
    on_event: Callable[[str], None] = lambda _line: None  # live console callback


@dataclass
class TaskResult:
    success: bool
    outcome: TaskOutcome
    status_line: str          # the STATUS: line (or synthesized failure reason)
    final_text: str
    cost_usd: float | None
    duration_s: float
    transcript: list[str]     # markdown lines for the run log
    error_detail: str = ""


def build_prompt(task: Task, ctx: TaskContext) -> str:
    parts = [f"Working directory: {ctx.workdir}", "", f"TASK: {task.text}"]
    if task.hints:
        parts += ["", "The user specifically suggested using these registered "
                  f"capabilities for this task: {', '.join(task.hints)}. "
                  "Favor them if applicable."]
    if ctx.capability_manifest:
        parts += ["", "Available capabilities (beyond your built-in tools):",
                  ctx.capability_manifest]
    else:
        parts += ["", "Available capabilities: none registered beyond your built-in tools."]
    if ctx.lessons:
        parts += ["", "Lessons from previous related tasks (use if helpful):",
                  ctx.lessons]
    if ctx.completed_summaries:
        parts += ["", "Tasks already completed earlier in this run:"]
        parts += [f"- {s}" for s in ctx.completed_summaries]
    if ctx.failure_memo:
        parts += ["", "IMPORTANT — a previous attempt at this task failed:",
                  ctx.failure_memo,
                  "Analyze what went wrong and take a DIFFERENT approach this time. "
                  "Do not repeat the failed approach."]
    return "\n".join(parts)


def _extract_status(final_text: str) -> tuple[bool, str]:
    for line in reversed(final_text.strip().splitlines()):
        line = line.strip()
        if line.upper().startswith("STATUS:"):
            body = line.split(":", 1)[1].strip()
            return body.lower().startswith("done"), line
    return False, "STATUS: failed — agent did not report a status line"


async def run_task(task: Task, ctx: TaskContext) -> TaskResult:
    options = ClaudeAgentOptions(
        cwd=str(ctx.workdir),
        permission_mode="bypassPermissions" if ctx.yolo else "acceptEdits",
        allowed_tools=[*BUILTIN_TOOLS, *ctx.extra_allowed_tools],
        mcp_servers=ctx.mcp_servers,
        setting_sources=["user", "project"],
        max_turns=ctx.max_turns,
        system_prompt=SYSTEM_PROMPT,
        hooks=ctx.hooks,
    )

    transcript: list[str] = [f"# Task {task.number}: {task.text}", ""]
    if ctx.failure_memo:
        transcript += ["*Retry attempt — previous failure memo was provided.*", ""]
    final_text = ""
    is_error = False
    error_detail = ""
    result_subtype = ""
    cost: float | None = None
    started = time.monotonic()

    async for message in query(prompt=build_prompt(task, ctx), options=options):
        if isinstance(message, AssistantMessage):
            turn_text = ""
            for block in message.content:
                if isinstance(block, TextBlock):
                    turn_text += block.text
                elif isinstance(block, ToolUseBlock):
                    line = f"[tool] {block.name}"
                    if block.name == "Bash" and isinstance(block.input, dict):
                        line += f": {block.input.get('command', '')}"
                    transcript.append(f"> {line}")
                    ctx.on_event(line)
            if turn_text.strip():
                final_text = turn_text  # keep the latest assistant text
                transcript += ["", turn_text, ""]
                ctx.on_event(turn_text.strip())
        elif isinstance(message, ResultMessage):
            is_error = bool(message.is_error)
            if is_error:
                error_detail = str(message.result)
            result_subtype = str(getattr(message, "subtype", "") or "")
            cost = getattr(message, "total_cost_usd", None)
        # loop is left to finish naturally — early return breaks SDK teardown

    duration = time.monotonic() - started
    status_ok, status_line = _extract_status(final_text)
    outcome = _classify(is_error, result_subtype, status_ok, status_line)
    if outcome is TaskOutcome.ENGINE_ERROR:
        status_line = f"STATUS: failed — engine error: {error_detail or 'unknown'}"
    success = outcome is TaskOutcome.DONE

    transcript += ["", "---",
                   f"Result: {'success' if success else 'FAILED'} | outcome: {outcome.value} | {status_line}",
                   f"Cost: ${cost:.4f}" if cost is not None else "Cost: n/a",
                   f"Duration: {duration:.1f}s"]
    return TaskResult(
        success=success,
        outcome=outcome,
        status_line=status_line,
        final_text=final_text,
        cost_usd=cost,
        duration_s=duration,
        transcript=transcript,
        error_detail=error_detail,
    )


def _classify(is_error: bool, result_subtype: str,
              status_ok: bool, status_line: str) -> TaskOutcome:
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
