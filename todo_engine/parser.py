"""Markdown checklist parsing and line rewriting.

The todo file is the source of truth. Every checklist line is a work item:

    - [ ] pending          - [~] in progress (engine-written)
    - [x] done             - [!] blocked / needs a human decision
    - [>] waiting on someone else (set after a nudge is sent)

Everything else in the file is left untouched. Indented checklist lines are
children of the nearest less-indented checklist line above them.

A task line may end with ``@key: value`` directives and a few valueless
flags (``@plan``, ``@solo``):

    - [ ] email the weekly report @use: gmail, xlsx @retries: 2 @owner: sam @id: f-031

Any key is accepted (the grammar is open — roles consume the keys they know).
A bare ``@name`` that is not a known flag is left in the text as a mention.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# Markers a checklist line may carry (one char between the brackets).
MARKER_PENDING = " "
MARKER_IN_PROGRESS = "~"
MARKER_DONE = "x"
MARKER_BLOCKED = "!"
MARKER_WAITING = ">"
MARKERS = " xX~!>"

# Tolerates leading whitespace and either "-" or "*" bullets.
_CHECKBOX_RE = re.compile(rf"^(\s*[-*]\s+\[)([{MARKERS}])(\]\s+)(.*)$")

# Directive grammar: `@key: value` with any key, plus a closed set of
# valueless flags. A value runs until the next directive or end of line.
_KEY = r"[A-Za-z][A-Za-z0-9_-]*"
FLAG_KEYS = ("plan", "solo")
_FLAGS = "|".join(FLAG_KEYS)
_DIRECTIVE_RE = re.compile(
    rf"\s+@(?:({_KEY}):[ \t]*(.*?)|({_FLAGS}))"
    rf"(?=\s+@(?:{_KEY}:|(?:{_FLAGS})(?=\s|$))|$)"
)

_WS_RE = re.compile(r"\s+")


def auto_id(text: str) -> str:
    """Stable identity for a task without an explicit ``@id:`` — a short hash
    of the whitespace-normalized, case-folded text."""
    normalized = _WS_RE.sub(" ", text).strip().lower()
    return "t-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


@dataclass(eq=True)
class Task:
    line_no: int  # 0-based index into the file's lines
    text: str  # task text with any @directive suffixes stripped
    done: bool
    hints: list[str] = field(default_factory=list)  # from @use:
    directives: dict[str, str] = field(default_factory=dict)
    number: int = 0  # 1-based position among checklist items, for --task N
    in_progress: bool = False  # a leftover [~] counts as pending and reruns
    marker: str = MARKER_PENDING
    indent: int = 0  # leading whitespace width; children are deeper than parents
    parent: Task | None = field(default=None, repr=False, compare=False)
    children: list[Task] = field(default_factory=list, repr=False, compare=False)

    @property
    def id(self) -> str:
        """``@id:`` if given, else a stable hash of the text."""
        return self.directives.get("id") or auto_id(self.text)

    @property
    def blocked(self) -> bool:
        return self.marker == MARKER_BLOCKED

    @property
    def waiting(self) -> bool:
        return self.marker == MARKER_WAITING

    @property
    def pending(self) -> bool:
        """Runnable by the engine: ``[ ]`` or a leftover ``[~]``."""
        return self.marker in (MARKER_PENDING, MARKER_IN_PROGRESS)

    @property
    def depends(self) -> list[str]:
        """Ids named by ``@depends:`` / ``@after:`` (comma separated)."""
        raw = self.directives.get("depends", "") or self.directives.get("after", "")
        return [d.strip() for d in raw.split(",") if d.strip()]

    def has_flag(self, name: str) -> bool:
        return name in self.directives

    def __hash__(self) -> int:
        return hash((self.line_no, self.text))


def split_directives(body: str) -> tuple[str, dict[str, str]]:
    """Split a checklist body into (text, directives). Flags map to ``""``."""
    directives: dict[str, str] = {}
    first_directive = None
    for dm in _DIRECTIVE_RE.finditer(body):
        if first_directive is None:
            first_directive = dm.start()
        if dm.group(3):
            directives[dm.group(3).lower()] = ""
        else:
            directives[dm.group(1).lower()] = dm.group(2).strip()
    text = body[:first_directive].strip() if first_directive is not None else body.strip()
    return text, directives


def format_line(text: str, directives: dict[str, str], indent: int = 0, marker: str = " ") -> str:
    """Render a checklist line the way :func:`parse` will read it back."""
    parts = [f"{' ' * indent}- [{marker}] {text}"]
    for key, value in directives.items():
        parts.append(f"@{key}" if value == "" and key in FLAG_KEYS else f"@{key}: {value}")
    return " ".join(parts)


def parse(path: str | Path) -> list[Task]:
    """Return all checklist items in file order (every marker), parents linked."""
    tasks: list[Task] = []
    stack: list[Task] = []  # open ancestors, shallowest first
    # utf-8-sig: tolerate a BOM (written by e.g. PowerShell Set-Content -Encoding utf8)
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    for line_no, line in enumerate(lines):
        m = _CHECKBOX_RE.match(line)
        if not m:
            continue
        text, directives = split_directives(m.group(4).strip())
        hints = [h.strip() for h in directives.get("use", "").split(",") if h.strip()]
        marker = m.group(2)
        indent = len(m.group(1)) - len(m.group(1).lstrip())
        task = Task(
            line_no=line_no,
            text=text,
            done=marker.lower() == MARKER_DONE,
            hints=hints,
            directives=directives,
            number=len(tasks) + 1,
            in_progress=marker == MARKER_IN_PROGRESS,
            marker=marker.lower() if marker == "X" else marker,
            indent=indent,
        )
        while stack and stack[-1].indent >= indent:
            stack.pop()
        if stack:
            task.parent = stack[-1]
            stack[-1].children.append(task)
        stack.append(task)
        tasks.append(task)
    return tasks


def _read(p: Path) -> tuple[list[str], bool]:
    content = p.read_text(encoding="utf-8-sig")
    return content.splitlines(), content.endswith("\n")


def _write(p: Path, lines: list[str], trailing_newline: bool) -> None:
    p.write_text("\n".join(lines) + ("\n" if trailing_newline else ""), encoding="utf-8")


def _set_marker(path: str | Path, line_no: int, marker: str) -> None:
    """Rewrite one checklist line's marker.

    The file is re-read immediately before writing so that a concurrently
    edited file (watch mode) is never clobbered wholesale; only the one
    line changes.
    """
    if marker not in MARKERS:
        raise ValueError(f"unknown marker {marker!r}")
    p = Path(path)
    lines, trailing_newline = _read(p)
    if line_no >= len(lines):
        raise IndexError(f"line {line_no} out of range for {p}")
    m = _CHECKBOX_RE.match(lines[line_no])
    if not m:
        raise ValueError(f"line {line_no} in {p} is not a checklist item: {lines[line_no]!r}")
    lines[line_no] = f"{m.group(1)}{marker}{m.group(3)}{m.group(4)}"
    _write(p, lines, trailing_newline)


def mark_done(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, MARKER_DONE)


def mark_in_progress(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, MARKER_IN_PROGRESS)


def mark_pending(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, MARKER_PENDING)


def mark_blocked(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, MARKER_BLOCKED)


def mark_waiting(path: str | Path, line_no: int) -> None:
    _set_marker(path, line_no, MARKER_WAITING)


def insert_lines(path: str | Path, after_line_no: int, new_lines: list[str]) -> None:
    """Insert ``new_lines`` directly after line ``after_line_no`` (``-1`` = at top).

    Re-reads before writing, like :func:`_set_marker`. Every ``Task.line_no``
    below the insertion point is stale afterwards — re-``parse`` or use
    :func:`find_line` to re-resolve by id.
    """
    p = Path(path)
    lines, trailing_newline = _read(p)
    if after_line_no >= len(lines) or after_line_no < -1:
        raise IndexError(f"line {after_line_no} out of range for {p}")
    was_empty = not lines
    lines[after_line_no + 1 : after_line_no + 1] = list(new_lines)
    _write(p, lines, trailing_newline or was_empty)


def find_line(path: str | Path, task_id: str) -> int:
    """Current line number of the task with ``task_id`` (re-parses the file)."""
    for task in parse(path):
        if task.id == task_id:
            return task.line_no
    raise LookupError(f"no task with id {task_id!r} in {path}")


# --- pipe tables ------------------------------------------------------------

_HEADING_RE = re.compile(r"^#+\s+(.*?)\s*#*\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass
class MdTable:
    heading: str  # nearest markdown heading above the table ("" if none)
    line_no: int  # 0-based line of the header row
    headers: list[str]
    rows: list[dict[str, str]]


def _split_row(line: str) -> list[str]:
    cells = line.strip()
    if cells.startswith("|"):
        cells = cells[1:]
    if cells.endswith("|"):
        cells = cells[:-1]
    return [c.strip() for c in cells.split("|")]


def parse_tables(path: str | Path) -> list[MdTable]:
    """Return every pipe table in the file as header-keyed row dicts.

    Used for ``raid.md``, ``people.md`` and milestone tables. Rows shorter
    than the header are padded with ``""``; longer rows are truncated.
    """
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    tables: list[MdTable] = []
    heading = ""
    i = 0
    while i < len(lines):
        hm = _HEADING_RE.match(lines[i])
        if hm:
            heading = hm.group(1)
            i += 1
            continue
        if "|" in lines[i] and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            headers = _split_row(lines[i])
            table = MdTable(heading=heading, line_no=i, headers=headers, rows=[])
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = _split_row(lines[i])
                cells = (cells + [""] * len(headers))[: len(headers)]
                table.rows.append(dict(zip(headers, cells, strict=True)))
                i += 1
            tables.append(table)
            continue
        i += 1
    return tables
