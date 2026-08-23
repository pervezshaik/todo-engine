"""Auth smoke test: verify the Agent SDK works with the Claude Code
subscription login and no ANTHROPIC_API_KEY.

Run:  python scripts/auth_check.py
Pass: prints the agent's reply ("ok") and AUTH CHECK PASSED.
"""

import asyncio
import os
import shutil
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)


async def main() -> int:
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("NOTE: ANTHROPIC_API_KEY is set — unsetting for this check "
              "so we prove the subscription-login path.")
        del os.environ["ANTHROPIC_API_KEY"]

    installed_cli = shutil.which("claude")
    print(f"Installed claude binary: {installed_cli or 'not found on PATH'}")

    attempts: list[tuple[str, ClaudeAgentOptions]] = [
        ("bundled engine + stored login", ClaudeAgentOptions(max_turns=1)),
    ]
    if installed_cli:
        attempts.append(
            ("installed claude binary (cli_path)",
             ClaudeAgentOptions(max_turns=1, cli_path=installed_cli)),
        )

    for label, options in attempts:
        print(f"\n--- Trying: {label} ---")
        try:
            reply_text = ""
            async for message in query(
                prompt="Reply with exactly: ok",
                options=options,
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            reply_text += block.text
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        print(f"ResultMessage error: {message.result}")
                        break
                    print(f"Reply: {reply_text.strip()!r}")
                    cost = getattr(message, "total_cost_usd", None)
                    print(f"Cost: {cost}")
                    print(f"\nAUTH CHECK PASSED via: {label}")
                    return 0
        except Exception as exc:  # noqa: BLE001 - report and try next path
            print(f"Failed: {type(exc).__name__}: {exc}")

    print("\nAUTH CHECK FAILED on all paths.")
    print("Fallback: run `claude setup-token`, set CLAUDE_CODE_OAUTH_TOKEN, retry.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
