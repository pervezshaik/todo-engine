from pathlib import Path

import pytest

from todo_engine.parser import Task, mark_done, mark_in_progress, mark_pending, parse

SAMPLE = """# My todos

Some free-form notes that must survive untouched.

- [ ] First pending task
- [ ] Email the weekly report @use: gmail, xlsx @retries: 2 @verify: off
- [x] Finished task
  - [ ] Indented subtask
* [ ] Star bullet task
- [X] Capital X counts as done
- [~] Interrupted task
Not a task line
"""


@pytest.fixture
def todo(tmp_path: Path) -> Path:
    p = tmp_path / "todo.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_parse_finds_every_checklist_item_in_order(todo: Path) -> None:
    tasks = parse(todo)
    assert [t.number for t in tasks] == [1, 2, 3, 4, 5, 6, 7]
    assert tasks[0] == Task(line_no=4, text="First pending task", done=False, hints=[], number=1)
    assert tasks[3].text == "Indented subtask"
    assert tasks[4].text == "Star bullet task"
    assert tasks[5].done is True
    assert tasks[6].in_progress is True and tasks[6].done is False


def test_directives_are_parsed_and_stripped_from_text(todo: Path) -> None:
    t = parse(todo)[1]
    assert t.text == "Email the weekly report"
    assert t.hints == ["gmail", "xlsx"]
    assert t.directives == {"use": "gmail, xlsx", "retries": "2", "verify": "off"}


def test_unknown_directive_key_is_left_in_text(tmp_path: Path) -> None:
    # Only the known keys are recognized today (evolution.md proposes opening this up).
    p = tmp_path / "t.md"
    p.write_text("- [ ] Chase the estimate @owner: sam\n", encoding="utf-8")
    assert parse(p)[0].text == "Chase the estimate @owner: sam"


def test_bom_is_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_bytes(b"\xef\xbb\xbf- [ ] BOM task\n")
    assert [t.text for t in parse(p)] == ["BOM task"]


def test_empty_and_non_checklist_files(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text("", encoding="utf-8")
    assert parse(p) == []
    p.write_text("# heading\njust notes\n", encoding="utf-8")
    assert parse(p) == []


def test_mark_done_changes_exactly_one_line(todo: Path) -> None:
    tasks = parse(todo)
    mark_done(todo, tasks[1].line_no)
    after = todo.read_text(encoding="utf-8")
    assert "- [x] Email the weekly report @use: gmail, xlsx @retries: 2 @verify: off" in after
    assert "Some free-form notes that must survive untouched." in after
    assert after.endswith("\n")
    assert parse(todo)[1].done is True
    assert parse(todo)[1].hints == ["gmail", "xlsx"]
    # everything else is byte-identical
    before_lines = SAMPLE.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines)
    assert [
        i for i, (a, b) in enumerate(zip(before_lines, after_lines, strict=False)) if a != b
    ] == [5]


def test_mark_preserves_missing_trailing_newline(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text("- [ ] only task", encoding="utf-8")
    mark_done(p, 0)
    assert p.read_text(encoding="utf-8") == "- [x] only task"


def test_in_progress_lifecycle(todo: Path) -> None:
    line = parse(todo)[0].line_no
    mark_in_progress(todo, line)
    working = parse(todo)[0]
    assert working.in_progress is True and working.done is False
    assert "- [~] First pending task" in todo.read_text(encoding="utf-8")
    mark_pending(todo, line)
    reverted = parse(todo)[0]
    assert reverted.in_progress is False and reverted.done is False
    assert "- [ ] First pending task" in todo.read_text(encoding="utf-8")


def test_set_marker_rereads_file_so_concurrent_edits_survive(todo: Path) -> None:
    line = parse(todo)[0].line_no
    # a user appends a line between parse and write (watch-mode race)
    with todo.open("a", encoding="utf-8") as f:
        f.write("- [ ] Added while running\n")
    mark_done(todo, line)
    text = todo.read_text(encoding="utf-8")
    assert "- [x] First pending task" in text
    assert "- [ ] Added while running" in text


def test_mark_errors(todo: Path) -> None:
    with pytest.raises(ValueError):
        mark_done(todo, 0)  # heading line
    with pytest.raises(IndexError):
        mark_done(todo, 10_000)
