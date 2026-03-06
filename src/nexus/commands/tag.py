"""nexus tag — Tag management commands.

Tags are free-form, lowercase labels attached to individual tasks.
They are normalised (stripped + lowercased) on write, so "Tech-Debt",
"tech-debt", and "  tech-debt  " all resolve to the same tag.

Commands
--------
nexus tag list [project_id]   List all tags in use with task counts.
nexus tag tasks <tag>         List every task that carries a given tag.
"""

from __future__ import annotations

import click
from rich import box
from rich.rule import Rule
from rich.table import Table

from ..db import Database
from ..models import Status
from ..ui import STATUS_ICONS, console, print_error, print_info


# ── Tag colour helper ──────────────────────────────────────────────────────────

_STATUS_STYLE: dict[Status, str] = {
    Status.TODO:        "dim",
    Status.IN_PROGRESS: "cyan",
    Status.BLOCKED:     "red",
    Status.DONE:        "green",
}


# ── CLI group ──────────────────────────────────────────────────────────────────


@click.group("tag")
def tag_cmd() -> None:
    """Manage task tags across projects."""


@tag_cmd.command("list")
@click.argument("project_id", type=int, required=False, default=None)
@click.pass_obj
def tag_list(db: Database, project_id: int | None) -> None:
    """List all tags in use, with task counts.

    Pass PROJECT_ID to scope results to a single project, or omit to see
    every tag used across the entire workspace.
    """
    if project_id is not None and not db.get_project(project_id):
        print_error(f"Project #{project_id} not found.")
        raise SystemExit(1)

    tags = db.get_all_tags(project_id=project_id)
    if not tags:
        scope = f"project #{project_id}" if project_id else "workspace"
        print_info(f"No tags found in {scope}. Add one with: nexus task add <id> --tag <name>")
        return

    scope_label = f"Project #{project_id}" if project_id else "Workspace"
    console.print(Rule(f"[nexus.title]Tags · {scope_label}[/nexus.title]", style="cyan"))
    console.print()

    table = Table(box=box.SIMPLE, show_header=True, expand=False, padding=(0, 1))
    table.add_column("Tag",   width=28)
    table.add_column("Tasks", justify="right", width=8)

    for tag, count in tags:
        table.add_row(f"[cyan]{tag}[/cyan]", str(count))

    console.print(table)
    console.print(
        f"  [dim]{len(tags)} tag(s) in use  ·  "
        "nexus tag tasks <tag>  to see tasks for a specific tag[/dim]"
    )
    console.print()


@tag_cmd.command("tasks")
@click.argument("tag")
@click.option(
    "--project-id", "-p",
    type=int,
    default=None,
    help="Scope results to a single project.",
)
@click.pass_obj
def tag_tasks(db: Database, tag: str, project_id: int | None) -> None:
    """List all tasks that carry a given tag.

    Searches across the entire workspace by default.
    Use --project-id to narrow results to a single project.
    """
    if project_id is not None and not db.get_project(project_id):
        print_error(f"Project #{project_id} not found.")
        raise SystemExit(1)

    tasks = db.list_tasks_by_tag(tag, project_id=project_id)
    if not tasks:
        scope = f" in project #{project_id}" if project_id else ""
        print_info(f"No tasks tagged '{tag}'{scope}.")
        return

    scope_label = f" · Project #{project_id}" if project_id else ""
    console.print(
        Rule(f"[nexus.title]Tasks tagged '{tag}'{scope_label}[/nexus.title]", style="cyan")
    )
    console.print()

    # Group by project for clarity
    projects = db.list_projects()
    proj_map = {p.id: p for p in projects}

    table = Table(box=box.SIMPLE, show_header=True, expand=False, padding=(0, 1))
    table.add_column("#",       style="dim", justify="right", width=4)
    table.add_column("Project", width=20)
    table.add_column("Status",  width=13)
    table.add_column("Task")

    for t in tasks:
        proj = proj_map.get(t.project_id)
        icon  = STATUS_ICONS.get(t.status, "○")
        style = _STATUS_STYLE.get(t.status, "")
        table.add_row(
            str(t.id),
            (proj.name[:20] if proj else "?"),
            f"[{style}]{icon} {t.status.value}[/{style}]" if style else f"{icon} {t.status.value}",
            t.title,
        )

    console.print(table)
    console.print(f"  [dim]{len(tasks)} task(s) tagged '{tag}'[/dim]")
    console.print()
