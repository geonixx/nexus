# Nexus

**Local-first CLI project and task intelligence tool.**

Nexus lives in your terminal and stays out of your way. It tracks projects, sprints, tasks, and time — with an optional AI layer (Claude or Gemini) that can suggest tasks, diagnose project health, write standups, and chat interactively about your work.

> Built for developers who want the power of Jira without the browser tab.

---

## Features

- **Full project management** — projects, sprints, tasks, time logging, priorities
- **Task dependencies** — declare prerequisites, detect cycles, visualise the DAG
- **AI-powered intelligence** — task suggestions, estimates, health diagnosis, interactive chat (Claude / Gemini)
- **GitHub Issues sync** — pull open issues into Nexus tasks, with upsert semantics (no duplicates on re-sync)
- **Portfolio workspace** — health grades and cross-project priority queue across every project at once
- **Security-first** — automatic file permission hardening, secret-in-config blocking, audit command
- **Fully local** — single SQLite file, zero cloud, works offline
- **415 tests, 0 warnings**

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

### Exports

```bash
nexus export markdown <project_id>           # full project as .md
nexus export csv <project_id>                # tasks CSV
nexus export csv <project_id> --type timelog # time entries CSV
nexus export markdown <project_id> --stdout  # pipe to other tools
```

### AI Chat

```bash
nexus chat [project_id]                      # interactive AI session with tool use
```

Claude reads your full project context and can take real actions: list tasks, update status, create tasks, log time, query stats. Use `/help` inside chat for slash commands.

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

Nexus supports two AI providers. Set one (or both) as environment variables:

```bash
# Claude (Anthropic) — preferred for chat and tool use
export ANTHROPIC_API_KEY=sk-ant-...

# Gemini — fallback; works for all non-chat features
export GOOGLE_API_KEY=AIza...
```

Nexus auto-selects Anthropic → Gemini in priority order. If neither is set, all non-AI commands continue to work normally.

> **Tip:** Add to `~/.zshrc` or `~/.bashrc` so you never have to think about it.

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
uv run pytest                                # all 415 tests
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
    ├── task.py       # nexus task *  (includes depend/graph)
    ├── sprint.py     # nexus sprint *
    ├── report.py     # nexus report *
    ├── dashboard.py  # nexus dashboard
    ├── export.py     # nexus export *
    ├── timer.py      # nexus timer *
    ├── chat.py       # nexus chat
    ├── github.py     # nexus github *
    ├── workspace.py  # nexus workspace *
    ├── config.py     # nexus config *
    └── security.py   # nexus security
```

---

## Roadmap

- [ ] Slack / webhook bridge (create tasks from channel messages)
- [ ] `nexus watch` — background daemon for notifications and auto-stale detection
- [ ] Web UI (read-only dashboard, served locally)
- [ ] Multi-user sync via git (collaborative local-first)
- [ ] Plugin system for custom integrations

---

## License

MIT
