"""Sequential run orchestration: tasks in, checked boxes + transcripts out."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agent import TaskContext, TaskOutcome, TaskResult, is_transient, run_task
from .capabilities import Capabilities, scan
from .history import record_attempt
from .hooks import make_shell_hooks
from .memory import distill, relevant_memos
from .parser import Task, mark_done, mark_in_progress, mark_pending, parse
from .verifier import verify

TRANSIENT_RETRIES = 2
TRANSIENT_DELAYS_S = (5, 15)


@dataclass
class RunConfig:
    todo_file: Path
    workdir: Path
    project_root: Path
    yolo: bool = False
    confirm: bool = False
    stop_on_failure: bool = False
    max_turns: int = 50
    only_task: int | None = None
    watch: bool = False
    no_verify: bool = False


class Runner:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.console = Console()
        self.run_dir = config.project_root / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.completed_summaries: list[str] = []
        self.results: list[tuple[Task, TaskResult]] = []
        self.capabilities: Capabilities = self._load_capabilities()

    def _load_capabilities(self) -> Capabilities:
        caps = scan(self.config.project_root)
        for warning in caps.warnings:
            self.console.print(f"[yellow]registry warning:[/yellow] {warning}")
        if caps.manifest:
            names = (
                [n for n, _, _ in caps.skills]
                + [f"mcp__local__{n}" for n, _ in caps.tools]
                + [n for n, _ in caps.servers]
            )
            self.console.print(f"[dim]capabilities registered: {', '.join(names)}[/dim]")
        return caps

    async def run_once(self) -> bool:
        """Process all pending tasks once. Returns True if anything ran."""
        tasks = parse(self.config.todo_file)
        pending = [t for t in tasks if t.pending]
        if self.config.only_task is not None:
            pending = [t for t in pending if t.number == self.config.only_task]
            if not pending:
                self.console.print(
                    f"[red]task {self.config.only_task} not found or already done[/red]"
                )
                return False
        if not pending:
            return False
        self._print_queue(tasks, pending)

        for task in pending:
            await self._run_one(task)
            if self.config.stop_on_failure and not self.results[-1][1].success:
                self.console.print("[red]stopping: --stop-on-failure[/red]")
                break
        return True

    def _print_queue(self, tasks: list[Task], pending: list[Task]) -> None:
        """Show what this pass picked up: queued vs done vs filtered out."""
        pending_numbers = {t.number for t in pending}
        self.console.print("[bold]Picked up this pass:[/bold]")
        for t in tasks:
            if t.number in pending_numbers:
                note = (
                    " [yellow](interrupted earlier — rerunning)[/yellow]" if t.in_progress else ""
                )
                self.console.print(f"  [cyan]QUEUED[/cyan]  {t.number}. {t.text}{note}")
            elif t.done:
                self.console.print(f"  [dim]DONE    {t.number}. {t.text} (skipped)[/dim]")
            elif t.blocked:
                self.console.print(f"  [yellow]HELD    {t.number}. {t.text} ([!] blocked)[/yellow]")
            elif t.waiting:
                self.console.print(f"  [dim]HELD    {t.number}. {t.text} ([>] waiting)[/dim]")
            else:
                self.console.print(
                    f"  [dim]HELD    {t.number}. {t.text} (not selected by --task)[/dim]"
                )

    async def _run_one(self, task: Task) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.run_dir / f"task-{task.number}.md"
        shell_log = self.run_dir / f"task-{task.number}.commands.log"

        # visible in the todo file itself: this line is being worked on
        mark_in_progress(self.config.todo_file, task.line_no)
        self.console.rule(f"[bold cyan]WORKING[/bold cyan] Task {task.number}: {task.text}")

        lessons = relevant_memos(task.text, self.config.project_root)
        if lessons:
            self.console.print("[dim]injecting lessons from previous related tasks[/dim]")
        try:
            max_reflexion = int(task.directives.get("retries", "1"))
        except ValueError:
            max_reflexion = 1
        verify_enabled = (
            not self.config.no_verify and task.directives.get("verify", "on").lower() != "off"
        )

        attempt = 0
        transient_used = 0
        reflexion_used = 0
        failure_memo = ""
        result: TaskResult

        while True:
            attempt += 1
            ctx = TaskContext(
                workdir=self.config.workdir,
                yolo=self.config.yolo,
                max_turns=self.config.max_turns,
                capability_manifest=self.capabilities.manifest,
                mcp_servers=self.capabilities.mcp_servers,
                extra_allowed_tools=self.capabilities.allowed_tools,
                hooks=make_shell_hooks(shell_log, self.config.confirm),
                completed_summaries=self.completed_summaries,
                lessons=lessons,
                failure_memo=failure_memo,
                on_event=lambda line: self.console.print(f"[dim]| {line}[/dim]"),
            )

            try:
                result = await run_task(task, ctx)
            except Exception as exc:  # noqa: BLE001 - a task failure must not kill the run
                result = TaskResult(
                    success=False,
                    outcome=TaskOutcome.ENGINE_ERROR,
                    status_line=f"STATUS: failed — {type(exc).__name__}: {exc}",
                    final_text="",
                    cost_usd=None,
                    duration_s=0.0,
                    transcript=[
                        f"# Task {task.number}: {task.text}",
                        "",
                        f"Engine exception: {type(exc).__name__}: {exc}",
                    ],
                    error_detail=str(exc),
                )

            # independent verification before trusting a claimed success
            verdict_reason = None
            if result.success and verify_enabled:
                self.console.print("[dim]verifying result...[/dim]")
                verdict = await verify(task, result.final_text, self.config.workdir)
                verdict_reason = verdict.reason
                if verdict.cost_usd:
                    result.cost_usd = (result.cost_usd or 0.0) + verdict.cost_usd
                result.transcript += ["", f"Verifier: {verdict.reason}"]
                if not verdict.passed:
                    result.success = False
                    result.outcome = TaskOutcome.FAILED
                    result.status_line = f"STATUS: failed — verification: {verdict.reason}"

            record_attempt(
                self.config.project_root,
                {
                    "task_number": task.number,
                    "task_text": task.text,
                    "attempt": attempt,
                    "outcome": result.outcome.value,
                    "success": result.success,
                    "duration_s": round(result.duration_s, 1),
                    "cost_usd": result.cost_usd,
                    "verifier": verdict_reason,
                    "status_line": result.status_line[:300],
                    "run_dir": str(self.run_dir),
                },
            )

            if result.success:
                break

            # retry policy by outcome
            if (
                result.outcome is TaskOutcome.ENGINE_ERROR
                and is_transient(result.error_detail)
                and transient_used < TRANSIENT_RETRIES
            ):
                delay = TRANSIENT_DELAYS_S[transient_used]
                transient_used += 1
                self.console.print(
                    f"[yellow]transient engine error — retrying in {delay}s "
                    f"({transient_used}/{TRANSIENT_RETRIES})[/yellow]"
                )
                await asyncio.sleep(delay)
                continue
            if (
                result.outcome in (TaskOutcome.FAILED, TaskOutcome.TIMEOUT)
                and reflexion_used < max_reflexion
            ):
                reflexion_used += 1
                failure_memo = (
                    f"Attempt {attempt} ended with: {result.status_line}\n"
                    f"Final message excerpt: {result.final_text[-600:]}"
                )
                self.console.print(
                    f"[yellow]retrying with failure analysis "
                    f"(retry {reflexion_used}/{max_reflexion})[/yellow]"
                )
                continue
            break  # missing_capability / declined / retries exhausted

        log_path.write_text("\n".join(result.transcript) + "\n", encoding="utf-8")
        self.results.append((task, result))

        if result.success:
            mark_done(self.config.todo_file, task.line_no)
            self.completed_summaries.append(f"{task.text} — {result.status_line}")
            self.console.print(f"[green][OK][/green] {result.status_line}")
            # distill a reusable lesson for future runs
            tool_trail = "\n".join(line for line in result.transcript if line.startswith("> "))[
                -1200:
            ]
            try:
                memo_path = await distill(
                    task, result.final_text, tool_trail, self.config.project_root
                )
                if memo_path:
                    self.console.print(f"[dim]lesson saved: {memo_path.name}[/dim]")
            except Exception as exc:  # noqa: BLE001 - memory must never fail the run
                self.console.print(f"[dim]lesson distillation skipped: {exc}[/dim]")
        else:
            mark_pending(self.config.todo_file, task.line_no)  # revert the [~] marker
            self.console.print(f"[red][FAILED][/red] ({result.outcome.value}) {result.status_line}")
        self.console.print(f"[dim]log: {log_path}[/dim]")

    def print_summary(self) -> None:
        if not self.results:
            self.console.print("[dim]nothing to do — no pending tasks[/dim]")
            return
        table = Table(title="Run summary")
        table.add_column("#", justify="right")
        table.add_column("Task")
        table.add_column("Status")
        table.add_column("Cost", justify="right")
        table.add_column("Time", justify="right")
        total_cost = 0.0
        for task, result in self.results:
            total_cost += result.cost_usd or 0.0
            table.add_row(
                str(task.number),
                task.text[:60],
                "[green]done[/green]" if result.success else f"[red]{result.outcome.value}[/red]",
                f"${result.cost_usd:.4f}" if result.cost_usd is not None else "-",
                f"{result.duration_s:.0f}s",
            )
        self.console.print(table)
        self.console.print(f"total cost: ${total_cost:.4f} · logs: {self.run_dir}")

    async def run(self) -> int:
        await self.run_once()
        self.print_summary()
        if self.config.watch:
            await self._watch_loop()
        return 0 if all(r.success for _, r in self.results) else 1

    async def _watch_loop(self) -> None:
        self.console.print(
            "\n[bold]watch mode[/bold] — save new '- [ ]' lines "
            f"to {self.config.todo_file.name} to run them (Ctrl-C to exit)"
        )
        last_mtime = self.config.todo_file.stat().st_mtime
        try:
            while True:
                await asyncio.sleep(2)
                mtime = self.config.todo_file.stat().st_mtime
                if mtime == last_mtime:
                    continue
                # settle briefly so we don't read a half-saved file
                await asyncio.sleep(0.5)
                if await self.run_once():
                    self.print_summary()
                # take the mtime AFTER running, so our own checkbox writes
                # don't retrigger a pass
                last_mtime = self.config.todo_file.stat().st_mtime
        except KeyboardInterrupt:
            self.console.print("[dim]watch mode stopped[/dim]")
