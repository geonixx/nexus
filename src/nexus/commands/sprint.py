"""Sprint management commands."""

from __future__ import annotations

from datetime import datetime, timezone

import click
from rich import box
from rich.table import Table

from ..db import Database
from ..models import Status
from ..ui import console, print_error, print_info, print_sprints, print_success, print_tasks


@click.group("sprint")
def sprint_cmd():
    """Manage sprints."""


@sprint_cmd.command("new")
@click.argument("project_id", type=int)
@click.argument("name")
@click.option("-g", "--goal", default="", help="Sprint goal.")
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.pass_obj
def sprint_new(
    db: Database,
    project_id: int,
    name: str,
    goal: str,
    start: str | None,
    end: str | None,
):
    """Create a sprint for a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    starts_at = datetime.strptime(start, "%Y-%m-%d") if start else None
    ends_at = datetime.strptime(end, "%Y-%m-%d") if end else None
    s = db.create_sprint(project_id, name, goal, starts_at, ends_at)
    print_success(f"Created sprint [bold]{s.name}[/bold] (id={s.id}) for '{project.name}'")


@sprint_cmd.command("list")
@click.argument("project_id", type=int)
@click.pass_obj
def sprint_list(db: Database, project_id: int):
    """List sprints for a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    sprints = db.list_sprints(project_id)
    print_sprints(sprints)


@sprint_cmd.command("tasks")
@click.argument("sprint_id", type=int)
@click.pass_obj
def sprint_tasks(db: Database, sprint_id: int):
    """Show tasks assigned to a sprint."""
    sprint = db.get_sprint(sprint_id)
    if not sprint:
        print_error(f"Sprint id={sprint_id} not found.")
        raise SystemExit(1)
    tasks = db.list_tasks(sprint_id=sprint_id)
    print_tasks(tasks, title=f"Sprint: {sprint.name}")


@sprint_cmd.command("start")
@click.argument("sprint_id", type=int)
@click.pass_obj
def sprint_start(db: Database, sprint_id: int):
    """Mark a sprint as in-progress."""
    sprint = db.get_sprint(sprint_id)
    if not sprint:
        print_error(f"Sprint id={sprint_id} not found.")
        raise SystemExit(1)
    db.update_sprint(sprint_id, status=Status.IN_PROGRESS, starts_at=datetime.now(timezone.utc))
    print_success(f"Sprint '{sprint.name}' started.")


@sprint_cmd.command("close")
@click.argument("sprint_id", type=int)
@click.pass_obj
def sprint_close(db: Database, sprint_id: int):
    """Mark a sprint as done."""
    sprint = db.get_sprint(sprint_id)
    if not sprint:
        print_error(f"Sprint id={sprint_id} not found.")
        raise SystemExit(1)
    db.update_sprint(sprint_id, status=Status.DONE, ends_at=datetime.now(timezone.utc))
    print_success(f"Sprint '{sprint.name}' closed.")


@sprint_cmd.command("velocity")
@click.argument("project_id", type=int)
@click.pass_obj
def sprint_velocity(db: Database, project_id: int):
    """Show sprint velocity history for a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    sprints = db.list_sprints(project_id)
    if not sprints:
        print_info("No sprints found for this project.")
        return

    table = Table(
        title=f"Sprint Velocity — {project.name}",
        box=box.ROUNDED,
        show_header=True,
        header_style="dim",
    )
    table.add_column("Sprint", style="bold", min_width=10, no_wrap=True)
    table.add_column("Status", width=11)
    table.add_column("Done/Tot", justify="center", width=8)
    table.add_column("Progress", width=14)
    table.add_column("Est h", justify="right", width=6)
    table.add_column("Act h", justify="right", width=6)

    STATUS_COLORS = {
        Status.DONE: "green",
        Status.IN_PROGRESS: "yellow",
        Status.TODO: "dim",
    }

    for sprint in sprints:
        tasks = db.list_tasks(project_id=project_id, sprint_id=sprint.id)
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == Status.DONE)
        est_h = sum(t.estimate_hours or 0.0 for t in tasks)
        act_h = sum(t.actual_hours or 0.0 for t in tasks)

        color = STATUS_COLORS.get(sprint.status, "dim")
        status_str = f"[{color}]{sprint.status.value}[/{color}]"

        # Progress bar: 8-block sparkline
        if total:
            filled = round(done / total * 8)
            bar = "█" * filled + "░" * (8 - filled)
            pct = f"{done / total * 100:.0f}%"
            progress = f"{bar} {pct}"
        else:
            progress = "—"

        table.add_row(
            sprint.name,
            status_str,
            f"{done}/{total}" if total else "0/0",
            progress,
            f"{est_h:.1f}" if est_h else "—",
            f"{act_h:.1f}" if act_h else "—",
        )

    console.print(table)

    # Summary: average velocity across completed sprints
    completed = [s for s in sprints if s.status == Status.DONE]
    if len(completed) >= 2:
        velocities = []
        for sprint in completed:
            tasks = db.list_tasks(project_id=project_id, sprint_id=sprint.id)
            velocities.append(sum(t.actual_hours or 0.0 for t in tasks))
        avg = sum(velocities) / len(velocities)
        console.print(
            f"  [dim]Average velocity ({len(completed)} completed sprints):[/dim] "
            f"[bold]{avg:.1f}h[/bold] / sprint"
        )


@sprint_cmd.command("plan")
@click.argument("project_id", type=int)
@click.option(
    "--capacity",
    type=float,
    default=None,
    help="Sprint capacity in hours (default: average past velocity).",
)
@click.pass_obj
def sprint_plan(db: Database, project_id: int, capacity: float | None):
    """Use AI to suggest which backlog tasks to pull into the next sprint."""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.rule import Rule

    from ..ai import NexusAI, sprint_plan_prompt

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
        raise SystemExit(1)

    # Gather backlog (todo tasks with no sprint)
    all_tasks = db.list_tasks(project_id=project_id)
    backlog = [t for t in all_tasks if t.status == Status.TODO and not t.sprint_id]
    in_progress = [t for t in all_tasks if t.status == Status.IN_PROGRESS]

    if not backlog:
        print_info("No backlog tasks found. Add tasks without a sprint first.")
        return

    # Compute average velocity from completed sprints
    sprints = db.list_sprints(project_id)
    completed_sprints = [s for s in sprints if s.status == Status.DONE]
    avg_velocity = None
    if completed_sprints:
        velocities = []
        for sprint in completed_sprints:
            tasks = db.list_tasks(project_id=project_id, sprint_id=sprint.id)
            velocities.append(sum(t.actual_hours or 0.0 for t in tasks))
        avg_velocity = sum(velocities) / len(velocities)

    sprint_capacity = capacity or avg_velocity

    console.print(Rule(
        f"[nexus.title]AI · Sprint Plan for '{project.name}'[/nexus.title]",
        style="cyan",
    ))
    if sprint_capacity:
        console.print(f"  [dim]Capacity:[/dim] {sprint_capacity:.1f}h")
    console.print()

    system, user = sprint_plan_prompt(
        project_name=project.name,
        backlog=[(t.id, t.title, t.priority.value, t.estimate_hours) for t in backlog],
        in_progress=[(t.id, t.title) for t in in_progress],
        capacity=sprint_capacity,
        past_velocity=avg_velocity,
    )

    try:
        with Live(Markdown(""), refresh_per_second=15, console=console, vertical_overflow="visible") as live:
            full_text = ""
            for chunk in ai.stream(system, user):
                full_text += chunk
                live.update(Markdown(full_text))
    except RuntimeError as e:
        print_error(str(e))
        raise SystemExit(1)

    console.print()
