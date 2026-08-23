"""Run history: one JSON line per task attempt, plus the aggregated report.

Every attempt (including retries and verifier rejections) is appended to
``runs/history.jsonl`` so the engine has a queryable record across runs:
success rates, cost totals, failure classes, and flaky-task detection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

HISTORY_FILE = "history.jsonl"
MAX_BYTES = 5 * 1024 * 1024  # prune oldest half beyond this


def _history_path(project_root: Path) -> Path:
    return project_root / "runs" / HISTORY_FILE


def record_attempt(project_root: Path, entry: dict[str, Any]) -> None:
    path = _history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if path.stat().st_size > MAX_BYTES:
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")


def load_history(project_root: Path) -> list[dict[str, Any]]:
    path = _history_path(project_root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a torn write
    return entries


def print_report(project_root: Path, console: Console | None = None) -> None:
    console = console or Console()
    entries = load_history(project_root)
    if not entries:
        console.print("[dim]no history yet — run some tasks first[/dim]")
        return

    by_task: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_task.setdefault(e.get("task_text", "?"), []).append(e)

    table = Table(title=f"Task history ({len(entries)} attempts)")
    table.add_column("Task")
    table.add_column("Attempts", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Failure classes")
    table.add_column("Cost", justify="right")
    table.add_column("Avg time", justify="right")
    table.add_column("Flaky?")

    total_cost = 0.0
    for text, attempts in by_task.items():
        successes = [a for a in attempts if a.get("success")]
        failures = [a for a in attempts if not a.get("success")]
        classes: dict[str, int] = {}
        for a in failures:
            outcome = a.get("outcome", "failed")
            classes[outcome] = classes.get(outcome, 0) + 1
        cost = sum(a.get("cost_usd") or 0.0 for a in attempts)
        total_cost += cost
        durations = [a.get("duration_s") or 0.0 for a in attempts]
        # flaky = failed at least once but eventually succeeded
        flaky = bool(failures) and bool(successes)
        table.add_row(
            text[:55],
            str(len(attempts)),
            f"{len(successes)}/{len(attempts)}",
            ", ".join(f"{k}×{v}" for k, v in classes.items()) or "-",
            f"${cost:.2f}",
            f"{sum(durations) / len(durations):.0f}s" if durations else "-",
            "[yellow]yes[/yellow]" if flaky else "no",
        )

    console.print(table)
    console.print(f"total historical cost: ${total_cost:.2f} · file: {_history_path(project_root)}")
