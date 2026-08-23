"""Verifier test: a false claim must fail, a true claim must pass."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from todo_engine.parser import Task  # noqa: E402
from todo_engine.verifier import verify  # noqa: E402


async def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        (workdir / "real.txt").write_text("hello engine\n", encoding="utf-8")

        # False claim: file was never created
        lie_task = Task(line_no=0, number=1, done=False,
                        text="Create a file named missing.txt containing the word banana")
        lie_verdict = await verify(
            lie_task, "I created missing.txt with the word banana. STATUS: done", workdir)
        print(f"false claim -> passed={lie_verdict.passed} | {lie_verdict.reason}")
        assert not lie_verdict.passed, "verifier believed a false claim!"

        # True claim
        true_task = Task(line_no=0, number=2, done=False,
                         text="Create a file named real.txt containing the words hello engine")
        true_verdict = await verify(
            true_task, "Created real.txt containing 'hello engine'. STATUS: done", workdir)
        print(f"true claim  -> passed={true_verdict.passed} | {true_verdict.reason}")
        assert true_verdict.passed, "verifier rejected an honest claim"

    print("\nVERIFIER TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
