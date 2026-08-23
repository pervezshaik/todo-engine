from pathlib import Path
from typing import Any

import pytest

from todo_engine.hooks import SHELL_TOOLS, make_shell_hooks


def get_hook(hooks: dict) -> tuple[list[str], Any]:
    matchers = hooks["PreToolUse"]
    return [m.matcher for m in matchers], matchers[0].hooks[0]


async def test_logs_every_command_before_execution(tmp_path: Path) -> None:
    log = tmp_path / "cmd.log"
    matchers, hook = get_hook(make_shell_hooks(log, confirm=False))
    assert matchers == list(SHELL_TOOLS) == ["Bash", "PowerShell"]
    assert await hook({"tool_input": {"command": "ls -la"}}, "id", None) == {}
    assert await hook({"tool_input": {"command": "rm x"}}) == {}
    assert log.read_text(encoding="utf-8") == "$ ls -la\n$ rm x\n"


async def test_confirm_deny_returns_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    _, hook = get_hook(make_shell_hooks(tmp_path / "cmd.log", confirm=True))
    out = await hook({"tool_input": {"command": "format c:"}})
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "declined" in decision["permissionDecisionReason"]
    assert "$ format c:" in (tmp_path / "cmd.log").read_text(
        encoding="utf-8"
    )  # logged even when denied


async def test_confirm_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "yes")
    _, hook = get_hook(make_shell_hooks(tmp_path / "cmd.log", confirm=True))
    assert await hook({"tool_input": {"command": "dir"}}) == {}
