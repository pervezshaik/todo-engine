"""Fake Claude Agent SDK plumbing for deterministic, $0 tests.

``FakeQuery`` stands in for ``claude_agent_sdk.query``: each call pops the next
scripted message list (or a callable producing one) and yields it as an async
generator, recording the prompt and options it was called with.
"""

from __future__ import annotations

from typing import Any, Callable

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

# --- message constructors ---------------------------------------------------


def text_block(text: str) -> TextBlock:
    return TextBlock(text=text)


def tool_use(name: str, **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(id="tu_1", name=name, input=tool_input)


def assistant(*blocks: Any) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="fake-model")


def result(is_error: bool = False, subtype: str = "success",
           cost: float | None = 0.01, result_text: str | None = None) -> ResultMessage:
    return ResultMessage(
        subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=is_error,
        num_turns=1, session_id="fake-session", total_cost_usd=cost, result=result_text,
    )


# --- canned scripts ---------------------------------------------------------


def agent_done(text: str = "All done.") -> list[Any]:
    return [assistant(text_block(f"{text}\nSTATUS: done")), result()]


def agent_failed(reason: str) -> list[Any]:
    return [assistant(text_block(f"Could not finish.\nSTATUS: failed — {reason}")), result()]


def engine_error(detail: str) -> list[Any]:
    return [result(is_error=True, result_text=detail)]


def verdict_pass() -> list[Any]:
    return [assistant(text_block("Artifacts look right.\nVERDICT: pass")), result(cost=0.001)]


def verdict_fail(reason: str) -> list[Any]:
    return [assistant(text_block(f"VERDICT: fail — {reason}")), result(cost=0.001)]


def memo_nothing() -> list[Any]:
    return [assistant(text_block("NOTHING")), result(cost=0.0005)]


def memo(text: str) -> list[Any]:
    return [assistant(text_block(text)), result(cost=0.0005)]


# --- the fake query ---------------------------------------------------------


class FakeQuery:
    """Scripted replacement for ``claude_agent_sdk.query``.

    ``push(*messages)`` queues one call's worth of messages; ``push_fn(fn)``
    queues a callable ``fn(prompt, options) -> list[messages]`` evaluated when
    the call is made (handy for inspecting state mid-run). A queued
    ``BaseException`` instance is raised instead of yielded.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.scripts: list[Any] = []
        self.calls: list[tuple[str, Any]] = []

    def push(self, *messages: Any) -> "FakeQuery":
        self.scripts.append(list(messages))
        return self

    def push_fn(self, fn: Callable[[str, Any], list[Any]]) -> "FakeQuery":
        self.scripts.append(fn)
        return self

    @property
    def prompts(self) -> list[str]:
        return [p for p, _ in self.calls]

    @property
    def options(self) -> list[Any]:
        return [o for _, o in self.calls]

    def __call__(self, prompt: str, options: Any = None) -> Any:
        self.calls.append((prompt, options))
        if not self.scripts:
            raise AssertionError(
                f"unexpected {self.name} query call #{len(self.calls)}; prompt: {prompt[:200]!r}")
        return self._gen(self.scripts.pop(0), prompt, options)

    async def _gen(self, script: Any, prompt: str, options: Any) -> Any:
        if callable(script):
            script = script(prompt, options)
        for message in script:
            if isinstance(message, BaseException):
                raise message
            yield message
