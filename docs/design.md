# Design & Implementation Plan — Agentic To-Do Execution Engine

**Status:** Draft v1 · 2026-08-22
**Companion doc:** [specs.md](specs.md) — product specification

## 1. Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python ≥ 3.10 | User preference; best-supported Agent SDK surface |
| Agent runtime | **Claude Agent SDK** (`claude-agent-sdk`) | Programmatically drives the Claude Code engine: full agent loop, built-in tools (Bash/Read/Write/Edit/Glob/Grep/WebSearch/WebFetch), MCP support, hooks — none of it reimplemented here |
| Auth | Claude Code subscription login | No API key available (see specs §10); SDK-spawned engine reads stored credentials |
| Console output | `rich` | Live task progress, summary table |
| Distribution | Local editable install (`pip install -e .`), console script `todo-engine` | Single-user local tool |

## 2. Architecture

```
todo.md ─→ Runner (sequential loop)
             └─ per task: claude_agent_sdk.query(prompt, options)
                  ├─ built-in tools: Bash · Read · Write · Edit · Glob · Grep
                  │                  WebSearch · WebFetch
                  ├─ capability registry: skills/ · tools/ (@tool) · mcp_config.json
                  ├─ user's Claude Code MCP connectors (Gmail / Calendar / Drive)
                  │      via setting_sources=["user", "project"]
                  └─ PreToolUse hook: logs every shell command; --confirm human gate
             on success ─→ mark "- [x]" + write runs/<timestamp>/task-N.md
```

One fresh `query()` per task (isolated session). The runner owns orchestration, checkbox state, and logging; the SDK owns the agent loop.

## 3. Project layout

```
todo/
├── docs/                      specs.md, design.md (this file)
├── todo_engine/
│   ├── __main__.py            CLI entry (argparse, asyncio.run)
│   ├── parser.py              markdown checklist parse/serialize + @use: hints
│   ├── capabilities.py        registry scan → manifest + mcp_servers + allowed_tools
│   ├── agent.py               single-task agent run
│   ├── hooks.py               PreToolUse logging / confirm gate
│   └── runner.py              sequential orchestration, logs, summary
├── skills/                    user skill registry (seeded with one example)
├── tools/                     user custom-tool registry (seeded with one example)
├── mcp_config.example.json    example external MCP server config
├── todo.md                    sample todo list
├── pyproject.toml
└── README.md
```

## 4. Module design

### 4.1 `parser.py`

- `Task(line_no: int, text: str, done: bool, hints: list[str])`
- `parse(path) -> list[Task]` — recognizes `- [ ]` / `- [x]` (tolerant of indentation); extracts a trailing `@use: a, b` into `hints` and strips it from `text`. All other lines untouched.
- `mark_done(path, line_no)` — re-reads the file, rewrites only that line's `[ ]` → `[x]`, writes back. Re-reading before writing keeps `--watch` safe against concurrent edits.

### 4.2 `capabilities.py`

- `scan(project_root) -> Capabilities` where `Capabilities` carries:
  - `manifest: str` — human-readable inventory injected into every task prompt: each skill (name + description from SKILL.md frontmatter), each custom tool (name + description from `@tool` metadata), each MCP server (name + origin).
  - `mcp_servers: dict` — `{"local": create_sdk_mcp_server(name="local", tools=[...])}` from `tools/*.py`, merged with entries from `mcp_config.json`.
  - `allowed_tools: list[str]` — `mcp__local__*` and `mcp__<server>__*` additions.
- Tool collection: import every module in `tools/`, collect objects created by the SDK `@tool` decorator.
- Validation: a skill without frontmatter, an import error in a tool module, or malformed JSON is reported at startup naming the file; the run proceeds without the broken entry only after printing the warning.

### 4.3 `agent.py`

- `async run_task(task, ctx) -> TaskResult(success, status_line, error, cost_usd, transcript)`
- Options per task:

```python
ClaudeAgentOptions(
    cwd=ctx.workdir,
    permission_mode="bypassPermissions" if ctx.yolo else "acceptEdits",
    allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep",
                   "WebSearch", "WebFetch", *ctx.capabilities.allowed_tools],
    mcp_servers=ctx.capabilities.mcp_servers,
    setting_sources=["user", "project"],   # pulls in existing Claude Code MCP connectors + skills
    max_turns=ctx.max_turns,
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[ctx.bash_hook])]},
    system_prompt=SYSTEM_PROMPT,
)
```

- **System prompt (core contract):** the agent is executing exactly one task from a to-do list; it must (1) inventory the capability manifest plus built-in tools before planning, (2) work autonomously and verify its own work, (3) end with exactly one line `STATUS: done` or `STATUS: failed — <reason>`, and (4) if a needed capability is missing, fail with `missing capability: <what>` rather than improvising.
- **Task prompt:** working directory, the task text, emphasized `@use:` hints (if any), the capability manifest, and one-line summaries of tasks already completed this run.
- **Message handling:** iterate `query()` — `AssistantMessage`/`TextBlock` → live console + transcript; `ToolUseBlock` → tool name shown + transcript; `ResultMessage` → capture `is_error`, `result`, `total_cost_usd`.
- **Success:** `not result.is_error` **and** final text contains `STATUS: done`.

### 4.4 `hooks.py`

- `make_bash_hook(log_file, confirm: bool)` → async PreToolUse hook:
  - Always appends the command to the task log **before** execution.
  - If `confirm`: synchronous terminal y/n; on "n" returns `permissionDecision: "deny"` with a reason string the agent sees.

### 4.5 `runner.py`

- Load tasks → skip done → for each pending (or the `--task N` selection):
  1. Print task header; open `runs/<timestamp>/task-N.md`.
  2. `run_task(...)`; on success `mark_done()`; on failure record and continue (`--stop-on-failure` halts).
  3. Append result summary (status, cost, duration) to the transcript.
- `--watch`: after a pass, watch `todo.md` mtime; re-parse on change; process any new unchecked tasks. Ctrl-C exits cleanly.
- Error handling: `CLINotFoundError` / `CLIConnectionError` → actionable message about the Claude Code engine + auth; `ProcessError` → task failure, run continues.
- End of run: `rich` summary table — task, status, cost, log path.

## 5. Authentication design

1. No `ANTHROPIC_API_KEY` anywhere in code, env, or docs beyond stating it is not needed.
2. Primary path: SDK-spawned Claude Code engine picks up the machine's stored subscription login.
3. Fallbacks, in order: `ClaudeAgentOptions(cli_path=<installed claude binary>)` (already logged in) → `claude setup-token` exported as `CLAUDE_CODE_OAUTH_TOKEN`.
4. **Smoke test is implementation step 1:** `scripts/auth_check.py` runs `query("Reply with exactly: ok")` and prints which path worked. Build halts until it passes.

## 6. Implementation order

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 0 | `docs/specs.md`, `docs/design.md` | this commit | ✅ Done (2026-08-22) |
| 1 | Auth smoke test (`scripts/auth_check.py`) | prints "ok" with no API key set | ✅ Done (2026-08-22) — passed via bundled engine + stored login; cost $0.12 |
| 2 | `parser.py` + sample `todo.md` | parse/mark round-trip self-test incl. `@use:` hints | ✅ Done (2026-08-22) — `scripts/parser_test.py` passing |
| 3 | `agent.py` minimal single-task run | one trivial task end-to-end | ✅ Done (2026-08-22) — `scripts/agent_test.py`: file created + self-verified, `STATUS: done`, $0.06 |
| 4 | `capabilities.py` + seeded example skill/tool/MCP config | manifest visible in transcript; `mcp__local__example` callable | ✅ Done (2026-08-22) — `scripts/capabilities_test.py`: agent called the tool, token verified against local hash |
| 5 | `hooks.py`, `runner.py`, `__main__.py` (flags incl. `--watch`) | full CLI run on the sample file | ✅ Done (2026-08-22) — both sample tasks executed & checked off; skip logic, transcripts, cost summary verified; Windows cp1252 console issue fixed (UTF-8 reconfigure) |
| 6 | README + polish | acceptance criteria pass | ✅ Done (2026-08-22) — all acceptance checks pass; see §7 results |
| 7 | Run visibility: pass queue display + `[~]` in-file working marker | queue printed, `[~]` lifecycle `[ ]→[~]→[x/ ]` verified live and in parser self-test | ✅ Done (2026-08-22) — also fixed watch loop retriggering on the engine's own checkbox writes |
| 8 | GitHub MCP server wired + `${VAR}` env expansion in `mcp_config.json` | agent used `mcp__github__search_repositories` to identify the authenticated user and wrote `github-check.md` | ✅ Done (2026-08-22) — token referenced via `${GITHUB_PERSONAL_ACCESS_TOKEN}`, never stored in the file |
| 9 | Playwright MCP server wired (headless browser) | agent navigated news.ycombinator.com, snapshotted, extracted top-5 stories, wrote `hn-top5.md` | ✅ Done (2026-08-22) — no auth needed; `npx @playwright/mcp@latest --headless` |
| 10 | claude.ai connectors (Gmail/Calendar/Drive/Alphavantage) inherited + auto-allowlisted | agent listed all 18 Gmail labels into `gmail-check.md` | ✅ Done (2026-08-22) — connectors discovered from `~/.claude.json`, server-level allow entries added; required user OAuth via `/mcp` with all Google consent scopes ticked |

### v2 (Tier 1 reliability core — per the ranked improvement roadmap)

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 11 | `history.py` — per-attempt JSONL (`runs/history.jsonl`) + `--report` command (attempts, success rate, failure classes, cost, flaky detection) | report matches performed runs | ✅ Done (2026-08-22) |
| 12 | Typed outcomes (`done/failed/timeout/missing_capability/declined/engine_error`) + smart retry: transient engine errors → backoff (5s/15s ×2); real failures → Reflexion retry with grounded failure memo; `@retries:N` directive; generic `@key:` directive grammar in parser | impossible task: retry visibly changed strategy (Test-Path + recursive search) then failed typed; parser self-test covers directives | ✅ Done (2026-08-22) |
| 13 | `verifier.py` — Haiku read-only judge (Read/Glob/Grep only) checks artifacts vs task text; `[x]` requires executor success AND `VERDICT: pass`; `--no-verify` / `@verify: off` escapes; verifier cost added to task cost | false claim rejected ("missing.txt does not exist"), honest claim passed (`scripts/verifier_test.py`); live run showed "verifying result..." before `[x]` | ✅ Done (2026-08-22) |
| 14 | `memory.py` — post-verification lesson distillation (Haiku, ≤8 lines, "NOTHING" filter) into `memory/lessons/` + `MEMORY.md` index; keyword top-3 retrieval injected into related task prompts | trivial task correctly produced no memo; version-check task produced transferable memo (commands, paths, versions); related task in a later run showed "injecting lessons" and used the knowledge | ✅ Done (2026-08-22) |
| — | BOM tolerance fix: parser reads `utf-8-sig` (PowerShell `Set-Content -Encoding utf8` writes a BOM that broke checklist detection) | reproduced + fixed during step 14 testing | ✅ Done (2026-08-22) |

### v3 — Professional tool (public open-source release)

**Decided 2026-08-23:** audience = open-source public release (GitHub + PyPI, permissive license); platforms = Windows + macOS + Linux, all three in CI; CLI moves to subcommands (`run / watch / report / init / doctor`) with `todo-engine todo.md` kept as an alias for `run`. Facts checked: PyPI names `todo-engine` and `agentic-todo` are both unclaimed; `gh` is authenticated (`pervezshaik`); dev machine is Python 3.13 / `claude-agent-sdk` 0.1.72.

**Gap analysis (what "professional" is missing today):**

| Area | Today | Target |
|---|---|---|
| Version control | not a git repo; no `.gitignore`; agent outputs, `runs/`, `memory/`, `__pycache__`, `*.egg-info` mixed into the source root | git repo on GitHub; source / examples / workspace separated; runtime dirs ignored |
| Tests | `scripts/*_test.py` — call the real SDK (cost, nondeterministic) | `pytest` suite with a fake `query()`; deterministic, $0, runs in CI; the SDK-hitting scripts become an opt-in `tests/live/` marker |
| Code quality | no linter / formatter / type-checker | `ruff` (lint + format), `mypy --strict` on `todo_engine/`, `pre-commit`, CI gate |
| Packaging | 20-line `pyproject.toml`, `0.1.0`, no license/readme/urls/classifiers | full metadata, `LICENSE` (MIT), `CHANGELOG.md` (Keep a Changelog), semver, `pipx install todo-engine` |
| CLI | one positional + flags; `--report` is a flag pretending to be a subcommand | subcommands + alias; `todo-engine.toml` config for defaults; `--model / --budget / --timeout / --json / --quiet / --dry-run` |
| Robustness | verifier **fails open** on engine error; `--confirm` blocks the event loop with `input()`; system prompt hardcodes "Windows 11"; model names hardcoded; history report joins on task text | fail closed (`[!]`); async-safe confirm; OS-aware prompt + shell tool; configurable models; stable task identity |
| Observability | console only; transcripts per task | engine log file (`runs/engine.log`), `--json` event stream for scheduled runs, exit codes documented |
| Security | command log; `${VAR}` expansion | secret redaction in transcripts/logs (values of env vars referenced in `mcp_config.json`), `SECURITY.md`, `--yolo` warning banner |
| Docs & presence | good README, two design docs | README with demo GIF + badges, `docs/` site (mkdocs-material), `CONTRIBUTING.md`, issue/PR templates, examples gallery |

**Principles for this phase:** no behavior regressions for the existing `todo-engine todo.md` flow (acceptance run §7 must still pass unchanged); every step lands with tests; public-facing from step 15 onward (write code as if a stranger reads it tonight).

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 15 | **Repo hygiene:** `git init`, `.gitignore` (`runs/`, `memory/`, `__pycache__/`, `*.egg-info/`, `.playwright-mcp/`, `mcp_config.json`), move sample outputs (`hello.txt`, `weather.md`, `colors.txt`, `loc-report.md`, `task-queues.md`, `hn-top5.md`, `github-check.md`, `gmail-*.md`, `helloworld.txt`) out of the root into `examples/outputs/` (or delete), `examples/todo.md` + `examples/workspace/` layout; `LICENSE` (MIT); initial commit | `git status` clean; `todo-engine examples/todo.md` still runs | ✅ Done (2026-08-23) — initial commit `95d91d0` on `main`; `runs/`, `memory/`, `mcp_config.json`, caches, egg-info confirmed ignored; both `examples/todo.md` and root `todo.md` parse and scan registries ($0 smoke test via `--task 99`) |
| 16 | **Test suite:** `tests/` with `conftest.py` providing a fake `claude_agent_sdk.query` (scripted messages per prompt); unit tests for `parser` (markers, directives, BOM, `_set_marker` re-read), `agent` (`_extract_status`, `_classify`, `is_transient`, `build_prompt`), `runner` (retry policy paths: transient backoff, Reflexion memo, missing_capability/declined no-retry, verifier reject → `[ ]`), `verifier` (pass/fail/no-verdict), `history` (append, prune, report grouping), `memory` (distill NOTHING filter, `relevant_memos` ranking), `capabilities` (frontmatter, `${VAR}` expansion + warning, collision); `scripts/*_test.py` → `tests/live/` behind `-m live` | `pytest -q` green on Windows/macOS/Linux, <10 s, $0; coverage ≥85 % on `todo_engine/` | ✅ Done (2026-08-23) — 91 unit tests, 1.1 s, 99 % coverage on Windows (macOS/Linux confirmed green in CI, step 18); `tests/fakes.py` scripted `FakeQuery` replaces `claude_agent_sdk.query` in agent/verifier/memory; old `scripts/*_test.py` removed, 4 live tests under `tests/live/` run only with `pytest -m live`; `pyproject` gained `[dev]` extras + pytest/coverage config; README "Development" section |
| 17 | **Quality gates:** `ruff` (lint + format, config in `pyproject`), `mypy --strict` for `todo_engine/`, `pre-commit` hooks, `Makefile`/`nox` tasks (`lint`, `test`, `typecheck`) | all gates pass locally; `pre-commit run --all-files` clean | ✅ Done (2026-08-23) — `ruff` (E/W/F/I/UP/B/BLE/C4/SIM/PT/RUF, line 100, py310) + `ruff format` applied repo-wide; `mypy --strict` clean on `todo_engine/` (hooks typed as `dict[HookEvent, list[HookMatcher]]`); `.pre-commit-config.yaml` (pre-commit-hooks, ruff-check/format, local mypy) passes `--all-files`; `noxfile.py` sessions `lint / fmt / typecheck / test / live` run in the current env (`nox` = lint+typecheck+test); dev extras grew ruff/mypy/pre-commit/nox |
| 18 | **CI:** GitHub Actions — matrix {ubuntu, windows, macos} × {3.10, 3.13}: install, ruff, mypy, pytest; `live` tests excluded; badge in README | green on first push; failure on a deliberately broken PR | ✅ Done (2026-08-23) — repo created **private** at `github.com/pervezshaik/todo-engine` (flip to public after reviewing `examples/outputs/gmail-check.md`, which carries the owner's email + mailbox stats and is in history); `.github/workflows/ci.yml` = `pre-commit` job + 6-job matrix running ruff / mypy --strict / pytest with coverage (`fail_under = 85` in pyproject), coverage.xml artifacts, concurrency cancel; green on run 3 (run 1: unpinned ruff 0.16 formats Markdown code blocks → pinned `ruff==0.15.4` + `docs/` excluded; run 2: `FORCE_COLOR` made rich wrap/colorize → autouse `plain_terminal` fixture); PR #1 with a deliberate break went red on 7/7 jobs and was closed |
| 19 | **Packaging & release:** full `pyproject` metadata (readme, license, authors, urls, classifiers, keywords), `CHANGELOG.md`, `0.2.0` tag, GitHub Release, PyPI via trusted publishing workflow on tag; `pipx install todo-engine` documented | `pipx install todo-engine && todo-engine --version` works on a clean machine | planned |
| 20 | **CLI restructure:** `argparse` subparsers `run` (default/alias when first arg is a file), `watch`, `report`, `init` (scaffold `todo.md`, `skills/`, `tools/example.py`, `mcp_config.example.json`, `todo-engine.toml`), `doctor` (auth smoke test + registry validation + connector discovery, exits non-zero on problems — absorbs `scripts/auth_check.py`); `--version`; exit codes documented (0 all done / 1 some failed / 2 usage / 3 engine unavailable) | help text snapshot tests; `todo-engine todo.md` ≡ `todo-engine run todo.md`; `doctor` reports the same as the old auth check | planned |
| 21 | **Config file:** `todo-engine.toml` next to the todo file (or `--config`): `[defaults]` model, verifier_model, memo_model, max_turns, verify, workdir, parallel=1, budget_usd, timeout_s; precedence CLI > env (`TODO_ENGINE_*`) > file > built-in; `init` writes a commented template | config round-trip tests; a bad key is reported with file + line | planned |
| 22 | **Robustness fixes:** verifier fails closed (engine error → outcome `engine_error`, line marked `[!]` + reason in transcript) ; `--confirm` prompt via `asyncio.to_thread`; OS-aware system prompt + shell tool selection (`platform.system()`); models from config; per-task `--timeout` (wall clock, `asyncio.wait_for`, outcome `timeout`); graceful Ctrl-C in `run` and `watch` (revert `[~]`, write transcript, print summary); `history` rows carry `task_id` (hash of file + normalized text) and `--report` groups on it | unit tests per fix; manual Ctrl-C leaves the file in a consistent state | planned |
| 23 | **Observability & output modes:** `runs/engine.log` (rotating, INFO), `--json` (one JSON object per event on stdout for schedulers/Task Scheduler/cron), `--quiet`; `--dry-run` (parse + print the plan: queue, directives, capabilities, resolved config — no agent calls) | `--json` output validates against a documented schema; `--dry-run` makes zero SDK calls (asserted via the fake) | planned |
| 24 | **Security pass:** redact values of env vars referenced in `mcp_config.json` from transcripts and `*.commands.log`; `--yolo` banner; `SECURITY.md`; dependency pinning policy; `mcp_config.json` git-ignored with `.example` tracked | a token in a command line appears as `***` in logs; test covers it | planned |
| 25 | **Docs & presence:** README rewrite for a stranger (30-second pitch, install, demo GIF via `vhs`, feature table, badges), `CONTRIBUTING.md`, issue/PR templates, `docs/` published with mkdocs-material (specs, design, CLI reference generated from argparse, FAQ); `examples/` gallery (file tasks, web research, custom tool, MCP server, `@use:`/`@retries:`/`@verify:`) | fresh-eyes review: a new user reaches a verified `[x]` from the README alone; docs site builds in CI | planned |
| 26 | **v0.3 cut:** cross-platform acceptance run (§7 checks on Windows + macOS + Linux CI, live tests on the dev machine), CHANGELOG, tag, release | all §7 acceptance checks pass on all three OSes | planned |

**Acceptance for the phase:** (1) `pipx install todo-engine` on a clean machine → `todo-engine init` → `todo-engine doctor` → `todo-engine run todo.md` completes the sample file; (2) CI green on three OSes; (3) coverage ≥85 %, `ruff`/`mypy --strict` clean; (4) the v2 acceptance run (§7) passes unchanged through the alias; (5) README + docs site let a stranger succeed without asking.

*Note:* `evolution.md` §8 provisionally numbers its platform steps 15–33; those will be rebased after this phase when that plan is picked up.

## 7. Verification plan (acceptance run)

Sample `todo.md`:

```markdown
- [ ] Create a file called hello.txt containing a haiku about agents
- [ ] Look up today's weather in Hyderabad and save a summary to weather.md
- [x] Already-done task (should be skipped)
```

1. `todo-engine todo.md` → task 3 skipped; task 1 creates `hello.txt`; task 2 uses web research and writes `weather.md`; both flip to `- [x]`; transcripts + cost table produced.
2. Impossible task → stays `- [ ]`, failure logged, run continues.
3. `--confirm` → every shell command prompts; "n" denies with reason surfaced to the agent.
4. Capability path → task with `@use: example` calls the seeded custom tool; task needing an unregistered capability ends `STATUS: failed — missing capability: …`.
5. Entire suite runs with no `ANTHROPIC_API_KEY` set.

### Acceptance results (2026-08-22)

| Check | Result |
|---|---|
| Sample run (skip + local file + web research + checkboxes + logs + cost table) | ✅ Pass — task 2 fetched live Hyderabad weather via WebFetch, $0.16 |
| Impossible task fails gracefully, run continues | ✅ Pass — `STATUS: failed — file ... does not exist`, next task still ran |
| Missing capability refused, not improvised | ✅ Pass — `STATUS: failed — missing capability: sms`; agent explicitly declined email-gateway workarounds |
| `--confirm` deny path | ✅ Pass — `whoami` intercepted (PowerShell tool on this machine), logged pre-execution, denial reason respected by agent |
| Watch mode | ✅ Pass — appended task picked up in ~10s, executed, box flipped |
| No API key anywhere | ✅ Pass — subscription login via stored Claude Code credentials |

Note: on this machine agents surface shell commands through the `PowerShell`
tool (no Git Bash in the agent environment); `hooks.py` matches both `Bash`
and `PowerShell`, so logging and the confirm gate cover either.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| SDK doesn't pick up subscription login (docs claim API-key-only) | Step-1 smoke test before any other work; `cli_path` and `setup-token` fallbacks; worst case the runner shells out to `claude -p` per task (same architecture, ~50-line change in `agent.py`) |
| Agent checks off work it didn't do | Two-factor success (no SDK error + explicit `STATUS: done`); transcripts for audit |
| Destructive shell commands | Pre-execution command log; `--confirm` gate; default mode is not `bypassPermissions` |
| `--watch` racing user edits | `mark_done` re-reads the file immediately before rewriting a single line |
| Windows shell quirks | Agents told they're on Windows 11; Git Bash present for a proper Bash tool |
