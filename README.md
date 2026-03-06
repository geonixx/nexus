# Nexus

[![CI](https://github.com/geonixx/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/geonixx/nexus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Local-first CLI project and task intelligence tool.**

Nexus lives in your terminal and stays out of your way. It tracks projects, sprints, tasks, and time — with an optional AI layer (Claude, Gemini, or local Ollama) that can suggest tasks, diagnose project health, write standups, and chat interactively about your work.

> Built for developers who want the power of Jira without the browser tab.

---

## Features

- **Full project management** — projects, sprints, tasks, time logging, priorities
- **AI-powered intelligence** — task suggestions, estimates, health diagnosis, interactive chat (Claude / Gemini / Ollama)
- **AI scrum master** — autonomous agent reviews your project, surfaces blockers, adds notes, creates tasks (`nexus agent run`); works with Anthropic (tool-use), Gemini, and Ollama (offline structured-output mode)
- **Local AI (Ollama)** — run every AI feature fully offline with any local model; zero API cost, zero data sent to the cloud (`OLLAMA_MODEL=llama3.2`); offline agent path works with Gemini and Ollama too
- **Tags / labels** — free-form tags on any task; filter by tag across sprints, next-queue, and search (`nexus tag`)
- **Watch daemon** — background monitor that polls for stale work and can trigger the AI agent on a schedule (`nexus watch`)
- **Slack bridge** — slash command server with Block Kit formatting, signature verification, and async AI review (`nexus slack serve`)
- **GitHub Issues sync** — pull open issues into Nexus tasks, with upsert semantics (no duplicates on re-sync)
- **Portfolio workspace** — health grades and cross-project priority queue across every project at once
- **Security-first** — automatic file permission hardening, secret-in-config blocking, audit command
- **Fully local** — single SQLite file, WAL mode for concurrent access, zero cloud, works offline
- **Interactive advisory chat** — `nexus chat` works with all three providers; Gemini/Ollama get advisory mode (streaming REPL that suggests CLI commands); Anthropic gets full tool mode
- **Claude Code integration** — `nexus claude-init` generates a ready-to-use `CLAUDE.md` snippet that wires Claude Code into your task tracker: check tasks before starting, log time when done, explicit forbidden-command list
- **797 tests, 0 warnings**

---

## Installation

### Quickstart (recommended)

```bash
# Install with AI features
pip install "nexus[ai]"

# Or via uvx (no install required, runs from cache)
uvx --with "nexus[ai]" nexus --help
```

### Without AI features

```bash
pip install nexus
```

### From source

```bash
git clone https://github.com/geonixx/nexus.git
cd nexus
pip install -e ".[ai]"
# or with uv:
uv sync && uv sync --extra ai
```

### First-time setup

```bash
nexus init
```

This creates `~/.nexus/` with the right permissions, checks for API keys, and walks you through initial config.

---

## Quick Start

```bash
# Create a project
nexus project new "My App" --description "A cool thing I'm building"

# Add some tasks
nexus task add 1 "Set up CI/CD pipeline" --priority high --estimate 4
nexus task add 1 "Write API documentation" --priority medium
nexus task add 1 "Add authentication" --priority critical --estimate 8

# Declare that auth depends on CI being done first
nexus task depend 3 --on 1

# See what you should work on right now
nexus task next 1

# Mark a task done
nexus task done 1

# Log time
nexus task log 2 1.5 --note "Drafted endpoints section"

# See the full project dashboard
nexus dashboard 1
```

---

## Command Reference

### Projects

```bash
nexus project new "Name" [-d description]   # create a project
nexus project list                           # list all projects
nexus project show <id>                      # details + stats
nexus project search <query>                 # search by name/description
nexus project health <id> [--ai]             # A–F health score + AI diagnosis
nexus project update <id> --status done      # update status
```

### Tasks

```bash
nexus task add <project_id> "Title" [-p priority] [-e hours] [-s sprint_id]
nexus task list <project_id> [--status todo|in_progress|done|blocked]
nexus task show <id>                         # full detail: notes, time log, dependencies
nexus task start <id>                        # mark in-progress
nexus task done <id>                         # mark complete
nexus task block <id>                        # mark blocked
nexus task update <id> [-t title] [-p priority] [-e estimate]
nexus task log <id> <hours> [-n note]        # log time
nexus task note <id> "Note text"             # append a timestamped note
nexus task next [project_id] [-n count]      # highest-priority tasks to work on
nexus task bulk done 1 2 3                   # batch-update multiple tasks
nexus task stale [project_id] [--days N]     # surface forgotten/stuck tasks
nexus task delete <id>                       # delete (with confirmation)

# Dependencies
nexus task depend <id>                       # show what this task needs / what needs it
nexus task depend <id> --on 3 --on 4        # add prerequisites (cycle-safe)
nexus task undepend <id> --from <dep_id>    # remove a prerequisite
nexus task graph <project_id>               # visualise the full dependency DAG

# AI-powered
nexus task suggest <project_id> [--add]     # AI task suggestions
nexus task estimate <id>                     # AI hour estimate with reasoning
```

### Sprints

```bash
nexus sprint new <project_id> "Sprint 1" [--goal "..."] [--starts DATE] [--ends DATE]
nexus sprint list <project_id>
nexus sprint velocity <project_id>           # historical velocity table
nexus sprint plan <project_id> [--capacity Xh]  # AI picks backlog tasks
nexus sprint start <id> / nexus sprint close <id>
```

### Time Tracking

```bash
nexus timer start <task_id>                  # start a live stopwatch
nexus timer status                           # show elapsed time
nexus timer stop [-n note]                   # stop + auto-log (rounded to 0.25h)
nexus timer cancel                           # discard without logging
```

### Reports & Dashboard

```bash
nexus dashboard <project_id>                 # Rich kanban board
nexus report digest <project_id>             # AI project status narrative
nexus report week <project_id> [--days N] [--ai]  # weekly activity bar chart
nexus standup [project_id] [--ai]            # Yesterday / Today / Blockers brief
```

### Portfolio (Workspace)

```bash
nexus workspace                              # health grades for every project
nexus workspace next [--limit N]             # cross-project priority queue
                                             # (tasks with unmet deps auto-hidden)
```

### GitHub Integration

```bash
nexus github sync <project_id> owner/repo           # sync open issues → tasks
nexus github sync <project_id> owner/repo --token $GH  # private repo
nexus github sync <project_id> owner/repo --state all  # include closed
nexus github sync <project_id> owner/repo --max 100    # cap at 100 issues
# Re-run any time — existing tasks are updated, not duplicated
```

### Tags

```bash
# Add tags when creating or updating tasks
nexus task add <project_id> "Fix login bug" --tag bug --tag auth
nexus task update <id> --tag security          # add a tag
nexus task update <id> --untag auth            # remove a tag
nexus task show <id>                           # tags shown in detail view

# Filter task lists and next-queue by tag
nexus task list <project_id> --tag bug
nexus task next <project_id> --tag auth

# Tag management
nexus tag list                                 # all tags in workspace with task counts
nexus tag list <project_id>                    # scoped to a single project
nexus tag tasks <tag>                          # every task carrying a tag (cross-project)
nexus tag tasks <tag> --project-id <id>        # scoped to a project
```

Tags are normalised to lowercase on write — `Bug`, `bug`, and `  bug  ` all resolve to the same tag.

### Exports

```bash
nexus export markdown <project_id>           # full project as .md
nexus export csv <project_id>                # tasks CSV
nexus export csv <project_id> --type timelog # time entries CSV
nexus export markdown <project_id> --stdout  # pipe to other tools
```

### AI Chat

```bash
nexus chat [project_id]                      # interactive chat — all providers
```

**Two modes depending on your active provider:**
- **Anthropic** — full tool mode: Claude can list tasks, update status, create tasks, log time, query stats
- **Gemini / Ollama** — advisory mode: streaming responses suggest the exact `nexus` CLI commands to run

Slash commands in both modes: `/context` (refresh project snapshot), `/help`, `/exit`. Advisory mode only: `/clear` (reset conversation history for context management).

### AI Scrum Master

```bash
nexus task ingest <project_id> "text"        # parse freeform text → structured task
nexus task ingest <project_id> "text" --add  # parse and create immediately
nexus task ingest 1 "$(pbpaste)"             # pipe from clipboard (macOS)

nexus agent run [project_id]                 # autonomous AI project review
nexus agent run [project_id] --dry-run       # show what agent would do, no writes
nexus agent run [project_id] --yes           # auto-approve all write actions
```

The agent reviews your project state, surfaces stale/blocked work, and can add notes or create tasks.

**Two agent modes depending on the active AI provider:**
- **Anthropic** — full iterative tool-use loop; reads tasks on demand; broader action set
- **Gemini / Ollama** — offline structured-output mode; full project snapshot in one prompt; returns a JSON action plan (`add_note` and `create_task` only); retries on parse failure

`nexus chat` works with all three providers — Anthropic for full tool use, Gemini/Ollama for advisory mode.

### Watch Daemon

```bash
nexus watch [project_id]                          # monitor for stale work (30-min interval)
nexus watch [project_id] --interval 10            # check every 10 minutes
nexus watch [project_id] --agent                  # also trigger AI review each cycle
nexus watch [project_id] --agent --agent-yes      # AI review with auto-approve writes
nexus watch [project_id] --agent --max-agent-cycles 3  # cap AI calls (prevent runaway spend)
nexus watch --all                                 # watch every project in the workspace
```

Polls your projects on a configurable interval and surfaces stale in-progress tasks, long-blocked work, and forgotten backlog. Press `Ctrl-C` to stop. Use `--max-agent-cycles N` to cap the number of AI passes per session (useful in automated/cron environments).

### Slack Bridge

```bash
# Start local slash command server (expose to Slack via ngrok)
nexus slack serve --project-id 1            # listen on :3000 (default)
nexus slack serve --port 4000 --project-id 1
nexus slack serve                           # uses default_project from config

# With HMAC signature verification (strongly recommended)
export SLACK_SIGNING_SECRET=abc123...
nexus slack serve --project-id 1

# Preview Block Kit JSON output
nexus slack format 1                        # print JSON to terminal
nexus slack format 1 | pbcopy              # copy to clipboard (macOS)

# Test an incoming webhook
nexus slack ping https://hooks.slack.com/services/...
```

Slash commands (once `/nexus` is configured in your Slack app):

| Command | Description |
|---|---|
| `/nexus` | Project health overview |
| `/nexus status` | Project health overview |
| `/nexus next [N]` | Next N ready tasks (default 5) |
| `/nexus add <title>` | Create a new task |
| `/nexus done <id>` | Mark a task done |
| `/nexus agent` | AI scrum-master review (async, posts when complete) |
| `/nexus help` | Usage reference |

Expose localhost with [ngrok](https://ngrok.com): `ngrok http 3000`, then set your Slack app's Request URL to the ngrok URL.

### Configuration

```bash
nexus config set default_project 3          # skip project_id on task next, stale, etc.
nexus config set ai_max_tokens 2048
nexus config get default_project
nexus config show                            # all values (secrets auto-masked)
nexus config unset default_project
```

### Security

```bash
nexus security                               # 7-point health check
nexus security --fix                         # also tighten file permissions
```

Checks: directory permissions (700), database permissions (600), config permissions (600), secrets in config, git tracking, API key env vars.

---

## AI Setup

Nexus supports three AI providers, auto-selected in priority order:

### 1. Anthropic Claude (preferred — full feature set)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Required for `nexus chat` **full tool mode** (real actions) and the **full** `nexus agent run` tool-use loop. Get a key at [console.anthropic.com](https://console.anthropic.com/).

### 2. Google Gemini (fallback — all non-tool features)

```bash
export GOOGLE_API_KEY=AIza...
```

Works for suggestions, estimates, digests, reports, and `nexus chat` advisory mode. Does not support tool use. Get a key at [aistudio.google.com](https://aistudio.google.com/app/apikey).

### 3. Ollama (local — fully offline, zero cost)

```bash
# Install Ollama: https://ollama.com
ollama pull llama3.2        # download the model (~2 GB)
ollama serve                # start the daemon (auto-starts on macOS)
export OLLAMA_MODEL=llama3.2
```

All streaming AI features work with Ollama, including `nexus chat` (advisory mode) and `nexus agent run` (offline structured-output mode). With Ollama, no data ever leaves your machine — zero API cost, zero cloud.

```bash
# Use a different model
export OLLAMA_MODEL=qwen2.5-coder   # great for code tasks
export OLLAMA_MODEL=mistral          # another solid option

# Override the host (e.g. Ollama on a different machine)
export OLLAMA_HOST=http://192.168.1.10:11434
```

Nexus auto-selects **Anthropic → Gemini → Ollama** in priority order. If none are set, all non-AI commands continue to work normally.

> **Tip:** Add your preferred provider to `~/.zshrc` or `~/.bashrc` so you never have to think about it.

---

## Shell Completion

```bash
# Bash
eval "$(_NEXUS_COMPLETE=bash_source nexus)"
# Add to ~/.bashrc:
echo 'eval "$(_NEXUS_COMPLETE=bash_source nexus)"' >> ~/.bashrc

# Zsh
eval "$(_NEXUS_COMPLETE=zsh_source nexus)"
# Add to ~/.zshrc:
echo 'eval "$(_NEXUS_COMPLETE=zsh_source nexus)"' >> ~/.zshrc

# Fish
_NEXUS_COMPLETE=fish_source nexus | source
# Add to ~/.config/fish/config.fish:
echo '_NEXUS_COMPLETE=fish_source nexus | source' >> ~/.config/fish/config.fish
```

---

## Data & Privacy

- **All data stays local.** Nexus uses a single SQLite file at `~/.nexus/nexus.db`.
- **AI features** send task titles and descriptions to the configured AI provider. No project data is stored by Nexus itself beyond the local database.
- **Secrets** are never written to config files. `nexus config set` blocks API key storage with a clear error and env-var hint.
- **File permissions** are automatically tightened to 600/700 on every startup. Run `nexus security` to audit your installation.

---

## Use a Custom Database

```bash
# Per-command
nexus --db ~/work/work.db task list 1

# Permanently (shell session)
export NEXUS_DB=~/work/work.db

# Per-directory (add to a project's .envrc with direnv)
echo 'export NEXUS_DB=$PWD/.nexus.db' >> .envrc
```

---

## Development

```bash
git clone https://github.com/geonixx/nexus.git
cd nexus

# Install with dev dependencies
uv sync --dev
# or: pip install -e ".[ai]" && pip install pytest pytest-cov

# Run tests
uv run pytest                                # all 662 tests
uv run pytest tests/test_deps.py -v         # specific module
uv run pytest --cov=nexus --cov-report=term-missing  # with coverage

# Run the CLI locally
uv run nexus --help
uv run nexus init

# Security audit
uv run nexus security
```

### Project Structure

```
src/nexus/
├── cli.py            # Click group, --db flag, context setup
├── models.py         # Pydantic models (Project, Sprint, Task, …)
├── db.py             # Database class — all CRUD, stats, dependencies
├── ai.py             # NexusAI (provider-agnostic), Anthropic + Gemini providers
├── security.py       # Secret detection, permission checks, git tracking
├── ui.py             # Rich tables, panels, theme, print_* helpers
└── commands/
    ├── project.py    # nexus project *
    ├── task.py       # nexus task *  (includes depend/graph, --tag)
    ├── tag.py        # nexus tag *
    ├── sprint.py     # nexus sprint *
    ├── report.py     # nexus report *
    ├── dashboard.py  # nexus dashboard
    ├── export.py     # nexus export *
    ├── timer.py      # nexus timer *
    ├── chat.py       # nexus chat
    ├── github.py     # nexus github *
    ├── workspace.py  # nexus workspace *
    ├── config.py     # nexus config *
    ├── watch.py      # nexus watch
    └── security.py   # nexus security
```

---

## Roadmap

### Shipped
- [x] `nexus watch` — background daemon for stale detection + AI agent scheduling
- [x] Slack bridge — slash command server with Block Kit and async AI review
- [x] Tags / labels — free-form task labels with cross-project search
- [x] SQLite WAL mode — concurrent multi-agent read/write access
- [x] Ollama provider — fully local AI; zero cloud, zero cost, zero latency tax
- [x] Offline agent — Gemini/Ollama structured-output action plan + retry loop
- [x] Offline chat — advisory streaming REPL for Gemini/Ollama providers
- [x] Claude Code integration — `nexus claude-init` generates a CLAUDE.md task workflow snippet

### Upcoming
- [ ] **M21 · Task dependencies** — declare prerequisites, detect cycles, visualise the DAG;
  `task next` respects the graph; AI context includes full dependency state so the agent
  can reason about order without hallucinating the critical path
- [ ] **M22 · AI sprint planner** — `nexus sprint plan` uses the dependency graph + priorities +
  estimates to suggest a coherent, achievable sprint; works with all three AI providers
- [ ] **M23 · Velocity analytics** — throughput charts, estimate accuracy, task cycle time;
  weekly/monthly breakdowns rendered with Rich ASCII charts

### Ideas backlog
- Web UI (read-only dashboard, served locally)
- Multi-user sync via git (collaborative local-first)
- Recurring tasks
- Plugin system for custom integrations

---

## License

MIT
