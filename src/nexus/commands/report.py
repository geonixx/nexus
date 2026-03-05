"""Report generation commands."""

from __future__ import annotations

from datetime import datetime, timezone

import click
from rich.markdown import Markdown

from ..db import Database
from ..models import Status
from ..ui import console, print_error, print_stats


@click.group("report")
def report_cmd():
    """Generate reports."""


@report_cmd.command("standup")
@click.argument("project_id", type=int)
@click.option("--ai", "use_ai", is_flag=True, default=False, help="Stream an AI-written Yesterday/Today/Blockers brief.")
@click.pass_obj
def report_standup(db: Database, project_id: int, use_ai: bool):
    """Print a daily standup report for a project.

    Without --ai: renders a structured task list snapshot.
    With --ai: streams an AI-written standup based on yesterday's activity.
    """
    from datetime import timedelta

    from rich.live import Live
    from rich.rule import Rule

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    tasks = db.list_tasks(project_id=project_id)
    done_all = [t for t in tasks if t.status == Status.DONE]
    in_prog = [t for t in tasks if t.status == Status.IN_PROGRESS]
    blocked = [t for t in tasks if t.status == Status.BLOCKED]
    todo = [t for t in tasks if t.status == Status.TODO]

    today = datetime.now(timezone.utc).strftime("%A, %d %B %Y")

    # ── Static markdown snapshot (always shown) ───────────────────────────
    md_lines = [
        f"# Standup — {project.name}",
        f"**{today}**",
        "",
        "## ✓ Done",
    ]
    for t in done_all:
        md_lines.append(f"- #{t.id} {t.title}")
    if not done_all:
        md_lines.append("- *(nothing yet)*")

    md_lines += ["", "## ● In Progress"]
    for t in in_prog:
        est = f" ({t.estimate_hours}h est)" if t.estimate_hours else ""
        md_lines.append(f"- #{t.id} {t.title}{est}")
    if not in_prog:
        md_lines.append("- *(nothing)*")

    md_lines += ["", "## ✗ Blocked"]
    for t in blocked:
        md_lines.append(f"- #{t.id} {t.title}")
    if not blocked:
        md_lines.append("- *(nothing)*")

    md_lines += ["", "## ○ Up Next"]
    for t in todo[:5]:
        md_lines.append(f"- #{t.id} {t.title}")
    if not todo:
        md_lines.append("- *(no pending tasks)*")
    elif len(todo) > 5:
        md_lines.append(f"- *…and {len(todo) - 5} more*")

    console.print(Markdown("\n".join(md_lines)))

    # ── Optional AI narrative ─────────────────────────────────────────────
    if use_ai:
        from ..ai import NexusAI, standup_prompt

        ai = NexusAI()
        if not ai.available:
            print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
            raise SystemExit(1)

        now = datetime.now(timezone.utc)
        since_yesterday = now - timedelta(hours=24)

        completed_yesterday = db.tasks_completed_since(project_id, since_yesterday)
        entries_yesterday = db.time_entries_since(project_id, since_yesterday)
        yesterday_hours = sum(e.hours for e, _ in entries_yesterday)

        # Top-N todo tasks by priority order (mirrors task next logic)
        _PRIO_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        top_next = sorted(todo, key=lambda t: _PRIO_ORDER.get(t.priority.value, 9))[:5]

        console.print(Rule("[nexus.title]AI · Standup Brief[/nexus.title]", style="cyan"))
        console.print()

        system, user = standup_prompt(
            project_name=project.name,
            yesterday_completed=[t.title for t in completed_yesterday],
            yesterday_hours=yesterday_hours,
            in_progress=[(t.id, t.title) for t in in_prog],
            blocked=[(t.id, t.title) for t in blocked],
            top_next=[(t.id, t.title) for t in top_next],
        )

        full_text = ""
        try:
            with Live(Markdown(""), refresh_per_second=15, console=console, vertical_overflow="visible") as live:
                for chunk in ai.stream(system, user):
                    full_text += chunk
                    live.update(Markdown(full_text))
        except RuntimeError as e:
            print_error(str(e))
            raise SystemExit(1)

        console.print()


@report_cmd.command("summary")
@click.argument("project_id", type=int)
@click.pass_obj
def report_summary(db: Database, project_id: int):
    """Print a full project summary with stats."""
    stats = db.project_stats(project_id)
    if not stats:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    print_stats(stats)

    sprints = db.list_sprints(project_id)
    if sprints:
        from ..ui import print_sprints
        print_sprints(sprints)

    tasks = db.list_tasks(project_id=project_id)
    if tasks:
        from ..ui import print_tasks
        print_tasks(tasks)


@report_cmd.command("digest")
@click.argument("project_id", type=int)
@click.pass_obj
def report_digest(db: Database, project_id: int):
    """Use Claude to write an AI project status digest."""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule

    from ..ai import NexusAI, digest_prompt

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
        raise SystemExit(1)

    stats = db.project_stats(project_id)
    tasks = db.list_tasks(project_id=project_id)
    sprints = db.list_sprints(project_id)

    done_tasks = [t for t in tasks if t.status == Status.DONE]
    in_prog_tasks = [t for t in tasks if t.status == Status.IN_PROGRESS]
    blocked_tasks = [t for t in tasks if t.status == Status.BLOCKED]

    # Find active sprint
    active_sprint = next(
        (s for s in reversed(sprints) if s.status == Status.IN_PROGRESS), None
    )

    console.print(Rule(f"[nexus.title]AI · Digest for '{project.name}'[/nexus.title]", style="cyan"))
    console.print()

    system, user = digest_prompt(
        project_name=project.name,
        project_desc=project.description,
        total=stats.total_tasks,
        done=stats.done_tasks,
        in_prog=stats.in_progress_tasks,
        blocked=stats.blocked_tasks,
        hours=stats.total_hours_logged,
        done_titles=[t.title for t in done_tasks],
        in_prog_titles=[t.title for t in in_prog_tasks],
        sprint_name=active_sprint.name if active_sprint else None,
        sprint_goal=active_sprint.goal if active_sprint else None,
    )

    full_text = ""
    try:
        with Live(Markdown(""), refresh_per_second=15, console=console, vertical_overflow="visible") as live:
            for chunk in ai.stream(system, user):
                full_text += chunk
                live.update(Markdown(full_text))
    except RuntimeError as e:
        print_error(str(e))
        raise SystemExit(1)

    console.print()


@report_cmd.command("week")
@click.argument("project_id", type=int)
@click.option("--ai", "use_ai", is_flag=True, default=False, help="Append an AI-written narrative.")
@click.option("--days", type=int, default=7, help="Number of days to look back (default: 7).")
@click.pass_obj
def report_week(db: Database, project_id: int, use_ai: bool, days: int):
    """Show activity over the last N days — hours logged, tasks completed."""
    from datetime import timedelta

    from rich import box
    from rich.rule import Rule
    from rich.table import Table

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    entries = db.time_entries_since(project_id, since)
    completed = db.tasks_completed_since(project_id, since)

    # All tasks added since (created_at >= since)
    all_tasks = db.list_tasks(project_id=project_id)
    added = [t for t in all_tasks if t.created_at and t.created_at >= since]
    in_progress = [t for t in all_tasks if t.status == Status.IN_PROGRESS]

    # --- Period label ---
    start_label = since.strftime("%b %-d")
    end_label = now.strftime("%-d, %Y")
    period = f"{start_label}–{end_label}"

    console.print(Rule(
        f"[nexus.title]Week Report · {project.name}[/nexus.title]",
        style="cyan",
    ))
    console.print(f"  [dim]{period}  ·  last {days} days[/dim]\n")

    # --- Hours by day chart ---
    hours_by_day: dict[str, float] = {}
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).strftime("%a %-d")
        hours_by_day[day] = 0.0

    for entry, _title in entries:
        if entry.logged_at:
            day_key = entry.logged_at.strftime("%a %-d")
            if day_key in hours_by_day:
                hours_by_day[day_key] += entry.hours

    total_hours = sum(hours_by_day.values())
    max_h = max(hours_by_day.values()) if hours_by_day else 0

    # Unicode bar chart (8 rows of blocks)
    BAR_CHARS = " ▁▂▃▄▅▆▇█"
    chart_lines = []
    for day, h in hours_by_day.items():
        if max_h > 0:
            idx = min(8, round(h / max_h * 8))
        else:
            idx = 0
        bar = BAR_CHARS[idx]
        chart_lines.append((day, h, bar))

    # Print the chart
    bar_row = "  "
    label_row = "  "
    for day, h, bar in chart_lines:
        bar_row += f"[{'cyan' if h > 0 else 'dim'}]{bar}[/]  "
        label_row += f"[dim]{day[:2]}[/]  "

    console.print(f"  [bold]Hours logged:[/bold] [cyan]{total_hours:.1f}h[/cyan]")
    console.print(bar_row)
    console.print(label_row)
    console.print()

    # --- Tasks completed ---
    console.print(f"  [bold]Completed ({len(completed)}):[/bold]")
    if completed:
        for t in completed:
            console.print(f"    [nexus.success]✓[/nexus.success] [dim]#{t.id}[/dim]  {t.title}")
    else:
        console.print("    [dim](none)[/dim]")

    console.print()
    console.print(f"  [bold]In progress ({len(in_progress)}):[/bold]")
    if in_progress:
        for t in in_progress:
            est = f"  [dim]{t.estimate_hours}h est[/dim]" if t.estimate_hours else ""
            console.print(f"    [yellow]●[/yellow] [dim]#{t.id}[/dim]  {t.title}{est}")
    else:
        console.print("    [dim](none)[/dim]")

    console.print()
    console.print(f"  [dim]New tasks added: {len(added)}[/dim]\n")

    # --- Optional AI narrative ---
    if use_ai:
        from rich.live import Live

        from ..ai import NexusAI, weekly_report_prompt

        ai = NexusAI()
        if not ai.available:
            print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
            raise SystemExit(1)

        console.print(Rule("[nexus.title]AI narrative[/nexus.title]", style="cyan"))
        console.print()

        hbd_list = [(day, h) for day, h in hours_by_day.items()]
        system, user = weekly_report_prompt(
            project_name=project.name,
            period_label=period,
            hours_by_day=hbd_list,
            total_hours=total_hours,
            tasks_completed=[t.title for t in completed],
            tasks_in_progress=[t.title for t in in_progress],
            tasks_added=len(added),
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
