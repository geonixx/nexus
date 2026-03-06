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

from ..ai import AGENT_TOOLS, NexusAI, agent_system_prompt, offline_agent_prompt
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

    Two modes depending on the active AI provider:

    \b
      Anthropic  — full tool-use loop; reads tasks on demand, many actions
      Gemini / Ollama — offline mode; project snapshot in one prompt,
                        conservative actions (add_note, create_task only)

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
        print_error(
            "No AI provider configured. "
            "Set ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OLLAMA_MODEL."
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

    # ── Offline path for Gemini / Ollama (no tool use) ─────────────────────
    if not ai.supports_tools:
        _run_offline_agent(ai, project, project_id, dry_run, yes, db)
        return

    # ── Anthropic tool-use path ─────────────────────────────────────────────

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
            f"Create task: ({priority}) '{title}'"
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


# ── Offline agent (Gemini / Ollama) ─────────────────────────────────────────


def _build_offline_context(db: Database, project_id: int) -> dict:
    """Gather project data for the offline (single-prompt) agent path.

    Returns a dict with keys: stats_line, tasks_ctx, stale_ctx, ready_ctx,
    deps_ctx, valid_task_ids.
    """
    tasks = db.list_tasks(project_id=project_id)
    total = len(tasks)
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

    done = by_status.get("done", 0)
    pct = int(done / total * 100) if total else 0
    stats_line = (
        f"{done}/{total} done ({pct}%) | "
        f"{by_status.get('in_progress', 0)} in-progress | "
        f"{by_status.get('blocked', 0)} blocked | "
        f"{by_status.get('todo', 0)} todo"
    )

    # Most-recent non-done tasks (cap at 10 for context window safety)
    from datetime import timezone as _tz  # local import to avoid name clash
    active = [t for t in tasks if t.status.value not in ("done", "cancelled")]
    active.sort(
        key=lambda t: t.updated_at or t.created_at or datetime.min.replace(tzinfo=_tz.utc),
        reverse=True,
    )
    task_lines = []
    for t in active[:10]:
        icon = STATUS_ICONS.get(t.status, "○")
        task_lines.append(
            f"#{t.id} [{t.status.value}] [{t.priority.value}] {icon} {t.title}"
            + (f" — {t.estimate_hours}h est" if t.estimate_hours else "")
        )
    tasks_ctx = "\n".join(task_lines) if task_lines else "(no active tasks)"

    # Stale / blocked work
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=3)
    blocked_threshold = now - timedelta(days=6)
    stale_ip = db.get_stale_tasks(project_id, stale_threshold)
    long_blocked = [
        t for t in tasks
        if t.status == Status.BLOCKED
        and t.updated_at and t.updated_at < blocked_threshold
    ]
    stale_parts: list[str] = []
    if stale_ip:
        stale_parts.append("Stale in-progress (3+ days no activity):")
        for t in stale_ip:
            stale_parts.append(f"  #{t.id} [{t.priority.value}] {t.title}")
    if long_blocked:
        stale_parts.append("Long-blocked (6+ days):")
        for t in long_blocked:
            stale_parts.append(f"  #{t.id} [{t.priority.value}] {t.title}")
    stale_ctx = "\n".join(stale_parts) if stale_parts else "(none)"

    # Ready tasks (cap at 5)
    ready = db.get_ready_tasks(project_id)
    ready_lines = [f"#{t.id} [{t.priority.value}] {t.title}" for t in ready[:5]]
    ready_ctx = "\n".join(ready_lines) if ready_lines else "(none — may have unmet dependencies)"

    valid_task_ids = [t.id for t in tasks]

    # M21: dependency chain summary so AI can reason about task ordering
    dep_graph = db.get_dependency_graph(project_id)
    task_map_for_deps = {t.id: t for t in tasks}
    dep_parts: list[str] = []
    for t in tasks:
        if t.status.value in ("done", "cancelled"):
            continue
        open_deps = [
            task_map_for_deps[did]
            for did in dep_graph.get(t.id, [])
            if did in task_map_for_deps
            and task_map_for_deps[did].status.value not in ("done", "cancelled")
        ]
        if open_deps:
            dep_strs = ", ".join(f"#{d.id} ({d.status.value})" for d in open_deps)
            dep_parts.append(f"  #{t.id} '{t.title}' needs: {dep_strs}")
    deps_ctx = "\n".join(dep_parts[:10]) if dep_parts else "(no blocked dependency chains)"

    return {
        "stats_line": stats_line,
        "tasks_ctx": tasks_ctx,
        "stale_ctx": stale_ctx,
        "ready_ctx": ready_ctx,
        "deps_ctx": deps_ctx,
        "valid_task_ids": valid_task_ids,
    }


def _parse_offline_plan(raw: str, valid_task_ids: set[int]) -> dict:
    """Parse and validate the JSON plan returned by the offline agent.

    Strips markdown fences if present.  Validates action types, task IDs, and
    priorities.  Unknown action types and invalid task IDs are silently skipped.

    Returns:
        {"observations": [str, ...], "actions": [{...}, ...]}

    Raises:
        ValueError on unparseable JSON or a top-level type mismatch.
    """
    import json as _json

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()

    try:
        data = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from offline agent: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Offline agent response must be a JSON object")

    # Observations — cap at 5, stringify each
    raw_obs = data.get("observations", [])
    observations = [str(o) for o in (raw_obs if isinstance(raw_obs, list) else []) if o][:5]

    # Actions — validate each item, silently drop invalid ones
    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    valid_priorities = {"low", "medium", "high", "critical"}
    actions: list[dict] = []

    for item in raw_actions[:5]:
        if not isinstance(item, dict):
            continue
        atype = item.get("type", "")

        if atype == "add_note":
            raw_id = item.get("task_id")
            note = str(item.get("note", "")).strip()
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if task_id not in valid_task_ids or not note:
                continue
            actions.append({"type": "add_note", "task_id": task_id, "note": note})

        elif atype == "create_task":
            title = str(item.get("title", "")).strip()[:80]
            if not title:
                continue
            priority = str(item.get("priority", "medium")).strip().lower()
            if priority not in valid_priorities:
                priority = "medium"
            description = str(item.get("description", "")).strip()
            actions.append({
                "type": "create_task",
                "title": title,
                "priority": priority,
                "description": description,
            })
        # Unknown types: silently skip

    return {"observations": observations, "actions": actions}


def _run_offline_agent(
    ai: NexusAI,
    project: object,
    project_id: int,
    dry_run: bool,
    auto_yes: bool,
    db: Database,
) -> None:
    """Run the offline (single-prompt) agent for Gemini and Ollama providers.

    Sends the full project context in one shot, parses the JSON action plan,
    and executes approved actions using the same _confirm_write guard as the
    Anthropic tool-use path.  Retries up to 2 times on JSON parse failure.
    """
    console.print(f"  [dim]Provider: {ai.provider_name} (offline mode)[/dim]")
    console.print("  [dim]Gathering project context…[/dim]\n")

    ctx = _build_offline_context(db, project_id)
    system, user_base = offline_agent_prompt(
        project_name=project.name,         # type: ignore[attr-defined]
        project_desc=getattr(project, "description", "") or "",
        stats_line=ctx["stats_line"],
        tasks_ctx=ctx["tasks_ctx"],
        stale_ctx=ctx["stale_ctx"],
        ready_ctx=ctx["ready_ctx"],
        deps_ctx=ctx["deps_ctx"],
        valid_task_ids=ctx["valid_task_ids"],
    )

    # ── Up to 3 attempts (initial + 2 retries) on JSON parse failure ────────
    last_error: str | None = None
    plan: dict = {}
    corrective_suffix = ""

    for attempt in range(3):
        label = (
            f"  [dim]Calling {ai.provider_name}…[/dim]"
            if attempt == 0
            else f"  [dim]Retry {attempt}/2 after parse error…[/dim]"
        )
        console.print(label)
        try:
            raw = ai.complete(system, user_base + corrective_suffix)
            plan = _parse_offline_plan(raw, set(ctx["valid_task_ids"]))
            last_error = None
            break
        except (ValueError, RuntimeError) as exc:
            last_error = str(exc)
            corrective_suffix = (
                f"\n\nYour previous response could not be parsed: {last_error}\n"
                "Please output ONLY valid JSON matching the schema above. "
                "No prose, no markdown fences."
            )
    else:
        print_error(f"Offline agent failed after 3 attempts: {last_error}")
        raise SystemExit(1)

    # ── Observations ─────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[nexus.title]Agent Observations[/nexus.title]", style="cyan"))
    console.print()
    for obs in plan["observations"]:
        console.print(f"  [dim]•[/dim]  {obs}")
    console.print()

    # ── Execute actions ───────────────────────────────────────────────────────
    write_log: list[str] = []

    for action in plan["actions"]:
        if action["type"] == "add_note":
            task_id = action["task_id"]
            note = action["note"]
            task = db.get_task(task_id)
            if not task:
                console.print(f"  [dim]Skip add_note: task #{task_id} not found[/dim]")
                continue
            short = note[:60] + ("…" if len(note) > 60 else "")
            action_desc = f"Add note to task #{task_id} '{task.title}': \"{short}\""
            if _confirm_write(action_desc, dry_run=dry_run, auto_yes=auto_yes):
                db.add_task_note(task_id, note)
                write_log.append(action_desc)

        elif action["type"] == "create_task":
            title = action["title"]
            priority = action["priority"]
            description = action.get("description", "")
            action_desc = f"Create task: ({priority}) '{title}'"
            if _confirm_write(action_desc, dry_run=dry_run, auto_yes=auto_yes):
                t = db.create_task(
                    project_id=project_id,
                    title=title,
                    description=description,
                    priority=Priority(priority),
                )
                write_log.append(f"{action_desc} → #{t.id}")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print(Rule("[nexus.title]Agent Summary[/nexus.title]", style="cyan"))
    console.print()
    if write_log:
        console.print(f"  [dim]Actions taken ({len(write_log)}):[/dim]")
        for entry in write_log:
            console.print(f"  [green]✓[/green]  {entry}")
        console.print()
    elif dry_run:
        console.print("  [yellow]Dry-run — no changes written.[/yellow]\n")
    else:
        console.print("  [dim]No write actions were taken.[/dim]\n")


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
