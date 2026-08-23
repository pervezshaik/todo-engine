from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import FakeQuery


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never read the developer's real ~/.claude.json during tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace the SDK ``query`` in every module that calls it."""
    import todo_engine.agent as agent_mod
    import todo_engine.memory as memory_mod
    import todo_engine.verifier as verifier_mod

    sdk = SimpleNamespace(
        agent=FakeQuery("agent"),
        verifier=FakeQuery("verifier"),
        memo=FakeQuery("memo"),
    )
    monkeypatch.setattr(agent_mod, "query", sdk.agent)
    monkeypatch.setattr(verifier_mod, "query", sdk.verifier)
    monkeypatch.setattr(memory_mod, "query", sdk.memo)
    return sdk


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make the runner's backoff/watch sleeps instant; returns the recorded delays."""
    import todo_engine.runner as runner_mod

    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(runner_mod, "asyncio", SimpleNamespace(sleep=fake_sleep))
    return delays
