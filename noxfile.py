"""Task runner: `nox -l` to list, `nox` to run the default gates.

Sessions run in the current environment (no virtualenv creation) so they are
fast and use the same installed SDK as the app:  pip install -e .[dev]
Tools are invoked as `python -m ...` so they always come from that interpreter.
"""

import sys

import nox

nox.options.sessions = ["lint", "typecheck", "test"]
PY = sys.executable


@nox.session(python=False)
def lint(session: nox.Session) -> None:
    """ruff check + ruff format --check."""
    session.run(PY, "-m", "ruff", "check", ".")
    session.run(PY, "-m", "ruff", "format", "--check", ".")


@nox.session(python=False)
def fmt(session: nox.Session) -> None:
    """Auto-fix lint and reformat."""
    session.run(PY, "-m", "ruff", "check", "--fix", ".")
    session.run(PY, "-m", "ruff", "format", ".")


@nox.session(python=False)
def typecheck(session: nox.Session) -> None:
    """mypy --strict on the package."""
    session.run(PY, "-m", "mypy")


@nox.session(python=False)
def test(session: nox.Session) -> None:
    """Unit tests with coverage (no engine calls, $0)."""
    session.run(PY, "-m", "pytest", "-q", "--cov", "--cov-report=term-missing", *session.posargs)


@nox.session(python=False)
def live(session: nox.Session) -> None:
    """End-to-end tests against the real Claude engine (costs money)."""
    session.run(PY, "-m", "pytest", "-q", "-m", "live", *session.posargs)
