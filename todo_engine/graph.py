"""Dependency graph over checklist items: ``@depends:`` edges + parent/child.

A task runs only after everything it depends on is ``[x]``. Dependencies are
named by id (``@id:`` or the automatic text hash). A parent line implicitly
depends on its indented children — children are the steps, the parent is the
integration. Waves are computed with Kahn's algorithm; anything unsatisfiable
this pass (unknown id, cycle, dependency that is blocked/waiting) is *held*
with a reason instead of run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import Task


@dataclass
class Plan:
    waves: list[list[Task]] = field(default_factory=list)  # run wave by wave, in order
    held: list[tuple[Task, str]] = field(default_factory=list)  # not runnable + why


def dependencies(task: Task) -> list[str]:
    """Explicit ``@depends``/``@after`` ids plus the implicit child ids."""
    deps = list(task.depends)
    for child in task.children:
        if child.id not in deps:
            deps.append(child.id)
    return deps


def plan(pending: list[Task], all_tasks: list[Task]) -> Plan:
    """Order ``pending`` into dependency waves; hold what cannot run this pass."""
    by_id: dict[str, Task] = {}
    duplicates: set[str] = set()
    for t in all_tasks:
        if t.id in by_id:
            duplicates.add(t.id)
        by_id.setdefault(t.id, t)

    result = Plan()
    pending_ids = {t.id for t in pending}
    edges: dict[str, list[str]] = {}  # task id -> pending ids it waits for
    candidates: list[Task] = []
    for t in pending:
        if t.id in duplicates:
            result.held.append((t, f"duplicate id {t.id!r} — add a unique @id:"))
            continue
        reason = None
        waits: list[str] = []
        for dep_id in dependencies(t):
            dep = by_id.get(dep_id)
            if dep is None:
                reason = f"unknown dependency {dep_id!r}"
                break
            if dep.done:
                continue
            if dep_id in pending_ids:
                waits.append(dep_id)
            else:
                reason = f"dependency {dep_id!r} is {'blocked' if dep.blocked else 'waiting'}"
                break
        if reason:
            result.held.append((t, reason))
        else:
            edges[t.id] = waits
            candidates.append(t)

    # Kahn's algorithm in waves; whatever never becomes ready is in a cycle
    # (or depends on a held task) — held with a reason, never run.
    done_ids: set[str] = set()
    remaining = list(candidates)
    while remaining:
        ready = [t for t in remaining if all(d in done_ids for d in edges[t.id])]
        if not ready:
            break
        result.waves.append(ready)
        done_ids.update(t.id for t in ready)
        remaining = [t for t in remaining if t.id not in done_ids]
    held_ids = {t.id for t, _ in result.held}
    stuck = {t.id: [d for d in edges[t.id] if d not in done_ids] for t in remaining}
    cycle_ids = {tid for tid in stuck if _reaches(tid, tid, stuck)}
    for t in remaining:
        if t.id in cycle_ids:
            via = next(d for d in stuck[t.id] if d in cycle_ids)
            result.held.append((t, f"dependency cycle via {via!r}"))
        else:
            via = next(d for d in stuck[t.id] if d in held_ids or d in cycle_ids)
            result.held.append((t, f"depends on held task {via!r}"))
    return result


def _reaches(start: str, target: str, edges: dict[str, list[str]]) -> bool:
    """True if ``target`` is reachable from ``start`` by following ``edges``."""
    seen: set[str] = set()
    stack = list(edges.get(start, []))
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return False
