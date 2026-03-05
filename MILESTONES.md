# Nexus — Milestones

## Milestone 1 — Foundation ✅ (complete)
**Goal:** Working CLI with full CRUD, tests, and clean architecture.

Deliverables:
- [x] `pyproject.toml` with hatchling build + uv
- [x] Pydantic models (`Project`, `Sprint`, `Task`, `TimeEntry`, `ProjectStats`)
- [x] SQLite database layer (`Database` class) — 96% test coverage
- [x] CLI commands: `project`, `task`, `sprint`, `report`
- [x] Rich terminal UI (tables, panels, progress bars, theme)
- [x] 47 tests, 85% overall coverage, 0 warnings (Python 3.14)

**Test command:** `uv run pytest`

---

## Milestone 2 — Polish & Usability ✅ (complete)
**Goal:** Make the tool genuinely pleasant to use every day.

Deliverables:
- [x] `nexus task show <id>` — full task detail panel with sprint, estimate, time log
- [x] `nexus project search <query>` — case-insensitive search across project names, descriptions, task titles
- [x] `nexus dashboard <project_id>` — Rich kanban board (TODO / IN PROGRESS / DONE / BLOCKED columns) + overview stats + active sprint panel
- [x] `--json` flag on `project list` and `task list` for scripting/piping
- [x] 64 tests, 0 warnings

**Remaining for later:**
- [ ] Shell completion (`nexus --install-completion`)
- [ ] `nexus init` to set a per-directory default project

---

## Milestone 3 — Intelligence ✅ (complete)
**Goal:** Add AI-powered features using the Claude API (`claude-sonnet-4-6`).

Deliverables:
- [x] `src/nexus/ai.py` — `NexusAI` client with streaming, graceful no-key fallback
- [x] `nexus task suggest <project_id>` — streams AI-generated task suggestions; `--add` flag for interactive creation
- [x] `nexus task estimate <task_id>` — streams an hour estimate with reasoning, uses completed tasks as reference
- [x] `nexus report digest <project_id>` — streams a 3-paragraph AI project status narrative
- [x] All AI output streamed live via Rich `Live` + `Markdown` (real-time rendering)
- [x] 84 tests (20 AI-specific with full Anthropic mock), 0 warnings
- [x] Graceful error if API key is missing

**Usage:** `export ANTHROPIC_API_KEY=sk-... && nexus task suggest 1`

---

## Milestone 6 — Smart Workflow ✅ (complete)
**Goal:** Remove daily friction with config defaults, batch operations, and activity reporting.

Deliverables:
- [x] `nexus config set/get/show/unset` — JSON config at `~/.nexus/config.json` (runtime lookup, test-safe)
- [x] `nexus task next [project_id]` — ranked task queue (in_progress → critical → high → medium); uses `default_project` from config when no arg given
- [x] `nexus task bulk <action> <ids...>` — batch done/start/block/cancel/sprint on multiple tasks
- [x] `nexus report week <project_id> [--days N] [--ai]` — 7-day bar chart + completed/in-progress summary + optional AI paragraph
- [x] `weekly_report_prompt()` added to `ai.py`
- [x] `db.time_entries_since()` + `db.tasks_completed_since()` new DB query methods
- [x] 166 tests, 0 warnings

**Usage:**
```bash
nexus config set default_project 3    # set a default project
nexus task next                       # "what do I work on?" uses default_project
nexus task next 1 -n 10              # show 10 tasks for project 1
nexus task bulk done 4 5 6           # batch-complete tasks
nexus task bulk sprint 2 4 5 6       # assign tasks 4,5,6 to sprint #2
nexus report week 1                  # 7-day activity bar chart
nexus report week 1 --ai             # + AI narrative paragraph
nexus report week 1 --days 14        # 2-week lookback
```

---

## Milestone 5 — Live Time Tracking & Sprint Intelligence ✅ (complete)
**Goal:** Add a live stopwatch and data-driven sprint planning.

Deliverables:
- [x] `nexus timer start <task_id>` — starts a persistent stopwatch (state in `timer.json`)
- [x] `nexus timer stop [-n NOTE]` — stops timer, rounds to nearest 0.25h, auto-logs via `db.log_time()`
- [x] `nexus timer status` — shows running task name and `HH:MM:SS` elapsed
- [x] `nexus timer cancel` — discard timer without logging
- [x] `nexus sprint velocity <project_id>` — table: sprint name, status, done/total, progress bar, est/act hours; average velocity footer for 2+ completed sprints
- [x] `nexus sprint plan <project_id> [--capacity Xh]` — AI suggests which backlog tasks to pull, falls back to average velocity if no capacity given
- [x] `sprint_plan_prompt()` added to `ai.py`
- [x] Timer state lives next to the DB (`<db-dir>/timer.json`)
- [x] 135 tests, 0 warnings

**Usage:**
```bash
nexus timer start 3          # start stopwatch on task #3
nexus timer status           # check elapsed time
nexus timer stop -n "done"   # stop and log
nexus sprint velocity 1      # see sprint history with progress bars
nexus sprint plan 1          # AI picks tasks for next sprint
```

---

## Milestone 4 — Export & Multi-Provider AI ✅ (complete)
**Goal:** Make data portable and add Gemini as a second AI provider.

Deliverables:
- [x] `nexus export markdown <id>` — full project dump as `.md` (header, sprints, tasks by status, time log, footer)
- [x] `nexus export csv <id> --type tasks|timelog` — CSV export of tasks or time entries
- [x] `--stdout` flag on both export commands for piping; `-o` for custom output path
- [x] `_build_markdown`, `_build_tasks_csv`, `_build_timelog_csv` helpers (tested independently)
- [x] Gemini provider (`GOOGLE_API_KEY`) as automatic fallback when no Anthropic key
- [x] Provider-agnostic `NexusAI` — auto-selects Anthropic → Gemini; exposes `.provider_name`
- [x] Clean error messages for both providers (quota, auth, rate limit)
- [x] 111 tests, 0 warnings

**Usage:**
```bash
# Export
nexus export markdown 1              # writes <slug>.md
nexus export csv 1 --stdout          # pipe to other tools
nexus export csv 1 --type timelog    # time tracking CSV

# AI with Gemini
export GOOGLE_API_KEY=...
nexus task suggest 1
nexus report digest 1
```

**Remaining for later:**
- [ ] GitHub Issues sync (read-only import of open issues as tasks)

---

## Milestone 7 — Conversational Intelligence ✅ (complete)
**Goal:** Let Claude actually *talk* to the user about their project and take real actions.

Deliverables:
- [x] `nexus chat [project_id]` — Interactive AI session with Anthropic tool use
  - Full project context injected into system prompt (tasks, stats, sprint)
  - Claude can call 6 tools: `list_tasks`, `get_task`, `update_task_status`, `create_task`, `log_time`, `get_project_stats`
  - Full agentic tool-use loop (send → tool_use → execute → tool_result → repeat → final text)
  - Slash commands: `/exit`, `/quit`, `/help`, `/context`
  - Graceful error when using Gemini (tool use is Anthropic-only)
- [x] `nexus standup --ai` — AI-written Yesterday/Today/Blockers brief
  - Uses `tasks_completed_since` + `time_entries_since` for real yesterday activity data
  - Streams via Rich `Live` + `Markdown`; works with Anthropic or Gemini
- [x] `standup_prompt()` added to `ai.py`
- [x] `CHAT_TOOLS`, `NexusAI.supports_tools`, `NexusAI.chat_turn()` added to `ai.py`
- [x] `_make_tool_handler()` in `commands/chat.py` — extracted for testability
- [x] 214 tests (48 chat-specific), 0 warnings

**Usage:**
```bash
# Interactive AI chat — Claude reads context and takes actions
nexus chat 1                    # chat about project #1
nexus chat                      # uses default_project from config

# Inside chat:
# > What should I work on today?
# > Mark task 5 as done
# > Create a high-priority task "Write migration script"
# > Log 2 hours to task 3, note "refactored the auth layer"
# /context    — live project summary
# /help       — slash command reference
# /exit       — end session

# AI standup brief
nexus standup 1 --ai            # AI writes Yesterday/Today/Blockers from real data
nexus standup 1                 # static task snapshot (no AI)
```

---

## Milestone 8 — Deep Task Intelligence ✅ (complete)
**Goal:** Make Nexus proactive — surface hidden problems, track decisions, score project health.

Deliverables:
- [x] `nexus task note <id> <text>` — append a timestamped note to any task
  - `TaskNote` model + `task_notes` DB table
  - `db.add_task_note()` / `db.get_task_notes()` methods
  - Notes shown in `nexus task show` below the time log
- [x] `nexus task stale [project_id] [--days N]` — surface tasks needing attention
  - Stale in-progress (no time logged in N days, default 3)
  - Long-blocked (updated_at > N×2 days ago)
  - Old backlog items (created > N×5 days ago, never started)
  - `db.get_stale_tasks()` — efficient SQL with MAX(logged_at) grouping
- [x] `nexus project health <id> [--ai]` — automated A–F health score
  - 5 metrics: Completion Rate (25), Blocked Health (20), Momentum (20), Estimate Coverage (15), Activity/7d (20)
  - 16-block Unicode bar chart per metric, color-coded (green/yellow/red)
  - `_compute_health()` extracted for testability
  - Optional `--ai` streams diagnosis + recommendations
- [x] `health_diagnosis_prompt()` added to `ai.py`
- [x] 252 tests (38 health-specific), 0 warnings

**Usage:**
```bash
# Capture decisions and context directly on tasks
nexus task note 3 "Using JWT — sessions won't scale horizontally"
nexus task note 7 "Blocked on design review — pinged @alice in Slack"

# See full task detail with notes and time log
nexus task show 3

# Surface forgotten work
nexus task stale 1            # default: 3-day threshold
nexus task stale 1 --days 7   # use 7-day threshold

# Project health dashboard
nexus project health 1           # A–F with metric breakdown
nexus project health 1 --ai      # + AI diagnosis and recommendations
```

---

## Milestone 9 — GitHub Integration & Portfolio View ✅ (complete)
**Goal:** Make Nexus genuinely *shippable* — connect it to the real world with
GitHub Issues sync, and give multi-project users a single command that shows
the health of their entire workbench.

Deliverables:
- [x] `Task` model gains `source: str` and `external_id: str` for external provenance
  - Safe ALTER TABLE migration in `db._init()` for existing databases (idempotent)
- [x] `db.get_task_by_external_id(source, external_id, project_id)` — dedup lookup
- [x] `db.create_task()` accepts `source=` and `external_id=` parameters
- [x] `db.update_task()` allowed-set extended with `source` and `external_id`
- [x] `nexus github sync <project_id> owner/repo [--token] [--state open|closed|all] [--max N]`
  - Pure stdlib `urllib.request` — zero new dependencies
  - Follows GitHub's `Link: rel="next"` pagination automatically
  - Filters pull-requests out of `/repos/{owner}/{repo}/issues` results
  - Maps GitHub labels → Nexus priority (critical/urgent/p0 → CRITICAL, bug/high/p1 → HIGH, low/p3 → LOW)
  - **Upsert semantics**: re-sync refreshes title/description/priority; closed issues → DONE; no destructive overwrites of local edits
  - `$GITHUB_TOKEN` auto-picked from environment; required for private repos
- [x] `nexus workspace` — portfolio health table for all projects at once
  - Shows: ID, name, status, health grade (A–F), score, task counts, blocked count, hrs/week
  - Empty projects display `—` instead of a grade
  - Invokes default view without a subcommand (`invoke_without_command=True`)
- [x] `nexus workspace next [--limit N]` — cross-project priority queue
  - Ranks all TODO + IN_PROGRESS tasks across every project: CRITICAL → HIGH → MEDIUM → LOW
  - Secondary sort: most recently updated first within the same priority band
  - Shows project name, priority, status, and task title in a single clean table
- [x] 308 tests (56 new integration tests), 0 warnings

**Usage:**
```bash
# Sync GitHub issues into a Nexus project
nexus github sync 1 cli/cli                          # open issues, unauthenticated
nexus github sync 1 myorg/private-repo --token $GH   # private repo
nexus github sync 1 myorg/repo --state all            # open + closed
nexus github sync 1 myorg/repo --max 50              # cap at 50 issues
# Re-run any time — existing tasks are updated, not duplicated

# Portfolio health view
nexus workspace                # A–F grade for every project at a glance

# Cross-project priority queue
nexus workspace next            # top 10 tasks you should be working on, any project
nexus workspace next --limit 5  # top 5 only
```

---

## Milestone 10 — Security & Hardening ✅ (complete)
**Goal:** Make Nexus safe to ship — no accidental credential leaks, tight file
permissions, and a first-class security audit command.

Deliverables:
- [x] `src/nexus/security.py` — pure, testable security utilities
  - `is_secret_value(v)` — detects Anthropic, OpenAI, GitHub, Google, AWS, GitLab, Slack, SendGrid key prefixes
  - `mask_secret(v)` — `sk-a****1234` redaction safe for display
  - `scan_config_secrets(cfg)` — list config keys with secret-looking values
  - `file_permission_mode`, `is_too_permissive`, `fix_permissions`, `is_git_tracked`
- [x] **File permission hardening** — applied automatically on every startup
  - `~/.nexus/` directory → `chmod 700`
  - `~/.nexus/nexus.db` → `chmod 600`
  - `~/.nexus/config.json` → `chmod 600` on every `save_config()` call
  - All `os.chmod()` calls wrapped in `try/except OSError` (Windows / Docker safe)
- [x] `nexus config set` blocks secret storage — exits with env-var hint if value matches a known API-key prefix; secret is never written to disk
- [x] `nexus config show` masks secret-looking values (`sk-a****1234`) and shows a warning count
- [x] `nexus security [--fix]` — 7-point security health-check command
  - Nexus directory permissions (700)
  - Database file permissions (600)
  - Config file permissions (600)
  - Secrets in config.json (scan)
  - Database tracked by git (`git ls-files`)
  - Config tracked by git (warning)
  - API key environment-variable audit (presence only — values never printed)
  - `--fix` auto-tightens permission issues; exits non-zero on any failure
- [x] 359 tests (51 new security tests), 0 warnings

**Usage:**
```bash
nexus security          # full security audit
nexus security --fix    # also fix permission issues

# Blocked with a clear message + env-var hint:
nexus config set ANTHROPIC_API_KEY sk-ant-...
# Instead:
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Milestone 11 — Task Dependency Graph ✅ (complete)
**Goal:** Model the real-world ordering of work — let tasks declare prerequisites,
block downstream work automatically, and visualise the full dependency DAG in the terminal.

Deliverables:
- [x] `task_dependencies` table — `(task_id, depends_on_id, created_at)` with `UNIQUE` constraint and `ON DELETE CASCADE` on both FK columns
- [x] `CREATE TABLE IF NOT EXISTS` migration in `db._init()` — safe for existing databases
- [x] **Cycle detection** (`_would_create_cycle`) — iterative DFS; blocks self-deps and circular chains
- [x] `db.add_dependency(task_id, dep_id)` — adds with cycle guard; idempotent via `INSERT OR IGNORE`
- [x] `db.remove_dependency(task_id, dep_id)` — removes edge, returns `False` if not found
- [x] `db.get_dependencies(task_id)` — prerequisites of a task (what must be done first)
- [x] `db.get_dependents(task_id)` — downstream tasks (what is waiting on this task)
- [x] `db.get_ready_tasks(project_id)` — TODO/IN_PROGRESS tasks whose every prerequisite is done or cancelled; uses efficient `NOT EXISTS` SQL subquery
- [x] `db.has_unmet_dependencies(task_id)` — quick boolean check for filtering
- [x] `nexus task depend <id>` — show prerequisites and downstream tasks
- [x] `nexus task depend <id> --on <dep_id>` — add one or more prerequisites (repeatable flag); graceful cycle/already-exists messages
- [x] `nexus task undepend <id> --from <dep_id>` — remove a prerequisite
- [x] `nexus task graph <project_id>` — Rich `Tree` visualisation of the full DAG
  - Root nodes = tasks with no local prerequisites (ready to start or already active)
  - Children = tasks that depend on their parent node
  - Diamond / fan-out shapes render correctly; visited-set prevents duplicate nodes
  - Footer shows task count, edge count, and ready-to-start count
- [x] `nexus task show` extended — "Depends on:" and "Needed by:" lines shown after notes; done deps rendered in green, cancelled in dim
- [x] `nexus workspace next` filters tasks with unmet dependencies — hidden tasks counted and reported in the footer
- [x] 56 new tests in `tests/test_deps.py`, 0 warnings — 415 total

**Usage:**
```bash
# Declare that task 5 can only start after tasks 3 and 4 are done
nexus task depend 5 --on 3 --on 4

# Inspect what a task is waiting on
nexus task depend 5

# Remove a dependency
nexus task undepend 5 --from 4

# Visualise the full dependency graph for project 1
nexus task graph 1

# Cross-project queue — blocked tasks auto-hidden
nexus workspace next
```

---

## Milestone 12 — Ship Readiness ✅ (complete)
**Goal:** Make Nexus presentable enough to share on GitHub — professional README,
smooth onboarding, clean packaging, and a proper `.gitignore`.

Deliverables:
- [x] `README.md` — comprehensive, GitHub-ready documentation
  - Feature overview, installation (pip, uvx, from source), quick start
  - Full command reference for every command group
  - AI setup guide (Anthropic + Gemini)
  - Shell completion instructions (Bash / Zsh / Fish)
  - Data privacy section
  - Custom database (`--db` / `NEXUS_DB`) usage
  - Development workflow and project structure
  - Roadmap (Slack bridge, watch daemon, web UI, multi-user sync, plugin system)
- [x] `nexus init` — first-time setup wizard
  - Confirms data directory and database path
  - Shell completion copy-paste hints
  - Checks for `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` with signup links
  - Offers to create the first project interactively
  - Offers to set it as the default project (writes to config)
  - Shows a personalised quick-reference on exit
  - Safe to re-run — never overwrites existing data
- [x] `pyproject.toml` hardened for public release
  - `readme = "README.md"` — shows on PyPI
  - `license = { text = "MIT" }`
  - `keywords`, `classifiers` (Development Status: Beta, Console app)
  - AI SDKs moved to optional extra: `pip install nexus[ai]`
  - `all` extra: `pip install nexus[all]` — same as `[ai]`
  - Base install has zero AI dependencies (lazy imports in `ai.py` already safe)
- [x] `.gitignore` — Python, venv, uv, test artefacts, Nexus runtime files, secrets
- [x] Wheel and sdist build cleanly: `uv build` → `nexus-0.1.0-py3-none-any.whl`
- [x] `nexus init` appears in `nexus --help` alongside all 12 other command groups
- [x] 415 tests still passing, 0 warnings

**Usage:**
```bash
# For new users
pip install "nexus[ai]"
nexus init                   # guided setup wizard

# For developers / contributors
git clone https://github.com/geonixx/nexus.git
cd nexus && uv sync --dev
uv run nexus init

# Shell completion (add to your shell RC file)
eval "$(_NEXUS_COMPLETE=zsh_source nexus)"    # zsh
eval "$(_NEXUS_COMPLETE=bash_source nexus)"   # bash
```

---

## Milestone 13 — AI Scrum Master ✅ (complete)
**Goal:** Give Nexus an autonomous agent mode — an AI that reviews your project
on demand, surfaces problems, writes follow-up notes, and creates missing tasks
without you having to drive every step.

Deliverables:
- [x] `nexus task ingest <project_id> <text> [--add]` — parse freeform text → structured task via AI
  - Calls `ai.complete()` (non-streaming JSON mode) with a structured prompt
  - Strips accidental markdown fences before JSON parsing
  - Validates and normalises priority (falls back to `medium` for unknown values)
  - Shows parsed fields: title, priority with colour, estimate, description, rationale
  - `--add` skips the confirmation prompt; without it, prompts the user
- [x] `nexus agent run [project_id] [--dry-run] [--yes]` — autonomous project review
  - Requires Anthropic Claude (tool use not available with Gemini); exits cleanly if only Gemini is set
  - Gathers full project context (tasks, stats, sprint, health) into the system prompt
  - Runs the full Anthropic tool-use loop with `AGENT_TOOLS` — agent calls tools iteratively until satisfied
  - Read tools run immediately; write tools (`create_task`, `update_task_status`, `add_task_note`) trigger a confirmation step
  - `--dry-run` shows exactly what the agent *would* do — no writes, no prompts
  - `--yes` / `-y` auto-approves all write actions for CI / scripted use
  - Logs all approved writes; prints a summary panel at the end
  - Falls back to `default_project` from config when `project_id` is omitted
- [x] `ingest_task_prompt(text)` added to `ai.py` — (system, user) tuple for JSON-mode task parsing
- [x] `agent_system_prompt(project_name, desc)` added to `ai.py` — autonomous scrum master persona
- [x] `AGENT_TOOLS` added to `ai.py` — extends `CHAT_TOOLS` with 5 additional tools:
  - `get_stale_tasks` — surfaces in-progress, blocked, and backlog tasks past a threshold
  - `get_ready_tasks` — lists tasks whose every prerequisite is done/cancelled
  - `get_project_health` — numeric health score (0–100) with metric breakdown
  - `add_task_note` — write a timestamped note to any task
  - `get_task_dependencies` — show prerequisites and downstream tasks for a task
- [x] `commands/agent.py` wired into `cli.py` as `nexus agent`
- [x] 47 new tests in `tests/test_agent.py`, 0 warnings — **462 total**
  - Prompt-shape tests for `ingest_task_prompt` and `agent_system_prompt`
  - `AGENT_TOOLS` structure (superset of `CHAT_TOOLS`, all expected tools present, required keys)
  - Full CLI coverage: `task ingest` (basic, fields display, skip creation, bad JSON, fenced JSON, missing project, no AI, invalid priority fallback)
  - Full CLI coverage: `agent run` (basic, dry-run, missing project, no AI, Gemini-only error, default project config, auto-yes, summary output)
  - `_handle_tool` unit tests for all 11 tool names (read and write paths, dry-run, auto-yes)

**Usage:**
```bash
# Parse a Slack message / bug report / brain-dump into a structured task
nexus task ingest 1 "the login button on iOS is totally broken, blocking all mobile users"
nexus task ingest 1 "$(pbpaste)" --add   # pipe from clipboard and create immediately

# Let Claude autonomously review your project
nexus agent run 1                # interactive — confirms each write action
nexus agent run 1 --dry-run      # show what the agent would do, touch nothing
nexus agent run 1 --yes          # auto-approve all writes (great for cron/CI)
nexus agent run                  # uses default_project from config
```

---

## Development Workflow

```bash
# Install / sync dependencies
uv sync --dev

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=nexus --cov-report=term-missing

# Run the CLI locally
uv run nexus --help

# Add a package
uv add <package>
```
