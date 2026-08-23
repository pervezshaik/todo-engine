"""Step-3 verification: run one trivial task end-to-end through agent.run_task."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from todo_engine.agent import TaskContext, run_task  # noqa: E402
from todo_engine.parser import Task  # noqa: E402


async def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        task = Task(line_no=0, number=1, done=False, hints=[],
                    text="Create a file named proof.txt containing the single line: agent was here")
        ctx = TaskContext(workdir=workdir, on_event=lambda s: print(f"  | {s[:120]}"))

        result = await run_task(task, ctx)

        print(f"\nstatus_line: {result.status_line}")
        print(f"success: {result.success}  cost: {result.cost_usd}  duration: {result.duration_s:.1f}s")

        proof = workdir / "proof.txt"
        assert result.success, "agent did not report success"
        assert proof.exists(), "proof.txt was not created"
        content = proof.read_text(encoding="utf-8").strip()
        assert content == "agent was here", f"unexpected content: {content!r}"
        print("\nAGENT SINGLE-TASK TEST PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
