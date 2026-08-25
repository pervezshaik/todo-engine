"""Compatibility shim — the verifier now lives in :mod:`todo_engine.roles.verifier`."""

from __future__ import annotations

from .roles.verifier import VERIFIER, VERIFIER_MODEL, VERIFIER_SYSTEM_PROMPT, Verdict, verify

__all__ = ["VERIFIER", "VERIFIER_MODEL", "VERIFIER_SYSTEM_PROMPT", "Verdict", "verify"]
