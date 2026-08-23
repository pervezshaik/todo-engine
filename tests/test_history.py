import io
from pathlib import Path

import pytest
from rich.console import Console

import todo_engine.history as history
from todo_engine.history import load_history, print_report, record_attempt


def row(
    task: str, success: bool, outcome: str = "done", cost: float = 0.1, **extra: object
) -> dict:
    return {
        "task_number": 1,
        "task_text": task,
        "attempt": 1,
        "outcome": outcome,
        "success": success,
        "duration_s": 10.0,
        "cost_usd": cost,
        **extra,
    }


def test_record_and_load_round_trip(tmp_path: Path) -> None:
    assert load_history(tmp_path) == []
    record_attempt(tmp_path, row("A", True))
    record_attempt(tmp_path, row("B", False, "failed"))
    entries = load_history(tmp_path)
    assert [e["task_text"] for e in entries] == ["A", "B"]
    assert all("ts" in e for e in entries)
    assert (tmp_path / "runs" / "history.jsonl").is_file()


def test_load_tolerates_torn_and_blank_lines(tmp_path: Path) -> None:
    record_attempt(tmp_path, row("A", True))
    path = tmp_path / "runs" / "history.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("\n{not json\n")
    record_attempt(tmp_path, row("B", True))
    assert [e["task_text"] for e in load_history(tmp_path)] == ["A", "B"]


def test_file_is_pruned_beyond_max_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history, "MAX_BYTES", 400)
    for i in range(20):
        record_attempt(tmp_path, row(f"task {i}", True))
    entries = load_history(tmp_path)
    assert 0 < len(entries) < 20
    assert entries[-1]["task_text"] == "task 19"  # newest survive


def test_report_groups_tasks_and_flags_flaky(tmp_path: Path) -> None:
    record_attempt(tmp_path, row("Flaky task", False, "failed", cost=0.1))
    record_attempt(tmp_path, row("Flaky task", True, cost=0.2))
    record_attempt(tmp_path, row("Stable task", True, cost=0.1))
    buf = io.StringIO()
    print_report(tmp_path, Console(file=buf, width=250))
    out = buf.getvalue()
    assert "Task history (3 attempts)" in out
    assert "Flaky task" in out and "Stable task" in out
    assert "failed×1" in out
    assert "yes" in out  # flaky column
    assert "total historical cost: $0.40" in out


def test_report_with_no_history(tmp_path: Path) -> None:
    buf = io.StringIO()
    print_report(tmp_path, Console(file=buf, width=120))
    assert "no history yet" in buf.getvalue()
