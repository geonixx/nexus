"""Task management commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import click
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..db import Database
from ..models import Priority, Status
from ..ui import STATUS_ICONS, STATUS_STYLES, console, print_error, print_info, print_success, print_tasks


@click.group("task")
def task_cmd():
    """Manage tasks."""


@task_cmd.command("add")
@click.argument("project_id", type=int)
@click.argument("title")
@click.option("-d", "--description", default="")
@click.option(
    "-p",
    "--priority",
    type=click.Choice([p.value for p in Priority]),
    default=Priority.MEDIUM.value,
)
@click.option("-e", "--estimate", type=float, default=None, help="Estimate in hours.")
@click.option("-s", "--sprint", "sprint_id", type=int, default=None, help="Assign to sprint id.")
@click.pass_obj
def task_add(
    db: Database,
    project_id: int,
    title: str,
    description: str,
    priority: str,
    estimate: float | None,
    sprint_id: int | None,
):
    """Add a task to a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    t = db.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=Priority(priority),
        estimate_hours=estimate,
        sprint_id=sprint_id,
    )
    print_success(f"Added task [bold]#{t.id}[/bold] '{t.title}' to project '{project.name}'")


@task_cmd.command("show")
@click.argument("task_id", type=int)
@click.pass_obj
def task_show(db: Database, task_id: int):
    """Show full detail for a single task."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)

    from ..ui import PRIORITY_ICONS, PRIORITY_STYLES, priority_text, status_text

    status_icon = STATUS_ICONS.get(task.status, "?")
    status_style = STATUS_STYLES.get(task.status, "white")

    header = Text()
    header.append(f" #{task.id}  ", style="dim")
    header.append(task.title, style="bold white")
    header.append(f"  {status_icon} {task.status.value}", style=status_style)

    body_lines = []
    body_lines.append(f"[dim]Priority:[/dim]  {priority_text(task.priority)}")

    project = db.get_project(task.project_id)
    if project:
        body_lines.append(f"[dim]Project:[/dim]   [cyan]{project.name}[/cyan] (id={project.id})")
    if task.sprint_id:
        sprint = db.get_sprint(task.sprint_id)
        if sprint:
            body_lines.append(f"[dim]Sprint:[/dim]    {sprint.name} (id={sprint.id})")

    if task.estimate_hours is not None or task.actual_hours is not None:
        est = f"{task.estimate_hours:.1f}h" if task.estimate_hours else "—"
        act = f"{task.actual_hours:.1f}h" if task.actual_hours else "0.0h"
        body_lines.append(f"[dim]Estimate:[/dim] {est}   [dim]Actual:[/dim] {act}")

    body_lines.append(f"[dim]Created:[/dim]  {task.created_at.strftime('%Y-%m-%d %H:%M')}")
    if task.completed_at:
        body_lines.append(f"[dim]Completed:[/dim]{task.completed_at.strftime('%Y-%m-%d %H:%M')}")

    if task.description:
        body_lines.append("")
        body_lines.append(task.description)

    console.print(Panel("\n".join(body_lines), title=header, border_style="cyan", expand=False))

    # Time entries
    entries = db.list_time_entries(task_id)
    if entries:
        table = Table(box=box.SIMPLE, show_header=True, header_style="dim", expand=False)
        table.add_column("Date", style="dim", width=20)
        table.add_column("Hours", justify="right", width=6)
        table.add_column("Note")
        for e in entries:
            table.add_row(
                e.logged_at.strftime("%Y-%m-%d %H:%M"),
                f"{e.hours:.1f}h",
                e.note or "—",
            )
        console.print(f"  [dim]Time log ({len(entries)} entries)[/dim]")
        console.print(table)

    # Task notes
    notes = db.get_task_notes(task_id)
    if notes:
        console.print(f"  [dim]Notes ({len(notes)})[/dim]")
        for n in notes:
            day = n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "?"
            console.print(f"  [dim]{day}[/dim]  {n.text}")

    # Dependencies
    deps = db.get_dependencies(task_id)
    dependents = db.get_dependents(task_id)
    if deps:
        parts = []
        for d in deps:
            icon = STATUS_ICONS.get(d.status, "○")
            if d.status == Status.DONE:
                parts.append(f"[green]{icon} #{d.id} {d.title}[/green]")
            elif d.status == Status.CANCELLED:
                parts.append(f"[dim]{icon} #{d.id} {d.title}[/dim]")
            else:
                parts.append(f"{icon} #{d.id} {d.title}")
        console.print("  [dim]Depends on:[/dim]  " + "  ·  ".join(parts))
    if dependents:
        parts = []
        for d in dependents:
            icon = STATUS_ICONS.get(d.status, "○")
            parts.append(f"{icon} #{d.id} {d.title}")
        console.print("  [dim]Needed by:[/dim]   " + "  ·  ".join(parts))


@task_cmd.command("list")
@click.argument("project_id", type=int)
@click.option("--status", type=click.Choice([s.value for s in Status]), default=None)
@click.option("--sprint", "sprint_id", type=int, default=None)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.pass_obj
def task_list(db: Database, project_id: int, status: str | None, sprint_id: int | None, as_json: bool):
    """List tasks for a project."""
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)
    s = Status(status) if status else None
    tasks = db.list_tasks(project_id=project_id, sprint_id=sprint_id, status=s)
    if as_json:
        click.echo(json.dumps([t.model_dump(mode="json") for t in tasks], indent=2))
        return
    print_tasks(tasks, title=f"Tasks — {project.name}")


@task_cmd.command("done")
@click.argument("task_id", type=int)
@click.pass_obj
def task_done(db: Database, task_id: int):
    """Mark a task as done."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    db.update_task(task_id, status=Status.DONE, completed_at=datetime.now(timezone.utc))
    print_success(f"Task #{task_id} '{task.title}' marked [green]done[/green]")


@task_cmd.command("start")
@click.argument("task_id", type=int)
@click.pass_obj
def task_start(db: Database, task_id: int):
    """Mark a task as in-progress."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    db.update_task(task_id, status=Status.IN_PROGRESS)
    print_success(f"Task #{task_id} '{task.title}' is now [yellow]in progress[/yellow]")


@task_cmd.command("block")
@click.argument("task_id", type=int)
@click.pass_obj
def task_block(db: Database, task_id: int):
    """Mark a task as blocked."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    db.update_task(task_id, status=Status.BLOCKED)
    print_success(f"Task #{task_id} '{task.title}' marked [red]blocked[/red]")


@task_cmd.command("update")
@click.argument("task_id", type=int)
@click.option("-t", "--title", default=None)
@click.option("-d", "--description", default=None)
@click.option("-p", "--priority", type=click.Choice([p.value for p in Priority]), default=None)
@click.option("-e", "--estimate", type=float, default=None)
@click.option("-s", "--sprint", "sprint_id", type=int, default=None)
@click.pass_obj
def task_update(
    db: Database,
    task_id: int,
    title: str | None,
    description: str | None,
    priority: str | None,
    estimate: float | None,
    sprint_id: int | None,
):
    """Update task fields."""
    updates = {}
    if title:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if priority:
        updates["priority"] = Priority(priority)
    if estimate is not None:
        updates["estimate_hours"] = estimate
    if sprint_id is not None:
        updates["sprint_id"] = sprint_id
    if not updates:
        print_info("Nothing to update.")
        return
    t = db.update_task(task_id, **updates)
    if not t:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    print_success(f"Updated task #{task_id}")


@task_cmd.command("log")
@click.argument("task_id", type=int)
@click.argument("hours", type=float)
@click.option("-n", "--note", default="", help="Optional note for this time entry.")
@click.pass_obj
def task_log(db: Database, task_id: int, hours: float, note: str):
    """Log hours worked on a task."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    entry = db.log_time(task_id, hours, note)
    new_task = db.get_task(task_id)
    print_success(
        f"Logged [bold]{hours}h[/bold] on task #{task_id} "
        f"(total: {new_task.actual_hours:.1f}h)"
    )


@task_cmd.command("delete")
@click.argument("task_id", type=int)
@click.confirmation_option(prompt="Delete this task?")
@click.pass_obj
def task_delete(db: Database, task_id: int):
    """Delete a task."""
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    db.delete_task(task_id)
    print_success(f"Deleted task #{task_id} '{task.title}'")


# ── AI commands ───────────────────────────────────────────────────────────────

@task_cmd.command("suggest")
@click.argument("project_id", type=int)
@click.option("--add", "auto_add", is_flag=True, default=False, help="Interactively add suggestions.")
@click.pass_obj
def task_suggest(db: Database, project_id: int, auto_add: bool):
    """Use Claude to suggest new tasks for a project."""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel as RPanel
    from rich.rule import Rule

    from ..ai import NexusAI, suggest_tasks_prompt

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
        raise SystemExit(1)

    existing = db.list_tasks(project_id=project_id)
    existing_titles = [t.title for t in existing]

    console.print(Rule(f"[nexus.title]AI · Suggesting tasks for '{project.name}'[/nexus.title]", style="cyan"))
    console.print()

    system, user = suggest_tasks_prompt(project.name, project.description, existing_titles)

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

    if auto_add:
        _interactive_add(db, project_id, full_text)


def _interactive_add(db, project_id: int, suggestion_text: str) -> None:
    """Parse suggestion output and offer to add tasks interactively."""
    import re
    from rich.rule import Rule

    # Parse lines matching: **[priority]** Title (Xh) — rationale
    pattern = re.compile(
        r"\*\*\[?(low|medium|high|critical)\]?\*\*\s+(.+?)\s+\((\d+(?:\.\d+)?)h\)",
        re.IGNORECASE,
    )
    lines = suggestion_text.strip().splitlines()
    parsed = []
    for line in lines:
        m = pattern.search(line)
        if m:
            parsed.append({
                "priority": m.group(1).lower(),
                "title": m.group(2).strip(),
                "estimate": float(m.group(3)),
            })

    if not parsed:
        console.print("[dim]Could not parse suggestions for auto-add. Add them manually.[/dim]")
        return

    console.print(Rule("[dim]Add suggestions[/dim]", style="bright_black"))
    console.print(f"  [dim]Found {len(parsed)} parseable suggestions.[/dim]\n")

    for i, t in enumerate(parsed, 1):
        console.print(f"  [dim]{i}.[/dim] [{t['priority']}] [bold]{t['title']}[/bold] ({t['estimate']}h)")

    console.print()
    choice = click.prompt(
        "  Add which tasks? (all / comma-separated numbers / none)",
        default="none",
    ).strip().lower()

    if choice == "none":
        return

    indices: list[int]
    if choice == "all":
        indices = list(range(len(parsed)))
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
        except ValueError:
            print_error("Invalid input — nothing added.")
            return

    from ..models import Priority as P
    added = 0
    for idx in indices:
        if 0 <= idx < len(parsed):
            t = parsed[idx]
            try:
                pri = P(t["priority"])
            except ValueError:
                pri = P.MEDIUM
            db.create_task(
                project_id=project_id,
                title=t["title"],
                priority=pri,
                estimate_hours=t["estimate"],
            )
            print_success(f"Added '{t['title']}'")
            added += 1

    console.print(f"\n  [nexus.success]Added {added} task(s).[/nexus.success]")


@task_cmd.command("estimate")
@click.argument("task_id", type=int)
@click.pass_obj
def task_estimate(db: Database, task_id: int):
    """Use Claude to estimate hours for a task."""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.rule import Rule

    from ..ai import NexusAI, estimate_task_prompt

    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
        raise SystemExit(1)

    # Gather completed tasks from the same project for reference
    completed = db.list_tasks(project_id=task.project_id, status=__import__("nexus.models", fromlist=["Status"]).Status.DONE)
    similar = [(t.title, t.actual_hours) for t in completed if t.actual_hours and t.id != task_id][:6]

    console.print(Rule(f"[nexus.title]AI · Estimating task #{task_id}[/nexus.title]", style="cyan"))
    console.print(f"  [bold]{task.title}[/bold]")
    if task.description:
        console.print(f"  [dim]{task.description}[/dim]")
    console.print()

    system, user = estimate_task_prompt(task.title, task.description, similar)

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


# ── Workflow shortcuts ────────────────────────────────────────────────────────

@task_cmd.command("next")
@click.argument("project_id", type=int, required=False, default=None)
@click.option("-n", "--count", type=int, default=5, help="Number of tasks to show (default: 5).")
@click.pass_obj
def task_next(db: Database, project_id: int | None, count: int):
    """Show the highest-priority tasks to work on next.

    PROJECT_ID may be omitted if 'default_project' is set in config.
    """
    from rich.rule import Rule
    from rich.text import Text

    from .config import load_config

    if project_id is None:
        cfg = load_config()
        project_id = cfg.get("default_project")
        if not project_id:
            print_error(
                "No project_id given and 'default_project' is not set in config.\n"
                "  Set one with: [bold]nexus config set default_project <id>[/bold]"
            )
            raise SystemExit(1)

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    all_tasks = db.list_tasks(project_id=project_id)

    PRIORITY_WEIGHT = {
        Priority.CRITICAL: 4,
        Priority.HIGH: 3,
        Priority.MEDIUM: 2,
        Priority.LOW: 1,
    }

    active = [t for t in all_tasks if t.status == Status.IN_PROGRESS]
    todo = [t for t in all_tasks if t.status == Status.TODO]
    blocked_tasks = [t for t in all_tasks if t.status == Status.BLOCKED]

    # Sort todo: highest priority first, oldest created first within same priority
    todo.sort(key=lambda t: (-PRIORITY_WEIGHT.get(t.priority, 0), t.created_at or ""))

    candidates = active + todo + blocked_tasks
    if not candidates:
        print_info(f"No actionable tasks in '{project.name}'.")
        return

    console.print(Rule(f"[nexus.title]Next up · {project.name}[/nexus.title]", style="cyan"))
    console.print()

    pri_colors = {
        Priority.CRITICAL: "bold red",
        Priority.HIGH: "bold yellow",
        Priority.MEDIUM: "cyan",
        Priority.LOW: "dim",
    }

    for t in candidates[:count]:
        icon = STATUS_ICONS.get(t.status, "○")
        line = Text()
        line.append(f"  {icon} ", style=STATUS_STYLES.get(t.status, ""))
        line.append(f"#{t.id}", style="dim")
        line.append(f"  {t.title}")
        line.append(f"  [{t.priority.value}]", style=pri_colors.get(t.priority, ""))
        if t.estimate_hours:
            line.append(f"  {t.estimate_hours}h", style="dim")
        console.print(line)

    if len(candidates) > count:
        console.print(f"\n  [dim]…and {len(candidates) - count} more tasks[/dim]")
    console.print()


@task_cmd.command("bulk")
@click.argument("action", type=click.Choice(["done", "start", "block", "cancel", "sprint"]))
@click.argument("ids", nargs=-1, type=int, required=True)
@click.pass_obj
def task_bulk(db: Database, action: str, ids: tuple[int, ...]):
    """Apply an action to multiple tasks at once.

    For 'sprint', the FIRST id is the sprint_id, the rest are task IDs:\n
      nexus task bulk sprint 2 4 5 6\n\n
    For all other actions, all IDs are task IDs:\n
      nexus task bulk done 1 2 3
    """
    if action == "sprint":
        if len(ids) < 2:
            print_error("'sprint' needs a sprint_id followed by one or more task IDs.")
            raise SystemExit(1)
        sprint_id_arg, task_ids = ids[0], ids[1:]
        sprint = db.get_sprint(sprint_id_arg)
        if not sprint:
            print_error(f"Sprint id={sprint_id_arg} not found.")
            raise SystemExit(1)
        ok, fail = 0, 0
        for tid in task_ids:
            if not db.get_task(tid):
                print_error(f"Task #{tid} not found — skipped.")
                fail += 1
                continue
            db.update_task(tid, sprint_id=sprint_id_arg)
            ok += 1
        if ok:
            print_success(f"Assigned {ok} task(s) to sprint '{sprint.name}'.")
        if fail:
            print_info(f"{fail} task(s) not found and skipped.")
        return

    STATUS_MAP = {
        "done":   Status.DONE,
        "start":  Status.IN_PROGRESS,
        "block":  Status.BLOCKED,
        "cancel": Status.CANCELLED,
    }
    new_status = STATUS_MAP[action]
    ok, fail = 0, 0
    for tid in ids:
        task = db.get_task(tid)
        if not task:
            print_error(f"Task #{tid} not found — skipped.")
            fail += 1
            continue
        kwargs: dict = {"status": new_status}
        if new_status == Status.DONE:
            kwargs["completed_at"] = datetime.now(timezone.utc)
        db.update_task(tid, **kwargs)
        ok += 1

    verb = {"done": "marked done", "start": "started", "block": "blocked", "cancel": "cancelled"}[action]
    if ok:
        print_success(f"{ok} task(s) {verb}.")
    if fail:
        print_info(f"{fail} task(s) not found and skipped.")


@task_cmd.command("note")
@click.argument("task_id", type=int)
@click.argument("text")
@click.pass_obj
def task_note(db: Database, task_id: int, text: str):
    """Append a timestamped note to a task.

    Useful for capturing decisions, blockers, or context directly on a task.

    \b
    Examples:
      nexus task note 3 "Decided to use JWT — session store was too slow"
      nexus task note 7 "Blocked on design review, pinged @alice"
    """
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    db.add_task_note(task_id, text)
    print_success(f"Note added to task #{task_id} '{task.title}'")


@task_cmd.command("ingest")
@click.argument("project_id", type=int)
@click.argument("text")
@click.option(
    "--add",
    "auto_add",
    is_flag=True,
    default=False,
    help="Create the task immediately without prompting.",
)
@click.pass_obj
def task_ingest(db: Database, project_id: int, text: str, auto_add: bool):
    """Create a structured task from freeform text using AI.

    Perfect for turning Slack messages, support tickets, or notes into
    properly structured tasks with a title, priority, and estimate.

    \b
    Examples:
      nexus task ingest 1 "login button broken on mobile for iOS users"
      nexus task ingest 1 "add CSV export to the reports page" --add
      nexus task ingest 1 "$(pbpaste)"   # pipe from clipboard on macOS
    """
    import json

    from rich.rule import Rule

    from ..ai import NexusAI, ingest_task_prompt
    from ..models import Priority as P

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    ai = NexusAI()
    if not ai.available:
        print_error("No AI provider configured. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY.")
        raise SystemExit(1)

    console.print(Rule(f"[nexus.title]AI · Ingest Task — {project.name}[/nexus.title]", style="cyan"))
    console.print()
    console.print(f"  [dim]Input:[/dim] {text[:120]}{'…' if len(text) > 120 else ''}")
    console.print()

    system, user = ingest_task_prompt(text)
    try:
        raw = ai.complete(system, user).strip()
    except RuntimeError as e:
        print_error(str(e))
        raise SystemExit(1)

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print_error("AI returned unexpected output (not valid JSON). Try again or add manually.")
        console.print(f"  [dim]Raw output:[/dim]\n{raw}")
        raise SystemExit(1)

    title = parsed.get("title", "Untitled")
    priority = parsed.get("priority", "medium")
    description = parsed.get("description", "")
    estimate = parsed.get("estimate_hours")
    rationale = parsed.get("rationale", "")

    # Validate priority
    try:
        pri = P(priority)
    except ValueError:
        pri = P.MEDIUM

    _PRIO_COLORS = {
        "critical": "bold red",
        "high": "bold yellow",
        "medium": "cyan",
        "low": "dim",
    }
    pstyle = _PRIO_COLORS.get(pri.value, "")
    priority_display = f"[{pstyle}]{pri.value}[/{pstyle}]" if pstyle else pri.value

    console.print(f"  [bold]Title:[/bold]       {title}")
    console.print(f"  [bold]Priority:[/bold]    {priority_display}  [dim]— {rationale}[/dim]")
    console.print(f"  [bold]Estimate:[/bold]    {f'{estimate}h' if estimate else '—'}")
    if description:
        console.print(f"  [bold]Description:[/bold] {description}")
    console.print()

    if auto_add or click.confirm("  Create this task?", default=True):
        t = db.create_task(
            project_id=project_id,
            title=title,
            description=description,
            priority=pri,
            estimate_hours=estimate,
        )
        print_success(f"Created task [bold]#{t.id}[/bold] '{t.title}' in project '{project.name}'")
    else:
        print_info("Task not created.")


# ── Dependency commands ───────────────────────────────────────────────────────

@task_cmd.command("depend")
@click.argument("task_id", type=int)
@click.option(
    "--on",
    "dep_ids",
    multiple=True,
    type=int,
    metavar="DEP_ID",
    help="Add this task as a dependency (repeatable). Omit to just display dependencies.",
)
@click.pass_obj
def task_depend(db: Database, task_id: int, dep_ids: tuple[int, ...]):
    """Show or add dependencies for a task.

    Without --on, lists what this task already depends on and what depends on it.
    With --on, adds one or more prerequisite tasks.

    \b
    Examples:
      nexus task depend 5                # show deps for task 5
      nexus task depend 5 --on 3        # task 5 needs task 3 done first
      nexus task depend 5 --on 3 --on 4 # task 5 needs both 3 and 4
    """
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)

    if dep_ids:
        added, failed = 0, 0
        for dep_id in dep_ids:
            dep_task = db.get_task(dep_id)
            if not dep_task:
                print_error(f"  Dependency task #{dep_id} not found — skipped.")
                failed += 1
                continue
            # Check if already a dependency before calling add (to give a better message)
            existing_dep_ids = [d.id for d in db.get_dependencies(task_id)]
            if dep_id in existing_dep_ids:
                console.print(f"  [dim]#{dep_id} is already a dependency — skipped.[/dim]")
                continue
            ok = db.add_dependency(task_id, dep_id)
            if ok:
                print_success(f"  Task #{task_id} now depends on #{dep_id} '{dep_task.title}'")
                added += 1
            else:
                # add_dependency only returns False for cycle (we handled missing/existing above)
                console.print(
                    f"  [yellow]⚠  Cannot add #{dep_id}: would create a circular dependency. Skipped.[/yellow]"
                )
                failed += 1
        if added:
            console.print(f"\n  [dim]{added} dependency(-ies) added.[/dim]")
        return

    # Display mode
    deps = db.get_dependencies(task_id)
    dependents = db.get_dependents(task_id)

    console.print(f"\n  [bold]#{task_id}[/bold] {task.title}")
    console.print()

    if deps:
        console.print("  [dim]This task depends on (must be done first):[/dim]")
        for d in deps:
            icon = STATUS_ICONS.get(d.status, "○")
            if d.status == Status.DONE:
                style = "green"
            elif d.status == Status.CANCELLED:
                style = "dim"
            else:
                style = ""
            line = f"    [{style}]{icon} #{d.id}  {d.title}  [{d.status.value}][/{style}]" if style else f"    {icon} #{d.id}  {d.title}  [{d.status.value}]"
            console.print(line)
    else:
        console.print("  [dim]No dependencies (this task can start immediately).[/dim]")

    console.print()

    if dependents:
        console.print("  [dim]Blocked tasks (waiting for this task):[/dim]")
        for d in dependents:
            icon = STATUS_ICONS.get(d.status, "○")
            console.print(f"    {icon} #{d.id}  {d.title}  [{d.status.value}]")
    else:
        console.print("  [dim]Nothing depends on this task.[/dim]")

    console.print()


@task_cmd.command("undepend")
@click.argument("task_id", type=int)
@click.option("--from", "dep_id", type=int, required=True, metavar="DEP_ID",
              help="ID of the dependency task to remove.")
@click.pass_obj
def task_undepend(db: Database, task_id: int, dep_id: int):
    """Remove a prerequisite dependency from a task.

    \b
    Example:
      nexus task undepend 5 --from 3   # task 5 no longer requires task 3
    """
    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)
    dep_task = db.get_task(dep_id)
    if not dep_task:
        print_error(f"Dependency task id={dep_id} not found.")
        raise SystemExit(1)
    removed = db.remove_dependency(task_id, dep_id)
    if removed:
        print_success(f"Removed dependency: #{task_id} no longer requires #{dep_id} '{dep_task.title}'")
    else:
        print_error(f"No dependency from #{task_id} on #{dep_id} found.")
        raise SystemExit(1)


@task_cmd.command("graph")
@click.argument("project_id", type=int)
@click.pass_obj
def task_graph(db: Database, project_id: int):
    """Visualise the task dependency graph for a project.

    Shows a tree rooted at tasks with no prerequisites.  Tasks are displayed
    with their status icon and priority.  Unblocked tasks appear first.

    \b
    Legend:
      ○  todo     ●  in-progress  ✓  done
      ✗  blocked  ⊘  cancelled
    """
    from rich.rule import Rule
    from rich.text import Text
    from rich.tree import Tree

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    all_tasks = db.list_tasks(project_id=project_id)
    if not all_tasks:
        print_info(f"No tasks in project '{project.name}'.")
        return

    task_map = {t.id: t for t in all_tasks}

    # Build adjacency: depends_on_id → list of task_ids that depend on it
    dependents_map: dict[int, list[int]] = {t.id: [] for t in all_tasks}
    dep_ids_map: dict[int, list[int]] = {}
    for t in all_tasks:
        deps = db.get_dependencies(t.id)
        dep_ids_map[t.id] = [d.id for d in deps]
        for d in deps:
            if d.id in dependents_map:
                dependents_map[d.id].append(t.id)

    # Root tasks = tasks in this project with no intra-project prerequisites
    roots = [t for t in all_tasks if not dep_ids_map.get(t.id)]

    # Tasks that have deps but deps are all outside this project (or missing)
    # are also shown as roots
    no_local_dep = [
        t for t in all_tasks
        if dep_ids_map.get(t.id)
        and not any(did in task_map for did in dep_ids_map[t.id])
    ]
    root_ids = {t.id for t in roots} | {t.id for t in no_local_dep}
    roots = [t for t in all_tasks if t.id in root_ids]

    _PRIO_STYLE_GRAPH = {
        "critical": "bold red",
        "high":     "red",
        "medium":   "yellow",
        "low":      "dim",
    }

    def _task_label(t) -> Text:
        icon = STATUS_ICONS.get(t.status, "○")
        style = STATUS_STYLES.get(t.status, "")
        pstyle = _PRIO_STYLE_GRAPH.get(t.priority.value, "")
        label = Text()
        label.append(f"{icon} ", style=style)
        label.append(f"#{t.id}", style="dim")
        label.append(f"  {t.title}  ")
        label.append(f"[{t.priority.value}]", style=pstyle)
        if t.estimate_hours:
            label.append(f"  {t.estimate_hours}h", style="dim")
        return label

    def _add_children(tree_node, task_id: int, visited: set[int]) -> None:
        """Recursively add dependents as child nodes."""
        for child_id in sorted(dependents_map.get(task_id, [])):
            if child_id not in task_map:
                continue  # cross-project dep
            if child_id in visited:
                tree_node.add(Text(f"↻ #{child_id} (already shown)", style="dim"))
                continue
            child_task = task_map[child_id]
            visited.add(child_id)
            child_node = tree_node.add(_task_label(child_task))
            _add_children(child_node, child_id, visited)

    console.print(Rule(f"[nexus.title]Dependency Graph · {project.name}[/nexus.title]", style="cyan"))
    console.print()

    if not any(dependents_map[t.id] or dep_ids_map.get(t.id) for t in all_tasks):
        console.print("  [dim]No dependencies defined for this project.[/dim]")
        console.print("  [dim]Use [bold]nexus task depend <id> --on <dep_id>[/bold] to add one.[/dim]\n")
        return

    visited_global: set[int] = set()

    # Sort roots: active/todo first, then by priority weight
    _PRIO_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    roots.sort(key=lambda t: (
        0 if t.status in (Status.TODO, Status.IN_PROGRESS) else 1,
        -_PRIO_WEIGHT.get(t.priority.value, 0),
    ))

    for root in roots:
        visited_global.add(root.id)
        root_tree = Tree(_task_label(root))
        _add_children(root_tree, root.id, visited_global)
        console.print(root_tree)
        console.print()

    # Orphaned tasks (neither root nor shown as a child — should not happen with DAG, but guard)
    orphans = [t for t in all_tasks if t.id not in visited_global]
    if orphans:
        orp_tree = Tree(Text("(tasks with all deps satisfied or outside project)", style="dim"))
        for t in orphans:
            orp_tree.add(_task_label(t))
        console.print(orp_tree)
        console.print()

    dep_count = sum(len(v) for v in dependents_map.values())
    ready = db.get_ready_tasks(project_id)
    console.print(
        f"  [dim]{len(all_tasks)} task(s) · "
        f"{dep_count} dependency edge(s) · "
        f"{len(ready)} ready to start[/dim]\n"
    )


@task_cmd.command("stale")
@click.argument("project_id", type=int, required=False, default=None)
@click.option(
    "--days", type=int, default=3,
    help="Flag in-progress tasks with no activity in this many days (default: 3).",
)
@click.pass_obj
def task_stale(db: Database, project_id: int | None, days: int):
    """Surface tasks that may need attention.

    Shows in-progress tasks with no recent time logged, long-blocked tasks,
    and very old todo tasks. Use to clean up stale work before sprint planning.

    PROJECT_ID may be omitted if 'default_project' is set in config.
    """
    from datetime import timedelta

    from rich.rule import Rule
    from rich.text import Text

    from .config import load_config

    if project_id is None:
        cfg = load_config()
        project_id = cfg.get("default_project")
        if not project_id:
            print_error(
                "No project_id given and 'default_project' is not set in config.\n"
                "  Set one with: [bold]nexus config set default_project <id>[/bold]"
            )
            raise SystemExit(1)

    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=days)
    blocked_threshold = now - timedelta(days=days * 2)
    old_todo_threshold = now - timedelta(days=days * 5)

    # Stale in-progress: no time logged in `days` days
    stale_ip = db.get_stale_tasks(project_id, stale_threshold)

    # Long-blocked: updated_at older than days*2 days
    all_tasks = db.list_tasks(project_id=project_id)
    long_blocked = [
        t for t in all_tasks
        if t.status == Status.BLOCKED
        and t.updated_at
        and t.updated_at < blocked_threshold
    ]

    # Old todo: created more than days*5 days ago, still unstarted
    old_todo = [
        t for t in all_tasks
        if t.status == Status.TODO
        and t.created_at
        and t.created_at < old_todo_threshold
    ]

    nothing = not stale_ip and not long_blocked and not old_todo
    console.print(Rule(f"[nexus.title]Stale Tasks · {project.name}[/nexus.title]", style="cyan"))

    if nothing:
        console.print(f"  [nexus.success]✓ No stale tasks found[/nexus.success] (threshold: {days} days)\n")
        return

    _PRIO_COLORS = {
        Priority.CRITICAL: "bold red",
        Priority.HIGH: "bold yellow",
        Priority.MEDIUM: "cyan",
        Priority.LOW: "dim",
    }

    def _age(t) -> str:
        ref = t.updated_at or t.created_at
        if not ref:
            return "?"
        delta = now - ref
        return f"{delta.days}d ago"

    if stale_ip:
        console.print(f"\n  [yellow]● In-progress with no activity ({len(stale_ip)})[/yellow]"
                      f"  [dim]— no time logged in {days}+ days[/dim]")
        for t in stale_ip:
            line = Text(f"    #{t.id}  {t.title}")
            line.append(f"  [{t.priority.value}]", style=_PRIO_COLORS.get(t.priority, ""))
            line.append(f"  {_age(t)}", style="dim")
            console.print(line)

    if long_blocked:
        console.print(f"\n  [red]✗ Long-blocked ({len(long_blocked)})[/red]"
                      f"  [dim]— blocked for {days * 2}+ days[/dim]")
        for t in long_blocked:
            line = Text(f"    #{t.id}  {t.title}")
            line.append(f"  [{t.priority.value}]", style=_PRIO_COLORS.get(t.priority, ""))
            line.append(f"  {_age(t)}", style="dim")
            console.print(line)

    if old_todo:
        console.print(f"\n  [dim]○ Old backlog items ({len(old_todo)})[/dim]"
                      f"  [dim]— created {days * 5}+ days ago, never started[/dim]")
        for t in old_todo[:10]:
            line = Text(f"    #{t.id}  {t.title}")
            line.append(f"  [{t.priority.value}]", style=_PRIO_COLORS.get(t.priority, ""))
            line.append(f"  {_age(t)}", style="dim")
            console.print(line)
        if len(old_todo) > 10:
            console.print(f"    [dim]…and {len(old_todo) - 10} more[/dim]")

    total_stale = len(stale_ip) + len(long_blocked) + len(old_todo)
    console.print(f"\n  [dim]{total_stale} task(s) need attention.[/dim]\n")
