from pathlib import Path

import pytest

from todo_engine.parser import (
    Task,
    _set_marker,
    auto_id,
    find_line,
    format_line,
    insert_lines,
    mark_blocked,
    mark_done,
    mark_in_progress,
    mark_pending,
    mark_waiting,
    parse,
    parse_tables,
    split_directives,
)

SAMPLE = """# My todos

Some free-form notes that must survive untouched.

- [ ] First pending task
- [ ] Email the weekly report @use: gmail, xlsx @retries: 2 @verify: off
- [x] Finished task
  - [ ] Indented subtask
* [ ] Star bullet task
- [X] Capital X counts as done
- [~] Interrupted task
- [!] Blocked task
- [>] Waiting on someone @owner: sam
Not a task line
"""


@pytest.fixture
def todo(tmp_path: Path) -> Path:
    p = tmp_path / "todo.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_parse_finds_every_checklist_item_in_order(todo: Path) -> None:
    tasks = parse(todo)
    assert [t.number for t in tasks] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert tasks[0] == Task(line_no=4, text="First pending task", done=False, hints=[], number=1)
    assert tasks[3].text == "Indented subtask"
    assert tasks[4].text == "Star bullet task"
    assert tasks[5].done is True and tasks[5].marker == "x"  # capital X normalized
    assert tasks[6].in_progress is True and tasks[6].done is False
    assert [t.pending for t in tasks] == [True, True, False, True, True, False, True, False, False]
    assert tasks[7].blocked and tasks[7].marker == "!"
    assert tasks[8].waiting and tasks[8].directives == {"owner": "sam"}


def test_indented_lines_are_children_of_the_line_above(todo: Path) -> None:
    tasks = parse(todo)
    child, parent = tasks[3], tasks[2]
    assert child.indent == 2 and parent.indent == 0
    assert child.parent is parent and parent.children == [child]
    assert tasks[4].parent is None  # back at top level
    assert all(t.parent is None for t in tasks if t is not child)


def test_nesting_is_by_indent_depth(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text("- [ ] A\n  - [ ] A1\n    - [ ] A1a\n  - [ ] A2\n- [ ] B\n", encoding="utf-8")
    a, a1, a1a, a2, b = parse(p)
    assert [c.text for c in a.children] == ["A1", "A2"]
    assert a1.children == [a1a] and a1a.parent is a1 and a2.parent is a
    assert b.parent is None and b.children == []


def test_directives_are_parsed_and_stripped_from_text(todo: Path) -> None:
    t = parse(todo)[1]
    assert t.text == "Email the weekly report"
    assert t.hints == ["gmail", "xlsx"]
    assert t.directives == {"use": "gmail, xlsx", "retries": "2", "verify": "off"}


def test_any_directive_key_is_accepted(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text(
        "- [ ] Chase the estimate @owner: sam @due: 2026-08-25 @source: jira:ENG-412 "
        "@depends: f-1, f-2 @id: f-031\n",
        encoding="utf-8",
    )
    t = parse(p)[0]
    assert t.text == "Chase the estimate"
    assert t.directives == {
        "owner": "sam",
        "due": "2026-08-25",
        "source": "jira:ENG-412",
        "depends": "f-1, f-2",
        "id": "f-031",
    }
    assert t.id == "f-031" and t.depends == ["f-1", "f-2"]


def test_flags_and_mentions() -> None:
    text, d = split_directives("Ping @priya about the deck @plan @Model: opus @solo")
    assert text == "Ping @priya about the deck"  # a bare mention is not a directive
    assert d == {"plan": "", "model": "opus", "solo": ""}
    text, d = split_directives("mail x@y.com @after: a-1")
    assert text == "mail x@y.com" and d == {"after": "a-1"}
    text, d = split_directives("no directives here")
    assert text == "no directives here" and d == {}


def test_auto_id_is_stable_and_normalized() -> None:
    t = Task(line_no=0, text="Write  Hello.txt", done=False)
    assert t.id == auto_id("write hello.txt")
    assert t.id.startswith("t-") and len(t.id) == 10
    assert auto_id("a") != auto_id("b")


def test_format_line_round_trips() -> None:
    line = format_line(
        "Child step", {"id": "c-1", "after": "c-0", "plan": ""}, indent=2, marker="~"
    )
    assert line == "  - [~] Child step @id: c-1 @after: c-0 @plan"
    text, d = split_directives(line.split("] ", 1)[1])
    assert text == "Child step" and d == {"id": "c-1", "after": "c-0", "plan": ""}


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


def test_blocked_and_waiting_markers(todo: Path) -> None:
    line = parse(todo)[0].line_no
    mark_blocked(todo, line)
    assert parse(todo)[0].blocked and not parse(todo)[0].pending
    assert "- [!] First pending task" in todo.read_text(encoding="utf-8")
    mark_waiting(todo, line)
    assert parse(todo)[0].waiting
    assert "- [>] First pending task" in todo.read_text(encoding="utf-8")
    mark_pending(todo, line)
    assert parse(todo)[0].pending
    with pytest.raises(ValueError):
        _set_marker(todo, line, "?")


def test_insert_lines_and_find_line(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text("- [ ] parent @id: p\n- [ ] later\n", encoding="utf-8")
    parent, later = parse(p)
    insert_lines(p, parent.line_no, ["  - [ ] child one @id: c1", "  - [ ] child two @id: c2"])
    assert p.read_text(encoding="utf-8") == (
        "- [ ] parent @id: p\n  - [ ] child one @id: c1\n  - [ ] child two @id: c2\n- [ ] later\n"
    )
    tasks = parse(p)
    assert [c.text for c in tasks[0].children] == ["child one", "child two"]
    assert find_line(p, later.id) == 3  # shifted by two
    assert find_line(p, "c2") == 2
    with pytest.raises(LookupError):
        find_line(p, "nope")
    with pytest.raises(IndexError):
        insert_lines(p, 99, ["x"])
    insert_lines(p, -1, ["# heading"])
    assert p.read_text(encoding="utf-8").startswith("# heading\n- [ ] parent")
    empty = tmp_path / "e.md"
    empty.write_text("", encoding="utf-8")
    insert_lines(empty, -1, ["- [ ] first"])
    assert empty.read_text(encoding="utf-8") == "- [ ] first\n"


def test_parse_tables(tmp_path: Path) -> None:
    p = tmp_path / "raid.md"
    p.write_text(
        "# RAID\n\n"
        "| ID | Type | Title |\n|---|:---:|---|\n"
        "| R-4 | Risk | Vendor EOL |\n"
        "| D-3 | Decision |\n"
        "| X-1 | A | B | extra |\n"
        "\nprose | with a pipe but no separator\n\n"
        "## People\n"
        "Handle | Name\n--- | ---\npriya | Priya N.\n",
        encoding="utf-8",
    )
    raid, people = parse_tables(p)
    assert raid.heading == "RAID" and raid.line_no == 2 and raid.headers == ["ID", "Type", "Title"]
    assert raid.rows == [
        {"ID": "R-4", "Type": "Risk", "Title": "Vendor EOL"},
        {"ID": "D-3", "Type": "Decision", "Title": ""},
        {"ID": "X-1", "Type": "A", "Title": "B"},
    ]
    assert people.heading == "People" and people.rows == [{"Handle": "priya", "Name": "Priya N."}]
    assert parse_tables(tmp_path / "raid.md") == [raid, people]


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
