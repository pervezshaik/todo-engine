"""Agent roles: each is a RoleSpec (prompt, model, tools, limits) run through
one shared SDK loop. See ``base.py``."""

from .base import RoleContext, RoleResult, RoleSpec, run_role

__all__ = ["RoleContext", "RoleResult", "RoleSpec", "run_role"]
