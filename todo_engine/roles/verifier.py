"""Verifier role: a read-only judge checks the work before [x].

The executing agent's self-reported ``STATUS: done`` is not trusted on its
own. A second, cheap-model agent with read-only tools inspects the working
directory against the task text and returns a verdict. The box is only
checked when the executor succeeded AND the verdict passes.

The verifier **fails closed**: if it cannot run (engine error) the task is
not accepted — the runner marks the line ``[!]`` for a human to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import query

from ..parser import Task
from .base import RoleContext, RoleSpec, last_line_starting_with, run_role

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

READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
WRITE_TOOLS = ("Write", "Edit", "Bash", "PowerShell", "WebSearch", "WebFetch")

VERIFIER = RoleSpec(
    name="verifier",
    system_prompt=VERIFIER_SYSTEM_PROMPT,
    model=VERIFIER_MODEL,
    allowed_tools=READ_ONLY_TOOLS,
    disallowed_tools=WRITE_TOOLS,
    permission_mode="default",
    max_turns=15,
)


@dataclass
class Verdict:
    passed: bool
    reason: str
    cost_usd: float | None
    engine_error: bool = False  # verifier could not run; nothing was judged


async def verify(
    task: Task, executor_claim: str, workdir: Path, model: str | None = None
) -> Verdict:
    prompt = (
        f"Working directory: {workdir}\n\n"
        f"TASK that was assigned: {task.text}\n\n"
        f"The executing agent's final report was:\n---\n{executor_claim[:2000]}\n---\n\n"
        "Verify whether the task was actually completed. Inspect artifacts, "
        "then give your VERDICT."
    )
    run = await run_role(
        VERIFIER, prompt, RoleContext(workdir=workdir, model=model), query_fn=query
    )

    if run.is_error:
        return Verdict(
            passed=False,
            reason=f"VERDICT: fail — verifier unavailable (engine error): {run.error_detail}",
            cost_usd=run.cost_usd,
            engine_error=True,
        )
    line = last_line_starting_with(run.final_text, "VERDICT:")
    if line is None:
        return Verdict(
            passed=False,
            reason="VERDICT: fail — verifier gave no verdict line",
            cost_usd=run.cost_usd,
        )
    body = line.split(":", 1)[1].strip()
    return Verdict(passed=body.lower().startswith("pass"), reason=line, cost_usd=run.cost_usd)
