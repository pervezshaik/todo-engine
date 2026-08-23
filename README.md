# todo-engine — agentic to-do execution

[![CI](https://github.com/pervezshaik/todo-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/pervezshaik/todo-engine/actions/workflows/ci.yml)

Write tasks in a markdown checklist; an autonomous Claude agent does each one
and checks it off. The todo file is the progress tracker.

```markdown
- [ ] Create a file called hello.txt containing a haiku about agents
- [ ] Look up today's weather in Hyderabad and save a summary to weather.md
- [ ] Email the weekly report to the team @use: gmail, xlsx
```

```
> todo-engine todo.md
─ Task 1: Create a file called hello.txt containing a haiku about agents ─
| [tool] Write
| [tool] Read
[OK] STATUS: done
...
```

Each task gets a fresh agent (Claude Agent SDK driving the Claude Code engine)
with shell, file, and web-research tools plus everything you register in the
capability registries below. Tasks run sequentially; every run leaves full
transcripts in `runs/<timestamp>/`.

**Watch progress live in the file itself:** the task being worked on shows as
`- [~]` (flips to `- [x]` on success, back to `- [ ]` on failure), and every
pass starts with a "Picked up this pass" queue in the console showing what's
queued vs skipped.

**Trust, but verify:** a box is only checked after an independent verifier
agent (cheap model, read-only tools) inspects the actual artifacts against the
task text — self-reported success is not enough. Failures get a smart retry:
transient errors back off and retry silently; real failures get one retry with
a "what went wrong" analysis (`@retries: N` to change). After each verified
success a ≤8-line lesson is distilled into `memory/` and injected into future
related tasks, so agents learn across runs. Every attempt lands in
`runs/history.jsonl` — see `todo-engine todo.md --report` for success rates,
failure classes, costs, and flaky tasks.

## Setup

**No Anthropic API key needed.** The engine authenticates through your
machine's Claude Code login.

```powershell
pip install -e .            # from this directory
python scripts\auth_check.py   # one-time: verify the login path works
```

If the auth check fails: run `claude setup-token` and set the printed token as
`CLAUDE_CODE_OAUTH_TOKEN` (still subscription-based — no API key).

## Usage

| Command | What it does |
|---|---|
| `todo-engine todo.md` | Run every unchecked task, top to bottom |
| `todo-engine todo.md --task 2` | Run only item 2 |
| `todo-engine todo.md --watch` | Stay running; new `- [ ]` lines run on file save |
| `todo-engine todo.md --confirm` | Ask y/n before every shell command |
| `todo-engine todo.md --yolo` | Fully autonomous — no permission gates |
| `todo-engine todo.md --stop-on-failure` | Halt at the first failed task |
| `todo-engine todo.md --workdir D:\proj` | Agents operate in that directory |
| `todo-engine todo.md --report` | Show run history: success rates, failure classes, costs |
| `todo-engine todo.md --no-verify` | Skip the independent verification pass |

Scheduled runs work out of the box (Windows Task Scheduler → `todo-engine
C:\...\todo.md --yolo`), since auth is the stored login.

## Extending what agents can do

Three registries live next to your todo file; all are optional and discovered
at startup. Every task agent receives a *capability manifest* describing them
and is instructed to inventory it before planning — and to fail with
`missing capability: <what>` rather than improvise when something's absent.

| Registry | What | How |
|---|---|---|
| `skills/<name>/SKILL.md` | Know-how documents (format guides, procedures). Frontmatter `name:` + `description:` required | Agent reads the skill file when the description matches the task |
| `tools/*.py` | Custom Python tools — `@tool`-decorated async functions (see `tools/example.py`) | Callable as `mcp__local__<name>` |
| `mcp_config.json` | External MCP servers (see `mcp_config.example.json`) | Their tools become `mcp__<server>__<tool>` |

Config values support `${VAR}` environment-variable expansion, so tokens never
sit in the file — e.g. the GitHub server is wired as:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}" }
    }
  }
}
```

Set the variable per session (`$env:GITHUB_PERSONAL_ACCESS_TOKEN = gh auth token`)
or persist it for scheduled runs
(`[Environment]::SetEnvironmentVariable("GITHUB_PERSONAL_ACCESS_TOKEN", (gh auth token), "User")`).

Your existing Claude Code MCP connectors (Gmail, Calendar, Drive, …) are also
loaded automatically via user/project settings.

**Steering a task:** append `@use: name, name` to a checklist line to point the
agent at specific capabilities.

## Safety

- Every shell command is logged to `runs/<ts>/task-N.commands.log` *before* it
  executes.
- Default mode (`acceptEdits`) auto-approves file edits but keeps the engine's
  gates on risky operations; `--confirm` adds a human gate per command; a "no"
  is delivered to the agent with the reason.
- A task is only checked off when the agent both finishes without engine error
  **and** explicitly reports `STATUS: done`.

## Development

```powershell
pip install -e .[dev]
pytest                  # unit tests: deterministic, no engine calls, $0
pytest --cov            # with coverage
pytest -m live          # end-to-end against the real engine (costs money, needs login)
```

The unit suite replaces the SDK's `query()` with a scripted fake
(`tests/fakes.py`), so retry policy, the verifier gate, checkbox lifecycle,
history, memory and watch mode are all exercised without spending a cent.

Quality gates (`ruff`, `mypy --strict`, `pytest` with coverage ≥ 85 %) run via
`nox` locally and in GitHub Actions on Ubuntu, Windows and macOS × Python 3.10
and 3.13 (`.github/workflows/ci.yml`). Live tests never run in CI.

## Docs

- [docs/specs.md](docs/specs.md) — product specification
- [docs/design.md](docs/design.md) — design, implementation plan, and step status
