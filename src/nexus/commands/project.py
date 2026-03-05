"""Project management commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import click
from rich import box
from rich.rule import Rule
from rich.text import Text

from ..db import Database
from ..models import Status
from ..ui import console, print_error, print_info, print_projects, print_stats, print_success, print_tasks


@click.group("project")
def project_cmd():
    """Manage projects."""


@project_cmd.command("new")
@click.argument("name")
@click.option("-d", "--description", default="", help="Project description.")
@click.pass_obj
def project_new(db: Database, name: str, description: str):
    """Create a new project."""
    existing = db.get_project_by_name(name)
    if existing:
        print_error(f"Project '{name}' already exists (id={existing.id}).")
        raise SystemExit(1)
    p = db.create_project(name, description)
    print_success(f"Created project [bold]{p.name}[/bold] (id={p.id})")


@project_cmd.command("list")
@click.option("--status", type=click.Choice([s.value for s in Status]), default=None)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_obj
def project_list(db: Database, status: str | None, as_json: bool):
    """List all projects."""
    s = Status(status) if status else None
    projects = db.list_projects(status=s)
    if as_json:
        click.echo(json.dumps([p.model_dump(mode="json") for p in projects], indent=2))
        return
    print_projects(projects)


@project_cmd.command("search")
@click.argument("query")
@click.pass_obj
def project_search(db: Database, query: str):
    """Search projects and tasks by name or description."""
    results = db.search(query)
    projects = results["projects"]
    tasks = results["tasks"]

    if not projects and not tasks:
        console.print(f"[dim]No results for '[white]{query}[/white]'[/dim]")
        return

    console.print(Rule(f"[dim]Search: [white]{query}[/white][/dim]", style="bright_black"))

    if projects:
        console.print(f"\n  [nexus.title]Projects[/nexus.title] ({len(projects)})")
        print_projects(projects)

    if tasks:
        console.print(f"\n  [nexus.title]Tasks[/nexus.title] ({len(tasks)})")
        print_tasks(tasks)


@project_cmd.command("show")
@click.argument("project_id", type=int)
@click.pass_obj
def project_show(db: Database, project_id: int):
    """Show project stats and details."""
    stats = db.project_stats(project_id)
    if not stats:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    print_stats(stats)


@project_cmd.command("update")
@click.argument("project_id", type=int)
@click.option("-n", "--name", default=None)
@click.option("-d", "--description", default=None)
@click.option(
    "-s",
    "--status",
    type=click.Choice([s.value for s in Status]),
    default=None,
)
@click.pass_obj
def project_update(db: Database, project_id: int, name: str | None, description: str | None, status: str | None):
    """Update a project's fields."""
    updates = {}
    if name:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if status:
        updates["status"] = Status(status)
    if not updates:
        print_info("Nothing to update.")
        return
    p = db.update_project(project_id, **updates)
    if not p:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    print_success(f"Updated project [bold]{p.name}[/bold]")


@project_cmd.command("delete")
@click.argument("project_id", type=int)
@click.confirmation_option(prompt="Delete this project and all its data?")
@click.pass_obj
def project_delete(db: Database, project_id: int):
    """Delete a project."""
    p = db.get_project(project_id)
    if not p:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    db.delete_project(project_id)
    print_success(f"Deleted project '{p.name}'")


# ── Health scoring ─────────────────────────────────────────────────────────────

def _compute_health(db: Database, project_id: int) -> dict:
    """Compute a 0–100 health score across 5 metrics.

    Returns a dict with keys: score, grade, metrics (list), context (dict).
    Returns {"score": 0, "grade": "?", "metrics": [], "context": {}} for empty projects.
    """
    from datetime import timedelta
    from ..models import Priority, Status

    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_3d = now - timedelta(days=3)

    tasks = db.list_tasks(project_id=project_id)
    total = len(tasks)
    if total == 0:
        return {"score": 0, "grade": "?", "metrics": [], "context": {}}

    done = [t for t in tasks if t.status == Status.DONE]
    in_prog = [t for t in tasks if t.status == Status.IN_PROGRESS]
    blocked = [t for t in tasks if t.status == Status.BLOCKED]
    todo = [t for t in tasks if t.status == Status.TODO]
    cancelled = [t for t in tasks if t.status == Status.CANCELLED]
    active = in_prog + blocked + todo

    # Metric 1: Completion rate (25 pts)
    non_cancelled = total - len(cancelled)
    completion_pct = len(done) / non_cancelled if non_cancelled > 0 else 0.0
    m1 = round(completion_pct * 25)

    # Metric 2: Blocked health — lower blocked ratio → higher score (20 pts)
    blocked_ratio = len(blocked) / len(active) if active else 0.0
    m2 = round((1.0 - blocked_ratio) * 20)

    # Metric 3: Momentum — in-progress tasks with recent activity (20 pts)
    stale = db.get_stale_tasks(project_id, since_3d) if in_prog else []
    stale_ratio = len(stale) / len(in_prog) if in_prog else 0.0
    m3 = round((1.0 - stale_ratio) * 20)

    # Metric 4: Estimate coverage of actionable tasks (15 pts)
    backlog = todo + in_prog
    estimated = [t for t in backlog if t.estimate_hours is not None]
    estimate_pct = len(estimated) / len(backlog) if backlog else 1.0
    m4 = round(estimate_pct * 15)

    # Metric 5: Activity this week — 20h = full 20 pts
    entries = db.time_entries_since(project_id, since_7d)
    hours_week = sum(e.hours for e, _ in entries)
    m5 = min(20, round(hours_week))

    score = m1 + m2 + m3 + m4 + m5
    grade = (
        "A" if score >= 90 else
        "B" if score >= 75 else
        "C" if score >= 60 else
        "D" if score >= 45 else
        "F"
    )

    return {
        "score": score,
        "grade": grade,
        "metrics": [
            {
                "name": "Completion Rate",
                "score": m1, "max": 25,
                "detail": (
                    f"{len(done)}/{non_cancelled} tasks complete "
                    f"({completion_pct * 100:.0f}%)"
                ),
            },
            {
                "name": "Blocked Health",
                "score": m2, "max": 20,
                "detail": (
                    f"{len(blocked)} blocked ({blocked_ratio * 100:.0f}% of active)"
                ),
            },
            {
                "name": "Momentum",
                "score": m3, "max": 20,
                "detail": (
                    f"{len(stale)} in-progress task(s) with no activity in 3+ days"
                ),
            },
            {
                "name": "Estimate Coverage",
                "score": m4, "max": 15,
                "detail": (
                    f"{len(estimated)}/{len(backlog)} actionable tasks estimated "
                    f"({estimate_pct * 100:.0f}%)"
                ),
            },
            {
                "name": "Activity (7d)",
                "score": m5, "max": 20,
                "detail": f"{hours_week:.1f}h logged this week",
            },
        ],
        "context": {
            "done": len(done),
            "in_progress": len(in_prog),
            "blocked": len(blocked),
            "todo": len(todo),
            "stale": len(stale),
            "hours_week": hours_week,
        },
    }


@project_cmd.command("health")
@click.argument("project_id", type=int)
@click.option(
    "--ai", "use_ai", is_flag=True, default=False,
    help="Stream an AI diagnosis with concrete recommendations.",
)
@click.pass_obj
def project_health(db: Database, project_id: int, use_ai: bool):
    """Show an automated health score for a project (A–F across 5 metrics).

    Metrics: completion rate, blocked ratio, in-progress momentum,
    estimate coverage, and recent activity.
    """
    from rich.table import Table

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    health = _compute_health(db, project_id)

    if not health["metrics"]:
        print_info(f"Project '{project.name}' has no tasks yet — nothing to score.")
        return

    score = health["score"]
    grade = health["grade"]

    # Grade colour
    grade_style = (
        "bold green" if grade == "A" else
        "bold cyan" if grade == "B" else
        "bold yellow" if grade == "C" else
        "bold red" if grade in ("D", "F") else
        "dim"
    )

    console.print(Rule(
        f"[nexus.title]Project Health · {project.name}[/nexus.title]",
        style="cyan",
    ))
    console.print()
    console.print(
        f"  Score: [{grade_style}]{score}/100   Grade: {grade}[/{grade_style}]"
    )
    console.print()

    # Metric table
    table = Table(box=box.SIMPLE, show_header=False, expand=False, padding=(0, 1))
    table.add_column("Metric", style="dim", width=20)
    table.add_column("Bar", width=18)
    table.add_column("Pts", justify="right", width=7)
    table.add_column("Detail")

    BAR_FULL = "█"
    BAR_EMPTY = "░"

    for m in health["metrics"]:
        pct = m["score"] / m["max"] if m["max"] else 0
        filled = round(pct * 16)
        bar = BAR_FULL * filled + BAR_EMPTY * (16 - filled)
        if pct >= 0.8:
            bar_style = "green"
        elif pct >= 0.5:
            bar_style = "yellow"
        else:
            bar_style = "red"

        table.add_row(
            m["name"],
            f"[{bar_style}]{bar}[/{bar_style}]",
            f"{m['score']}/{m['max']}",
            f"[dim]{m['detail']}[/dim]",
        )

    console.print(table)

    # Optional AI diagnosis
    if use_ai:
        from rich.live import Live
        from rich.markdown import Markdown

        from ..ai import NexusAI, health_diagnosis_prompt

        ai = NexusAI()
        if not ai.available:
            print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
            raise SystemExit(1)

        console.print(Rule("[nexus.title]AI · Diagnosis[/nexus.title]", style="cyan"))
        console.print()

        system, user = health_diagnosis_prompt(
            project_name=project.name,
            grade=grade,
            score=score,
            metrics=health["metrics"],
            context=health["context"],
        )

        full_text = ""
        try:
            with Live(
                Markdown(""),
                refresh_per_second=15,
                console=console,
                vertical_overflow="visible",
            ) as live:
                for chunk in ai.stream(system, user):
                    full_text += chunk
                    live.update(Markdown(full_text))
        except RuntimeError as e:
            print_error(str(e))
            raise SystemExit(1)

        console.print()
