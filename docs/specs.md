# Product Specification — Agentic To-Do Execution Engine

**Status:** Draft v1 · 2026-08-22
**Owner:** Pervez Shaik

## 1. Overview

A Python command-line engine that reads a to-do list from a markdown file and executes each task autonomously. For every unchecked item, the engine spins up a fresh AI agent (powered by the Claude Agent SDK, which drives the Claude Code engine) that reasons about how to accomplish the task, surveys the capabilities available to it (built-in tools, user-registered skills, custom tools, and MCP servers), executes the work, and reports the outcome. Completed tasks are checked off in the file itself, so **the todo file doubles as the progress tracker**.

## 2. Goals

- Turn a plain markdown checklist into executable work with zero per-task setup.
- Each task is handled by an autonomous agent that plans, selects tools, executes, and self-verifies.
- The engine is extensible: users can register **skills** (know-how documents), **custom tools** (Python functions), and **MCP servers** (external services) that every task agent can discover and use.
- Runs entirely on the user's **Claude Code subscription login — no Anthropic API key**.
- Safe by default, fully autonomous on request.

## 3. Non-goals (v1)

- No parallel task execution (sequential only).
- No web UI (terminal + markdown logs; the todo file is the state).
- No task dependency graph, priorities, or scheduling semantics inside the file (file order = execution order).
- No OAuth plumbing for productivity services — those come via already-configured Claude Code MCP connectors.

## 4. Users & invocation

Single-user, local machine (Windows 11 primary target).

| Invocation | Command | Behavior |
|---|---|---|
| Run all | `todo-engine todo.md` | Processes every unchecked task, top to bottom |
| Run one | `todo-engine todo.md --task N` | Runs only the Nth task |
| Watch mode | `todo-engine todo.md --watch` | Stays running; processes new `- [ ]` lines whenever the file is saved — adding a line becomes the invocation |
| Scheduled | Windows Task Scheduler → `todo-engine todo.md` | Unattended runs; auth is the stored Claude Code login, no secrets to provision |

**Behavior flags:**

| Flag | Effect |
|---|---|
| `--workdir DIR` | Directory the agents operate in (default: current directory) |
| `--confirm` | Human gate: prompt y/n before every shell command an agent wants to run |
| `--yolo` | Fully autonomous: no permission prompts at all |
| `--stop-on-failure` | Halt the run at the first failed task (default: continue) |
| `--max-turns N` | Cap agent turns per task (default 50) |

## 5. Task file format

Standard markdown checklist. Everything that is not a checklist line is preserved untouched (headings, notes, blank lines).

```markdown
# My todos

- [ ] Create a file called hello.txt containing a haiku about agents
- [ ] Look up today's weather in Hyderabad and save a summary to weather.md
- [ ] Email the weekly report to the team @use: gmail, xlsx
- [x] Already-done task (skipped)
```

- `- [ ]` — pending task; `- [x]` — done (skipped by the engine, written by the engine on success).
- `- [~]` — **in progress** (engine-written): while a task is being worked on, its line carries this marker, so the open todo file shows live which task is active. On success it becomes `[x]`; on failure it reverts to `[ ]`. A leftover `[~]` (crashed run) is treated as pending and reruns.
- **Directives (optional):** trailing `@key: value` suffixes on a task line:
  - `@use: name, name` — steer the agent toward specific registered capabilities (emphasis, not hard restriction)
  - `@retries: N` — number of Reflexion retries on real failure (default 1)
  - `@verify: off` — skip independent verification for this task

## 6. Capability registry

Three optional, user-extensible registries. All are discovered at startup; registry problems (skill missing frontmatter, tool module failing to import, malformed config) are reported at startup with the file named — never silently skipped.

| Registry | Contents | Exposure to agents |
|---|---|---|
| `skills/<name>/SKILL.md` | Task know-how with YAML frontmatter (`name`, `description`) — e.g. "weekly-report format", "how to file expenses" | Loaded through the engine's skill system; name + description injected into the capability manifest so the agent knows to read the skill when relevant |
| `tools/*.py` | Custom Python tools written with the SDK `@tool` decorator (async functions) | Auto-aggregated into an in-process tool server; callable as `mcp__local__<name>` |
| `mcp_config.json` | External MCP servers, Claude-Desktop-style (`command`/`args`/`env` or `url`) | Merged into each agent's MCP server set; tools callable as `mcp__<server>__<tool>` |

In addition, the user's **existing Claude Code configuration** (user + project settings) is loaded, so MCP connectors already set up in Claude Code (Gmail, Calendar, Drive, …) are available to every task agent.

### Capability discovery requirement

Before planning, every task agent must **account for what it can do**:

1. The engine builds a **capability manifest** — every skill, custom tool, and MCP server with its description — and injects it into the task prompt.
2. The system prompt directs the agent to inventory the manifest plus its built-in tools, and choose the capabilities suited to the task.
3. If the task needs a capability the agent doesn't have, it must **not improvise around it** — it ends with `STATUS: failed — missing capability: <what>`, and the task stays unchecked.

## 7. Execution semantics

- **Sequential:** one task at a time, file order.
- **Isolated:** each task gets a fresh agent session; a failing task cannot pollute the next. A short summary of previously completed tasks in the run is provided as context.
- **Success is three-factor:** the SDK reports no error, the agent's final message contains `STATUS: done`, **and** an independent verifier agent (cheap model, read-only tools) inspects the actual artifacts against the task text and returns `VERDICT: pass`. Only then is the box checked. Escapes: `--no-verify` (run-wide) or `@verify: off` (per task).
- **Typed outcomes:** every attempt is classified — `done / failed / timeout / missing_capability / declined / engine_error` — driving retry policy and reporting.
- **Smart retry:** transient engine errors (rate limit, network, overload) retry automatically with backoff (5s/15s, twice) without consuming task retries. Real failures get a Reflexion retry (default 1, `@retries:N` to change): the next attempt receives a grounded "what failed and why" memo and is instructed to take a different approach. `missing_capability` and `declined` never retry.
- **Cross-run memory:** after each *verified* success, a ≤8-line lesson memo (commands, paths, gotchas) is distilled into `memory/lessons/` and indexed in `memory/MEMORY.md`; future related tasks receive the top-3 relevant memos in their prompt, so agents don't start cold. Trivial tasks produce no memo.
- **Failure isolation:** a failed task is logged and the run continues (unless `--stop-on-failure`).
- **Run history:** every attempt appends to `runs/history.jsonl` (`ts, task, attempt, outcome, success, duration, cost, verifier verdict`); `todo-engine <file> --report` prints per-task attempts, success rate, failure classes, cost totals, and flaky-task flags.
- **Auditability:** every run writes `runs/<timestamp>/task-N.md` transcripts (agent text, tool calls, every shell command) plus an end-of-run summary table (done / failed / skipped, per-task cost).
- **Visibility:** each pass opens with a "Picked up this pass" queue (QUEUED / DONE-skipped / HELD), the active task is announced with a `WORKING` banner, and its line in the todo file carries the `[~]` marker while it runs.

## 8. Built-in agent capabilities

Every task agent has, at minimum: shell execution (Bash), file read/write/edit, file search (Glob/Grep), and web research (WebSearch, WebFetch).

## 9. Safety model

| Layer | Behavior |
|---|---|
| Default (`acceptEdits`) | File edits auto-approved; risky operations still gated by the engine's permission system |
| Command log | Every shell command is logged to the task transcript **before** execution (PreToolUse hook) |
| `--confirm` | Human y/n on every shell command; a "no" is delivered to the agent with the denial reason |
| `--yolo` | All gates off — for trusted, unattended runs |

## 10. Authentication constraint

- **No Anthropic API key exists or will be provisioned.**
- The engine authenticates through the machine's **Claude Code subscription login** (the Agent SDK spawns the Claude Code engine, which reads stored credentials).
- Fallback if the bundled engine doesn't pick up the login: `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` (still subscription-based), or pointing the SDK at the installed, logged-in `claude` binary.
- Verifying this auth path is **implementation step 1** (smoke test) — nothing else proceeds until it passes.

## 11. Acceptance criteria

1. Running the engine on the sample todo file completes the local-file task and the web-research task, flips both to `- [x]`, and leaves transcripts + a cost summary in `runs/<timestamp>/`.
2. Checked tasks are skipped; non-checklist file content is never modified.
3. An impossible task stays unchecked with a logged failure and does not stop the run.
4. With `--confirm`, every shell command prompts first; denial reaches the agent with the reason.
5. A registered custom tool is discoverable in the manifest and callable by an agent; a hinted task (`@use:`) shows the hint emphasized in its prompt.
6. A task requiring an unregistered capability ends `STATUS: failed — missing capability: …` without improvising.
7. The whole flow works with no `ANTHROPIC_API_KEY` set anywhere.
