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

## Milestone 14 — Watch Daemon ✅ (complete)
**Goal:** Add a background monitoring daemon that polls projects on a configurable
interval, surfaces stale and blocked work, and can optionally trigger the autonomous
AI scrum master agent on a schedule.

Deliverables:
- [x] `nexus watch [project_id] [--all] [--interval N] [--agent] [--agent-yes] [--stale-days N]`
  - Polls every N minutes (default 30); press Ctrl-C to stop cleanly (SIGINT handler)
  - Single-project or `--all` portfolio-wide monitoring
  - Falls back to `default_project` from config if no project_id given
  - Per-project summary: healthy ✓ or issue tables (stale in-progress, long-blocked, forgotten backlog)
  - Shows count of ready tasks (all deps met) and currently blocked tasks
  - `--agent` triggers `_run_agent_pass()` each cycle — runs the AI scrum master with dry-run by default
  - `--agent-yes` enables full AI write approval (auto-yes) for automated/cron use
  - Inner sleep loop ticks at 1-second intervals so Ctrl-C feels instant even on long intervals
- [x] `_check_project(db, project, stale_days, now)` — pure, testable per-project health check
  - Stale in-progress: `get_stale_tasks(project_id, threshold)` — tasks with no logged time
  - Long-blocked: manually filtered `status == BLOCKED and updated_at < stale_days*2 threshold`
  - Forgotten backlog: `status == TODO and created_at < stale_days*5 threshold`
  - Capped backlog display at 5 + "… and N more"
  - Projects with no tasks show a `—  #id name (no tasks)` line and return 0
- [x] `_run_agent_pass(db, projects, auto_yes)` — calls the agent for each project
  - Lazy-imports AI modules (safe when AI extras not installed)
  - Skips gracefully when no AI key or Gemini-only (prints skip message)
  - Catches exceptions and prints error without crashing the daemon
- [x] `_age(dt, now)` helper — human-readable duration ("just now", "5h ago", "14d ago")
- [x] `_prio(p)` helper — Rich-coloured priority label; guards against `[/]` empty-closing-tag bug
- [x] CI badge + provider badges added to `README.md`
- [x] `README.md` updated with `nexus watch` and `nexus agent` / `nexus task ingest` command sections
- [x] Roadmap updated: `nexus watch` marked complete
- [x] `.github/workflows/ci.yml` — runs full suite on Python 3.11/3.12/3.13 on every push + PR
- [x] 34 new tests in `tests/test_watch.py`, 0 warnings — **496 total**
  - `_age` formatting (just now, hours, 1 day, many days)
  - `_prio` markup correctness, no `[/]` bug
  - `_check_project` — empty project, fresh TODO, in-progress with log, stale in-progress, blocked stale, done tasks, return type
  - `watch_cmd` CLI — clean exit, project name in output, stopped message, cycle header, healthy output, missing project, no default, default from config, --all flag, no projects error, stale task shown, --agent with no AI
  - `_run_agent_pass` — no AI skip, Gemini skip, chat_turn called, multi-project, write_log populated, exception handled

**Usage:**
```bash
# Simple project watcher
nexus watch 1                        # check every 30 min, print issues
nexus watch 1 --interval 5           # check every 5 minutes
nexus watch 1 --stale-days 7         # use 7-day stale threshold

# Portfolio-wide monitoring
nexus watch --all                    # watch every project
nexus watch --all --interval 60      # hourly portfolio sweep

# AI-powered monitoring (dry-run by default)
nexus watch 1 --agent                # AI reviews each cycle, shows what it would do
nexus watch 1 --agent --agent-yes    # AI auto-creates notes/tasks (great for cron)

# Add to crontab for automated morning review:
# 0 9 * * 1-5 nexus watch 1 --agent --agent-yes --interval 1 &
```

---

## Milestone 15 — Slack Bridge ✅ (complete)
**Goal:** Connect Nexus to Slack — a lightweight local HTTP server that handles
Slack slash commands and formats project data as rich Block Kit payloads, with
HMAC-SHA256 signature verification and an async AI agent path.  Zero new
runtime dependencies (stdlib only).

Deliverables:
- [x] `nexus slack serve [--port N] [--secret TOKEN] [--project-id N]`
  - Starts a local `http.server.HTTPServer` that handles `POST /` Slack slash commands
  - Falls back to `default_project` from config when `--project-id` is omitted
  - Optional HMAC-SHA256 signature verification via `SLACK_SIGNING_SECRET` env var or `--secret`
  - Rejects stale requests (timestamp >5 minutes) to prevent replay attacks
  - Dev mode (no secret) accepts all requests for quick iteration
  - Rich startup panel shows project, URL, and signing status; Ctrl-C stops cleanly
- [x] Slash command routing — all sent as `/nexus <subcommand>`:
  - `status` (or empty) — project health overview (Block Kit: header, grade, progress, ready tasks, blocked tasks, timestamp footer)
  - `next [N]` — next N ready tasks sorted by priority (default 5)
  - `add <title>` — create a task, returns confirmation with task ID and `/nexus done` hint
  - `done <id>` — mark a task done, returns confirmation with task title; accepts `#42` or `42`
  - `agent` — fire-and-forget AI scrum-master review; returns immediately, posts result to `response_url` in background thread
  - `help` — ephemeral reference card for all subcommands
- [x] `nexus slack format [project_id]` — print Block Kit JSON to stdout for previewing / clipboard
- [x] `nexus slack ping <webhook_url>` — POST a test message to an incoming webhook URL
- [x] Pure-function command handlers (`_cmd_status`, `_cmd_next`, `_cmd_add`, `_cmd_done`, `_cmd_help`, `_route_command`) — all independently unit-testable
- [x] Block Kit helpers (`_header`, `_mrkdwn`, `_divider`, `_context`, `_ephemeral`, `_in_channel`, `_slack_prio`)
- [x] `_verify_slack_signature(secret, timestamp, body, signature)` — pure HMAC-SHA256 verification
- [x] `_post_to_slack(url, payload)` — stdlib `urllib.request` POST helper
- [x] `_async_agent(db, project_id, response_url)` — background thread AI review; handles no-AI, Gemini-only, missing project, and exception cases gracefully
- [x] `_make_handler(db, project_id, signing_secret)` — factory returns a `BaseHTTPRequestHandler` subclass bound to the given DB and project; includes `/GET` health-check endpoint
- [x] 77 new tests in `tests/test_slack.py`, 0 warnings — **573 total**
  - Block Kit helper shape tests (header, mrkdwn, divider, context, ephemeral, in_channel, slack_prio)
  - `_verify_slack_signature` — valid, wrong secret, tampered body, stale timestamp, malformed timestamp, empty inputs
  - `_cmd_status` — missing project, valid project, blocks present, header name, health grade, ready tasks, blocked tasks, context footer
  - `_cmd_next` — no ready tasks, tasks shown, limit respected, priority ordering, header block
  - `_cmd_add` — creates task, in-channel response, title in payload, user name, task ID
  - `_cmd_done` — marks done, in-channel, title in payload, `#` prefix accepted, non-numeric ephemeral, not-found ephemeral
  - `_cmd_help` — ephemeral with all subcommands listed
  - `_route_command` — empty text, status, next, next with limit, add, add without title, done, done without arg, agent (thread spawn), agent no response_url, help, unknown subcommand, case-insensitive
  - `_async_agent` — no AI, Gemini-only, missing project, chat_turn called, no-changes message, write log reported, exception handled
  - `_make_handler` — returns handler class with and without secret
  - `slack_format` CLI — prints JSON, no project, bad project, default from config
  - `slack_serve` CLI — missing project, no default, starts and stops (mocked server), project name shown, signature disabled/enabled, default from config
  - `slack_ping` CLI — success, failure exits nonzero, failure shows error

**Usage:**
```bash
# Start the slash command server (expose via ngrok for Slack to reach localhost)
nexus slack serve --project-id 1 --port 3000

# With signature verification (strongly recommended for production)
export SLACK_SIGNING_SECRET=abc123...
nexus slack serve --project-id 1

# Set default project so you don't have to pass --project-id
nexus config set default_project 1
nexus slack serve

# Preview Block Kit JSON in terminal
nexus slack format 1

# Copy Block Kit payload to clipboard (macOS)
nexus slack format 1 | pbcopy

# Test an incoming webhook
nexus slack ping https://hooks.slack.com/services/T.../B.../...

# Expose localhost to Slack with ngrok
ngrok http 3000
# Then set Slack app Request URL to: https://your-ngrok-host.ngrok.io
```

---

## Milestone 16 — Tags + Agent-Ready Infrastructure ✅ (complete)
**Goal:** Address the two most important gaps from external feedback — missing task labels
(the #1 feature request) and agent orchestration safety (runaway API spend in multi-agent
environments).  Also enable concurrent agent access with SQLite WAL mode.

Deliverables:
- [x] **SQLite WAL mode** — `PRAGMA journal_mode=WAL` set on every connection in `_connect()`
  - Readers no longer block writers; writers no longer block readers
  - Essential for concurrent access by multiple `nexus agent` / `nexus watch` processes
  - Persists in the DB file; fully idempotent for existing databases
- [x] **Task tags** — free-form lowercase labels stored in a `task_tags` junction table
  - `task_tags(id, task_id, tag, created_at)` with `UNIQUE(task_id, tag)` and `ON DELETE CASCADE`
  - `CREATE TABLE IF NOT EXISTS` migration — safe for all existing databases
  - `db.add_tag(task_id, tag)` — `INSERT OR IGNORE`; normalised via `strip().lower()`
  - `db.remove_tag(task_id, tag)` — returns `True` if tag was found and removed
  - `db.get_tags(task_id)` → `List[str]` — sorted alphabetically
  - `db.list_tasks_by_tag(tag, project_id=None)` — cross-project or scoped query
  - `db.get_all_tags(project_id=None)` → `List[(tag, count)]` — usage counts, sorted by frequency
- [x] **`nexus task` integration** — tags woven into 5 existing subcommands
  - `nexus task add` — `--tag <name>` (repeatable); tags applied immediately after creation
  - `nexus task update` — `--tag <name>` (add, repeatable) and `--untag <name>` (remove, repeatable); tag-only updates allowed without field changes
  - `nexus task show` — tags displayed in detail panel below dependencies
  - `nexus task list` — `--tag <name>` filter; applies on top of status/sprint filters
  - `nexus task next` — `--tag <name>` filter; applied to the ready-task queue
- [x] **`nexus tag` command group** — new top-level group in `cli.py`
  - `nexus tag list [project_id]` — table of all tags in use with task counts; optional project scope
  - `nexus tag tasks <tag> [--project-id N]` — cross-project task list for a given tag, grouped by project
- [x] **`--max-agent-cycles N`** on `nexus watch --agent`
  - Default `0` = unlimited (existing behaviour preserved)
  - When limit reached: prints one-time warning, stops calling `_run_agent_pass()`
  - Header shows `(max N cycles)` when limit is set
  - Prevents runaway API spend in automated / cron environments
- [x] 50 new tests in `tests/test_tags.py`, 0 warnings — **623 total**
  - `TestWALMode` — verifies `PRAGMA journal_mode` returns `'wal'`
  - `TestAddTag`, `TestRemoveTag`, `TestGetTags` — full DB method coverage incl. normalisation, idempotency, cascade delete
  - `TestListTasksByTag`, `TestGetAllTags` — project scope, cross-project, count accuracy, frequency sort
  - `TestTaskAddTag`, `TestTaskUpdateTag`, `TestTaskShowTags`, `TestTaskListTag`, `TestTaskNextTag` — full CLI coverage
  - `TestTagListCmd`, `TestTagTasksCmd` — table output, no-tags/no-tasks messages, project scope, invalid project
  - `TestWatchMaxAgentCycles` — max shown in header, zero means unlimited

**Usage:**
```bash
# Tagging tasks
nexus task add 1 "Fix auth bug" --tag bug --tag auth
nexus task update 5 --tag backend --untag draft
nexus task show 5                                 # shows tags in detail panel

# Filtering
nexus task list 1 --tag bug
nexus task next 1 --tag auth

# Tag management
nexus tag list                                    # all tags in workspace
nexus tag list 1                                  # tags for project #1
nexus tag tasks bug                               # all tasks tagged 'bug'
nexus tag tasks bug --project-id 1               # scoped to project

# Agent loop safety
nexus watch 1 --agent --max-agent-cycles 5        # cap AI at 5 passes
nexus watch 1 --agent --max-agent-cycles 0        # unlimited (default)
```

---

## Milestone 17 — Ollama Integration (Local AI) ✅ (complete)
**Goal:** Add Ollama as a third AI provider, closing the "local-first paradox" gap.
Every AI feature runs fully offline with a local model — no API key, no cloud, no cost.
Architecture is surgically minimal: a single new `_OllamaProvider` class; no new CLI
commands; no new runtime dependencies.

Deliverables:
- [x] **`_OllamaProvider`** in `ai.py` — pure stdlib (`urllib.request`), zero new dependencies
  - `available` — checks `OLLAMA_MODEL` is set AND probes `GET /api/tags` with a **3-second hard timeout**
  - Health check result is cached; never hangs waiting for a sleeping daemon
  - `stream(system, user)` — `POST /api/chat` with `stream=true`; parses NDJSON line-by-line; skips malformed lines silently
  - `complete(system, user)` — `POST /api/chat` with `stream=false`; used for JSON-mode tasks (`nexus task ingest`)
  - `supports_tools = False` — tool use is Anthropic-only; `chat_turn()` raises a clear error naming the active provider
  - Graceful `RuntimeError` on `URLError` with a "is the daemon running? Try: ollama serve" hint
  - Config: `OLLAMA_MODEL` (required to enable), `OLLAMA_HOST` (optional, default `http://localhost:11434`)
- [x] **Provider chain** updated: Anthropic → Gemini → Ollama
  - `NexusAI.__init__` falls through to Ollama if neither cloud key is set
  - `NexusAI.provider_name` returns `"Ollama (llama3.2)"` style string
  - `NexusAI.supports_tools` docstring updated: "True only for Anthropic — not available via Gemini **or Ollama**"
  - `NexusAI.chat_turn()` error message includes the active provider name: `"…not available with Ollama (llama3.2)."`
- [x] **Module docstring** updated with Ollama quick-start (`brew install ollama` → `ollama pull llama3.2` → `export OLLAMA_MODEL=llama3.2`)
- [x] **`nexus init`** — Ollama detection step added (uses `shutil.which("ollama")`)
  - If Ollama binary found AND `OLLAMA_MODEL` set → green ✓ confirmation
  - If binary found but no model → cyan hint with `export OLLAMA_MODEL=llama3.2` and `ollama pull` instruction
  - If no binary AND no cloud keys → suggest Ollama install with link
  - No-providers warning updated: "No AI providers found." (was "No AI keys found.")
- [x] **No `nexus ollama` command group** — users already have `ollama list`; zero extra CLI surface
- [x] **All existing AI features work with Ollama** (streaming, non-streaming)
  - `nexus task suggest`, `nexus task estimate`, `nexus report digest`, `nexus report week --ai`
  - `nexus standup --ai`, `nexus sprint plan --ai`, `nexus project health --ai`
  - `nexus task ingest` (JSON-mode via `complete()`)
  - `nexus chat` and `nexus agent run` → print helpful error and exit cleanly
- [x] 39 new tests in `tests/test_ollama.py`, 0 warnings — **662 total**
  - `TestOllamaProviderAvailability` — model env var, empty model, daemon healthy, daemon unreachable, status!=200, caching, custom host, trailing slash strip, default host, model name stored
  - `TestOllamaStream` — chunks yielded, system+user messages sent, empty system skipped, correct model name, URLError → RuntimeError, malformed JSON lines skipped, stops after done=true
  - `TestOllamaComplete` — content returned, stream=false sent, URLError → RuntimeError
  - `TestNexusAIProviderChain` — Ollama selected, Anthropic priority, Gemini priority, unreachable daemon, provider_name, supports_tools=False, chat_turn error names provider, no-providers fallback
  - `TestOllamaCLI` — suggest, digest, estimate via Ollama; chat + agent run reject Ollama gracefully; daemon-down shows user-readable error
  - `TestInitOllamaDetection` — model set, bin found but no model, no bin no cloud, no-providers warning

**Usage:**
```bash
# Quick-start (macOS)
brew install ollama
ollama pull llama3.2          # ~2 GB, one-time download
export OLLAMA_MODEL=llama3.2  # add to ~/.zshrc for persistence

# Now all AI features work offline
nexus task suggest 1           # local suggestions, zero cost
nexus task estimate 3          # local estimate
nexus report digest 1          # local status narrative
nexus task ingest 1 "user reports login failure on iOS"  # parse to task

# Different models
export OLLAMA_MODEL=qwen2.5-coder   # optimised for code tasks
export OLLAMA_MODEL=mistral          # fast, general purpose

# Custom Ollama host (e.g. GPU server on your LAN)
export OLLAMA_HOST=http://192.168.1.42:11434
export OLLAMA_MODEL=llama3.2

# Tool-use features still require Anthropic
export ANTHROPIC_API_KEY=sk-ant-...  # takes priority; unlocks chat + agent run
nexus agent run 1
nexus chat 1
```

---

## Milestone 18 — Offline Agent ✅ (complete)
**Goal:** Close the "local-first paradox" — `nexus agent run` now works with
Gemini and Ollama, not just Anthropic.  Instead of requiring tool use, a single
structured-output prompt injects the full project snapshot and the model returns
a JSON action plan.  The Anthropic tool-use path is completely unchanged.

Deliverables:
- [x] **`offline_agent_prompt()`** added to `ai.py`
  - Accepts: `project_name`, `project_desc`, `stats_line`, `tasks_ctx`, `stale_ctx`, `ready_ctx`, `valid_task_ids`
  - Returns a `(system, user)` tuple for a single `ai.complete()` call
  - System prompt instructs JSON-only output (no fences, no prose)
  - User prompt embeds full project snapshot + strict JSON schema + rules section
  - Rules: observations 2–5, actions 0–5, only `add_note` / `create_task` types, task_id must be from valid list
- [x] **Provider routing** in `agent_run` (`commands/agent.py`)
  - `if not ai.supports_tools:` → `_run_offline_agent(...)` (Gemini or Ollama)
  - `else:` → existing Anthropic tool-use loop (unchanged)
  - Error message updated: lists all three provider env vars (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_MODEL`)
  - `agent_run` docstring updated to describe both modes
- [x] **`_build_offline_context(db, project_id)`** — pure function, no AI calls
  - `stats_line`: done/total, in-progress, blocked, todo counts
  - `tasks_ctx`: up to 10 most-recently-updated non-done tasks (context-window safe)
  - `stale_ctx`: stale in-progress (3+ days) and long-blocked (6+ days) task lists
  - `ready_ctx`: up to 5 tasks whose every prerequisite is met
  - `valid_task_ids`: flat list of all task IDs in the project (for hallucination defence)
- [x] **`_parse_offline_plan(raw, valid_task_ids)`** — strict, defensive validator
  - Strips markdown code fences before parsing
  - Raises `ValueError` on invalid JSON or non-dict top-level
  - Observations: capped at 5, non-list treated as empty
  - `add_note`: `task_id` must cast to `int` AND be in valid set; empty/whitespace notes skipped
  - `create_task`: title truncated to 80 chars; unknown priority normalised to `"medium"`; empty title skipped
  - Unknown action types silently skipped (forward-compatible)
  - Actions capped at 5 total
- [x] **`_run_offline_agent(ai, project, project_id, dry_run, auto_yes, db)`**
  - Builds context, formats prompt, calls `ai.complete()`
  - Retry loop: up to 3 attempts (initial + 2 retries) on `ValueError` / `RuntimeError`
  - Corrective suffix appended on each retry: explains the parse error, re-states JSON requirement
  - All 3 failures → `print_error(...)` + `SystemExit(1)`
  - Displays observations as a bulleted list after the model call
  - Actions executed with the same `_confirm_write()` guard as the Anthropic path (dry-run / auto-yes / interactive)
  - `add_note` actions: validates task still exists in DB before writing
  - `create_task` actions: honours `priority` from the plan (already normalised)
  - Summary panel shows write log or "no changes" / "dry-run" message
- [x] 66 new tests in `tests/test_agent_offline.py`, 0 warnings — **728 total**
  - `TestOfflineAgentPrompt` (13) — tuple shape, system JSON instruction, project name/stats/ctx/schema in user, sorted ID list, desc optional
  - `TestParseOfflinePlan` (23) — happy path, fence stripping (json/plain), invalid JSON, non-dict, observation cap, obs-not-list, add_note valid/invalid-id/non-int-id/float-id/empty-note, create_task valid/no-desc/empty-title/long-title/bad-priority/missing-priority, action cap, unknown type skipped, non-dict item skipped, actions-not-list
  - `TestBuildOfflineContext` (9) — expected keys, stats reflect counts, all IDs present, done excluded from tasks_ctx, active tasks included, empty project defaults, 10-task cap, ready tasks shown, no-stale monkeypatched
  - `TestRunOfflineAgent` (9) — no-actions run, observations displayed, add_note written, create_task written, dry_run no write, retry success, 3-fail exit, invalid-id skipped, Ollama provider name
  - `TestAgentRunRouting` (8) — no-AI error, Gemini offline path, Ollama offline path, Anthropic skips offline, dry-run flag, default_project fallback, no default exits, invalid project exits
  - `TestOfflineAgentPromptExported` (2) — importable from `nexus.ai`, helpers importable from `nexus.commands.agent`

**Usage:**
```bash
# Offline agent with Gemini (no Anthropic key required)
export GOOGLE_API_KEY=...
nexus agent run 1                # offline review — confirms before writes
nexus agent run 1 --dry-run      # show what the model suggests, no changes
nexus agent run 1 --yes          # auto-approve all suggestions

# Offline agent with Ollama (fully local, zero cost, zero cloud)
export OLLAMA_MODEL=llama3.2
nexus agent run 1                # completely offline agent review

# Anthropic path is unchanged (full tool-use loop)
export ANTHROPIC_API_KEY=sk-ant-...
nexus agent run 1                # iterative tool calls, richer analysis
```

---

## Milestone 20 — Claude Code Integration ✅ (complete)
**Goal:** Wire Nexus into Claude Code via a generated `CLAUDE.md` snippet.  A single
command — `nexus claude-init` — produces a ready-to-paste (or file-written) Markdown
file that tells Claude Code exactly how to interact with the project: check tasks
before starting, log time after finishing, and which commands are forbidden.

Deliverables:
- [x] **`build_claude_md(project_name, project_id, nexus_db_path, test_cmd)`** in `commands/claude_init.py`
  - Pure function, no DB access — renders the `_TEMPLATE` string with `.format()`
  - Template sections: Before starting work, After completing work, Rules, Project reference, Quick reference
  - Rules section explicitly forbids `nexus agent run` (two-AI problem), destructive ops, and `nexus slack serve`
  - All embedded commands pre-filled with `NEXUS_DB=<path>` and the project ID so they are ready to run
- [x] **`claude_init_cmd`** Click command (`nexus claude-init`)
  - `PROJECT_ID` — optional argument; falls back to `default_project` from config (same pattern as `nexus chat`)
  - `--output / -o PATH` — write to file; creates parent directories; shows success message with byte count
  - `--db-path PATH` — override the DB path embedded in the snippet (independent of `--db` / `NEXUS_DB`)
  - `--test-cmd TEXT` — test command to embed (default: `pytest`; common override: `uv run pytest`)
  - Default (no `--output`): `click.echo(content)` to stdout — unmodified, no Rich processing
- [x] Registered in `cli.py` between `chat_cmd` and `config_cmd`
- [x] **31 tests** in `tests/test_claude_init.py` — **797 total**
  - `TestBuildClaudeMd` (10) — pure function: project name, ID, DB path, test_cmd, forbidden section, quick reference, section headers, multi-occurrence of project ID
  - `TestClaudeInitStdout` (6) — CLI stdout: basic output, DB path embedded, forbidden section, custom test cmd, custom db-path, default pytest
  - `TestClaudeInitFileOutput` (5) — file writing: creates file, content complete, creates parent dirs, success message, short `-o` flag
  - `TestClaudeInitDefaultProject` (3) — config fallback: uses default_project, errors when missing, explicit ID overrides default
  - `TestClaudeInitErrors` (2) — missing project (direct and via config)
  - `TestClaudeInitContent` (5) — read/write commands present, NEXUS_DB= in output, project ID in commands, custom db-path in NEXUS_DB var

Also shipped in this session (polish tasks):
- [x] `nexus task update --help` now shows the status-change subcommands (`done/start/block/cancel`) in the docstring
- [x] `nexus task suggest` now shows the provider name in the header rule (`Provider: Ollama (llama3.2)`)

**Usage:**
```bash
# Print to stdout (pipe or paste wherever needed)
nexus claude-init 1

# Write directly to the project root
nexus claude-init 1 --output CLAUDE.md

# Write to Claude Code's project config dir
nexus claude-init 1 --output .claude/CLAUDE.md --test-cmd "uv run pytest"

# Use default_project from config (no project_id needed)
nexus config set default_project 1
nexus claude-init --output CLAUDE.md

# Override the embedded DB path (e.g. project has its own database)
nexus claude-init 1 --db-path .nexus/myproject.db --output CLAUDE.md
```

---

## Milestone 19 — Offline Chat ✅ (complete)
**Goal:** Make `nexus chat` work with Gemini and Ollama (advisory mode) — the last
local-first gap.  Previously `nexus chat` required `ANTHROPIC_API_KEY` and exited
with an error for any other provider.  Now all three providers are supported.

Deliverables:
- [x] **`offline_chat_system_prompt()`** added to `ai.py`
  - Args: `project_name`, `project_desc`, `stats_line`, `tasks_ctx`, `stale_ctx`, `ready_ctx`
  - Returns a single `str` (not a tuple) — the system prompt to pass to `ai.stream()` each turn
  - Includes full project snapshot (stats, recent active tasks, stale/blocked work, ready tasks)
  - Tells the model it is in "advisory mode" (read-only) and to suggest CLI commands for actions
  - Gives example `nexus task done <id>`, `nexus task start <id>`, `nexus task add ...` forms
- [x] **`_run_offline_chat(db, project_id, ai, project, stats, *, history_window=6)`** in `commands/chat.py`
  - Streaming REPL loop (yields chunks directly from `ai.stream()` — no buffering)
  - History windowing: last `history_window` exchange pairs prepended to each turn as:
    ```
    Conversation so far:
    User: ...
    Assistant: ...

    Current message:
    [new user input]
    ```
  - Slash commands: `/exit`, `/quit`, `/help`, `/context` (refresh snapshot + system), `/clear` (offline-only, resets history)
  - `/context` calls `_build_offline_context(db, project_id)` (from `commands/agent.py`) to get a live snapshot, rebuilds the system prompt, and shows refreshed task counts
  - `/clear` is only in the advisory-mode help text (tool-mode /help omits it)
  - `RuntimeError` from `ai.stream()` displayed as error and breaks the loop cleanly
  - Empty / whitespace input lines skipped (no AI call)
  - `EOFError` / `KeyboardInterrupt` print "Goodbye!" and exit with code 0
- [x] **`commands/chat.py` refactored**
  - Removed hard `supports_tools` gate (previously printed error and raised `SystemExit(1)`)
  - Existing Anthropic tool-use REPL extracted into `_run_tool_chat(db, project_id, ai, project)`
  - New `_run_offline_chat(...)` added for Gemini / Ollama
  - `chat_cmd` routes: `ai.supports_tools → _run_tool_chat(...)`, otherwise `_run_offline_chat(...)`
  - Welcome banner updated: shows mode label — "Full tool mode" (Anthropic) or "Advisory mode" (Gemini/Ollama)
  - Error message for no-AI updated to list all three provider env vars
- [x] **`test_chat.py` updated**: `test_chat_gemini_only_exits_with_message` renamed and updated to
  `test_chat_gemini_enters_advisory_mode` — expects exit_code 0 + "Advisory mode" in banner
- [x] **37 new tests in `tests/test_chat_offline.py`** — **766 total**
  - `TestOfflineChatSystemPrompt` (10) — returns str, project name, description, stats, tasks_ctx,
    stale_ctx, ready_ctx, advisory language, nexus CLI commands, non-empty result
  - `TestChatCmdRouting` (7) — no-AI exits, Gemini → advisory banner, Ollama → advisory banner,
    Anthropic → "Full tool mode" banner, provider name shown, invalid project exits, EOF exits cleanly
  - `TestRunOfflineChatSlashCommands` (7) — /exit + goodbye, /quit + goodbye, /help shows /clear,
    /context shows stats, /clear shows "cleared", empty lines skipped, /clear absent from tool-mode /help
  - `TestRunOfflineChatStreaming` (5) — chunks in output, user message in turn_user arg,
    project name in system arg, RuntimeError breaks loop, slash commands don't call AI
  - `TestRunOfflineChatHistory` (6) — first turn no history, second turn includes first exchange,
    window=1 evicts old pairs, /clear resets history, history grows across turns,
    /context preserves history
  - `TestOfflineChatExported` (2) — importable from nexus.ai and nexus.commands.chat

**Usage:**
```bash
# Advisory chat with Gemini (no Anthropic key required)
export GOOGLE_API_KEY=...
nexus chat 1                # advisory mode — streaming, suggests CLI commands

# Advisory chat with Ollama (fully local, zero cost, zero cloud)
export OLLAMA_MODEL=llama3.2
nexus chat 1                # completely offline advisory chat

# Anthropic path is unchanged (full tool-use, real actions)
export ANTHROPIC_API_KEY=sk-ant-...
nexus chat 1                # tool mode — can create tasks, update statuses, log time

# Useful slash commands during chat
/context      # refresh the project snapshot (run after you make changes)
/clear        # reset conversation history (helps if responses start repeating)
/help         # see all available commands
/exit         # end the session
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
