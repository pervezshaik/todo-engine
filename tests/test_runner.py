"""Runner orchestration against the fake SDK: retry policy, verifier gate,
checkbox lifecycle, history, memory and watch mode. Every test is $0."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import (
    agent_done,
    agent_failed,
    engine_error,
    memo,
    memo_nothing,
    verdict_fail,
    verdict_pass,
)
from todo_engine.agent import TaskOutcome
from todo_engine.history import load_history
from todo_engine.runner import RunConfig, Runner


def make_runner(tmp_path: Path, todo_text: str, **cfg: object) -> tuple[Runner, Path]:
    todo = tmp_path / "todo.md"
    todo.write_text(todo_text, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    config = RunConfig(todo_file=todo, workdir=work, project_root=tmp_path, **cfg)  # type: ignore[arg-type]
    return Runner(config), todo


def happy_path(sdk: SimpleNamespace) -> None:
    sdk.agent.push(*agent_done())
    sdk.verifier.push(*verdict_pass())
    sdk.memo.push(*memo_nothing())


# --- success & selection ----------------------------------------------------


async def test_success_checks_box_and_records_everything(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, todo = make_runner(tmp_path, "# t\n\n- [ ] Write hello.txt\n")
    happy_path(fake_sdk)

    assert await runner.run() == 0

    assert "- [x] Write hello.txt" in todo.read_text(encoding="utf-8")
    _, res = runner.results[0]
    assert res.success and res.outcome is TaskOutcome.DONE
    assert res.cost_usd == pytest.approx(0.01 + 0.001)  # executor + verifier
    assert runner.completed_summaries == ["Write hello.txt — STATUS: done"]

    rows = load_history(tmp_path)
    assert len(rows) == 1
    assert rows[0]["success"] is True and rows[0]["attempt"] == 1
    assert rows[0]["verifier"] == "VERDICT: pass" and rows[0]["outcome"] == "done"

    logs = list((tmp_path / "runs").glob("*/task-1.md"))
    assert len(logs) == 1 and "Verifier: VERDICT: pass" in logs[0].read_text(encoding="utf-8")
    assert len(fake_sdk.memo.calls) == 1

    out = capsys.readouterr().out
    assert "Picked up this pass" in out and "QUEUED" in out
    assert "[OK] STATUS: done" in out and "Run summary" in out and "total cost" in out


async def test_done_tasks_are_skipped(
    tmp_path: Path, fake_sdk: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    runner, _ = make_runner(tmp_path, "- [x] already done\n")
    assert await runner.run_once() is False
    assert await runner.run() == 0
    assert fake_sdk.agent.calls == []
    assert "nothing to do" in capsys.readouterr().out


async def test_only_task_selection(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] first\n- [ ] second\n", only_task=2)
    happy_path(fake_sdk)
    await runner.run()
    assert len(fake_sdk.agent.calls) == 1 and "TASK: second" in fake_sdk.agent.prompts[0]
    assert todo.read_text(encoding="utf-8") == "- [ ] first\n- [x] second\n"
    assert "HELD" in capsys.readouterr().out

    runner2, _ = make_runner(tmp_path, "- [ ] first\n", only_task=9)
    assert await runner2.run_once() is False
    assert "not found or already done" in capsys.readouterr().out


async def test_in_progress_marker_is_visible_while_running(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt\n")
    seen: dict[str, str] = {}

    def script(prompt: str, options: object) -> list:
        seen["during"] = todo.read_text(encoding="utf-8")
        return agent_done()

    fake_sdk.agent.push_fn(script)
    fake_sdk.verifier.push(*verdict_pass())
    fake_sdk.memo.push(*memo_nothing())
    await runner.run()
    assert seen["during"] == "- [~] Write hello.txt\n"
    assert todo.read_text(encoding="utf-8") == "- [x] Write hello.txt\n"


# --- verifier gate ----------------------------------------------------------


async def test_verifier_rejection_reverts_box(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt @retries: 0\n")
    fake_sdk.agent.push(*agent_done())
    fake_sdk.verifier.push(*verdict_fail("hello.txt is missing"))
    assert await runner.run() == 1
    assert todo.read_text(encoding="utf-8") == "- [ ] Write hello.txt @retries: 0\n"
    _, res = runner.results[0]
    assert not res.success and res.outcome is TaskOutcome.FAILED
    assert "verification:" in res.status_line and "hello.txt is missing" in res.status_line
    row = load_history(tmp_path)[0]
    assert row["success"] is False and row["verifier"] == "VERDICT: fail — hello.txt is missing"
    assert fake_sdk.memo.calls == []  # no lesson from a rejected task


async def test_verify_off_directive_skips_verifier(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] quick note @verify: off\n")
    fake_sdk.agent.push(*agent_done())
    fake_sdk.memo.push(*memo_nothing())
    await runner.run()
    assert fake_sdk.verifier.calls == []
    assert "- [x] quick note" in todo.read_text(encoding="utf-8")
    assert load_history(tmp_path)[0]["verifier"] is None


async def test_no_verify_flag_skips_verifier(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] quick note\n", no_verify=True)
    fake_sdk.agent.push(*agent_done())
    fake_sdk.memo.push(*memo_nothing())
    await runner.run()
    assert fake_sdk.verifier.calls == []
    assert "- [x] quick note" in todo.read_text(encoding="utf-8")


# --- retry policy -----------------------------------------------------------


async def test_reflexion_retry_passes_failure_memo(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] find the config\n")
    fake_sdk.agent.push(*agent_failed("could not find config.yml"))
    happy_path(fake_sdk)
    assert await runner.run() == 0

    assert len(fake_sdk.agent.calls) == 2
    assert "IMPORTANT" not in fake_sdk.agent.prompts[0]
    second = fake_sdk.agent.prompts[1]
    assert "IMPORTANT — a previous attempt at this task failed:" in second
    assert "Attempt 1 ended with: STATUS: failed — could not find config.yml" in second
    assert no_sleep == []  # no backoff for real failures
    rows = load_history(tmp_path)
    assert [(r["attempt"], r["outcome"], r["success"]) for r in rows] == [
        (1, "failed", False),
        (2, "done", True),
    ]
    assert "- [x] find the config" in todo.read_text(encoding="utf-8")


async def test_retries_directive_controls_reflexion_count(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] impossible @retries: 2\n")
    for _ in range(3):
        fake_sdk.agent.push(*agent_failed("nope"))
    assert await runner.run() == 1
    assert len(fake_sdk.agent.calls) == 3
    assert todo.read_text(encoding="utf-8") == "- [ ] impossible @retries: 2\n"


async def test_invalid_retries_directive_falls_back_to_default(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, _ = make_runner(tmp_path, "- [ ] impossible @retries: lots\n")
    fake_sdk.agent.push(*agent_failed("nope"))
    fake_sdk.agent.push(*agent_failed("nope"))
    await runner.run()
    assert len(fake_sdk.agent.calls) == 2  # default of 1 retry


async def test_transient_engine_error_backs_off_then_succeeds(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt\n")
    fake_sdk.agent.push(*engine_error("API Error: 429 rate limit"))
    happy_path(fake_sdk)
    assert await runner.run() == 0
    assert no_sleep == [5]
    assert len(fake_sdk.agent.calls) == 2
    assert "IMPORTANT" not in fake_sdk.agent.prompts[1]  # not a Reflexion retry
    assert [r["outcome"] for r in load_history(tmp_path)] == ["engine_error", "done"]
    assert "transient engine error — retrying in 5s (1/2)" in capsys.readouterr().out
    assert "- [x] Write hello.txt" in todo.read_text(encoding="utf-8")


async def test_transient_errors_exhaust_after_two_retries(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt\n")
    for _ in range(3):
        fake_sdk.agent.push(*engine_error("connection reset"))
    assert await runner.run() == 1
    assert no_sleep == [5, 15]
    assert len(fake_sdk.agent.calls) == 3
    assert runner.results[0][1].outcome is TaskOutcome.ENGINE_ERROR
    assert todo.read_text(encoding="utf-8") == "- [ ] Write hello.txt\n"


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("missing capability: sms", TaskOutcome.MISSING_CAPABILITY),
        ("user declined the command", TaskOutcome.DECLINED),
    ],
)
async def test_missing_capability_and_declined_never_retry(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, reason: str, outcome: TaskOutcome
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] send an sms\n")
    fake_sdk.agent.push(*agent_failed(reason))
    assert await runner.run() == 1
    assert len(fake_sdk.agent.calls) == 1
    assert runner.results[0][1].outcome is outcome
    assert todo.read_text(encoding="utf-8") == "- [ ] send an sms\n"


async def test_engine_exception_is_contained(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt\n- [ ] second\n")
    fake_sdk.agent.push(RuntimeError("boom"))
    happy_path(fake_sdk)
    assert await runner.run() == 1  # one failed, but the run continued
    first, second = (r for _, r in runner.results)
    assert first.outcome is TaskOutcome.ENGINE_ERROR
    assert first.status_line == "STATUS: failed — RuntimeError: boom"
    assert "Engine exception: RuntimeError: boom" in first.transcript
    assert second.success
    assert todo.read_text(encoding="utf-8") == "- [ ] Write hello.txt\n- [x] second\n"


async def test_stop_on_failure(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, todo = make_runner(
        tmp_path, "- [ ] first @retries: 0\n- [ ] second\n", stop_on_failure=True
    )
    fake_sdk.agent.push(*agent_failed("nope"))
    assert await runner.run() == 1
    assert len(fake_sdk.agent.calls) == 1
    assert todo.read_text(encoding="utf-8") == "- [ ] first @retries: 0\n- [ ] second\n"
    assert "stopping: --stop-on-failure" in capsys.readouterr().out


# --- memory -----------------------------------------------------------------


async def test_lessons_flow_into_later_related_tasks(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, _ = make_runner(
        tmp_path,
        "- [ ] Look up the weather in Hyderabad\n- [ ] Summarize the Hyderabad weather forecast\n",
    )
    fake_sdk.agent.push(*agent_done())
    fake_sdk.verifier.push(*verdict_pass())
    fake_sdk.memo.push(*memo("- wttr.in/Hyderabad?format=3 returns a one-line forecast"))
    happy_path(fake_sdk)
    assert await runner.run() == 0

    assert list((tmp_path / "memory" / "lessons").glob("*-task-1.md"))
    second = fake_sdk.agent.prompts[1]
    assert "Lessons from previous related tasks" in second and "wttr.in" in second
    assert "Tasks already completed earlier in this run:" in second
    assert "Look up the weather in Hyderabad — STATUS: done" in second
    out = capsys.readouterr().out
    assert "lesson saved:" in out and "injecting lessons" in out


async def test_memory_failure_never_fails_the_run(
    tmp_path: Path, fake_sdk: SimpleNamespace, no_sleep: list, capsys: pytest.CaptureFixture
) -> None:
    runner, todo = make_runner(tmp_path, "- [ ] Write hello.txt\n")
    fake_sdk.agent.push(*agent_done())
    fake_sdk.verifier.push(*verdict_pass())
    fake_sdk.memo.push(RuntimeError("memo service down"))
    assert await runner.run() == 0
    assert "- [x] Write hello.txt" in todo.read_text(encoding="utf-8")
    assert "lesson distillation skipped" in capsys.readouterr().out


# --- watch mode -------------------------------------------------------------


async def test_watch_mode_picks_up_appended_task(
    tmp_path: Path,
    fake_sdk: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    import todo_engine.runner as runner_mod

    runner, todo = make_runner(tmp_path, "- [x] old\n", watch=True)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 1:  # user appends a task and saves
            with todo.open("a", encoding="utf-8") as f:
                f.write("- [ ] New task\n")
            st = todo.stat()
            os.utime(todo, (st.st_atime + 10, st.st_mtime + 10))
        elif len(sleeps) >= 3:  # Ctrl-C after the pass completed
            raise KeyboardInterrupt

    monkeypatch.setattr(runner_mod, "asyncio", SimpleNamespace(sleep=fake_sleep))
    happy_path(fake_sdk)

    assert await runner.run() == 0
    assert todo.read_text(encoding="utf-8") == "- [x] old\n- [x] New task\n"
    assert sleeps == [2, 0.5, 2]
    out = capsys.readouterr().out
    assert "watch mode" in out and "watch mode stopped" in out
