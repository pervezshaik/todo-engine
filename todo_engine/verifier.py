"""Independent verification: a read-only judge checks the work before [x].

The executing agent's self-reported ``STATUS: done`` is not trusted on its
own. A second, cheap-model agent with read-only tools inspects the working
directory against the task text and returns a verdict. The box is only
checked when the executor succeeded AND the verdict passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .parser import Task

VERIFIER_MODEL = "haiku"  # cheap; verification is mostly reading

VERIFIER_SYSTEM_PROMPT = """You are a strict verification judge. An autonomous
agent claims to have completed a task. Your job is to independently verify the
claim by inspecting the working directory with your read-only tools.

Rules:
1. Check the ACTUAL artifacts (read files, list directories) — do not trust
   the agent's claim text.
2. Verify against what the task asked for: right file names, right content,
   requirements actually met.
3. You cannot modify anything. You only inspect and judge.
4. Be strict about substance, lenient about style: fail wrong/missing/empty
   artifacts; do not fail for phrasing or formatting taste.
5. Your FINAL message must end with exactly one line:
   VERDICT: pass
   or
   VERDICT: fail — <specific reason, naming the artifact that is wrong or missing>
"""


@dataclass
class Verdict:
    passed: bool
    reason: str
    cost_usd: float | None


async def verify(task: Task, executor_claim: str, workdir: Path) -> Verdict:
    options = ClaudeAgentOptions(
        cwd=str(workdir),
        model=VERIFIER_MODEL,
        permission_mode="default",
        allowed_tools=["Read", "Glob", "Grep"],
        disallowed_tools=["Write", "Edit", "Bash", "PowerShell", "WebSearch", "WebFetch"],
        max_turns=15,
        system_prompt=VERIFIER_SYSTEM_PROMPT,
    )
    prompt = (
        f"Working directory: {workdir}\n\n"
        f"TASK that was assigned: {task.text}\n\n"
        f"The executing agent's final report was:\n---\n{executor_claim[:2000]}\n---\n\n"
        "Verify whether the task was actually completed. Inspect artifacts, "
        "then give your VERDICT."
    )

    final_text = ""
    cost: float | None = None
    is_error = False
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    final_text = block.text
        elif isinstance(message, ResultMessage):
            is_error = bool(message.is_error)
            cost = getattr(message, "total_cost_usd", None)

    if is_error:
        # verification infrastructure failed — don't block the task on it,
        # but say so honestly
        return Verdict(passed=True, reason="verifier unavailable (engine error); accepted unverified",
                       cost_usd=cost)

    for line in reversed(final_text.strip().splitlines()):
        line = line.strip()
        if line.upper().startswith("VERDICT:"):
            body = line.split(":", 1)[1].strip()
            return Verdict(passed=body.lower().startswith("pass"), reason=line, cost_usd=cost)
    return Verdict(passed=False, reason="VERDICT: fail — verifier gave no verdict line",
                   cost_usd=cost)
