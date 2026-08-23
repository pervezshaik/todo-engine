"""PreToolUse hooks: shell-command logging and the --confirm human gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookEvent

SHELL_TOOLS = ("Bash", "PowerShell")

DENY_REASON = (
    "The user declined this command. Try a different, safer approach or finish with STATUS: failed."
)


def make_shell_hooks(log_file: Path, confirm: bool) -> dict[HookEvent, list[HookMatcher]]:
    """Hooks dict for ClaudeAgentOptions.

    Every shell command is appended to ``log_file`` *before* it executes.
    With ``confirm=True`` the user is prompted y/n per command; "n" denies the
    call and the reason is delivered back to the agent.
    """

    async def shell_hook(input_data: Any, tool_use_id: Any = None, context: Any = None) -> Any:
        del tool_use_id, context
        command = str(input_data.get("tool_input", {}).get("command", ""))
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"$ {command}\n")

        if confirm:
            print(f"\n[confirm] agent wants to run:\n  {command}")
            answer = input("[confirm] allow? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": DENY_REASON,
                    }
                }
        return {}

    return {"PreToolUse": [HookMatcher(matcher=tool, hooks=[shell_hook]) for tool in SHELL_TOOLS]}
