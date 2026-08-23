# Evolution Blueprint — from todo-engine to a Personal Program-Management Platform

**Status:** Draft v1 · 2026-08-23
**Owner:** Pervez Shaik
**Companion docs:** [specs.md](specs.md) (what v2 is) · [design.md](design.md) (how v2 is built; steps 0–14 ✅)

> todo-engine today turns one markdown checklist into executed, verified work. This document describes how the same primitives grow into a **local, file-based control plane for one person running many programs and projects** — agents that do work, watch systems, follow up with people, keep RAID documentation and write status reports — and catalogs the ideas worth building along the way. It also gives a home to the "ranked improvement roadmap" that `design.md` §6 cites but which previously lived only in conversation.

## 1. Context — what v2 proves, and the leap

v2 (specs §7) proves the loop: a `- [ ]` line → fresh agent → independent verification → `[x]`, with typed outcomes, smart retry, cross-run memory, a JSONL event log, and three user-extensible capability registries. Gmail, Calendar, Drive, GitHub and Playwright are already wired (design §6 steps 8–10). Every primitive below exists and is exercised; the platform is a generalization, not a rewrite.

| v2 primitive (where) | What it becomes |
|---|---|
| `parser.py` — `_CHECKBOX_RE` markers, generic `Task.directives` | The **universal work item**: any checklist line in any file, with an open `@key:` grammar (owner, due, depends, source, …) and more lifecycle markers |
| `agent.py` — `SYSTEM_PROMPT`, `TaskContext`, `TaskOutcome`, `run_task` | The **agent role** pattern: system prompt + model + tool allow/deny + autonomy + trigger. Executor is role #1 |
| `verifier.py` — Haiku, `Read/Glob/Grep` only, `VERDICT:` | Template for every **read-only role** (Monitor, Risk Radar, citation check) and for "verify before any outward action" |
| `memory.py` — `distill`, `relevant_memos` | **Scoped memory**: global + per-program + per-person, same memo format |
| `history.py` — `record_attempt` rows, `--report` | The **platform event log**: every agent action, approval and outward write, per program |
| `hooks.py` — PreToolUse deny-with-reason | The **approval gate**: outward MCP tools (send mail, post Slack, write Jira) are intercepted, queued to an inbox file, and released by the human checking a box |
| `capabilities.py` — registries, manifest, `${VAR}` expansion, inherited connectors | **Per-program capability scopes**: which skills/tools/servers a program's agents may see and use |
| `runner.py` — `run_once`, `_run_one`, `_watch_loop`, `[~]` | The **scheduler tick**: many files, cadences, pollers, per-program lanes — `_watch_loop` is already a one-file scheduler |

**The leap** is four-fold: from *pull* ("do my tasks") to *push* (agents write lines into files for me); from *me* to *people* (work owed by others, follow-ups, commitments); adding *time* (cadences, due dates, SLAs); and adding *reporting* (status, RAID, portfolio views) as first-class outputs. Jira and Slack are the only net-new integrations; everything else is already proven.

## 2. Vision & end-state

**Vision:** a local, file-based operating system for one program manager — every program has a folder, every folder has agents, every agent writes markdown, and the human's job is to read, edit and check boxes.

### 2.1 A day in the life (target end-state)

| Time | What happens | Who |
|---|---|---|
| 07:30 | `portfolio.md` regenerated: per-program health, slipped milestones, open RAID items, overdue follow-ups | Portfolio role (scheduled) |
| 07:35 | `inbox.md` holds 6 proposed outward actions (2 Slack nudges, 1 Jira comment, 3 emails). Owner checks 5 boxes, deletes 1 | Human ≈ 3 min |
| 08:00 | Monitor finds two Jira tickets past due with no update → appends `- [ ] Chase ENG-412 @owner: priya @due: 2026-08-25 @source: jira:ENG-412` to `programs/atlas/followups.md` | Monitor |
| 08:05 | Approved nudges go out; `[>]` marker set on those lines; `history.jsonl` links each send to its approval | Chaser + gate |
| 09:50 | Before the 10:00 steering meeting, `notes/2026-08-23-steerco-prep.md` appears: agenda from Calendar, open RAID items, last status, unresolved threads | Meeting Prep |
| 11:10 | Owner pastes raw notes into `notes/2026-08-23-steerco.md`; Coordinator extracts `- [ ]` actions (with `@owner`), `Decision:` lines into `raid.md`, and new `@depends` edges | Coordinator |
| 14:00 | Executor runs the owner's own `projects/ingest-v2/todo.md` exactly as today | Executor + Verifier |
| 16:30 | Risk Radar proposes one new risk ("vendor API deprecation, evidence: 3 threads, 1 ticket") into `inbox.md` for acceptance into `raid.md` | Risk Radar |
| Fri 15:00 | Status Reporter drafts the weekly per `skills/weekly-report/SKILL.md`; a citation verifier rejects one sentence with no source; the draft lands in Gmail Drafts and `inbox.md` | Status Reporter + Verifier |
| Monthly | Portfolio retro: cost per program, autonomy promotions, stale assumptions | Portfolio + Memory Curator |

### 2.2 What the owner stops doing manually

| Today | Target |
|---|---|
| Re-reading Jira boards / PR lists to find slippage | Reads `followups.md` and `portfolio.md` |
| Writing chase messages from scratch | Approves drafted nudges in `inbox.md` |
| Assembling meeting-prep packs | Opens the generated prep note |
| Turning notes into actions and decisions | Edits what the Coordinator extracted |
| Maintaining the RAID log | Reviews proposals; accepts by checking a box |
| Writing the weekly status | Edits a cited draft |

**Explicitly not the vision:** not a chatbot, not a Jira/Confluence replacement, not a team server. A *personal* control plane, single-user, local.

## 3. Guiding principles

1. **Markdown is state and source of truth.** External systems are synced-from / pushed-to. Any index (`index.sqlite`, dashboards) must be rebuildable from files. `_set_marker`'s re-read-before-write stays the rule for every engine write.
2. **Graduated autonomy ladder.** L0 *Observe* (read only) · L1 *Draft* (write to files only) · L2 *Approve-to-act* (outward action queued in `inbox.md`) · L3 *Policy-auto* (outward action auto-allowed under an explicit per-program rule) · L4 *Full auto*. Anything another human sees starts at L1/L2 and is promoted per program after N clean approvals.
3. **Verify before claim.** Executor work is judged by the verifier today; reports follow "no citation, no sentence"; outward actions are verified against their source lines.
4. **Auditability by construction.** Every action = a `history.jsonl` row + a transcript + (for outward actions) the approving inbox line and payload file.
5. **No API key; subscription login; local first.** Haiku for cheap read-mostly roles, the default model for Executor/Coordinator.
6. **Small composable agents that share files, never sessions.** One `query()` per role invocation, as today.
7. **Humans edit files freely.** Only `runs/` and `memory/` are engine-owned; everything else is human-editable and engine-tolerant.
8. **Cost-aware.** Per-role budgets (max turns / max cost per tick), per-program cost in `--report`.
9. **Prompt injection is a first-class threat.** Content pulled from email, Jira, Slack or the web is *data*, never instructions; any outward action derived from untrusted content is always L2 regardless of promotion (mitigations in §10).

## 4. Domain model evolution

### 4.1 Entities

| Entity | Definition | Lives in | Identity |
|---|---|---|---|
| Task | Atomic unit of agent work (today's checklist line) | any checklist file | file + line; optional `@id:` when referenced elsewhere |
| Project | A deliverable with its own task list | `programs/<p>/projects/<q>/` | folder name |
| Program | A set of projects, people and cadences with one owner | `programs/<p>/` | folder name |
| Portfolio | All programs | workspace root | — |
| Person / Stakeholder | Someone work is owed to or by; channel preferences | `programs/<p>/people.md` | handle |
| Follow-up / Commitment | Work owed by someone else, with due date and source | `followups.md` | line (`@id:` if chased) |
| RAID entry | Risk / Assumption / Issue / Dependency / Decision | `raid.md` table | `R-12`, `D-3`, … |
| Milestone | Dated target with status | `program.md` table | name |
| Status report | Dated, cited narrative | `status/<date>.md` | date |
| Approval | A proposed outward action awaiting a human | `inbox.md` line + `runs/<ts>/approvals/<id>.md` | `@id:` |
| Event | One attempt/action/approval record | `runs/history.jsonl` | row |

### 4.2 Workspace layout

```
workspace/
├── portfolio.md              generated: cross-program health (engine-written, read-only to humans)
├── inbox.md                  approval checklist: check = approve, delete = deny
├── agents.md                 global roster: role · cadence · autonomy · model · budget
├── skills/  tools/  mcp_config.json   shared registries (exactly today's)
├── memory/                   global lessons (today's memory/)
├── runs/                     transcripts, approvals/, history.jsonl, index.sqlite (rebuildable)
└── programs/
    └── atlas/
        ├── program.md        goals, milestones table, cadences, links to Jira/Confluence/Slack
        ├── people.md         stakeholders, channels, nudge preferences
        ├── raid.md           RAID table
        ├── followups.md      checklist of work owed by others
        ├── agents.md         per-program overrides (autonomy, scopes, cadences)
        ├── status/           2026-W34.md …
        ├── notes/            meeting notes + generated prep packs
        ├── memory/           program-scoped lessons
        └── projects/
            └── ingest-v2/
                ├── project.md
                └── todo.md   ← exactly today's file; today's CLI keeps working on it unchanged
```

**Backward-compatibility requirement:** `todo-engine programs/atlas/projects/ingest-v2/todo.md` must behave exactly as v2 does today. Registries are resolved by walking up from the todo file to the workspace root (today: `project_root = todo_file.parent`). Frontmatter on `program.md`/`project.md` uses the existing `capabilities._parse_frontmatter` (key: value lines, no nested YAML — see §10 open questions).

Samples (fictional program "Atlas"):

```markdown
<!-- programs/atlas/program.md -->
---
name: atlas
owner: pervez
jira: ATL
slack: #atlas-core
confluence: ATLAS
---
# Atlas — data platform consolidation

| Milestone | Target | Status | Evidence |
|---|---|---|---|
| Ingest v2 GA | 2026-09-30 | at risk | R-4, ATL-412 slipped twice |
| Legacy decommission | 2026-11-15 | on track | — |
```

```markdown
<!-- programs/atlas/raid.md -->
| ID | Type | Title | Owner | Sev | Likelihood | Status | Source | Last reviewed | Next action |
|---|---|---|---|---|---|---|---|---|---|
| R-4 | Risk | Vendor API v1 deprecation before migration | priya | H | M | open | mail:thread/18c…, ATL-398 | 2026-08-22 | confirm vendor EOL date |
| D-3 | Decision | Keep Kafka, drop Pulsar evaluation | pervez | — | — | decided 2026-08-19 | notes/2026-08-19-steerco.md | — | — |
```

```markdown
<!-- programs/atlas/followups.md -->
- [>] Chase ENG-412 estimate from @priya @owner: priya @due: 2026-08-25 @source: jira:ENG-412 @id: f-031
- [ ] Get vendor EOL date in writing @owner: sam @due: 2026-08-27 @source: mail:thread/18c9f… @project: ingest-v2
```

```markdown
<!-- programs/atlas/people.md -->
| Handle | Name | Role | Channel | Nudge policy |
|---|---|---|---|---|
| priya | Priya N. | Tech lead, ingest | slack DM | ≤1/day, never before 10:00 |
| sam | Sam O. | Vendor manager | email | weekly digest only |
```

### 4.3 Directive grammar generalization

Today `parser._DIRECTIVE_KEYS` is a closed tuple (`use`, `retries`, `verify`). Open it to any `@key:` and standardize:

| Directive | Meaning | Consumed by |
|---|---|---|
| `@use:` | Favor these capabilities (exists) | Executor |
| `@retries:` / `@verify:` | Retry count / verification escape (exist) | Runner |
| `@owner:` | Person handle responsible | Chaser, Portfolio |
| `@due:` | ISO date | Monitor, Chaser, Portfolio |
| `@depends:` | `@id`s that must be `[x]` first | Scheduler |
| `@cadence:` | `daily 07:30`, `weekly fri 15:00`, `every 2h` | Scheduler |
| `@project:` / `@program:` | Scope when a line lives outside its folder (e.g. global `inbox.md`) | All |
| `@agent:` | Role that should run this line (default Executor) | Scheduler |
| `@gate:` | Force an autonomy level for this line (`L2`) | Gate |
| `@source:` | Provenance of an engine-written line (`jira:ATL-412`, `mail:thread/…`, `slack:…`) — **mandatory** for engine-written lines | Dedupe, audit |
| `@priority:` | `P0`–`P3` ordering within a lane | Scheduler |
| `@id:` | Stable identity for cross-references | Everything |

New markers (one place to extend: `_CHECKBOX_RE`): `[!]` blocked / needs a human decision; `[>]` waiting on an external person (set by the Chaser after a nudge is sent). Lifecycle: `[ ]` → `[~]` → `[x]` | `[ ]` | `[!]` | `[>]` → … Rule: **no hidden state** — every engine-written line or marker is human-editable, and editing it is the supported way to steer.

## 5. Agent roster per program

A **role** = system prompt + model + tool allow/deny lists + autonomy level + trigger + budget. `verifier.py` is the reference implementation (read-only tools, cheap model, one-line verdict). Proposed: `todo_engine/roles/<role>.py` each exporting a `RoleSpec`; `agent.run_task` becomes `roles/executor.py`, and `TaskContext` generalizes to `RoleContext`.

| Role | Trigger | Reads | Writes | Autonomy | Model | Builds on |
|---|---|---|---|---|---|---|
| Executor | pending line | task text, registries, memory | working dir, `[x]` | L1–L4 (today: acceptEdits/yolo) | default | `agent.py` (exists) |
| Verifier | after Executor success | working dir | verdict | L0 | haiku | `verifier.py` (exists) |
| Monitor / Watcher | `@cadence` poll | Jira, GitHub, Calendar, Gmail, Slack | `followups.md` lines with `@source` | L1 | haiku | verifier pattern + connectors |
| Follow-up / Chaser | overdue `followups.md` lines | `people.md`, chase log | drafted nudge → `inbox.md`; `[>]` | L2 → L3 per person | default | hooks gate |
| Coordinator / Planner | new/changed `notes/*.md` | notes, `raid.md`, todo files | actions, decisions, `@depends` | L1 | default | Executor + parser |
| RAID Scribe | weekly + on Coordinator output | threads, tickets, notes | `raid.md` rows, "last reviewed" | L1 | haiku | read-only pattern |
| Status Reporter | `@cadence: weekly fri 15:00` | `status/`, `raid.md`, history, Jira | `status/<week>.md` + Gmail/Confluence draft | L2 | default | `skills/weekly-report` |
| Inbox Triage | `@cadence: every 2h` | Gmail/Slack | `followups.md`, notes, `inbox.md` | L1 | haiku | Gmail connector |
| Meeting Prep / Notes | Calendar event − 30 min | Calendar, RAID, threads, status | `notes/<date>-prep.md` | L1 | default | Calendar connector |
| Risk Radar | weekly | everything read-only | risk candidates → `inbox.md` | L1 | default | read-only pattern |
| Scheduler | engine tick | all files, `agents.md` | work queue | — (not an LLM) | — | `runner._watch_loop` |
| Memory Curator | monthly | `memory/`, history | merged/expired memos, promotion proposals | L1 | haiku | `memory.py` |

Per-role notes:

- **Monitor:** one poller per source; dedupe on `@source` before appending; never edits human-written lines. Failure mode: noisy lines → cap per tick, summarize overflow into one line.
- **Chaser:** respects `people.md` nudge policy; **never more than one nudge per person per day**, never to someone not in `people.md`; every nudge is L2 until the program's promotion rule says otherwise; writes a chase log under `runs/`.
- **Coordinator:** extracts, never executes; marks ambiguous items `[!]`.
- **Status Reporter:** every sentence carries a citation (`[ATL-412]`, `[R-4]`, `[mail:…]`); a **citation verifier** (Verifier variant) rejects uncited claims before the draft is offered.
- **Risk Radar:** proposes only with ≥2 independent pieces of evidence; proposals go to `inbox.md`, not straight into `raid.md`.
- **Scheduler:** pure engine code — cron parsing, mtime watching, poll timers, lane queues. The only component that must be correct without an LLM.

## 6. Architecture evolution

### 6.1 From runner to orchestrator — target

```
 Sources of truth (files)                            External systems (synced-from / pushed-to)
 ┌────────────────────────────────┐                  ┌─────────────────────────────────────┐
 │ programs/*/todo.md followups.md│◄── read ────────►│ Jira · Confluence · Gmail · Calendar│
 │ raid.md people.md notes/ status│                  │ Drive · GitHub · Slack · Playwright │
 │ inbox.md agents.md portfolio.md│                  └──────────────▲──────────────────────┘
 └──────────────▲─────────────────┘                                 │ MCP / acli / connectors
                │ parse · write one line (re-read first)            │ read = L0 · write = gated
 ┌──────────────┴─────────────────────────────────────────────────┐ │
 │ todo-engine serve                                               │ │
 │  Scheduler: cron/@cadence · multi-file watch · pollers          │ │
 │      └─► per-program lanes (sequential inside, concurrent across)│ │
 │            └─► role runners  = query(prompt, RoleSpec options)  ├─┘
 │                   ├─ PreToolUse gates (gates.py)                 │
 │                   │    outward tool? → payload → inbox.md, deny  │
 │                   └─ Verifier / citation check                   │
 │  Approval gate: inbox.md box checked → release payload → history │
 │  Event log: runs/history.jsonl  ──► runs/index.sqlite (rebuild)  │
 │  Memory: memory/ (global) + programs/*/memory/                   │
 │  Notifier: toast · Slack self-DM · daily digest                  │
 └─────────────────────────────────────────────────────────────────┘
```

### 6.2 Module map — today → evolved

| Module today | Evolves into |
|---|---|
| `__main__.py` (flags) | Subcommands: `run` (today's behavior, default), `serve` (scheduler daemon), `report`, `inbox` (list/approve from terminal), `status` (portfolio), `new-program <name>` (scaffold) |
| `runner.py` — `Runner`, `run_once`, `_run_one`, `_watch_loop` | `scheduler.py` (tick, cadences, pollers, multi-file watch) + `lane.py` (`ProgramLane`: sequential per program; lanes concurrent, `--parallel N`); `_run_one` becomes the Executor lane step |
| `agent.py` — `run_task`, `TaskContext` | `roles/executor.py`; `RoleSpec` + `RoleContext` shared by all roles |
| `verifier.py` | `roles/verifier.py` + `roles/citation_verifier.py`; **fix the soft spot: fails open on engine error** (`Verdict(passed=True, …)`) → fail closed with `[!]` |
| `hooks.py` — `make_shell_hooks` | `gates.py`: PreToolUse matchers on shell *and* outward MCP tools (`mcp__claude_ai_Gmail__send_message`, Slack post, Jira transition …) → write payload to `runs/<ts>/approvals/<id>.md`, append inbox line, deny with reason ("queued for approval as a-017") |
| `memory.py` | Scoped dirs (global / program / person); `relevant_memos` searches program first, then global |
| `history.py` — `record_attempt` | Extra fields `program, project, agent, source, approval_ref, action_type`; `index.sqlite` rebuilt from the JSONL; **fix the gap: report joins on `task_text`** → join on `@id`/file+line |
| `capabilities.py` | Per-program scopes from `agents.md` (allow/deny lists filter manifest + `allowed_tools`) |
| `parser.py` | Open directive grammar, `[!]`/`[>]`, `parse_tables()` for `raid.md`/`people.md`/milestones |

### 6.3 Mechanics

- **Triggers:** polling first (`@cadence` per role, per program); webhooks never — this runs on a laptop behind NAT. Event → line materialization always dedupes on `@source` and never rewrites a line a human touched.
- **Parallelism:** one lane per program (sequential inside, preserving today's isolation guarantees); lanes run concurrently with a global cap (`--parallel N`, default 2) for rate limits and cost.
- **Approval inbox:** an outward tool call hits a gate → payload saved → `- [ ] Send Slack nudge to priya re ENG-412 @id: a-017 @program: atlas @gate: L2` appended to `inbox.md` → tool call denied with the reason. The human checks the box (or deletes the line / adds `@deny: reason`). The Scheduler sees the `[x]` on its watch, replays the payload, records `approval_ref=a-017` in history. This reuses 100 % of today's watch + parse + `_set_marker` machinery.
- **Per-program isolation:** `cwd` = program folder, filtered capability manifest, program memory, program budget.
- **State store:** files are truth; `runs/index.sqlite` is a derived index for `status`/dashboards and is deleted+rebuilt on schema change.
- **Dashboards:** markdown first (`portfolio.md`); later `serve --ui` — a tiny read-only local web page over the index.
- **Notifications:** Windows toast on new inbox items; optional Slack self-DM; daily digest email via the existing Gmail connector (itself L2 until promoted).
- **Windows operation:** Task Scheduler at logon → `todo-engine serve --workspace C:\...`; health file `runs/serve.heartbeat` so a stalled daemon is visible.

## 7. Integration map

| System | Access path | Read for | Write for | Starting autonomy | Promotion rule |
|---|---|---|---|---|---|
| Jira | `acli` (present on this machine) first; Atlassian MCP later | ticket status, due dates, comments | comments, transitions | read L0 / write L2 | 20 clean approvals per program → L3 for comments only |
| Confluence | `acli` / Atlassian MCP | existing pages, decision log | status pages, decision log | L2 | never above L2 (public artifact) |
| Gmail | inherited connector (wired, design step 10) | threads, commitments | drafts (L1), send (L2) | L1 draft / L2 send | per recipient in `people.md` |
| Calendar | inherited connector | events, attendees | prep notes only | L0 | — |
| Drive / Docs / Sheets | inherited connector | shared docs | status exports | L2 | L3 for owner-only files |
| GitHub | `mcp_config.json` (wired, step 8) | PRs, CI, issues | comments | L0 / L2 | as Jira |
| Slack | **net new** — MCP server via `mcp_config.json`, token as `${SLACK_BOT_TOKEN}` through `_expand_env` | channels, DMs | nudges, digests | L2 | per person in `people.md` |
| Playwright | wired (step 9) | anything without an API | — | L0 | — |
| Markdown files | direct | everything | everything | L4 | — |

Write-tool patterns (which `mcp__*` tools count as outward) live in `agents.md` and are enforced by `gates.py`, not by prompts.

## 8. Phased roadmap

Continues `design.md` §6 numbering. All statuses `planned`. Each phase ends with what it unlocks.

### v3 — Multi-project & scheduling

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 15 | Open directive grammar (`_DIRECTIVE_KEYS` → any key) + `[!]`/`[>]` markers + `parse_tables()` | `scripts/parser_test.py` covers new keys, markers, a RAID table round-trip | planned |
| 16 | Workspace layout + `new-program` scaffold + history fields `program/project/agent`; registries resolved by walking up to the workspace root | today's CLI runs a `programs/<p>/projects/<q>/todo.md` unchanged; `--report` groups by program | planned |
| 17 | `serve`: scheduler tick — multi-file watch, `@cadence` parsing, `@depends` ordering | a cadence line fires on time; a dependent line waits for its `@id` | planned |
| 18 | Program lanes + `--parallel N` | two programs run concurrently, each sequential inside; transcripts untangled | planned |
| 19 | `gates.py` + `inbox.md` approval loop on Gmail send | send intercepted → inbox line → box checked → mail sent → history row carries `approval_ref` | planned |

*Unlocks:* many projects, timed work, the first safe outward action.

### v4 — Program agents

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 20 | `RoleSpec`/`RoleContext` refactor; Executor + Verifier moved under `roles/`; verifier fails closed | all v2 tests pass; engine-error verdict yields `[!]` not `[x]` | planned |
| 21 | Monitor (Jira via `acli`, GitHub, Calendar) → `followups.md` with `@source`, dedupe | a slipped ticket appears once, not twice, across two ticks | planned |
| 22 | Chaser with `people.md` policy, `[>]`, chase log | drafted nudge reaches inbox; second nudge same day is suppressed | planned |
| 23 | RAID Scribe | `raid.md` rows updated with "last reviewed"; no human row rewritten | planned |
| 24 | Status Reporter + citation verifier, `weekly-report` skill | weekly draft in Gmail Drafts; an uncited sentence is rejected in the transcript | planned |

*Unlocks:* a program that watches, chases and reports itself with the human approving.

### v5 — Coordination & dashboard

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 25 | Coordinator (notes → actions / decisions / `@depends`) | pasted notes produce correct lines; ambiguous ones marked `[!]` | planned |
| 26 | Meeting Prep + Inbox Triage | prep note 30 min before an event; triage creates follow-ups from a real thread | planned |
| 27 | `index.sqlite` + `portfolio.md` + notifications | portfolio regenerated on schedule; index deleted → rebuilt identical | planned |
| 28 | `serve --ui` read-only local page | renders portfolio, inbox, history per program | planned |
| 29 | Slack + Confluence integrations | nudge via Slack (L2); status page published with diff shown in inbox | planned |

*Unlocks:* the full day-in-the-life of §2.1.

### v6 — Portfolio & intelligence

| Step | Deliverable | Verified by | Status |
|---|---|---|---|
| 30 | Risk Radar (evidence-gated proposals) | proposal cites ≥2 sources; goes to inbox not `raid.md` | planned |
| 31 | Portfolio role (cross-program health, people-load heatmap) | `portfolio.md` flags a person with >N open follow-ups | planned |
| 32 | Memory Curator + autonomy promotion by track record | promotion proposal after N clean approvals; contradicted memos merged | planned |
| 33 | Retro / analytics (cost, latency, success per role and program) | `report` shows per-role and per-program breakdowns over history | planned |

*Unlocks:* the system improves itself and the owner manages a portfolio, not tasks.

## 9. Idea catalog

Value H/M/L · Effort S/M/L. Not commitments — a ranked pool to pull from.

**Execution**

| Idea | Value | Effort |
|---|---|---|
| `@depends:` DAG with cycle detection and topological ordering | H | S |
| Task templates `@template: release-checklist` expanding into lines | M | S |
| `--plan` dry run: agent proposes steps, no tools executed | M | S |
| `@budget: $0.50` per line; lane stops at budget | M | S |
| Sandboxed branch + PR per code task (git worktree), never writes main | H | M |

**Monitoring**

| Idea | Value | Effort |
|---|---|---|
| Jira drift detector (due date moved ≥2 times, no comment in N days) | H | S |
| Stale PR / red CI watcher | M | S |
| Calendar overload radar (>6 h meetings/day, back-to-backs) | M | S |
| SLA timers + escalation ladder (person → lead → owner) | H | M |
| Silence detector (stakeholder quiet for N days on an open item) | M | S |

**People & follow-up**

| Idea | Value | Effort |
|---|---|---|
| Per-person preference learning (channel, tone, best time) | M | M |
| Commitment extraction from threads ("I'll send it Friday") | H | M |
| Drafted replies in the owner's voice from a `skills/voice` skill | M | S |
| 1:1 prep packs | M | S |
| Recognition nudges (things worth thanking people for) | L | S |

**Reporting**

| Idea | Value | Effort |
|---|---|---|
| RAG rationale with citations for every status line | H | M |
| Multi-audience variants (exec / team / vendor) from one source | M | S |
| Confluence / Docs publish with the diff shown in inbox | H | M |
| Decision log page generated from `raid.md` D-rows | M | S |
| "What changed since I last looked" digest per program | H | M |
| Sheets export of milestones / RAID | L | S |

**Planning & intelligence**

| Idea | Value | Effort |
|---|---|---|
| Milestone forecast from history velocity | M | M |
| Risk radar with proposed mitigations | H | M |
| What-if replanning ("if ENG-412 slips 2 weeks…") | M | L |
| Cross-program dependency / people-load heatmap | H | M |
| Assumption expiry (re-validate `raid.md` A-rows after N days) | M | S |

**Personal productivity**

| Idea | Value | Effort |
|---|---|---|
| Morning brief / evening wrap | H | S |
| Inbox buckets (act / delegate / read / ignore) | M | S |
| Notes → actions in <5 min of paste | H | M |
| Batched approval windows (inbox processed at 09:00 / 14:00 only) | M | S |

**Meta**

| Idea | Value | Effort |
|---|---|---|
| Autonomy promotion by track record (per role × program × person) | H | M |
| Memory Curator + contradiction detection | M | M |
| Skill auto-drafting after 3 similar verified tasks | M | M |
| Eval harness replaying `history.jsonl` against prompt changes | H | M |
| GEPA-style reflective prompt evolution from failure transcripts (guarded, human-reviewed) | M | L |
| Cost / latency per role in `report` | H | S |

## 10. Risks, open questions, non-goals

### 10.1 Risks

| Risk | Mitigation |
|---|---|
| Prompt injection via email / Jira / Slack / web content | External content is quoted as data in prompts; outward actions derived from it are always L2; gates enforce by tool name, not by prompt; verifier checks action against its `@source` |
| Hallucinated or noisy engine-written lines clutter human files | Mandatory `@source:`; per-tick caps; engine never edits human-written lines; lines are deletable and deletion is remembered (dedupe key) |
| Over-nudging / wrong tone damages relationships | `people.md` policy, ≤1 nudge/person/day, L2 by default, chase log visible |
| Human inbox overload (approval fatigue) | Batched windows, digest mode, promotion to L3 where the track record is clean, `@priority` |
| Multi-writer markdown conflicts (human + lanes) | Single-line re-read-before-write, per-file write lock inside the daemon, `[!]` on conflict |
| Rate limits / fair-use on the subscription | Global `--parallel` cap, per-role budgets, Haiku for read-mostly roles |
| OAuth expiry on scheduled runs | Heartbeat + toast on auth failure; roles that need a connector degrade to `[!]` lines, not silent skips |
| Windows daemon reliability | Task Scheduler at logon, heartbeat file, idempotent ticks (safe to restart mid-tick) |
| People data privacy | `people.md` stays local; nothing leaves except approved outward actions; no cloud sync by default |
| Scope creep | Phases end with "unlocks"; each step has a concrete verification; the idea catalog is explicitly not a commitment |

### 10.2 Open questions

| Question | Current recommendation |
|---|---|
| Jira via `acli` or Atlassian MCP? | `acli` first (already installed, CLI-friendly for Monitor); MCP when write gating needs tool-name matching |
| Slack auth path | Bot token in env, `${SLACK_BOT_TOKEN}` via `_expand_env`; self-DM first, channels later |
| Workspace location: git, Drive, Obsidian vault? | git repo + optional Drive sync of `programs/`; `runs/` git-ignored |
| Daemon (`serve`) vs scheduled one-shots? | `serve` for watch/inbox latency; one-shot `run --tick` as a fallback for Task Scheduler |
| Global vs per-program inbox | Global `inbox.md` with `@program:`; one place to check in the morning |
| Model policy per role | Haiku for read-mostly roles, default for Executor/Coordinator/Reporter; overridable in `agents.md` |
| Real YAML for frontmatter? | Keep `_parse_frontmatter` (flat key: value) until a nested need appears |

### 10.3 Non-goals

Multi-user / team server · replacing Jira or Confluence · mobile app · general chat assistant · real-time webhooks · cloud hosting · fine-grained RBAC.

## 11. Next 3 concrete steps

1. **This document** + pointers from `README.md` and `docs/design.md` §6. ✅ Done (2026-08-23)
2. **Groundwork (steps 15–16):** open the directive grammar and add `[!]`/`[>]` in `todo_engine/parser.py`; add `program/project/agent` to `history.record_attempt` rows; scaffold one real program under `programs/<name>/` and run today's engine on its `projects/<q>/todo.md` unchanged.
3. **First outward loop end-to-end on one real program, draft-only (step 19):** Chaser → `inbox.md` → `gates.py` denies the Gmail send and queues it → box check sends → history links the approval. This exercises the riskiest assumptions (gating by tool name, inbox-as-approval, human-in-the-loop latency) before any other role is built.
