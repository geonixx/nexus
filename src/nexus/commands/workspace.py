"""Workspace command — portfolio view across all projects.

Commands
--------
nexus workspace          Portfolio table: every project with health grade,
                         task counts, and activity.
nexus workspace next     Cross-project priority queue — highest-priority
                         actionable tasks regardless of which project they
                         belong to.
"""

from __future__ import annotations

import click
from rich import box
from rich.rule import Rule
from rich.table import Table

from ..commands.project import _compute_health
from ..db import Database
from ..models import Priority, Status
from ..ui import console, print_info

# ── Shared helpers ─────────────────────────────────────────────────────────────

_GRADE_STYLE: dict[str, str] = {
    "A": "bold green",
    "B": "bold cyan",
    "C": "bold yellow",
    "D": "bold red",
    "F": "bold red",
}

_PRIO_ORDER = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}

_PRIO_STYLE: dict[Priority, str] = {
    Priority.CRITICAL: "bold red",
    Priority.HIGH: "red",
    Priority.MEDIUM: "yellow",
    Priority.LOW: "dim",
}

_STATUS_STYLE: dict[Status, str] = {
    Status.TODO: "dim",
    Status.IN_PROGRESS: "cyan",
}


def _show_portfolio(db: Database) -> None:
    """Print the portfolio health table for all projects."""
    projects = db.list_projects()
    if not projects:
        print_info("No projects yet. Create one with: nexus project new <name>")
        return

    console.print(Rule("[nexus.title]Workspace · Portfolio Overview[/nexus.title]", style="cyan"))
    console.print()

    table = Table(box=box.SIMPLE, show_header=True, expand=False, padding=(0, 1))
    table.add_column("ID",      style="dim", justify="right", width=4)
    table.add_column("Project", width=24)
    table.add_column("Status",  width=12)
    table.add_column("Grade",   justify="center", width=6)
    table.add_column("Score",   justify="right", width=6)
    table.add_column("Tasks",   justify="right", width=6)
    table.add_column("Done",    justify="right", width=6)
    table.add_column("Blocked", justify="right", width=8)
    table.add_column("Hrs/wk",  justify="right", width=8)

    for p in projects:
        health = _compute_health(db, p.id)
        ctx = health.get("context", {})

        grade = health["grade"]
        score = health["score"]
        done_count    = ctx.get("done", 0)
        in_prog_count = ctx.get("in_progress", 0)
        blocked_count = ctx.get("blocked", 0)
        todo_count    = ctx.get("todo", 0)
        hours_week    = ctx.get("hours_week", 0.0)
        total_tasks   = done_count + in_prog_count + blocked_count + todo_count

        # Project status colour
        status_map = {
            "done": "green",
            "in_progress": "cyan",
            "blocked": "red",
        }
        status_style = status_map.get(p.status.value, "dim")

        if health["metrics"]:
            gs = _GRADE_STYLE.get(grade, "dim")
            grade_cell = f"[{gs}]{grade}[/{gs}]"
            score_cell = str(score)
        else:
            grade_cell = "[dim]—[/dim]"
            score_cell = "[dim]—[/dim]"

        table.add_row(
            str(p.id),
            p.name[:24],
            f"[{status_style}]{p.status.value}[/{status_style}]",
            grade_cell,
            score_cell,
            str(total_tasks),
            f"[green]{done_count}[/green]" if done_count else "[dim]0[/dim]",
            f"[red]{blocked_count}[/red]"  if blocked_count else "[dim]0[/dim]",
            f"{hours_week:.1f}h" if hours_week else "[dim]—[/dim]",
        )

    console.print(table)
    console.print(
        f"  [dim]{len(projects)} project(s) · "
        "nexus workspace next  for cross-project priority queue[/dim]"
    )
    console.print()


# ── Click group ────────────────────────────────────────────────────────────────


@click.group("workspace", invoke_without_command=True)
@click.pass_context
def workspace_cmd(ctx: click.Context):
    """Portfolio view across all projects.

    Run without a subcommand to see the health dashboard.
    Use 'nexus workspace next' to surface the highest-priority tasks
    across every project at once.
    """
    if ctx.invoked_subcommand is None:
        _show_portfolio(ctx.obj)


@workspace_cmd.command("next")
@click.option(
    "--limit",
    type=int,
    default=10,
    show_default=True,
    help="Max tasks to display.",
)
@click.pass_obj
def workspace_next(db: Database, limit: int):
    """Show the highest-priority actionable tasks across all projects.

    Tasks are ranked CRITICAL → HIGH → MEDIUM → LOW, then by most recently
    updated within the same priority band.  Only TODO and IN_PROGRESS tasks
    are included.
    """
    projects = db.list_projects()
    if not projects:
        print_info("No projects yet.")
        return

    proj_map = {p.id: p for p in projects}

    # Collect all actionable tasks from every project in one pass
    # Exclude tasks whose dependencies are not yet fully satisfied
    candidates = []
    dep_blocked_count = 0
    for p in projects:
        for t in db.list_tasks(project_id=p.id):
            if t.status in (Status.TODO, Status.IN_PROGRESS):
                if db.has_unmet_dependencies(t.id):
                    dep_blocked_count += 1
                else:
                    candidates.append(t)

    if not candidates:
        msg = "No actionable tasks found across any project."
        if dep_blocked_count:
            msg += f" ({dep_blocked_count} task(s) waiting on dependencies)"
        print_info(msg)
        return

    # Sort: primary = priority (CRITICAL first), secondary = updated_at DESC
    candidates.sort(
        key=lambda t: (
            _PRIO_ORDER.get(t.priority, 99),
            -(t.updated_at.timestamp() if t.updated_at else 0),
        )
    )

    top = candidates[:limit]

    console.print(
        Rule(
            "[nexus.title]Workspace · Cross-Project Priority Queue[/nexus.title]",
            style="cyan",
        )
    )
    console.print()

    table = Table(box=box.SIMPLE, show_header=True, expand=False, padding=(0, 1))
    table.add_column("#",        style="dim", justify="right", width=3)
    table.add_column("Project",  width=18)
    table.add_column("Priority", width=10)
    table.add_column("Status",   width=12)
    table.add_column("Task")

    for i, t in enumerate(top, 1):
        proj = proj_map.get(t.project_id)
        proj_name  = proj.name[:18] if proj else "?"
        prio_style = _PRIO_STYLE.get(t.priority, "")
        stat_style = _STATUS_STYLE.get(t.status, "dim")

        table.add_row(
            str(i),
            proj_name,
            f"[{prio_style}]{t.priority.value}[/{prio_style}]",
            f"[{stat_style}]{t.status.value}[/{stat_style}]",
            t.title,
        )

    console.print(table)
    footer = f"  [dim]Showing {len(top)} of {len(candidates)} actionable task(s)"
    if dep_blocked_count:
        footer += f" · {dep_blocked_count} hidden (waiting on dependencies)"
    footer += "[/dim]"
    console.print(footer)
    console.print()
