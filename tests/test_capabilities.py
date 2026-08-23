import json
from pathlib import Path

import pytest

from todo_engine.capabilities import (
    Capabilities,
    _expand_env,
    _parse_frontmatter,
    _scan_inherited_connectors,
    scan,
)

GOOD_TOOL = """
from claude_agent_sdk import tool

@tool(name="good", description="a good tool", input_schema={"text": str})
async def good(args: dict) -> dict:
    return {"content": [{"type": "text", "text": "ok"}]}
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- frontmatter ------------------------------------------------------------


def test_parse_frontmatter() -> None:
    assert _parse_frontmatter("---\nName: 'x'\ndescription: \"d: e\"\n---\nbody") == {
        "name": "x",
        "description": "d: e",
    }
    assert _parse_frontmatter("# no frontmatter") == {}
    assert _parse_frontmatter("---\nname: x\n(never closed)") == {}
    assert _parse_frontmatter("") == {}


# --- skills -----------------------------------------------------------------


def test_skills_scan(tmp_path: Path) -> None:
    write(tmp_path / "skills" / "ok" / "SKILL.md", "---\nname: ok\ndescription: fine\n---\n")
    write(tmp_path / "skills" / "bad" / "SKILL.md", "---\nname: bad\n---\n")
    caps = scan(tmp_path)
    assert [(n, d) for n, d, _ in caps.skills] == [("ok", "fine")]
    assert (
        len(caps.warnings) == 1 and "bad" in caps.warnings[0] and "frontmatter" in caps.warnings[0]
    )
    assert "- ok: fine" in caps.manifest


# --- tools ------------------------------------------------------------------


def test_tools_scan_registers_local_server(tmp_path: Path) -> None:
    write(tmp_path / "tools" / "good.py", GOOD_TOOL)
    write(tmp_path / "tools" / "_private.py", "raise RuntimeError('must be skipped')")
    caps = scan(tmp_path)
    assert caps.tools == [("good", "a good tool")]
    assert "mcp__local__good" in caps.allowed_tools
    assert "local" in caps.mcp_servers
    assert caps.warnings == []
    assert "- mcp__local__good: a good tool" in caps.manifest


def test_tools_scan_reports_broken_modules(tmp_path: Path) -> None:
    write(tmp_path / "tools" / "broken.py", "def (\n")
    write(tmp_path / "tools" / "empty.py", "x = 1\n")
    caps = scan(tmp_path)
    assert caps.tools == [] and "local" not in caps.mcp_servers
    assert any("broken.py" in w and "import failed" in w for w in caps.warnings)
    assert any("empty.py" in w and "no @tool-decorated" in w for w in caps.warnings)


# --- ${VAR} expansion -------------------------------------------------------


def test_expand_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TE_TOKEN", "s3cr3t")
    monkeypatch.delenv("TE_MISSING", raising=False)
    caps = Capabilities()
    value = {"env": {"A": "${TE_TOKEN}", "B": "pre-${TE_MISSING}-post"}, "args": ["${TE_TOKEN}", 1]}
    out = _expand_env(value, caps, "cfg [x]")
    assert out == {"env": {"A": "s3cr3t", "B": "pre-${TE_MISSING}-post"}, "args": ["s3cr3t", 1]}
    assert caps.warnings == ["cfg [x]: environment variable TE_MISSING is not set"]


# --- mcp_config.json --------------------------------------------------------


def test_mcp_config_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")
    write(tmp_path / "tools" / "good.py", GOOD_TOOL)
    write(
        tmp_path / "mcp_config.json",
        json.dumps(
            {
                "mcpServers": {
                    "//": "comment entry",
                    "github": {
                        "command": "npx",
                        "args": ["-y", "srv"],
                        "env": {"T": "${GH_TOKEN}"},
                    },
                    "remote": {"type": "http", "url": "https://example.com/mcp"},
                    "local": {"command": "collides-with-tools-server"},
                }
            }
        ),
    )
    caps = scan(tmp_path)
    assert caps.servers == [("github", "npx"), ("remote", "https://example.com/mcp")]
    assert caps.mcp_servers["github"]["env"] == {"T": "tok"}
    assert "mcp__github__*" in caps.allowed_tools and "mcp__remote__*" in caps.allowed_tools
    assert any("'local' collides" in w for w in caps.warnings)
    assert (
        "- github (npx)" in caps.manifest and "- remote (https://example.com/mcp)" in caps.manifest
    )


@pytest.mark.parametrize(
    "content", ["{not json", json.dumps({"servers": {}}), json.dumps({"mcpServers": []})]
)
def test_mcp_config_malformed(tmp_path: Path, content: str) -> None:
    write(tmp_path / "mcp_config.json", content)
    caps = scan(tmp_path)
    assert caps.servers == []
    assert len(caps.warnings) == 1 and "malformed" in caps.warnings[0]


# --- inherited Claude Code connectors -------------------------------------


def test_inherited_connectors(isolated_home: Path) -> None:
    (isolated_home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {"foo-bar": {}},
                "claudeAiMcpEverConnected": ["claude.ai Gmail", "foo-bar"],
            }
        ),
        encoding="utf-8",
    )
    caps = Capabilities()
    _scan_inherited_connectors(caps)
    assert caps.inherited == ["foo-bar", "claude.ai Gmail"]
    assert caps.allowed_tools == ["mcp__foo_bar", "mcp__claude_ai_Gmail"]


def test_inherited_connectors_unreadable(isolated_home: Path) -> None:
    (isolated_home / ".claude.json").write_text("{", encoding="utf-8")
    caps = Capabilities()
    _scan_inherited_connectors(caps)
    assert caps.inherited == [] and len(caps.warnings) == 1


def test_inherited_appear_in_manifest(tmp_path: Path, isolated_home: Path) -> None:
    (isolated_home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"gh": {}}}), encoding="utf-8"
    )
    caps = scan(tmp_path)
    assert "Inherited Claude Code connectors" in caps.manifest and "- gh" in caps.manifest


def test_empty_root_has_empty_manifest(tmp_path: Path) -> None:
    caps = scan(tmp_path)
    assert caps.manifest == "" and caps.warnings == [] and caps.allowed_tools == []
