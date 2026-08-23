import sys
from pathlib import Path

import pytest

import todo_engine.__main__ as cli
import todo_engine.history as history


def run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["todo-engine", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0)


def test_missing_todo_file_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert run_cli(monkeypatch, str(tmp_path / "nope.md")) == 2
    assert "todo file not found" in capsys.readouterr().err


def test_confirm_and_yolo_are_exclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    todo = tmp_path / "todo.md"
    todo.write_text("- [ ] x\n", encoding="utf-8")
    assert run_cli(monkeypatch, str(todo), "--confirm", "--yolo") == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_report_flag_prints_report_and_exits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    todo = tmp_path / "todo.md"
    todo.write_text("- [ ] x\n", encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(history, "print_report", lambda root, console=None: seen.append(root))
    assert run_cli(monkeypatch, str(todo), "--report") == 0
    assert seen == [tmp_path]


def test_run_builds_config_and_exits_with_runner_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    todo = tmp_path / "todo.md"
    todo.write_text("- [ ] x\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, config: object) -> None:
            captured["config"] = config

        async def run(self) -> int:
            return 3

    monkeypatch.setattr(cli, "Runner", FakeRunner)
    code = run_cli(
        monkeypatch,
        str(todo),
        "--workdir",
        str(work),
        "--yolo",
        "--watch",
        "--task",
        "2",
        "--max-turns",
        "9",
        "--stop-on-failure",
        "--no-verify",
    )
    assert code == 3
    cfg = captured["config"]
    assert cfg.todo_file == todo.resolve() and cfg.project_root == tmp_path.resolve()  # type: ignore[attr-defined]
    assert cfg.workdir == work.resolve() and cfg.yolo and cfg.watch  # type: ignore[attr-defined]
    assert cfg.only_task == 2 and cfg.max_turns == 9  # type: ignore[attr-defined]
    assert cfg.stop_on_failure and cfg.no_verify and not cfg.confirm  # type: ignore[attr-defined]
