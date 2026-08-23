from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import assistant, engine_error, result, text_block, verdict_fail, verdict_pass
from todo_engine.parser import Task
from todo_engine.verifier import VERIFIER_MODEL, verify

TASK = Task(line_no=0, text="Create real.txt containing hello", done=False, number=1)


async def test_pass_verdict(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.verifier.push(*verdict_pass())
    v = await verify(TASK, "Created real.txt. STATUS: done", tmp_path)
    assert v.passed is True
    assert v.reason == "VERDICT: pass"
    assert v.cost_usd == pytest.approx(0.001)


async def test_fail_verdict(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.verifier.push(*verdict_fail("real.txt does not exist"))
    v = await verify(TASK, "Created real.txt. STATUS: done", tmp_path)
    assert v.passed is False
    assert v.reason == "VERDICT: fail — real.txt does not exist"


async def test_missing_verdict_line_fails(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.verifier.push(assistant(text_block("Looks fine I guess.")), result())
    v = await verify(TASK, "claim", tmp_path)
    assert v.passed is False
    assert "no verdict line" in v.reason


async def test_engine_error_currently_fails_open(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    # Documented soft spot (design.md step 22 will make this fail closed).
    fake_sdk.verifier.push(*engine_error("overloaded"))
    v = await verify(TASK, "claim", tmp_path)
    assert v.passed is True
    assert "accepted unverified" in v.reason


async def test_verifier_is_read_only_cheap_and_prompted_with_task(
    tmp_path: Path, fake_sdk: SimpleNamespace
) -> None:
    fake_sdk.verifier.push(*verdict_pass())
    claim = "x" * 5000
    await verify(TASK, claim, tmp_path)
    opts = fake_sdk.verifier.options[0]
    assert opts.model == VERIFIER_MODEL == "haiku"
    assert opts.allowed_tools == ["Read", "Glob", "Grep"]
    assert {"Write", "Edit", "Bash", "PowerShell", "WebSearch", "WebFetch"} <= set(
        opts.disallowed_tools
    )
    assert opts.permission_mode == "default"
    assert opts.max_turns == 15
    assert opts.cwd == str(tmp_path)
    prompt = fake_sdk.verifier.prompts[0]
    assert "TASK that was assigned: Create real.txt containing hello" in prompt
    assert "x" * 2000 in prompt and "x" * 2001 not in prompt  # claim truncated to 2000 chars
