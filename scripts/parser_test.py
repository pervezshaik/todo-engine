"""Self-test for todo_engine.parser: parse + hints + mark_done round-trip."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from todo_engine.parser import (  # noqa: E402
    Task, mark_done, mark_in_progress, mark_pending, parse,
)

SAMPLE = """# My todos

Some free-form notes that must survive untouched.

- [ ] First pending task
- [ ] Email the weekly report @use: gmail, xlsx @retries: 2 @verify: off
- [x] Finished task
  - [ ] Indented subtask
* [ ] Star bullet task
Not a task line
"""

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "todo.md"
    p.write_text(SAMPLE, encoding="utf-8")

    tasks = parse(p)
    assert len(tasks) == 5, tasks
    assert [t.number for t in tasks] == [1, 2, 3, 4, 5]
    assert tasks[0] == Task(line_no=4, text="First pending task", done=False, hints=[], number=1)
    assert tasks[1].text == "Email the weekly report"
    assert tasks[1].hints == ["gmail", "xlsx"]
    assert tasks[1].directives == {"use": "gmail, xlsx", "retries": "2", "verify": "off"}
    assert tasks[2].done is True
    assert tasks[3].text == "Indented subtask"
    assert tasks[4].text == "Star bullet task"

    # mark_done flips exactly one line, preserving everything else
    mark_done(p, tasks[1].line_no)
    after = p.read_text(encoding="utf-8")
    assert "- [x] Email the weekly report @use: gmail, xlsx @retries: 2 @verify: off" in after
    assert "Some free-form notes that must survive untouched." in after
    assert after.count("[x]") == 2
    assert after.endswith("\n")

    reparsed = parse(p)
    assert reparsed[1].done is True
    assert reparsed[1].hints == ["gmail", "xlsx"]

    # in-progress marker lifecycle: [ ] -> [~] -> [ ] and [~] parses as pending
    mark_in_progress(p, tasks[0].line_no)
    working = parse(p)[0]
    assert working.in_progress is True and working.done is False
    assert "- [~] First pending task" in p.read_text(encoding="utf-8")
    mark_pending(p, tasks[0].line_no)
    reverted = parse(p)[0]
    assert reverted.in_progress is False and reverted.done is False

    # errors
    try:
        mark_done(p, 0)  # heading line
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

print("PARSER SELF-TEST PASSED")
