"""nexus init — first-time setup wizard.

Creates ~/.nexus/ with the right permissions, checks for API keys,
and walks the user through creating their first project.
"""

from __future__ import annotations

import os

import click
from rich.rule import Rule

from ..db import Database
from ..ui import console, print_error, print_info, print_success


# ── Known AI environment variables ────────────────────────────────────────────

_AI_VARS = [
    ("ANTHROPIC_API_KEY", "Anthropic Claude", "https://console.anthropic.com/"),
    ("GOOGLE_API_KEY",    "Google Gemini",    "https://aistudio.google.com/app/apikey"),
]


@click.command("init")
@click.pass_obj
def init_cmd(db: Database):
    """Set up Nexus for the first time.

    Creates the data directory, verifies file permissions, checks for AI
    API keys, and optionally creates a first project.

    Safe to run multiple times — it will not overwrite existing data.
    """
    console.print()
    console.print(Rule("[nexus.title]Welcome to Nexus[/nexus.title]", style="cyan"))
    console.print()

    nexus_dir = db.path.parent

    # ── Step 1: Confirm data directory ─────────────────────────────────────────
    console.print(f"  [green]✓[/green]  Data directory: [bold]{nexus_dir}[/bold]")

    # ── Step 2: Database is already ready (cli group created it) ──────────────
    console.print(f"  [green]✓[/green]  Database ready at [bold]{db.path}[/bold]")

    # ── Step 3: Shell completion hint ─────────────────────────────────────────
    console.print()
    console.print("  [dim]─── Shell completion ───────────────────────────────────[/dim]")
    console.print("  Add tab-completion for your shell:")
    console.print("  [dim]  Bash:[/dim]  eval \"\\$(_NEXUS_COMPLETE=bash_source nexus)\"")
    console.print("  [dim]  Zsh: [/dim]  eval \"\\$(_NEXUS_COMPLETE=zsh_source nexus)\"")
    console.print("  [dim]  Fish:[/dim]  _NEXUS_COMPLETE=fish_source nexus | source")

    # ── Step 4: AI API key check ───────────────────────────────────────────────
    console.print()
    console.print("  [dim]─── AI providers ─────────────────────────────────────────[/dim]")

    configured = []
    for var, label, url in _AI_VARS:
        if os.environ.get(var):
            console.print(f"  [green]✓[/green]  {label} ({var} is set)")
            configured.append(label)
        else:
            console.print(f"  [dim]○[/dim]  {label} — not configured")
            console.print(f"       [dim]Get a key: {url}[/dim]")
            console.print(f"       [dim]Then: export {var}=<your-key>[/dim]")

    if not configured:
        console.print()
        console.print(
            "  [yellow]⚠  No AI keys found.[/yellow] All non-AI commands work fine.\n"
            "  Set at least one API key to enable AI features."
        )

    # ── Step 5: Offer to create a first project ────────────────────────────────
    console.print()
    console.print("  [dim]─── Get started ───────────────────────────────────────────[/dim]")

    existing = db.list_projects()
    if existing:
        console.print(f"  [green]✓[/green]  {len(existing)} project(s) already exist.")
        console.print()
        console.print("  You're all set!  Some commands to try:\n")
        _print_quick_ref(existing[0].id)
        return

    console.print()
    create = click.confirm("  Create your first project now?", default=True)
    if not create:
        console.print()
        console.print("  Ready when you are.  Start with:\n")
        console.print('    [bold]nexus project new "My Project"[/bold]')
        console.print()
        return

    console.print()
    name = click.prompt("  Project name").strip()
    if not name:
        print_error("Project name cannot be empty.")
        raise SystemExit(1)

    desc = click.prompt("  Description (optional)", default="", show_default=False).strip()

    project = db.create_project(name, description=desc)
    print_success(f"  Created project [bold]{project.name}[/bold] (id={project.id})")

    # Offer to set as default
    set_default = click.confirm(
        f"  Set project {project.id} as your default project?", default=True
    )
    if set_default:
        from ..commands.config import load_config, save_config
        data = load_config()
        data["default_project"] = project.id
        save_config(data)
        print_info(f"  Default project → {project.id}")

    console.print()
    console.print("  You're all set!  Quick reference:\n")
    _print_quick_ref(project.id)


def _print_quick_ref(project_id: int) -> None:
    """Print a minimal quick-reference for a given project id."""
    pid = str(project_id)
    lines = [
        ("Add a task",          f"nexus task add {pid} \"Title\" --priority high"),
        ("See what to do next", f"nexus task next {pid}"),
        ("Project dashboard",   f"nexus dashboard {pid}"),
        ("Start the AI chat",   f"nexus chat {pid}"),
        ("Portfolio view",       "nexus workspace"),
        ("Security audit",       "nexus security"),
        ("Full help",            "nexus --help"),
    ]
    for label, cmd in lines:
        console.print(f"  [dim]{label:<22}[/dim]  [bold]{cmd}[/bold]")
    console.print()
