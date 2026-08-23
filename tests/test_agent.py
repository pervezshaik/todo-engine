from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import agent_done, assistant, engine_error, result, text_block, tool_use
from todo_engine.agent import (
    BUILTIN_TOOLS,
    SYSTEM_PROMPT,
    TaskContext,
    TaskOutcome,
    _classify,
    _extract_status,
    build_prompt,
    is_transient,
    run_task,
)
from todo_engine.parser import Task


def make_task(text: str = "Write hello.txt", **kw: object) -> Task:
    return Task(line_no=0, text=text, done=False, number=1, **kw)  # type: ignore[arg-type]


# --- pure helpers -----------------------------------------------------------


@pytest.mark.parametrize(
    "final_text, ok, line",
    [
        ("did things\nSTATUS: done", True, "STATUS: done"),
        ("status: DONE — all good", True, "status: DONE — all good"),
        ("STATUS: failed — missing capability: sms", False, "STATUS: failed — missing capability: sms"),
        ("STATUS: done\nactually no\nSTATUS: failed — oops", False, "STATUS: failed — oops"),
        ("no status at all", False, "STATUS: failed — agent did not report a status line"),
        ("", False, "STATUS: failed — agent did not report a status line"),
    ],
)
def test_extract_status(final_text: str, ok: bool, line: str) -> None:
    assert _extract_status(final_text) == (ok, line)


@pytest.mark.parametrize(
    "is_error, subtype, status_ok, status_line, expected",
    [
        (True, "success", True, "STATUS: done", TaskOutcome.ENGINE_ERROR),
        (False, "error_max_turns", False, "STATUS: failed — x", TaskOutcome.TIMEOUT),
        (False, "success", True, "STATUS: done", TaskOutcome.DONE),
        (False, "success", False, "STATUS: failed — missing capability: sms", TaskOutcome.MISSING_CAPABILITY),
        (False, "success", False, "STATUS: failed — user declined the command", TaskOutcome.DECLINED),
        (False, "success", False, "STATUS: failed — permission denied for rm", TaskOutcome.DECLINED),
        (False, "success", False, "STATUS: failed — file not found", TaskOutcome.FAILED),
    ],
)
def test_classify(is_error: bool, subtype: str, status_ok: bool, status_line: str,
                  expected: TaskOutcome) -> None:
    assert _classify(is_error, subtype, status_ok, status_line) is expected


@pytest.mark.parametrize("text, expected", [
    ("API Error: 429 Rate Limit", True),
    ("ECONNRESET while reading", True),
    ("Overloaded (529)", True),
    ("SyntaxError in tool input", False),
    ("", False),
])
def test_is_transient(text: str, expected: bool) -> None:
    assert is_transient(text) is expected


def test_build_prompt_minimal(tmp_path: Path) -> None:
    prompt = build_prompt(make_task(), TaskContext(workdir=tmp_path))
    assert f"Working directory: {tmp_path}" in prompt
    assert "TASK: Write hello.txt" in prompt
    assert "none registered beyond your built-in tools" in prompt
    assert "Lessons" not in prompt and "IMPORTANT" not in prompt


def test_build_prompt_full(tmp_path: Path) -> None:
    ctx = TaskContext(
        workdir=tmp_path,
        capability_manifest="Skills:\n- weekly-report: how to",
        lessons="Use wttr.in",
        completed_summaries=["Earlier task — STATUS: done"],
        failure_memo="Attempt 1 ended with: STATUS: failed — nope",
    )
    prompt = build_prompt(make_task(hints=["gmail", "xlsx"]), ctx)
    assert "suggested using these registered capabilities for this task: gmail, xlsx" in prompt
    assert "Available capabilities (beyond your built-in tools):\nSkills:" in prompt
    assert "Lessons from previous related tasks" in prompt and "Use wttr.in" in prompt
    assert "Tasks already completed earlier in this run:\n- Earlier task — STATUS: done" in prompt
    assert "IMPORTANT — a previous attempt at this task failed:" in prompt
    assert "take a DIFFERENT approach" in prompt


# --- run_task with the fake SDK --------------------------------------------


async def test_run_task_success_collects_transcript_and_options(tmp_path: Path,
                                                                 fake_sdk: SimpleNamespace) -> None:
    events: list[str] = []
    fake_sdk.agent.push(
        assistant(text_block("Plan: write file"), tool_use("Bash", command="echo hi > hello.txt")),
        assistant(tool_use("Read", file_path="hello.txt")),
        assistant(text_block("Verified.\nSTATUS: done")),
        result(cost=0.042),
    )
    ctx = TaskContext(workdir=tmp_path, extra_allowed_tools=["mcp__local__example"],
                      max_turns=7, on_event=events.append)
    res = await run_task(make_task(), ctx)

    assert res.success and res.outcome is TaskOutcome.DONE
    assert res.status_line == "STATUS: done"
    assert res.final_text == "Verified.\nSTATUS: done"
    assert res.cost_usd == pytest.approx(0.042)
    assert "> [tool] Bash: echo hi > hello.txt" in res.transcript
    assert "> [tool] Read" in res.transcript
    assert res.transcript[0] == "# Task 1: Write hello.txt"
    assert any(line.startswith("Result: success | outcome: done") for line in res.transcript)
    assert events == ["[tool] Bash: echo hi > hello.txt", "Plan: write file",
                      "[tool] Read", "Verified.\nSTATUS: done"]

    opts = fake_sdk.agent.options[0]
    assert opts.cwd == str(tmp_path)
    assert opts.permission_mode == "acceptEdits"
    assert opts.allowed_tools == [*BUILTIN_TOOLS, "mcp__local__example"]
    assert opts.setting_sources == ["user", "project"]
    assert opts.max_turns == 7
    assert opts.system_prompt == SYSTEM_PROMPT
    assert "TASK: Write hello.txt" in fake_sdk.agent.prompts[0]


async def test_run_task_yolo_uses_bypass_permissions(tmp_path: Path,
                                                     fake_sdk: SimpleNamespace) -> None:
    fake_sdk.agent.push(*agent_done())
    await run_task(make_task(), TaskContext(workdir=tmp_path, yolo=True))
    assert fake_sdk.agent.options[0].permission_mode == "bypassPermissions"


async def test_run_task_engine_error(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.agent.push(*engine_error("API Error: overloaded"))
    res = await run_task(make_task(), TaskContext(workdir=tmp_path))
    assert res.outcome is TaskOutcome.ENGINE_ERROR and not res.success
    assert res.status_line == "STATUS: failed — engine error: API Error: overloaded"
    assert res.error_detail == "API Error: overloaded"


async def test_run_task_max_turns_is_timeout(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.agent.push(assistant(text_block("still working...")),
                        result(subtype="error_max_turns"))
    res = await run_task(make_task(), TaskContext(workdir=tmp_path))
    assert res.outcome is TaskOutcome.TIMEOUT


async def test_run_task_without_status_line_fails(tmp_path: Path,
                                                  fake_sdk: SimpleNamespace) -> None:
    fake_sdk.agent.push(assistant(text_block("I think I'm done?")), result())
    res = await run_task(make_task(), TaskContext(workdir=tmp_path))
    assert res.outcome is TaskOutcome.FAILED
    assert res.status_line == "STATUS: failed — agent did not report a status line"


async def test_run_task_retry_attempt_is_noted_in_transcript(tmp_path: Path,
                                                             fake_sdk: SimpleNamespace) -> None:
    fake_sdk.agent.push(*agent_done())
    res = await run_task(make_task(), TaskContext(workdir=tmp_path, failure_memo="memo"))
    assert "*Retry attempt — previous failure memo was provided.*" in res.transcript
