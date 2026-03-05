"""Rich kanban dashboard command."""

from __future__ import annotations

from typing import List, Optional

import click
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ..db import Database
from ..models import Priority, Sprint, Status, Task
from ..ui import (
    PRIORITY_ICONS,
    PRIORITY_STYLES,
    STATUS_ICONS,
    STATUS_STYLES,
    console,
    print_error,
)

# Priority sort order (higher = rendered first in column)
_PRIORITY_ORDER = {
    Priority.CRITICAL: 4,
    Priority.HIGH: 3,
    Priority.MEDIUM: 2,
    Priority.LOW: 1,
}


def _task_card(task: Task) -> Panel:
    """Render a single task as a small Rich Panel card."""
    status_style = STATUS_STYLES.get(task.status, "white")
    pri_icon = PRIORITY_ICONS.get(task.priority, "")
    pri_style = PRIORITY_STYLES.get(task.priority, "white")

    title_text = Text()
    title_text.append(f"#{task.id} ", style="dim")
    title_text.append(task.title, style="bold white")

    body = Text()
    body.append(f"{pri_icon} {task.priority.value}", style=pri_style)
    if task.estimate_hours:
        body.append(f"  est {task.estimate_hours:.0f}h", style="dim")
    if task.actual_hours:
        body.append(f"  act {task.actual_hours:.1f}h", style="cyan dim")

    border = status_style if status_style else "bright_black"
    return Panel(body, title=title_text, title_align="left", border_style=border, width=30, padding=(0, 1))


def _kanban_column(title: str, tasks: List[Task], style: str, icon: str) -> Panel:
    """Render a vertical kanban column of task cards."""
    header = Text()
    header.append(f"{icon}  {title}", style=style)
    header.append(f"  {len(tasks)}", style="dim")

    if not tasks:
        content: object = Align(Text("empty", style="dim italic"), align="center")
    else:
        sorted_tasks = sorted(tasks, key=lambda t: _PRIORITY_ORDER.get(t.priority, 0), reverse=True)
        content = Group(*[_task_card(t) for t in sorted_tasks])

    return Panel(
        content,
        title=header,
        title_align="left",
        border_style="bright_black",
        width=34,
        padding=(0, 0),
    )


def _sprint_panel(sprint: Optional[Sprint], sprint_task_count: int, sprint_done: int) -> Panel:
    if sprint is None:
        return Panel("[dim]No active sprint[/dim]", title="Sprint", border_style="bright_black", width=34)

    pct = int(sprint_done / sprint_task_count * 100) if sprint_task_count else 0
    bar_w = 20
    filled = int(pct / 100 * bar_w)
    bar = "[cyan]" + "█" * filled + "[/cyan][dim]" + "░" * (bar_w - filled) + "[/dim]"

    lines = Text()
    lines.append(f"{sprint.name}\n", style="bold white")
    if sprint.goal:
        lines.append(f"{sprint.goal}\n", style="dim")
    lines.append(f"\n{bar} {pct}%\n", style="white")
    lines.append(f"{sprint_done}/{sprint_task_count} tasks done", style="dim")

    if sprint.ends_at:
        lines.append(f"\nEnds {sprint.ends_at.strftime('%Y-%m-%d')}", style="yellow dim")

    return Panel(lines, title="[nexus.title]Active Sprint[/nexus.title]", border_style="cyan", width=34)


def _stats_panel(total: int, done: int, in_prog: int, blocked: int, hours: float) -> Panel:
    pct = int(done / total * 100) if total else 0
    bar_w = 20
    filled = int(pct / 100 * bar_w)
    bar = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_w - filled) + "[/dim]"

    lines = Text()
    lines.append(f"{bar} {pct}%\n\n", style="white")
    lines.append("  Total     ", style="dim")
    lines.append(f"{total}\n", style="bold white")
    lines.append("  Done      ", style="dim")
    lines.append(f"{done}\n", style="bold green")
    lines.append("  In Prog   ", style="dim")
    lines.append(f"{in_prog}\n", style="bold yellow")
    lines.append("  Blocked   ", style="dim")
    lines.append(f"{blocked}\n", style="bold red")
    lines.append("  Hours     ", style="dim")
    lines.append(f"{hours:.1f}h", style="bold cyan")

    return Panel(lines, title="[nexus.title]Overview[/nexus.title]", border_style="bright_black", width=34)


@click.command("dashboard")
@click.argument("project_id", type=int)
@click.pass_obj
def dashboard_cmd(db: Database, project_id: int):
    """Render a kanban dashboard for a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    tasks = db.list_tasks(project_id=project_id)
    sprints = db.list_sprints(project_id)

    # Find the most recent active sprint
    active_sprint: Optional[Sprint] = None
    for s in reversed(sprints):
        if s.status == Status.IN_PROGRESS:
            active_sprint = s
            break

    # Partition tasks
    todo = [t for t in tasks if t.status == Status.TODO]
    in_prog = [t for t in tasks if t.status == Status.IN_PROGRESS]
    done = [t for t in tasks if t.status == Status.DONE]
    blocked = [t for t in tasks if t.status == Status.BLOCKED]
    hours = sum(t.actual_hours or 0 for t in tasks)

    # Sprint task counts
    sprint_tasks = (
        [t for t in tasks if t.sprint_id == active_sprint.id] if active_sprint else []
    )
    sprint_done = sum(1 for t in sprint_tasks if t.status == Status.DONE)

    # ── Header ────────────────────────────────────────────────────────────
    title = Text()
    title.append("NEXUS", style="bold cyan")
    title.append(" · ", style="dim")
    title.append(project.name, style="bold white")
    if project.description:
        title.append(f" — {project.description}", style="dim")

    console.print(Panel(Align(title, align="center"), border_style="cyan", padding=(0, 2)))

    # ── Top row: overview + sprint ─────────────────────────────────────────
    top_row = Columns(
        [
            _stats_panel(len(tasks), len(done), len(in_prog), len(blocked), hours),
            _sprint_panel(active_sprint, len(sprint_tasks), sprint_done),
        ],
        padding=(0, 1),
        equal=False,
    )
    console.print(top_row)

    # ── Kanban board ──────────────────────────────────────────────────────
    console.print(Rule("[dim]Kanban[/dim]", style="bright_black"))

    board = Columns(
        [
            _kanban_column("TODO", todo, STATUS_STYLES[Status.TODO], STATUS_ICONS[Status.TODO]),
            _kanban_column("IN PROGRESS", in_prog, STATUS_STYLES[Status.IN_PROGRESS], STATUS_ICONS[Status.IN_PROGRESS]),
            _kanban_column("DONE", done, STATUS_STYLES[Status.DONE], STATUS_ICONS[Status.DONE]),
            _kanban_column("BLOCKED", blocked, STATUS_STYLES[Status.BLOCKED], STATUS_ICONS[Status.BLOCKED]),
        ],
        padding=(0, 1),
        equal=False,
    )
    console.print(board)
    console.print()
