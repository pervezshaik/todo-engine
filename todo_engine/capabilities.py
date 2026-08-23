"""Capability registry: skills/, tools/, mcp_config.json.

Scans the three user-extensible registries and produces:
- a human-readable *capability manifest* injected into every task prompt,
- the ``mcp_servers`` dict for ``ClaudeAgentOptions`` (in-process "local"
  server built from @tool functions in tools/, plus external servers from
  mcp_config.json),
- the extra ``allowed_tools`` entries (``mcp__local__*``, ``mcp__<server>__*``).

Registry problems are collected as warnings naming the offending file and
reported at startup — never silently skipped.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

LOCAL_SERVER = "local"


@dataclass
class Capabilities:
    manifest: str = ""
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skills: list[tuple[str, str, Path]] = field(default_factory=list)  # name, description, path
    tools: list[tuple[str, str]] = field(default_factory=list)  # name, description
    servers: list[tuple[str, str]] = field(default_factory=list)  # name, origin
    inherited: list[str] = field(default_factory=list)  # Claude Code connectors


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML frontmatter parse: leading --- block of `key: value` lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("'\"")
    return {}  # never closed


def _scan_skills(root: Path, caps: Capabilities) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        name = meta.get("name")
        description = meta.get("description")
        if not name or not description:
            caps.warnings.append(
                f"skill {skill_md}: missing 'name' or 'description' frontmatter — skipped"
            )
            continue
        caps.skills.append((name, description, skill_md))


def _scan_tools(root: Path, caps: Capabilities) -> None:
    tools_dir = root / "tools"
    if not tools_dir.is_dir():
        return
    sdk_tools: list[SdkMcpTool[Any]] = []
    for py in sorted(tools_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"todo_tools_{py.stem}", py)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - registry errors must be reported, not fatal
            caps.warnings.append(f"tool module {py}: import failed — {type(exc).__name__}: {exc}")
            continue
        found = [obj for obj in vars(module).values() if isinstance(obj, SdkMcpTool)]
        if not found:
            caps.warnings.append(f"tool module {py}: no @tool-decorated functions found")
        sdk_tools.extend(found)
    if sdk_tools:
        caps.mcp_servers[LOCAL_SERVER] = create_sdk_mcp_server(name=LOCAL_SERVER, tools=sdk_tools)
        for t in sdk_tools:
            caps.tools.append((t.name, t.description))
            caps.allowed_tools.append(f"mcp__{LOCAL_SERVER}__{t.name}")


_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(value: Any, caps: Capabilities, origin: str) -> Any:
    """Expand ${VAR} placeholders in mcp_config.json string values.

    Keeps secrets out of the config file — reference an environment variable
    instead of pasting a token.
    """
    if isinstance(value, str):

        def replace(m: re.Match[str]) -> str:
            var = m.group(1)
            if var in os.environ:
                return os.environ[var]
            caps.warnings.append(f"{origin}: environment variable {var} is not set")
            return str(m.group(0))

        return _ENV_VAR_RE.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, caps, origin) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, caps, origin) for v in value]
    return value


def _scan_mcp_config(root: Path, caps: Capabilities) -> None:
    config_path = root / "mcp_config.json"
    if not config_path.is_file():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        servers = config["mcpServers"]
        assert isinstance(servers, dict)
    except Exception as exc:  # noqa: BLE001
        caps.warnings.append(
            f"{config_path}: malformed (expected {{'mcpServers': {{...}}}}) — {exc}"
        )
        return
    for name, server_config in servers.items():
        if name.startswith("//"):
            continue  # comment entry
        if name in caps.mcp_servers:
            caps.warnings.append(f"{config_path}: server name {name!r} collides — skipped")
            continue
        server_config = _expand_env(server_config, caps, f"{config_path} [{name}]")
        caps.mcp_servers[name] = server_config
        origin = server_config.get("url") or server_config.get("command", "?")
        caps.servers.append((name, str(origin)))
        caps.allowed_tools.append(f"mcp__{name}__*")


def _scan_inherited_connectors(caps: Capabilities) -> None:
    """Discover MCP servers/connectors inherited from the user's Claude Code
    settings (loaded into agents via setting_sources) and allowlist them, so
    autonomous runs don't stall on a permission prompt nobody can answer."""
    user_config = Path.home() / ".claude.json"
    if not user_config.is_file():
        return
    try:
        config = json.loads(user_config.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        caps.warnings.append(f"{user_config}: unreadable — {exc}")
        return
    names = list(config.get("mcpServers", {}).keys())
    names += [n for n in config.get("claudeAiMcpEverConnected", []) if n not in names]
    for name in names:
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", name)
        caps.inherited.append(name)
        caps.allowed_tools.append(f"mcp__{normalized}")  # server-level allow


def _build_manifest(caps: Capabilities) -> str:
    lines: list[str] = []
    if caps.skills:
        lines.append("Skills (read the SKILL.md file with your Read tool when relevant):")
        lines += [f"- {name}: {desc}  [file: {path}]" for name, desc, path in caps.skills]
    if caps.tools:
        lines.append("Custom tools (call directly):")
        lines += [f"- mcp__{LOCAL_SERVER}__{name}: {desc}" for name, desc in caps.tools]
    if caps.servers:
        lines.append("Connected MCP servers (their tools are available as mcp__<server>__<tool>):")
        lines += [f"- {name} ({origin})" for name, origin in caps.servers]
    if caps.inherited:
        lines.append("Inherited Claude Code connectors (tools follow the same naming):")
        lines += [f"- {name}" for name in caps.inherited]
    return "\n".join(lines)


def scan(project_root: str | Path) -> Capabilities:
    root = Path(project_root)
    caps = Capabilities()
    _scan_skills(root, caps)
    _scan_tools(root, caps)
    _scan_mcp_config(root, caps)
    _scan_inherited_connectors(caps)
    caps.manifest = _build_manifest(caps)
    return caps
