"""nexus agent — autonomous AI scrum master.

Connects to your Anthropic Claude instance and autonomously reviews the
project state: surfaces stale/blocked work, identifies bottlenecks, adds
follow-up notes, and optionally creates missing tasks.

Requires ANTHROPIC_API_KEY (tool use is not available with Gemini).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
from rich.rule import Rule

from ..ai import AGENT_TOOLS, NexusAI, agent_system_prompt
from ..commands.config import load_config
from ..commands.project import _compute_health
from ..db import Database
from ..models import Priority, Status
from ..ui import STATUS_ICONS, console, print_error, print_info, print_success


# ── CLI command ─────────────────────────────────────────────────────────────


@click.group("agent")
def agent_cmd():
    """Autonomous AI scrum master commands."""


@agent_cmd.command("run")
@click.argument("project_id", type=int, required=False, default=None)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Plan only — show what the agent would do without any write operations.",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    default=False,
    help="Auto-confirm all write actions (no prompts).",
)
@click.pass_obj
def agent_run(db: Database, project_id: int | None, dry_run: bool, yes: bool):
    """Run an autonomous AI review of a project.

    The agent inspects the project's health, surfaces stale and blocked work,
    identifies dependency bottlenecks, and takes corrective actions (with
    confirmation for any writes).

    Requires ANTHROPIC_API_KEY — tool use is not available with Gemini.

    \b
    Examples:
      nexus agent run 1             # review project 1 (confirms before writes)
      nexus agent run 1 --dry-run   # plan only, no changes
      nexus agent run 1 --yes       # auto-approve all actions
    """
    if project_id is None:
        cfg = load_config()
        project_id = cfg.get("default_project")
        if not project_id:
            print_error(
                "No project_id given and 'default_project' is not set in config.\n"
                "  Set one: [bold]nexus config set default_project <id>[/bold]"
            )
            raise SystemExit(1)

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY.")
        raise SystemExit(1)
    if not ai.supports_tools:
        print_error(
            "nexus agent requires ANTHROPIC_API_KEY — tool use is not available with Gemini."
        )
        raise SystemExit(1)

    mode_label = "[yellow]dry-run[/yellow]" if dry_run else "[green]live[/green]"
    console.print(Rule(
        f"[nexus.title]Agent · {project.name}[/nexus.title]  {mode_label}",
        style="cyan",
    ))
    console.print()
    if dry_run:
        console.print("  [yellow]Dry-run mode — no changes will be written.[/yellow]\n")

    # ── Build tool handler ──────────────────────────────────────────────────

    write_log: list[str] = []   # track what was actually written

    def tool_handler(name: str, inputs: dict) -> str:
        return _handle_tool(
            name, inputs,
            db=db,
            project_id=project_id,
            dry_run=dry_run,
            auto_yes=yes,
            write_log=write_log,
        )

    # ── Run agent turn ──────────────────────────────────────────────────────

    system = agent_system_prompt(project.name, project.description)
    initial_message = (
        f"Please review project #{project_id} '{project.name}' now. "
        "Start with project stats, then investigate tasks. "
        "Be thorough — check for stale work, blockers, and dependency issues."
    )
    messages = [{"role": "user", "content": initial_message}]

    console.print("  [dim]Agent is reviewing your project…[/dim]\n")

    try:
        response_text, _ = ai.chat_turn(
            messages,
            AGENT_TOOLS,
            tool_handler,
            system=system,
            max_tokens=4096,
        )
    except RuntimeError as e:
        print_error(str(e))
        raise SystemExit(1)

    # ── Show agent summary ──────────────────────────────────────────────────

    from rich.markdown import Markdown
    console.print(Rule("[nexus.title]Agent Summary[/nexus.title]", style="cyan"))
    console.print()
    console.print(Markdown(response_text))
    console.print()

    if write_log:
        console.print(f"  [dim]Actions taken ({len(write_log)}):[/dim]")
        for entry in write_log:
            console.print(f"  [green]✓[/green]  {entry}")
        console.print()
    elif not dry_run:
        console.print("  [dim]No write actions were taken.[/dim]\n")


# ── Tool handler ────────────────────────────────────────────────────────────


def _handle_tool(
    name: str,
    inputs: dict,
    *,
    db: Database,
    project_id: int,
    dry_run: bool,
    auto_yes: bool,
    write_log: list[str],
) -> str:
    """Execute a single tool call from the agent, with confirmation for writes."""

    # ── Read-only tools ─────────────────────────────────────────────────────

    if name == "list_tasks":
        status_filter = inputs.get("status")
        from ..models import Status as S
        s = S(status_filter) if status_filter else None
        tasks = db.list_tasks(project_id=project_id, status=s)
        if not tasks:
            return "No tasks found."
        lines = []
        for t in tasks:
            icon = STATUS_ICONS.get(t.status, "○")
            lines.append(
                f"#{t.id} [{t.status.value}] [{t.priority.value}] {icon} {t.title}"
                + (f" — {t.estimate_hours}h est" if t.estimate_hours else "")
            )
        _log_tool(name, inputs)
        return "\n".join(lines)

    if name == "get_task":
        task = db.get_task(inputs["task_id"])
        if not task:
            return f"Task #{inputs['task_id']} not found."
        notes = db.get_task_notes(task.id)
        deps = db.get_dependencies(task.id)
        dep_str = ", ".join(f"#{d.id} {d.title} [{d.status.value}]" for d in deps) or "none"
        lines = [
            f"#{task.id}: {task.title}",
            f"Status: {task.status.value} | Priority: {task.priority.value}",
            f"Estimate: {task.estimate_hours or '—'}h | Actual: {task.actual_hours or 0}h",
            f"Depends on: {dep_str}",
            f"Description: {task.description or '(none)'}",
        ]
        if notes:
            lines.append("Notes:")
            for n in notes[-3:]:  # last 3 notes
                day = n.created_at.strftime("%Y-%m-%d") if n.created_at else "?"
                lines.append(f"  [{day}] {n.text}")
        _log_tool(name, inputs)
        return "\n".join(lines)

    if name == "get_project_stats":
        tasks = db.list_tasks(project_id=project_id)
        total = len(tasks)
        by_status = {}
        for t in tasks:
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        done = by_status.get("done", 0)
        pct = int(done / total * 100) if total else 0
        _log_tool(name, inputs)
        return (
            f"Total tasks: {total} | Done: {done} ({pct}%) | "
            f"In-progress: {by_status.get('in_progress', 0)} | "
            f"Blocked: {by_status.get('blocked', 0)} | "
            f"Todo: {by_status.get('todo', 0)} | "
            f"Cancelled: {by_status.get('cancelled', 0)}"
        )

    if name == "get_stale_tasks":
        from datetime import timedelta
        days = inputs.get("days", 3)
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=days)
        blocked_threshold = now - timedelta(days=days * 2)
        old_todo_threshold = now - timedelta(days=days * 5)

        stale_ip = db.get_stale_tasks(project_id, stale_threshold)
        all_tasks = db.list_tasks(project_id=project_id)
        long_blocked = [
            t for t in all_tasks
            if t.status == Status.BLOCKED
            and t.updated_at and t.updated_at < blocked_threshold
        ]
        old_todo = [
            t for t in all_tasks
            if t.status == Status.TODO
            and t.created_at and t.created_at < old_todo_threshold
        ]

        parts = []
        if stale_ip:
            parts.append(f"STALE IN-PROGRESS (no activity {days}+ days):")
            for t in stale_ip:
                parts.append(f"  #{t.id} [{t.priority.value}] {t.title}")
        if long_blocked:
            parts.append(f"LONG-BLOCKED ({days*2}+ days):")
            for t in long_blocked:
                parts.append(f"  #{t.id} [{t.priority.value}] {t.title}")
        if old_todo:
            parts.append(f"OLD BACKLOG ({days*5}+ days, never started):")
            for t in old_todo[:10]:
                parts.append(f"  #{t.id} [{t.priority.value}] {t.title}")
        _log_tool(name, inputs)
        return "\n".join(parts) if parts else f"No stale tasks found (threshold: {days} days)."

    if name == "get_ready_tasks":
        ready = db.get_ready_tasks(project_id)
        if not ready:
            return "No ready tasks (all TODO/IN_PROGRESS tasks have unmet dependencies or there are none)."
        lines = [f"Tasks ready to start ({len(ready)} total):"]
        for t in ready:
            lines.append(f"  #{t.id} [{t.priority.value}] {t.title}")
        _log_tool(name, inputs)
        return "\n".join(lines)

    if name == "get_project_health":
        health = _compute_health(db, project_id)
        metrics = health.get("metrics", [])
        if not metrics:
            return "Insufficient data to compute health score."
        lines = [f"Health: {health['grade']} ({health['score']}/100)"]
        for m in metrics:
            lines.append(f"  {m['name']}: {m['score']}/{m['max']} — {m['detail']}")
        _log_tool(name, inputs)
        return "\n".join(lines)

    if name == "get_task_dependencies":
        task_id = inputs["task_id"]
        deps = db.get_dependencies(task_id)
        dependents = db.get_dependents(task_id)
        parts = []
        if deps:
            parts.append("Depends on (must be done first):")
            for d in deps:
                parts.append(f"  #{d.id} [{d.status.value}] {d.title}")
        else:
            parts.append("No prerequisites — can start immediately.")
        if dependents:
            parts.append("Blocked by this task:")
            for d in dependents:
                parts.append(f"  #{d.id} [{d.status.value}] {d.title}")
        _log_tool(name, inputs)
        return "\n".join(parts)

    # ── Write tools (require confirmation) ────────────────────────────────

    if name == "update_task_status":
        task_id = inputs["task_id"]
        new_status = inputs["status"]
        task = db.get_task(task_id)
        if not task:
            return f"Task #{task_id} not found."
        action = f"Update task #{task_id} '{task.title}' status: {task.status.value} → {new_status}"
        if not _confirm_write(action, dry_run=dry_run, auto_yes=auto_yes):
            return "Action skipped by user."
        from ..models import Status as S
        kwargs: dict = {"status": S(new_status)}
        if new_status == "done":
            kwargs["completed_at"] = datetime.now(timezone.utc)
        db.update_task(task_id, **kwargs)
        write_log.append(action)
        return f"Updated task #{task_id} status to {new_status}."

    if name == "create_task":
        title = inputs["title"]
        priority = inputs.get("priority", "medium")
        description = inputs.get("description", "")
        estimate = inputs.get("estimate_hours")
        action = (
            f"Create task: [{priority}] '{title}'"
            + (f" ({estimate}h)" if estimate else "")
        )
        if not _confirm_write(action, dry_run=dry_run, auto_yes=auto_yes):
            return "Task creation skipped by user."
        t = db.create_task(
            project_id=project_id,
            title=title,
            description=description,
            priority=Priority(priority),
            estimate_hours=estimate,
        )
        write_log.append(action)
        return f"Created task #{t.id}: '{t.title}'"

    if name == "log_time":
        task_id = inputs["task_id"]
        hours = inputs["hours"]
        note = inputs.get("note", "")
        task = db.get_task(task_id)
        if not task:
            return f"Task #{task_id} not found."
        action = f"Log {hours}h to task #{task_id} '{task.title}'"
        if not _confirm_write(action, dry_run=dry_run, auto_yes=auto_yes):
            return "Time log skipped by user."
        db.log_time(task_id, hours, note)
        write_log.append(action)
        return f"Logged {hours}h to task #{task_id}."

    if name == "add_task_note":
        task_id = inputs["task_id"]
        note = inputs["note"]
        task = db.get_task(task_id)
        if not task:
            return f"Task #{task_id} not found."
        action = f"Add note to task #{task_id} '{task.title}': \"{note[:60]}{'…' if len(note) > 60 else ''}\""
        if not _confirm_write(action, dry_run=dry_run, auto_yes=auto_yes):
            return "Note skipped by user."
        db.add_task_note(task_id, note)
        write_log.append(action)
        return f"Note added to task #{task_id}."

    return f"Unknown tool: {name}"


def _confirm_write(action: str, *, dry_run: bool, auto_yes: bool) -> bool:
    """Print the action and ask for confirmation. Returns True if approved."""
    if dry_run:
        console.print(f"  [yellow]DRY-RUN:[/yellow] Would: {action}")
        return False
    console.print(f"\n  [cyan]Agent wants to:[/cyan] {action}")
    if auto_yes:
        console.print("  [dim](auto-confirmed via --yes)[/dim]")
        return True
    return click.confirm("  Allow this action?", default=True)


def _log_tool(name: str, inputs: dict) -> None:
    """Print a dim log line showing which tool was called."""
    args = ", ".join(f"{k}={v!r}" for k, v in inputs.items()) if inputs else ""
    console.print(f"  [dim]→ {name}({args})[/dim]")
