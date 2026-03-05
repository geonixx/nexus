"""nexus watch — background project monitoring daemon.

Polls your projects on a configurable interval, surfaces stale and
blocked tasks, and optionally triggers an autonomous AI review each
cycle.  Press Ctrl-C to stop cleanly.

Examples
--------
nexus watch 1                         # watch project 1, check every 30 min
nexus watch 1 --interval 10           # check every 10 minutes
nexus watch 1 --agent                 # also run AI agent each cycle (dry-run)
nexus watch 1 --agent --agent-yes     # AI agent with auto-approve writes
nexus watch --all                     # watch every project in the workspace
nexus watch --all --interval 60       # workspace watch, hourly
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import click
from rich.columns import Columns
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box

from ..commands.config import load_config
from ..db import Database
from ..models import Priority, Status
from ..ui import STATUS_ICONS, console, print_error, print_info

# ── Priority ordering for display ─────────────────────────────────────────────
_PRIO_ORDER = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}
_PRIO_STYLE = {
    Priority.CRITICAL: "bold red",
    Priority.HIGH: "bold yellow",
    Priority.MEDIUM: "cyan",
    Priority.LOW: "dim",
}

# ── Stale thresholds (same as nexus task stale defaults) ──────────────────────
_STALE_IN_PROGRESS_DAYS = 3
_STALE_BLOCKED_DAYS = 6
_STALE_BACKLOG_DAYS = 15


# ── CLI group ──────────────────────────────────────────────────────────────────


@click.command("watch")
@click.argument("project_id", type=int, required=False, default=None)
@click.option(
    "--all", "all_projects",
    is_flag=True,
    default=False,
    help="Watch every project in the workspace.",
)
@click.option(
    "--interval", "-i",
    type=int,
    default=30,
    show_default=True,
    metavar="MINUTES",
    help="How often to poll for changes.",
)
@click.option(
    "--agent",
    is_flag=True,
    default=False,
    help="Run autonomous AI review each cycle (dry-run by default).",
)
@click.option(
    "--agent-yes",
    is_flag=True,
    default=False,
    help="Auto-approve AI agent write actions (implies --agent).",
)
@click.option(
    "--stale-days",
    type=int,
    default=_STALE_IN_PROGRESS_DAYS,
    show_default=True,
    help="Days of inactivity before a task is considered stale.",
)
@click.pass_obj
def watch_cmd(
    db: Database,
    project_id: Optional[int],
    all_projects: bool,
    interval: int,
    agent: bool,
    agent_yes: bool,
    stale_days: int,
) -> None:
    """Monitor projects for stale work and blockers.

    Polls on a regular interval and prints a summary whenever something
    needs attention.  Run with --agent to also trigger an AI scrum-master
    review each cycle.

    Press Ctrl-C to stop.
    """
    # ── Resolve project list ──────────────────────────────────────────────────
    if all_projects:
        projects = db.list_projects()
        if not projects:
            print_error("No projects found.")
            raise SystemExit(1)
    else:
        # Fall back to default_project from config if no arg given
        pid = project_id
        if pid is None:
            cfg = load_config()
            pid = cfg.get("default_project")
        if pid is None:
            print_error(
                "No project specified.  Pass a project_id, use --all, "
                "or set a default with: nexus config set default_project <id>"
            )
            raise SystemExit(1)
        project = db.get_project(pid)
        if not project:
            print_error(f"Project #{pid} not found.")
            raise SystemExit(1)
        projects = [project]

    if agent_yes:
        agent = True

    # ── Header ────────────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[nexus.title]nexus watch[/nexus.title]", style="cyan"))
    scope = "all projects" if all_projects else f"project #{projects[0].id} · {projects[0].name}"
    console.print(
        f"  Watching [bold]{scope}[/bold] · "
        f"interval [bold]{interval}m[/bold]"
        + (" · AI agent enabled" if agent else "")
    )
    console.print("  Press [bold]Ctrl-C[/bold] to stop.\n")

    # ── Graceful Ctrl-C ───────────────────────────────────────────────────────
    _running = True

    def _stop(sig, frame):  # noqa: ANN001
        nonlocal _running
        _running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    cycle = 0
    while _running:
        cycle += 1
        now = datetime.now(timezone.utc)

        console.print(
            Rule(
                f"[dim]Cycle {cycle} · {now.strftime('%H:%M:%S')}[/dim]",
                style="dim",
            )
        )

        total_issues = 0
        for project in projects:
            issues = _check_project(db, project, stale_days, now)
            total_issues += issues

        if total_issues == 0:
            console.print("  [green]✓[/green]  Everything looks healthy — no issues detected.\n")
        else:
            console.print(
                f"  [yellow]⚠[/yellow]  {total_issues} issue(s) found across "
                f"{len(projects)} project(s).\n"
            )

        # ── Optional AI agent pass ────────────────────────────────────────────
        if agent and _running:
            _run_agent_pass(db, projects, agent_yes)

        # ── Sleep in 1-second ticks so Ctrl-C feels instant ──────────────────
        next_check = now + timedelta(minutes=interval)
        console.print(
            f"  [dim]Next check at {next_check.strftime('%H:%M:%S')} "
            f"(in {interval} min)[/dim]\n"
        )

        deadline = time.monotonic() + interval * 60
        while _running and time.monotonic() < deadline:
            time.sleep(1)

    console.print()
    console.print(Rule("[dim]nexus watch stopped[/dim]", style="dim"))
    console.print()


# ── Per-project health check ──────────────────────────────────────────────────


def _check_project(
    db: Database,
    project,  # Project
    stale_days: int,
    now: datetime,
) -> int:
    """Print a summary for one project and return the number of issues found."""
    tasks = db.list_tasks(project_id=project.id)
    if not tasks:
        header = f"[bold]#{project.id}[/bold] {project.name}"
        console.print(f"  [dim]—[/dim]  {header}  [dim](no tasks)[/dim]")
        return 0

    threshold = now - timedelta(days=stale_days)
    stale_threshold_blocked = now - timedelta(days=stale_days * 2)
    stale_threshold_backlog = now - timedelta(days=stale_days * 5)

    stale_ip = db.get_stale_tasks(project.id, threshold)

    # Manually compute blocked and backlog stale since get_stale_tasks uses one threshold
    blocked_stale = [
        t for t in tasks
        if t.status == Status.BLOCKED
        and t.updated_at < stale_threshold_blocked
    ]
    backlog_stale = [
        t for t in tasks
        if t.status == Status.TODO
        and t.created_at < stale_threshold_backlog
    ]

    # Ready tasks (all deps met)
    ready = db.get_ready_tasks(project.id)
    ready_todo = [t for t in ready if t.status == Status.TODO]

    # Blocked tasks
    blocked = [t for t in tasks if t.status == Status.BLOCKED]

    total_issues = len(stale_ip) + len(blocked_stale) + len(backlog_stale)

    header = f"[bold]#{project.id}[/bold] {project.name}"
    if total_issues == 0:
        console.print(f"  [green]✓[/green]  {header}")
        return 0

    console.print(f"\n  [yellow]⚠[/yellow]  {header}")

    if stale_ip:
        table = _make_table("Stale in-progress", "bold yellow")
        for t in stale_ip:
            table.add_row(
                f"#{t.id}",
                t.title[:60],
                _prio(t.priority),
                _age(t.updated_at, now),
            )
        console.print(table)

    if blocked_stale:
        table = _make_table("Long-blocked", "bold red")
        for t in blocked_stale:
            table.add_row(
                f"#{t.id}",
                t.title[:60],
                _prio(t.priority),
                _age(t.updated_at, now),
            )
        console.print(table)

    if backlog_stale:
        table = _make_table("Forgotten backlog", "dim")
        for t in backlog_stale[:5]:  # cap display
            table.add_row(
                f"#{t.id}",
                t.title[:60],
                _prio(t.priority),
                _age(t.created_at, now),
            )
        if len(backlog_stale) > 5:
            console.print(f"    [dim]… and {len(backlog_stale) - 5} more[/dim]")
        console.print(table)

    # Info: ready tasks
    if ready_todo:
        pids = ", ".join(f"#{t.id}" for t in ready_todo[:5])
        console.print(
            f"  [cyan]→[/cyan]  {len(ready_todo)} task(s) ready to start: {pids}"
        )

    # Info: currently blocked count
    if blocked:
        console.print(
            f"  [red]✗[/red]  {len(blocked)} task(s) currently blocked"
        )

    console.print()
    return total_issues


# ── Agent pass ────────────────────────────────────────────────────────────────


def _run_agent_pass(db: Database, projects, auto_yes: bool) -> None:
    """Run nexus agent run for each project in this cycle."""
    try:
        from ..ai import AGENT_TOOLS, NexusAI, agent_system_prompt
        from ..commands.agent import _handle_tool, _confirm_write
        from ..commands.project import _compute_health
        from ..models import Status as S
    except ImportError:
        print_error("AI extras not installed.  Run: pip install nexus[ai]")
        return

    ai = NexusAI()
    if not ai.available:
        console.print("  [dim]⟳  AI agent skipped (no API key)[/dim]")
        return
    if not ai.supports_tools:
        console.print("  [dim]⟳  AI agent skipped (Gemini doesn't support tool use)[/dim]")
        return

    for project in projects:
        console.print(f"  [cyan]⟳[/cyan]  Running AI agent for [bold]{project.name}[/bold]…")
        tasks = db.list_tasks(project_id=project.id)
        stats = db.project_stats(project.id)
        health = _compute_health(db, project.id)
        system = agent_system_prompt(project.name, project.description or "")

        context_lines = [
            f"Project: {project.name} (id={project.id})",
            f"Health: {health['grade']} ({health['score']}/100)",
            f"Tasks: {stats.total_tasks} total, {stats.done_tasks} done, "
            f"{stats.blocked_tasks} blocked",
        ]
        if tasks:
            context_lines.append("\nOpen tasks (sample):")
            for t in tasks[:10]:
                icon = STATUS_ICONS.get(t.status, "○")
                context_lines.append(f"  {icon} #{t.id} [{t.priority.value}] {t.title}")

        system_with_ctx = system + "\n\n" + "\n".join(context_lines)

        messages: list[dict] = [
            {"role": "user", "content": "Please review this project and take any helpful actions."}
        ]
        write_log: list[str] = []

        def tool_handler(name: str, inputs: dict) -> str:
            return _handle_tool(
                name, inputs, db, project.id, write_log,
                dry_run=(not auto_yes),
                auto_yes=auto_yes,
            )

        try:
            ai.chat_turn(messages, AGENT_TOOLS, tool_handler,
                         system=system_with_ctx, max_tokens=2048)
        except Exception as exc:
            console.print(f"  [yellow]Agent error:[/yellow] {exc}")
            return

        if write_log:
            console.print(f"  [green]✓[/green]  Agent made {len(write_log)} change(s):")
            for entry in write_log:
                console.print(f"      · {entry}")
        else:
            console.print("  [dim]  Agent: no changes needed[/dim]")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_table(title: str, title_style: str = "bold") -> Table:
    t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        title=f"[{title_style}]{title}[/{title_style}]",
        title_justify="left",
    )
    t.add_column("id", style="dim", width=6)
    t.add_column("title", max_width=60)
    t.add_column("prio", width=10)
    t.add_column("age", style="dim", width=12)
    return t


def _prio(p: Priority) -> str:
    style = _PRIO_STYLE.get(p, "")
    return f"[{style}]{p.value}[/{style}]" if style else p.value


def _age(dt: datetime, now: datetime) -> str:
    delta = now - dt
    days = delta.days
    if days == 0:
        hours = delta.seconds // 3600
        return f"{hours}h ago" if hours else "just now"
    if days == 1:
        return "1d ago"
    return f"{days}d ago"
