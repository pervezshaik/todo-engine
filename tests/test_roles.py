"""The shared role loop: option building, transcript/cost collection, structured output."""

from __future__ import annotations

from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage

from fakes import FakeQuery, assistant, engine_error, result, text_block, tool_use
from todo_engine.roles.base import (
    RoleContext,
    RoleSpec,
    build_options,
    last_line_starting_with,
    run_role,
)

SPEC = RoleSpec(
    name="probe",
    system_prompt="be a probe",
    model="haiku",
    allowed_tools=("Read",),
    disallowed_tools=("Write",),
    max_turns=3,
    effort="low",
    max_budget_usd=0.5,
    output_format={"type": "json_schema", "schema": {"type": "object"}},
    setting_sources=("user",),
)


def test_build_options_from_spec(tmp_path: Path) -> None:
    opts = build_options(SPEC, RoleContext(workdir=tmp_path, extra_allowed_tools=["mcp__x__y"]))
    assert opts.model == "haiku" and opts.cwd == str(tmp_path)
    assert opts.allowed_tools == ["Read", "mcp__x__y"] and opts.disallowed_tools == ["Write"]
    assert opts.permission_mode == "default" and opts.max_turns == 3
    assert opts.effort == "low" and opts.max_budget_usd == 0.5
    assert opts.output_format == SPEC.output_format and opts.setting_sources == ["user"]
    assert opts.system_prompt == "be a probe"


def test_context_overrides_spec() -> None:
    ctx = RoleContext(
        model="opus",
        max_turns=9,
        permission_mode="bypassPermissions",
        effort="max",
        max_budget_usd=2.0,
        agents={"researcher": object()},
    )
    opts = build_options(SPEC, ctx)
    assert opts.model == "opus" and opts.max_turns == 9
    assert opts.permission_mode == "bypassPermissions" and opts.effort == "max"
    assert opts.max_budget_usd == 2.0 and "researcher" in opts.agents
    assert opts.cwd is None  # no workdir → the SDK default


def test_minimal_spec_leaves_sdk_defaults() -> None:
    opts = build_options(RoleSpec(name="m", system_prompt="p"), RoleContext())
    assert opts.model is None and opts.effort is None and opts.max_budget_usd is None
    assert opts.output_format is None and opts.agents is None and opts.setting_sources is None


async def test_run_role_collects_everything() -> None:
    events: list[str] = []
    fake = FakeQuery("probe").push(
        assistant(text_block("thinking"), tool_use("PowerShell", command="dir")),
        assistant(tool_use("Read", file_path="x")),
        assistant(text_block("final answer")),
        result(cost=0.02),
    )
    res = await run_role(SPEC, "hello", RoleContext(on_event=events.append), query_fn=fake)
    assert res.final_text == "final answer" and res.cost_usd == 0.02
    assert not res.is_error and res.subtype == "success" and res.model == "haiku"
    assert res.transcript == [
        "> [tool] PowerShell: dir",
        "",
        "thinking",
        "",
        "> [tool] Read",
        "",
        "final answer",
        "",
    ]
    assert events == ["[tool] PowerShell: dir", "thinking", "[tool] Read", "final answer"]
    assert res.duration_s >= 0
    assert fake.prompts == ["hello"]


async def test_run_role_engine_error_and_structured_output() -> None:
    fake = FakeQuery("probe").push(*engine_error("boom"))
    res = await run_role(SPEC, "p", RoleContext(), query_fn=fake)
    assert res.is_error and res.error_detail == "boom" and res.final_text == ""

    structured = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        total_cost_usd=0.001,
        structured_output={"complexity": "simple"},
    )
    fake.push(assistant(text_block("{}")), structured)
    res = await run_role(SPEC, "p", RoleContext(), query_fn=fake)
    assert res.structured == {"complexity": "simple"}


async def test_run_role_drains_the_stream_even_after_result() -> None:
    # a message after ResultMessage must not be lost/raise — the loop runs to the end
    fake = FakeQuery("probe").push(result(cost=0.1), assistant(text_block("late")))
    res = await run_role(SPEC, "p", RoleContext(), query_fn=fake)
    assert res.final_text == "late" and res.cost_usd == 0.1


@pytest.mark.parametrize(
    ("text", "prefix", "expected"),
    [
        ("a\nSTATUS: done\n", "STATUS:", "STATUS: done"),
        ("STATUS: done\nx\nstatus: failed — y", "STATUS:", "status: failed — y"),
        ("nothing", "VERDICT:", None),
        ("", "VERDICT:", None),
    ],
)
def test_last_line_starting_with(text: str, prefix: str, expected: str | None) -> None:
    assert last_line_starting_with(text, prefix) == expected
