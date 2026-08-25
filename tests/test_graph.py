from pathlib import Path

from todo_engine.graph import dependencies, plan
from todo_engine.parser import parse


def _plan(tmp_path: Path, text: str) -> tuple[list[list[str]], list[tuple[str, str]]]:
    p = tmp_path / "t.md"
    p.write_text(text, encoding="utf-8")
    tasks = parse(p)
    result = plan([t for t in tasks if t.pending], tasks)
    return (
        [[t.text for t in wave] for wave in result.waves],
        [(t.text, reason) for t, reason in result.held],
    )


def test_no_dependencies_is_one_wave_in_file_order(tmp_path: Path) -> None:
    waves, held = _plan(tmp_path, "- [ ] a\n- [x] b\n- [ ] c\n")
    assert waves == [["a", "c"]] and held == []


def test_depends_orders_into_waves(tmp_path: Path) -> None:
    waves, held = _plan(
        tmp_path,
        "- [ ] deploy @id: d @depends: build, test\n"
        "- [ ] build @id: build\n"
        "- [ ] test @id: test @after: build\n"
        "- [ ] docs\n",
    )
    assert waves == [["build", "docs"], ["test"], ["deploy"]] and held == []


def test_done_dependency_is_satisfied(tmp_path: Path) -> None:
    waves, held = _plan(tmp_path, "- [x] build @id: build\n- [ ] test @depends: build\n")
    assert waves == [["test"]] and held == []


def test_unknown_blocked_waiting_and_duplicate_ids_are_held(tmp_path: Path) -> None:
    waves, held = _plan(
        tmp_path,
        "- [ ] a @id: a @depends: nope\n"
        "- [!] b @id: b\n"
        "- [ ] c @depends: b\n"
        "- [>] w @id: w\n"
        "- [ ] d @after: w\n"
        "- [ ] same @id: dup\n"
        "- [ ] same @id: dup\n"
        "- [ ] e @depends: a\n"
        "- [ ] ok\n",
    )
    assert waves == [["ok"]]
    assert held == [
        ("a", "unknown dependency 'nope'"),
        ("c", "dependency 'b' is blocked"),
        ("d", "dependency 'w' is waiting"),
        ("same", "duplicate id 'dup' — add a unique @id:"),
        ("same", "duplicate id 'dup' — add a unique @id:"),
        ("e", "depends on held task 'a'"),
    ]


def test_cycle_is_held_not_run(tmp_path: Path) -> None:
    waves, held = _plan(
        tmp_path,
        "- [ ] a @id: a @depends: b\n- [ ] b @id: b @depends: a\n"
        "- [ ] c @id: c @depends: a\n- [ ] free\n",
    )
    assert waves == [["free"]]
    assert held == [
        ("a", "dependency cycle via 'b'"),
        ("b", "dependency cycle via 'a'"),
        ("c", "depends on held task 'a'"),
    ]


def test_children_run_before_their_parent(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text(
        "- [ ] parent\n  - [ ] step one\n  - [x] step two\n  - [ ] step three\n- [ ] other\n"
    )
    tasks = parse(p)
    assert dependencies(tasks[0]) == [tasks[1].id, tasks[2].id, tasks[3].id]
    result = plan([t for t in tasks if t.pending], tasks)
    assert [[t.text for t in w] for w in result.waves] == [
        ["step one", "step three", "other"],
        ["parent"],
    ]
    assert result.held == []
