"""nexus claude-init — generate a CLAUDE.md snippet for Claude Code integration.

Produces a ready-to-use Markdown file that tells Claude Code how to:
  - Check the Nexus task list before starting work
  - Log time and mark tasks done after tests pass
  - Avoid running the Nexus autonomous agent (avoids two-AI conflicts)

By default the snippet is printed to stdout for piping or pasting.
Use --output to write it directly to a file (e.g. CLAUDE.md or .claude/CLAUDE.md).
"""

from __future__ import annotations

from pathlib import Path

import click

from ..commands.config import load_config
from ..db import Database
from ..ui import print_error, print_success


# ── Template ──────────────────────────────────────────────────────────────────

_TEMPLATE = """\
# Nexus Task Integration

This project is tracked in [Nexus](https://github.com/geonixx/nexus).

## Before starting work

Run these commands to orient yourself:

```bash
# What needs to be done (highest priority first)
NEXUS_DB={nexus_db_path} nexus task next {project_id}

# Full project dashboard
NEXUS_DB={nexus_db_path} nexus dashboard {project_id}

# See all open tasks
NEXUS_DB={nexus_db_path} nexus task list {project_id}
```

## After completing work

Only update task status **after tests pass**:

```bash
# Run tests first — do not mark done unless these pass
{test_cmd}

# Mark the task done and log your time
NEXUS_DB={nexus_db_path} nexus task done <task_id>
NEXUS_DB={nexus_db_path} nexus task log <task_id> <hours> -n "brief summary"
```

## Rules

- **Always query before mutating.** Run `nexus task list {project_id}` first to confirm
  the task ID you intend to update.
- **Never mark done without passing tests.** The test command above must succeed first.
- **Do not run `nexus agent run`** — the autonomous agent must not run inside Claude Code
  (avoids two-AI feedback loops and unintended write operations).
- **Do not run destructive commands**: `nexus task delete`, `nexus project delete`.
- **Do not run `nexus slack serve`** — server-side command, not for automated use.

## Project reference

| Field | Value |
|-------|-------|
| Project | {project_name} |
| Project ID | {project_id} |
| Database | `{nexus_db_path}` |
| Test command | `{test_cmd}` |

## Quick reference

| Goal | Command |
|------|---------|
| See what to work on | `NEXUS_DB={nexus_db_path} nexus task next {project_id}` |
| Start a task | `NEXUS_DB={nexus_db_path} nexus task start <task_id>` |
| Mark done | `NEXUS_DB={nexus_db_path} nexus task done <task_id>` |
| Log time | `NEXUS_DB={nexus_db_path} nexus task log <task_id> <hours> -n "note"` |
| Add a task | `NEXUS_DB={nexus_db_path} nexus task add {project_id} "Title"` |
| Project overview | `NEXUS_DB={nexus_db_path} nexus dashboard {project_id}` |
"""


def build_claude_md(
    project_name: str,
    project_id: int,
    nexus_db_path: str,
    test_cmd: str = "pytest",
) -> str:
    """Return the rendered CLAUDE.md snippet as a string.

    This is a pure function — no DB access, no side effects.
    Suitable for unit testing in isolation.
    """
    return _TEMPLATE.format(
        project_name=project_name,
        project_id=project_id,
        nexus_db_path=nexus_db_path,
        test_cmd=test_cmd,
    )


# ── CLI command ───────────────────────────────────────────────────────────────


@click.command("claude-init")
@click.argument("project_id", type=int, required=False, default=None)
@click.option(
    "-o", "--output",
    default=None,
    type=click.Path(),
    help="Write snippet to this file instead of printing to stdout.",
)
@click.option(
    "--db-path",
    default=None,
    type=click.Path(),
    help=(
        "DB path to embed in the generated snippet. "
        "Defaults to the active database path (from --db or NEXUS_DB)."
    ),
)
@click.option(
    "--test-cmd",
    default="pytest",
    show_default=True,
    help="Test command to embed in the snippet.",
)
@click.pass_obj
def claude_init_cmd(
    db: Database,
    project_id: int | None,
    output: str | None,
    db_path: str | None,
    test_cmd: str,
) -> None:
    """Generate a CLAUDE.md snippet for Claude Code integration.

    Produces a ready-to-use Markdown file that tells Claude Code how to
    check the task list before writing code and how to log time and mark
    tasks done after tests pass.

    Prints to stdout by default — pipe it or paste it wherever you need it.
    Use --output to write directly to a file.

    \b
    Examples:
      nexus claude-init 1
      nexus claude-init 1 --output CLAUDE.md
      nexus claude-init 1 --output .claude/CLAUDE.md --test-cmd "uv run pytest"
      nexus claude-init --output CLAUDE.md   # uses default_project from config
    """
    # Resolve project_id — fall back to config default
    if project_id is None:
        cfg = load_config()
        project_id = cfg.get("default_project")
        if not project_id:
            print_error(
                "No project_id given and 'default_project' is not set in config.\n"
                "  Run: [bold]nexus config set default_project <id>[/bold]"
            )
            raise SystemExit(1)

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    # --db-path overrides the embedded path; otherwise inherit from active DB
    embed_path = db_path if db_path else str(db.path)

    content = build_claude_md(
        project_name=project.name,
        project_id=project_id,
        nexus_db_path=embed_path,
        test_cmd=test_cmd,
    )

    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print_success(
            f"Wrote CLAUDE.md snippet for [bold]{project.name}[/bold] "
            f"→ [cyan]{out}[/cyan]  ({len(content):,} bytes)"
        )
    else:
        # Raw echo — no Rich markup processing — so the Markdown is unmodified
        click.echo(content)
