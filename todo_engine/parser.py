"""Markdown checklist parsing and checkbox rewriting.

The todo file is the source of truth: `- [ ]` lines are pending tasks,
`- [x]` lines are done. Everything else in the file is left untouched.

A task line may end with a capability hint suffix:
    - [ ] email the weekly report @use: gmail, xlsx
The hint names registered capabilities the agent should favor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Tolerates leading whitespace and either "-" or "*" bullets.
# Markers: [ ] pending · [~] in progress (engine-written) · [x] done
_CHECKBOX_RE = re.compile(r"^(\s*[-*]\s+\[)([ xX~])(\]\s+)(.*)$")

# Directive grammar on a task line: `@key: value` suffixes, e.g.
#   - [ ] email the report @use: gmail, xlsx @retries: 2 @verify: off
_DIRECTIVE_KEYS = ("use", "retries", "verify")
_KEYS_ALT = "|".join(_DIRECTIVE_KEYS)
_DIRECTIVE_RE = re.compile(
    rf"\s+@({_KEYS_ALT}):\s*(.*?)(?=\s+@(?:{_KEYS_ALT}):|$)")


@dataclass
class Task:
    line_no: int          # 0-based index into the file's lines
    text: str             # task text with any @directive suffixes stripped
    done: bool
    hints: list[str] = field(default_factory=list)      # from @use:
    directives: dict[str, str] = field(default_factory=dict)
    number: int = 0       # 1-based position among checklist items, for --task N
    in_progress: bool = False  # a leftover [~] counts as pending and reruns


def parse(path: str | Path) -> list[Task]:
    """Return all checklist items in file order (done and pending)."""
    tasks: list[Task] = []
    # utf-8-sig: tolerate a BOM (written by e.g. PowerShell Set-Content -Encoding utf8)
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    for line_no, line in enumerate(lines):
        m = _CHECKBOX_RE.match(line)
        if not m:
            continue
        text = m.group(4).strip()
        directives: dict[str, str] = {}
        first_directive = None
        for dm in _DIRECTIVE_RE.finditer(text):
            if first_directive is None:
                first_directive = dm.start()
            directives[dm.group(1)] = dm.group(2).strip()
        if first_directive is not None:
            text = text[:first_directive].strip()
        hints = [h.strip() for h in directives.get("use", "").split(",") if h.strip()]
        tasks.append(
            Task(
                line_no=line_no,
                text=text,
                done=m.group(2).lower() == "x",
                hints=hints,
                directives=directives,
                number=len(tasks) + 1,
                in_progress=m.group(2) == "~",
            )
        )
    return tasks


def _set_marker(path: str | Path, line_no: int, marker: str) -> None:
    """Rewrite one checklist line's marker (' ', '~', or 'x').

    The file is re-read immediately before writing so that a concurrently
    edited file (watch mode) is never clobbered wholesale; only the one
    line changes.
    """
    p = Path(path)
    content = p.read_text(encoding="utf-8-sig")
    trailing_newline = content.endswith("\n")
    lines = content.splitlines()
    if line_no >= len(lines):
        raise IndexError(f"line {line_no} out of range for {p}")
    m = _CHECKBOX_RE.match(lines[line_no])
    if not m:
        raise ValueError(f"line {line_no} in {p} is not a checklist item: {lines[line_no]!r}")
    lines[line_no] = f"{m.group(1)}{marker}{m.group(3)}{m.group(4)}"
    p.write_text("\n".join(lines) + ("\n" if trailing_newline else ""), encoding="utf-8")


def mark_done(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, "x")


def mark_in_progress(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, "~")


def mark_pending(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, " ")
