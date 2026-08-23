"""LIVE: the real Haiku verifier must reject a false claim and accept a true one.

Costs real money (~$0.02). Run with:  pytest -m live tests/live/test_live_verifier.py
"""

from pathlib import Path

import pytest

from todo_engine.parser import Task
from todo_engine.verifier import verify

pytestmark = pytest.mark.live


async def test_false_claim_is_rejected(tmp_path: Path) -> None:
    task = Task(line_no=0, number=1, done=False,
                text="Create a file named missing.txt containing the word banana")
    verdict = await verify(task, "I created missing.txt with the word banana. STATUS: done", tmp_path)
    print(f"false claim -> passed={verdict.passed} | {verdict.reason}")
    assert not verdict.passed, "verifier believed a false claim"


async def test_true_claim_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("hello engine\n", encoding="utf-8")
    task = Task(line_no=0, number=2, done=False,
                text="Create a file named real.txt containing the words hello engine")
    verdict = await verify(task, "Created real.txt containing 'hello engine'. STATUS: done", tmp_path)
    print(f"true claim  -> passed={verdict.passed} | {verdict.reason}")
    assert verdict.passed, "verifier rejected an honest claim"
