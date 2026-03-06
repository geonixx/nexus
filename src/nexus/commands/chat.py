"""Interactive AI chat for a Nexus project.

`nexus chat [project_id]` opens a conversational session with full project
context.  Two modes depending on the active AI provider:

  Anthropic (ANTHROPIC_API_KEY):
    Full tool mode — Claude can take real actions:
    list / inspect tasks, create tasks, update statuses, log time, report stats.

  Gemini / Ollama (GOOGLE_API_KEY or OLLAMA_MODEL):
    Advisory mode — read-only; the model answers questions and suggests the
    exact `nexus` CLI commands to run for any action.

Slash commands available in both modes:
  /exit or /quit   End the session
  /context         Refresh and show current project summary
  /help            Show available commands

Advisory-mode only:
  /clear           Clear conversation history (manages context window)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import click

from ..commands.config import load_config
from ..db import Database
from ..models import Priority, Status
from ..ui import console, print_error, print_info


def _make_tool_handler(db: Database, project_id: int) -> Callable[[str, dict], str]:
    """Return a tool-handler closure bound to *db* and *project_id*.

    Extracted as a standalone function so tests can exercise tool execution
    directly without spinning up a full CLI invocation.
    """

    def handle_tool(name: str, inputs: dict) -> str:  # noqa: C901 (complexity ok)
        try:
            if name == "list_tasks":
                status_val = inputs.get("status")
                status = Status(status_val) if status_val else None
                task_list = db.list_tasks(project_id=project_id, status=status)
                if not task_list:
                    return "No tasks found."
                return "\n".join(
                    f"#{t.id}  [{t.status.value}]  [{t.priority.value}]  {t.title}"
                    + (
                        f"  ({t.estimate_hours}h est / {t.actual_hours or 0:.1f}h actual)"
                        if t.estimate_hours
                        else ""
                    )
                    for t in task_list
                )

            elif name == "get_task":
                t = db.get_task(inputs["task_id"])
                if not t:
                    return f"Task {inputs['task_id']} not found."
                entries = db.list_time_entries(t.id)
                total_logged = sum(e.hours for e in entries)
                lines = [
                    f"#{t.id}  {t.title}",
                    f"Status: {t.status.value}   Priority: {t.priority.value}",
                    f"Estimate: {t.estimate_hours or 'none'}h   Logged: {total_logged:.1f}h",
                    f"Description: {t.description or '(none)'}",
                ]
                if entries:
                    lines.append(f"Time entries ({len(entries)}):")
                    for e in entries[-5:]:
                        day = e.logged_at.strftime("%Y-%m-%d") if e.logged_at else "?"
                        note = f" — {e.note}" if e.note else ""
                        lines.append(f"  {day}  {e.hours}h{note}")
                return "\n".join(lines)

            elif name == "update_task_status":
                task = db.get_task(inputs["task_id"])
                if not task:
                    return f"Task {inputs['task_id']} not found."
                new_status = Status(inputs["status"])
                completed_at = None
                if new_status == Status.DONE:
                    completed_at = datetime.now(timezone.utc)
                db.update_task(
                    inputs["task_id"],
                    status=new_status,
                    completed_at=completed_at,
                )
                return f"Task #{inputs['task_id']} '{task.title}' → {inputs['status']}."

            elif name == "create_task":
                priority = Priority(inputs.get("priority", "medium"))
                task = db.create_task(
                    project_id=project_id,
                    title=inputs["title"],
                    description=inputs.get("description", ""),
                    priority=priority,
                    estimate_hours=inputs.get("estimate_hours"),
                )
                return f"Created task #{task.id}: '{task.title}' [{priority.value}]."

            elif name == "log_time":
                task = db.get_task(inputs["task_id"])
                if not task:
                    return f"Task {inputs['task_id']} not found."
                db.log_time(inputs["task_id"], inputs["hours"], inputs.get("note", ""))
                return f"Logged {inputs['hours']}h to task #{inputs['task_id']} '{task.title}'."

            elif name == "get_project_stats":
                s = db.project_stats(project_id)
                if not s:
                    return "Project not found."
                return (
                    f"Project: {s.project.name}\n"
                    f"Tasks: {s.total_tasks} total | {s.done_tasks} done | "
                    f"{s.in_progress_tasks} in progress | {s.blocked_tasks} blocked\n"
                    f"Completion: {s.completion_pct:.1f}%\n"
                    f"Hours logged: {s.total_hours_logged:.1f}h"
                )

            else:
                return f"Unknown tool: {name}"

        except Exception as e:  # noqa: BLE001
            return f"Error executing {name}: {e}"

    return handle_tool


def _build_system_prompt(db: Database, project_id: int) -> str:
    """Construct a rich system prompt with current project context."""
    from ..ai import CHAT_TOOLS  # noqa: F401 (not used here — just for reference)

    project = db.get_project(project_id)
    if not project:
        return ""

    tasks = db.list_tasks(project_id=project_id)
    stats = db.project_stats(project_id)
    sprints = db.list_sprints(project_id)
    active_sprint = next(
        (s for s in reversed(sprints) if s.status == Status.IN_PROGRESS), None
    )

    # Cap task list at 60 to stay within context limits
    task_lines = "\n".join(
        f"  #{t.id}  [{t.status.value}]  [{t.priority.value}]  {t.title}"
        + (f"  ({t.estimate_hours}h est)" if t.estimate_hours else "")
        for t in tasks[:60]
    ) or "  (no tasks yet)"

    sprint_ctx = (
        f"Active sprint: {active_sprint.name}"
        + (f" — {active_sprint.goal}" if active_sprint.goal else "")
        if active_sprint
        else "No active sprint."
    )

    return f"""You are a helpful assistant embedded in the Nexus project management CLI.

Project: **{project.name}**
{('Description: ' + project.description) if project.description else ''}

Current statistics:
- Tasks: {stats.total_tasks} total | {stats.done_tasks} done | {stats.in_progress_tasks} in progress | {stats.blocked_tasks} blocked
- Completion: {stats.completion_pct:.0f}%
- Hours logged: {stats.total_hours_logged:.1f}h
- {sprint_ctx}

Current tasks:
{task_lines}

You can help the user by:
- Answering questions about the project state
- Recommending what to work on next
- Updating task statuses (mark done, start, block, cancel)
- Creating new tasks from the conversation
- Logging time to tasks
- Providing analysis and insights

Always use the provided tools when taking actions on tasks. After each action, \
confirm what changed concisely. Be direct and practical."""


def _run_tool_chat(db: Database, project_id: int, ai: object, project: object) -> None:
    """Anthropic tool-use chat REPL.

    Requires ai.supports_tools == True (Anthropic provider only).
    """
    from rich.markdown import Markdown

    from ..ai import CHAT_TOOLS

    system_prompt = _build_system_prompt(db, project_id)
    tool_handler = _make_tool_handler(db, project_id)
    messages: list[dict] = []

    while True:
        # ── Prompt ────────────────────────────────────────────────────────
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # ── Slash commands ────────────────────────────────────────────────
        cmd = user_input.lower()
        if cmd in ("/exit", "/quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "/help":
            console.print(
                "  [bold]/exit[/bold] or [bold]/quit[/bold]  — end session\n"
                "  [bold]/context[/bold]           — show project summary\n"
                "  [bold]/help[/bold]              — this message"
            )
            continue

        if cmd == "/context":
            s = db.project_stats(project_id)
            from rich.markdown import Markdown as _Md
            console.print(_Md(
                f"**{project.name}** — {s.total_tasks} tasks, "
                f"{s.done_tasks} done, {s.in_progress_tasks} in progress, "
                f"{s.blocked_tasks} blocked. "
                f"Completion: {s.completion_pct:.0f}%. "
                f"Hours logged: {s.total_hours_logged:.1f}h."
            ))
            console.print()
            continue

        # ── AI turn ───────────────────────────────────────────────────────
        messages.append({"role": "user", "content": user_input})

        try:
            response_text, messages = ai.chat_turn(
                messages=messages,
                tools=CHAT_TOOLS,
                tool_handler=tool_handler,
                system=system_prompt,
            )
        except RuntimeError as e:
            print_error(str(e))
            break

        console.print("\n[bold green]Nexus:[/bold green]")
        console.print(Markdown(response_text))
        console.print()


def _run_offline_chat(
    db: Database,
    project_id: int,
    ai: object,
    project: object,
    stats: object,
    *,
    history_window: int = 6,
) -> None:
    """Advisory-mode streaming chat REPL for Gemini/Ollama providers.

    The model receives a project snapshot in the system prompt on every turn
    and is asked to suggest CLI commands rather than take actions directly.

    History is windowed to the last `history_window` exchange pairs to avoid
    overflowing context limits on smaller local models.
    """
    from ..ai import offline_chat_system_prompt
    from ..commands.agent import _build_offline_context

    # Build initial project snapshot
    ctx = _build_offline_context(db, project_id)

    def _make_system() -> str:
        return offline_chat_system_prompt(
            project.name,
            getattr(project, "description", "") or "",
            ctx["stats_line"],
            ctx["tasks_ctx"],
            ctx["stale_ctx"],
            ctx["ready_ctx"],
        )

    system = _make_system()

    # History: list of (user_text, assistant_text) tuples
    history: list[tuple[str, str]] = []

    while True:
        # ── Prompt ────────────────────────────────────────────────────────
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # ── Slash commands ────────────────────────────────────────────────
        cmd = user_input.lower()
        if cmd in ("/exit", "/quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "/help":
            console.print(
                "  [bold]/exit[/bold] or [bold]/quit[/bold]  — end session\n"
                "  [bold]/context[/bold]           — refresh project summary\n"
                "  [bold]/clear[/bold]             — clear conversation history\n"
                "  [bold]/help[/bold]              — this message"
            )
            continue

        if cmd == "/context":
            # Refresh snapshot from the live DB
            ctx.update(_build_offline_context(db, project_id))
            system = _make_system()
            s = db.project_stats(project_id)
            console.print(
                f"[dim]Context refreshed — {s.total_tasks} tasks, "
                f"{s.done_tasks} done, {s.in_progress_tasks} in progress, "
                f"{s.blocked_tasks} blocked. {s.completion_pct:.0f}% complete.[/dim]\n"
            )
            continue

        if cmd == "/clear":
            history.clear()
            console.print("[dim]Conversation history cleared.[/dim]\n")
            continue

        # ── Build windowed turn string ─────────────────────────────────
        window = history[-history_window:]
        parts: list[str] = []
        if window:
            parts.append("Conversation so far:")
            for u, a in window:
                parts.append(f"User: {u}")
                parts.append(f"Assistant: {a}")
            parts.append("")
        parts.append(f"Current message:\n{user_input}")
        turn_user = "\n".join(parts)

        # ── Stream the response ────────────────────────────────────────
        console.print("\n[bold green]Nexus:[/bold green] ", end="")
        chunks: list[str] = []
        try:
            for chunk in ai.stream(system, turn_user):
                console.print(chunk, end="")
                chunks.append(chunk)
        except RuntimeError as e:
            print_error(str(e))
            break

        console.print("\n")
        response_text = "".join(chunks)
        history.append((user_input, response_text))


@click.command("chat")
@click.argument("project_id", type=int, required=False)
@click.pass_obj
def chat_cmd(db: Database, project_id: int | None):
    """Start an interactive AI chat session for a project.

    \b
    Anthropic (full tool mode):
      Claude has full context and can take real actions:
      list tasks, create tasks, update statuses, log time.

    \b
    Gemini / Ollama (advisory mode):
      Read-only chat — answers questions and suggests the exact nexus CLI
      commands to run for any action you want to take.

    \b
    Commands during chat:
      /exit or /quit   End the session
      /context         Refresh and show current project summary
      /help            Show available commands
      /clear           Clear history (advisory mode only)
    """
    from rich.rule import Rule

    from ..ai import NexusAI

    # Resolve project_id — fall back to config default
    if project_id is None:
        cfg = load_config()
        project_id = cfg.get("default_project")
        if not project_id:
            print_error("No project_id given and no default_project configured.")
            print_info("Usage: nexus chat <project_id>")
            print_info("       nexus config set default_project <id>")
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

    stats = db.project_stats(project_id)
    mode_label = "Full tool mode" if ai.supports_tools else "Advisory mode"

    # ── Welcome banner ─────────────────────────────────────────────────────
    console.print(Rule(f"[nexus.title]Nexus Chat · {project.name}[/nexus.title]", style="cyan"))
    console.print(
        f"  [dim]Provider: {ai.provider_name}  ·  {mode_label}  ·  "
        f"{stats.total_tasks} tasks  ·  {stats.completion_pct:.0f}% complete[/dim]"
    )
    if ai.supports_tools:
        console.print(
            "  [dim]Type [bold]/exit[/bold] to quit · [bold]/help[/bold] for commands[/dim]\n"
        )
    else:
        console.print(
            "  [dim]Advisory mode: I'll answer questions and suggest CLI commands.[/dim]"
        )
        console.print(
            "  [dim]Type [bold]/exit[/bold] to quit · [bold]/help[/bold] for commands[/dim]\n"
        )

    # ── Route to the right chat loop ───────────────────────────────────────
    if ai.supports_tools:
        _run_tool_chat(db, project_id, ai, project)
    else:
        _run_offline_chat(db, project_id, ai, project, stats)
