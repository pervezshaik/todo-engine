"""CLI entry point: todo-engine todo.md [flags]"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .runner import RunConfig, Runner


def main() -> None:
    # Windows consoles may default to cp1252, which cannot print agent output
    # (unicode arrows, non-Latin text). Force UTF-8 with replacement.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - non-reconfigurable stream (piped, etc.)
                pass
    parser = argparse.ArgumentParser(
        prog="todo-engine",
        description="Run each unchecked task in a markdown todo file with an "
                    "autonomous Claude agent. Uses your Claude Code login — "
                    "no API key needed.",
    )
    parser.add_argument("todo_file", type=Path, help="markdown checklist file (e.g. todo.md)")
    parser.add_argument("--workdir", type=Path, default=Path.cwd(),
                        help="directory agents operate in (default: current dir)")
    parser.add_argument("--task", type=int, default=None, metavar="N",
                        help="run only the Nth checklist item")
    parser.add_argument("--watch", action="store_true",
                        help="keep running; process new '- [ ]' lines on file save")
    parser.add_argument("--confirm", action="store_true",
                        help="ask y/n before every shell command an agent runs")
    parser.add_argument("--yolo", action="store_true",
                        help="fully autonomous: no permission gates at all")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="halt the run at the first failed task")
    parser.add_argument("--max-turns", type=int, default=50, metavar="N",
                        help="agent turn cap per task (default 50)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the independent verification pass before checking a box")
    parser.add_argument("--report", action="store_true",
                        help="print the run-history report for this todo file's project and exit")
    args = parser.parse_args()

    todo_file = args.todo_file.resolve()
    if not todo_file.is_file():
        parser.error(f"todo file not found: {todo_file}")

    if args.report:
        from .history import print_report
        print_report(todo_file.parent)
        sys.exit(0)

    if args.confirm and args.yolo:
        parser.error("--confirm and --yolo are mutually exclusive")

    # capability registries (skills/, tools/, mcp_config.json) live next to the todo file
    config = RunConfig(
        todo_file=todo_file,
        workdir=args.workdir.resolve(),
        project_root=todo_file.parent,
        yolo=args.yolo,
        confirm=args.confirm,
        stop_on_failure=args.stop_on_failure,
        max_turns=args.max_turns,
        only_task=args.task,
        watch=args.watch,
        no_verify=args.no_verify,
    )
    sys.exit(asyncio.run(Runner(config).run()))


if __name__ == "__main__":
    main()
