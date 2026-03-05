"""Rich terminal UI components for Nexus."""

from __future__ import annotations

from typing import List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .models import Priority, Project, ProjectStats, Sprint, Status, Task

NEXUS_THEME = Theme(
    {
        "nexus.title": "bold cyan",
        "nexus.dim": "dim white",
        "nexus.success": "bold green",
        "nexus.warn": "bold yellow",
        "nexus.error": "bold red",
        "nexus.info": "bold blue",
        "status.todo": "white",
        "status.in_progress": "bold yellow",
        "status.done": "bold green",
        "status.blocked": "bold red",
        "status.cancelled": "dim strike white",
        "priority.low": "dim white",
        "priority.medium": "white",
        "priority.high": "bold yellow",
        "priority.critical": "bold red",
    }
)

console = Console(theme=NEXUS_THEME)

STATUS_ICONS = {
    Status.TODO: "○",
    Status.IN_PROGRESS: "●",
    Status.DONE: "✓",
    Status.BLOCKED: "✗",
    Status.CANCELLED: "⊘",
}

PRIORITY_ICONS = {
    Priority.LOW: "▽",
    Priority.MEDIUM: "◇",
    Priority.HIGH: "▲",
    Priority.CRITICAL: "⬆",
}

STATUS_STYLES = {
    Status.TODO: "status.todo",
    Status.IN_PROGRESS: "status.in_progress",
    Status.DONE: "status.done",
    Status.BLOCKED: "status.blocked",
    Status.CANCELLED: "status.cancelled",
}

PRIORITY_STYLES = {
    Priority.LOW: "priority.low",
    Priority.MEDIUM: "priority.medium",
    Priority.HIGH: "priority.high",
    Priority.CRITICAL: "priority.critical",
}


def status_text(status: Status) -> Text:
    icon = STATUS_ICONS.get(status, "?")
    style = STATUS_STYLES.get(status, "white")
    return Text(f"{icon} {status.value}", style=style)


def priority_text(priority: Priority) -> Text:
    icon = PRIORITY_ICONS.get(priority, "")
    style = PRIORITY_STYLES.get(priority, "white")
    return Text(f"{icon} {priority.value}", style=style)


def print_projects(projects: List[Project]) -> None:
    if not projects:
        console.print("[nexus.dim]No projects found.[/]")
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="nexus.title",
        border_style="bright_black",
        expand=False,
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Project", min_width=20)
    table.add_column("Status", width=14)
    table.add_column("Description", max_width=40, overflow="ellipsis")
    table.add_column("Updated", width=12, style="nexus.dim")

    for p in projects:
        table.add_row(
            str(p.id),
            f"[bold]{p.name}[/]",
            status_text(p.status),
            p.description or "—",
            p.updated_at.strftime("%Y-%m-%d"),
        )

    console.print(table)


def print_tasks(tasks: List[Task], title: Optional[str] = None) -> None:
    if not tasks:
        console.print("[nexus.dim]No tasks found.[/]")
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="nexus.title",
        border_style="bright_black",
        expand=False,
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Title", min_width=24)
    table.add_column("Priority", width=14)
    table.add_column("Status", width=14)
    table.add_column("Est.", width=5, justify="right", style="nexus.dim")
    table.add_column("Act.", width=5, justify="right", style="nexus.dim")

    for t in tasks:
        est = f"{t.estimate_hours:.1f}h" if t.estimate_hours else "—"
        act = f"{t.actual_hours:.1f}h" if t.actual_hours else "—"
        table.add_row(
            str(t.id),
            t.title,
            priority_text(t.priority),
            status_text(t.status),
            est,
            act,
        )

    console.print(table)


def print_sprints(sprints: List[Sprint]) -> None:
    if not sprints:
        console.print("[nexus.dim]No sprints found.[/]")
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="nexus.title",
        border_style="bright_black",
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Sprint", min_width=16)
    table.add_column("Status", width=14)
    table.add_column("Goal", max_width=40, overflow="ellipsis")
    table.add_column("Start", width=12, style="nexus.dim")
    table.add_column("End", width=12, style="nexus.dim")

    for s in sprints:
        table.add_row(
            str(s.id),
            f"[bold]{s.name}[/]",
            status_text(s.status),
            s.goal or "—",
            s.starts_at.strftime("%Y-%m-%d") if s.starts_at else "—",
            s.ends_at.strftime("%Y-%m-%d") if s.ends_at else "—",
        )

    console.print(table)


def print_stats(stats: ProjectStats) -> None:
    p = stats.project

    # Header panel
    header = Text()
    header.append(f" {p.name} ", style="bold cyan")
    header.append(f"  {STATUS_ICONS[p.status]} {p.status.value}", style=STATUS_STYLES[p.status])
    if p.description:
        header.append(f"\n {p.description}", style="dim")

    console.print(Panel(header, border_style="cyan", expand=False))

    # Stats grid
    total = stats.total_tasks
    done = stats.done_tasks

    pct = stats.completion_pct
    bar_filled = int(pct / 5)  # 20-char bar
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    console.print(
        f"  Progress  [cyan]{bar}[/] [bold]{pct:.0f}%[/]  "
        f"([green]{done}[/]/[white]{total}[/] tasks)"
    )
    console.print(
        f"  In Progress: [yellow]{stats.in_progress_tasks}[/]   "
        f"Blocked: [red]{stats.blocked_tasks}[/]   "
        f"Hours logged: [cyan]{stats.total_hours_logged:.1f}h[/]"
    )
    console.print()


def print_success(msg: str) -> None:
    console.print(f"[nexus.success]✓[/] {msg}")


def print_error(msg: str) -> None:
    console.print(f"[nexus.error]✗[/] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[nexus.info]→[/] {msg}")


def nexus_banner() -> None:
    console.print(
        Panel(
            Text("NEXUS", style="bold cyan", justify="center"),
            subtitle="[dim]local-first project intelligence[/]",
            border_style="cyan",
            expand=False,
        )
    )
