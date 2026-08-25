from pathlib import Path
from types import SimpleNamespace

from fakes import engine_error, memo, memo_nothing
from todo_engine.memory import _keywords, distill, relevant_memos
from todo_engine.parser import Task

TASK = Task(line_no=0, text="Look up the weather in Hyderabad and save it", done=False, number=3)


def test_keywords_drop_stopwords_and_short_words() -> None:
    assert _keywords("Create the file and write TWO lines for Hyderabad") == {"lines", "hyderabad"}


async def test_distill_nothing_writes_no_memo(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.memo.push(*memo_nothing())
    m = await distill(TASK, "done", "> [tool] Write", tmp_path)
    assert m.path is None and m.cost_usd == 0.0005  # the call still cost something
    assert not (tmp_path / "memory").exists()


async def test_distill_engine_error_writes_no_memo(
    tmp_path: Path, fake_sdk: SimpleNamespace
) -> None:
    fake_sdk.memo.push(*engine_error("overloaded"))
    assert (await distill(TASK, "done", "", tmp_path)).path is None


async def test_distill_writes_memo_and_index(tmp_path: Path, fake_sdk: SimpleNamespace) -> None:
    fake_sdk.memo.push(*memo("- wttr.in/Hyderabad?format=3 gives a one-line forecast"))
    m = await distill(TASK, "final report " * 200, "> [tool] WebFetch", tmp_path)
    path = m.path
    assert path is not None and path.parent == tmp_path / "memory" / "lessons"
    assert m.cost_usd == 0.0005
    assert path.name.endswith("-task-3.md")
    content = path.read_text(encoding="utf-8")
    assert content.startswith(f"# {TASK.text}\n\n")
    assert "wttr.in" in content
    index = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert index.startswith("# Task lessons index")
    assert f"(lessons/{path.name})" in index
    prompt = fake_sdk.memo.prompts[0]
    assert f"TASK: {TASK.text}" in prompt
    assert len(prompt) < 3000  # report and trail are truncated
    assert fake_sdk.memo.options[0].model == "haiku"
    assert fake_sdk.memo.options[0].allowed_tools == []

    # a second memo appends to the existing index
    fake_sdk.memo.push(*memo("second lesson"))
    await distill(TASK, "x", "", tmp_path)
    assert (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8").count("](lessons/") == 2


def _write_memo(root: Path, name: str, text: str) -> None:
    d = root / "memory" / "lessons"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_relevant_memos_ranks_by_keyword_overlap(tmp_path: Path) -> None:
    assert relevant_memos("weather hyderabad", tmp_path) == ""  # no memory dir yet
    _write_memo(tmp_path, "a.md", "# weather\n\nUse wttr.in for Hyderabad weather")
    _write_memo(tmp_path, "b.md", "# git\n\nUse git commit -m for commits")
    _write_memo(tmp_path, "c.md", "# weather api\n\nOpen-Meteo needs lat/long; weather only")
    out = relevant_memos("Summarize Hyderabad weather", tmp_path)
    assert "wttr.in" in out and "Open-Meteo" in out
    assert "git commit" not in out
    assert out.index("wttr.in") < out.index("Open-Meteo")  # higher overlap first
    assert "\n\n---\n\n" in out


def test_relevant_memos_limits(tmp_path: Path) -> None:
    for i in range(5):
        _write_memo(tmp_path, f"m{i}.md", f"# weather {i}\n\n" + ("weather detail " * 100))
    assert relevant_memos("weather", tmp_path, k=1).count("# weather") == 1
    assert len(relevant_memos("weather", tmp_path, k=5, max_chars=1500)) <= 1500
    assert relevant_memos("the and for", tmp_path) == ""  # only stopwords
    assert relevant_memos("kubernetes", tmp_path) == ""  # no overlap
