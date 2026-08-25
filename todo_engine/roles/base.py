"""The agent-role pattern: one ``query()`` per role invocation.

A *role* is a system prompt + model + tool allow/deny lists + limits
(:class:`RoleSpec`). A *context* carries the per-invocation environment
(:class:`RoleContext`). :func:`run_role` is the single place the SDK message
stream is consumed — every role (executor, verifier, memo, triage, …) goes
through it, so cost accounting, transcripts and error handling are uniform.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import HookEvent

PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]
Effort = Literal["low", "medium", "high", "max"]

# the SDK's query(); type-erased so tests can substitute a fake
QueryFn = Callable[..., Any]


@dataclass(frozen=True)
class RoleSpec:
    """What a role *is*, independent of any single invocation."""

    name: str
    system_prompt: str
    model: str | None = None  # None → the CLI's default model
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: PermissionMode = "default"
    max_turns: int = 15
    effort: Effort | None = None
    max_budget_usd: float | None = None
    output_format: dict[str, Any] | None = None  # JSON-schema structured output
    setting_sources: tuple[str, ...] | None = None


@dataclass
class RoleContext:
    """Per-invocation environment and overrides."""

    workdir: Path | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    extra_allowed_tools: list[str] = field(default_factory=list)
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    on_event: Callable[[str], None] = lambda _line: None  # live console callback
    model: str | None = None  # overrides spec.model (tier escalation, @model:)
    max_turns: int | None = None
    permission_mode: PermissionMode | None = None
    effort: Effort | None = None
    max_budget_usd: float | None = None
    agents: dict[str, Any] | None = None  # SDK AgentDefinition roster


@dataclass
class RoleResult:
    final_text: str  # last non-empty assistant text
    cost_usd: float | None
    duration_s: float
    is_error: bool
    error_detail: str = ""
    subtype: str = ""
    structured: Any = None  # ResultMessage.structured_output when output_format was set
    transcript: list[str] = field(default_factory=list)  # markdown lines
    model: str | None = None  # the model actually requested


def build_options(spec: RoleSpec, ctx: RoleContext) -> ClaudeAgentOptions:
    model = ctx.model or spec.model
    options = ClaudeAgentOptions(
        permission_mode=ctx.permission_mode or spec.permission_mode,
        allowed_tools=[*spec.allowed_tools, *ctx.extra_allowed_tools],
        disallowed_tools=list(spec.disallowed_tools),
        max_turns=ctx.max_turns or spec.max_turns,
        system_prompt=spec.system_prompt,
        mcp_servers=ctx.mcp_servers,
        hooks=ctx.hooks,
    )
    if ctx.workdir is not None:
        options.cwd = str(ctx.workdir)
    if model:
        options.model = model
    if spec.setting_sources is not None:
        options.setting_sources = list(spec.setting_sources)  # type: ignore[arg-type]
    effort = ctx.effort or spec.effort
    if effort:
        options.effort = effort
    budget = ctx.max_budget_usd if ctx.max_budget_usd is not None else spec.max_budget_usd
    if budget is not None:
        options.max_budget_usd = budget
    if spec.output_format is not None:
        options.output_format = spec.output_format
    if ctx.agents:
        options.agents = ctx.agents
    return options


async def run_role(spec: RoleSpec, prompt: str, ctx: RoleContext, query_fn: QueryFn) -> RoleResult:
    """Run one role invocation to completion and collect what happened.

    ``query_fn`` is the SDK ``query`` as seen by the *calling* module, so a
    test can substitute a fake per role. The stream is always drained —
    returning early breaks SDK teardown.
    """
    options = build_options(spec, ctx)
    transcript: list[str] = []
    final_text = ""
    is_error = False
    error_detail = ""
    subtype = ""
    cost: float | None = None
    structured: Any = None
    started = time.monotonic()

    async for message in query_fn(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            turn_text = ""
            for block in message.content:
                if isinstance(block, TextBlock):
                    turn_text += block.text
                elif isinstance(block, ToolUseBlock):
                    line = f"[tool] {block.name}"
                    if block.name in ("Bash", "PowerShell") and isinstance(block.input, dict):
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
            subtype = str(getattr(message, "subtype", "") or "")
            cost = getattr(message, "total_cost_usd", None)
            structured = getattr(message, "structured_output", None)

    return RoleResult(
        final_text=final_text,
        cost_usd=cost,
        duration_s=time.monotonic() - started,
        is_error=is_error,
        error_detail=error_detail,
        subtype=subtype,
        structured=structured,
        transcript=transcript,
        model=options.model,
    )


def last_line_starting_with(text: str, prefix: str) -> str | None:
    """The last line of ``text`` whose upper-cased form starts with ``prefix``."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.upper().startswith(prefix.upper()):
            return line
    return None
