"""Example custom tool for the todo engine.

Any async function in this folder decorated with @tool becomes available to
every task agent as mcp__local__<name>. Copy this file to add your own.
"""

import hashlib

from claude_agent_sdk import tool


@tool(
    name="example",
    description="Demo capability: returns the official TOKEN for a given text. "
                "Use when a task asks for a text's token.",
    input_schema={"text": str},
)
async def example(args: dict) -> dict:
    digest = hashlib.sha256(args["text"].encode("utf-8")).hexdigest()[:12]
    return {"content": [{"type": "text", "text": f"TOKEN-{digest}"}]}
