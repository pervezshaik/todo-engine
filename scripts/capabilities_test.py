"""Step-4 verification: registry scan + agent actually calls mcp__local__example."""

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from todo_engine.agent import TaskContext, run_task  # noqa: E402
from todo_engine.capabilities import scan  # noqa: E402
from todo_engine.parser import Task  # noqa: E402


async def main() -> int:
    caps = scan(ROOT)
    print("--- warnings ---")
    for w in caps.warnings:
        print(f"  ! {w}")
    print("--- manifest ---")
    print(caps.manifest)
    assert any(name == "weekly-report" for name, _, _ in caps.skills), "skill not found"
    assert ("mcp__local__example" in caps.allowed_tools), "example tool not registered"
    assert "local" in caps.mcp_servers

    expected = "TOKEN-" + hashlib.sha256(b"hello-engine").hexdigest()[:12]

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        task = Task(line_no=0, number=1, done=False, hints=["example"],
                    text="Get the official TOKEN for the text 'hello-engine' and write it, "
                         "and nothing else, into token.txt")
        ctx = TaskContext(
            workdir=workdir,
            capability_manifest=caps.manifest,
            mcp_servers=caps.mcp_servers,
            extra_allowed_tools=caps.allowed_tools,
            on_event=lambda s: print(f"  | {s[:120]}"),
        )
        result = await run_task(task, ctx)
        print(f"\nstatus_line: {result.status_line}")

        token_file = workdir / "token.txt"
        assert result.success, "agent did not report success"
        assert token_file.exists(), "token.txt not created"
        content = token_file.read_text(encoding="utf-8").strip()
        print(f"token.txt: {content!r}  expected: {expected!r}")
        assert content == expected, "token mismatch — tool was not actually used"
        assert any("mcp__local__example" in line for line in result.transcript), \
            "transcript shows no mcp__local__example call"

    print("\nCAPABILITIES TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
