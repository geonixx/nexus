"""nexus slack — Slack slash-command bridge.

Exposes a local HTTP server that handles Slack slash commands and formats
project status as Slack Block Kit payloads.

Slash command text routing (all via /nexus <text>):
  status         — project health overview (default)
  next [N]       — N ready tasks (default 5)
  add <title>    — create a task
  done <id>      — mark task #id as done
  agent          — trigger AI scrum-master pass (async via response_url)
  help           — usage reference

Examples
--------
nexus slack serve --port 3000 --project-id 1
nexus slack serve --secret $SLACK_SIGNING_SECRET --project-id 1
nexus slack format 1
nexus slack ping https://hooks.slack.com/services/...
"""

from __future__ import annotations

import hashlib
import hmac
import json
import signal
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

import click
from rich.rule import Rule
from rich.syntax import Syntax

from ..commands.config import load_config
from ..db import Database
from ..models import Priority, Status
from ..ui import STATUS_ICONS, console, print_error, print_info


# ── Slack Block Kit helpers ────────────────────────────────────────────────────


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _mrkdwn(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _divider() -> dict:
    return {"type": "divider"}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _ephemeral(text: str) -> dict:
    """Visible only to the user who ran the slash command."""
    return {"response_type": "ephemeral", "text": text}


def _in_channel(blocks: list[dict]) -> dict:
    """Visible to the entire channel."""
    return {"response_type": "in_channel", "blocks": blocks}


_PRIO_EMOJI: dict[Priority, str] = {
    Priority.CRITICAL: "🔴",
    Priority.HIGH: "🟠",
    Priority.MEDIUM: "🟡",
    Priority.LOW: "⚪",
}


def _slack_prio(p: Priority) -> str:
    return f"{_PRIO_EMOJI.get(p, '')} {p.value}"


# ── Signing verification ───────────────────────────────────────────────────────


def _verify_slack_signature(
    signing_secret: str,
    timestamp: str,
    body: str,
    signature: str,
) -> bool:
    """Verify a Slack request using HMAC-SHA256 signing (v0 scheme).

    Returns False if the timestamp is stale (>5 min) or the signature
    doesn't match — either condition should cause a 403 response.
    """
    try:
        if abs(time.time() - float(timestamp)) > 300:
            return False
        base = f"v0:{timestamp}:{body}"
        mac = hmac.new(signing_secret.encode(), base.encode(), digestmod=hashlib.sha256)
        expected = "v0=" + mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


# ── Slack HTTP post ────────────────────────────────────────────────────────────


def _post_to_slack(url: str, payload: dict) -> None:
    """POST a JSON payload to a Slack response_url or incoming webhook."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


# ── Command handlers (pure functions — easy to unit-test) ─────────────────────


def _cmd_status(db: Database, project_id: int) -> dict:
    """Return Block Kit payload for project health overview."""
    project = db.get_project(project_id)
    if not project:
        return _ephemeral(f"Project #{project_id} not found.")

    stats = db.project_stats(project_id)
    if stats is None:
        return _ephemeral(f"No stats available for project #{project_id}.")

    from ..commands.project import _compute_health  # lazy — avoids circular import

    health = _compute_health(db, project_id)
    grade = health.get("grade", "?")
    score = health.get("score", 0)

    done_pct = (
        int(stats.done_tasks / stats.total_tasks * 100) if stats.total_tasks > 0 else 0
    )

    overview_lines = [
        f"*Health:* {grade}  ({score}/100)",
        f"*Progress:* {stats.done_tasks}/{stats.total_tasks} done ({done_pct}%)  •  "
        f"{stats.in_progress_tasks} in progress  •  {stats.blocked_tasks} blocked",
    ]
    if project.description:
        overview_lines.insert(0, f"_{project.description}_\n")

    blocks: list[dict] = [
        _header(f"📋 {project.name}"),
        _mrkdwn("\n".join(overview_lines)),
    ]

    # Ready tasks
    ready = [t for t in db.get_ready_tasks(project_id) if t.status == Status.TODO]
    if ready:
        lines = "\n".join(
            f"  {_PRIO_EMOJI.get(t.priority, '')} *#{t.id}* {t.title}"
            for t in ready[:5]
        )
        if len(ready) > 5:
            lines += f"\n  _…and {len(ready) - 5} more_"
        blocks += [_divider(), _mrkdwn(f"*Ready to start ({len(ready)}):*\n{lines}")]

    # Blocked tasks
    blocked = [
        t for t in db.list_tasks(project_id=project_id) if t.status == Status.BLOCKED
    ]
    if blocked:
        lines = "\n".join(f"  ✗ *#{t.id}* {t.title}" for t in blocked[:5])
        if len(blocked) > 5:
            lines += f"\n  _…and {len(blocked) - 5} more_"
        blocks.append(_mrkdwn(f"*Blocked ({len(blocked)}):*\n{lines}"))

    blocks.append(
        _context(
            f"_nexus · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
        )
    )
    return _in_channel(blocks)


def _cmd_next(db: Database, project_id: int, limit: int = 5) -> dict:
    """Return Block Kit payload for the next N ready tasks."""
    ready = [t for t in db.get_ready_tasks(project_id) if t.status == Status.TODO]
    if not ready:
        return _ephemeral("No tasks are ready to start right now. 🎉")

    _prio_order = {
        Priority.CRITICAL: 0,
        Priority.HIGH: 1,
        Priority.MEDIUM: 2,
        Priority.LOW: 3,
    }
    ready.sort(key=lambda t: _prio_order.get(t.priority, 9))

    shown = ready[:limit]
    lines = "\n".join(
        f"  {_PRIO_EMOJI.get(t.priority, '')} *#{t.id}* {t.title}  _{t.priority.value}_"
        for t in shown
    )

    blocks: list[dict] = [
        _header("⚡ Next Tasks"),
        _mrkdwn(lines),
        _context(
            f"Showing {len(shown)} of {len(ready)} ready tasks"
            "  ·  `/nexus next N` for more"
        ),
    ]
    return _in_channel(blocks)


def _cmd_add(db: Database, project_id: int, title: str, user_name: str) -> dict:
    """Create a task and return a Block Kit confirmation."""
    task = db.create_task(project_id=project_id, title=title)
    blocks: list[dict] = [
        _mrkdwn(f"✅ *Task #{task.id} created* by @{user_name}\n>{title}"),
        _context(
            f"Priority: {_slack_prio(task.priority)}  •  Status: todo  •  "
            f"Mark done with `/nexus done {task.id}`"
        ),
    ]
    return _in_channel(blocks)


def _cmd_done(db: Database, project_id: int, arg: str) -> dict:  # noqa: ARG001
    """Mark a task done and return a Block Kit confirmation."""
    tid_str = arg.lstrip("#").strip()
    if not tid_str.isdigit():
        return _ephemeral("Usage: `/nexus done <task_id>`  e.g. `/nexus done 42`")
    task = db.update_task(int(tid_str), status=Status.DONE)
    if not task:
        return _ephemeral(f"Task #{tid_str} not found.")
    return _in_channel([_mrkdwn(f"✅ *Task #{task.id} marked done!*\n>{task.title}")])


def _cmd_help() -> dict:
    """Return an ephemeral help reference card."""
    text = (
        "*nexus slash commands*\n"
        "  `/nexus`               — project health overview\n"
        "  `/nexus status`        — project health overview\n"
        "  `/nexus next [N]`      — next N ready tasks (default 5)\n"
        "  `/nexus add <title>`   — create a new task\n"
        "  `/nexus done <id>`     — mark a task as done\n"
        "  `/nexus agent`         — AI scrum-master review (async)\n"
        "  `/nexus help`          — this message"
    )
    return _ephemeral(text)


def _route_command(
    db: Database,
    project_id: int,
    text: str,
    user_name: str,
    response_url: str,
) -> dict:
    """Parse the slash command text and dispatch to the correct handler."""
    parts = text.strip().split(None, 1)
    sub = parts[0].lower() if parts else "status"
    arg = parts[1] if len(parts) > 1 else ""

    if sub in ("status", ""):
        return _cmd_status(db, project_id)
    if sub == "next":
        limit = int(arg) if arg.strip().isdigit() else 5
        return _cmd_next(db, project_id, limit)
    if sub == "add":
        if not arg:
            return _ephemeral("Usage: `/nexus add <task title>`")
        return _cmd_add(db, project_id, arg, user_name)
    if sub == "done":
        if not arg:
            return _ephemeral("Usage: `/nexus done <task_id>`  e.g. `/nexus done 42`")
        return _cmd_done(db, project_id, arg)
    if sub == "agent":
        if not response_url:
            return _ephemeral("No response_url provided — cannot deliver async result.")
        threading.Thread(
            target=_async_agent,
            args=(db, project_id, response_url),
            daemon=True,
        ).start()
        return _ephemeral("⟳ Running AI scrum-master review… I'll post here when done.")
    if sub == "help":
        return _cmd_help()
    return _ephemeral(f"Unknown subcommand: `{sub}`. Try `/nexus help`.")


# ── Async AI agent pass ────────────────────────────────────────────────────────


def _async_agent(db: Database, project_id: int, response_url: str) -> None:
    """Run an AI agent review in a background thread, post results to response_url."""
    try:
        from ..ai import AGENT_TOOLS, NexusAI, agent_system_prompt
        from ..commands.agent import _handle_tool
        from ..commands.project import _compute_health

        project = db.get_project(project_id)
        if not project:
            _post_to_slack(response_url, {"text": f"Project #{project_id} not found."})
            return

        ai = NexusAI()
        if not ai.available:
            _post_to_slack(
                response_url,
                {"text": "AI not available — no API key configured."},
            )
            return
        if not ai.supports_tools:
            _post_to_slack(
                response_url,
                {"text": "AI agent requires Anthropic — Gemini does not support tool use."},
            )
            return

        tasks = db.list_tasks(project_id=project_id)
        stats = db.project_stats(project_id)
        health = _compute_health(db, project_id)
        system = agent_system_prompt(project.name, project.description or "")

        context_lines = [
            f"Project: {project.name} (id={project.id})",
            f"Health: {health['grade']} ({health['score']}/100)",
        ]
        if stats:
            context_lines.append(
                f"Tasks: {stats.total_tasks} total, {stats.done_tasks} done, "
                f"{stats.blocked_tasks} blocked"
            )
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
                name, inputs, db, project_id, write_log,
                dry_run=False,
                auto_yes=True,
            )

        ai.chat_turn(
            messages, AGENT_TOOLS, tool_handler,
            system=system_with_ctx, max_tokens=2048,
        )

        if write_log:
            changes = "\n".join(f"  • {e}" for e in write_log)
            text = (
                f"✅ AI agent made *{len(write_log)} change(s)* "
                f"to *{project.name}*:\n{changes}"
            )
        else:
            text = f"✓ AI agent reviewed *{project.name}* — no changes needed."

        _post_to_slack(response_url, {"text": text, "response_type": "in_channel"})

    except Exception as exc:
        try:
            _post_to_slack(response_url, {"text": f"Agent error: {exc}"})
        except Exception:
            pass


# ── HTTP request handler ───────────────────────────────────────────────────────


def _make_handler(
    db: Database,
    project_id: int,
    signing_secret: Optional[str],
):
    """Return a BaseHTTPRequestHandler class bound to the given db and project."""

    class _SlackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Health-check endpoint — returns 200 OK."""
            self._respond(200, {"status": "ok", "service": "nexus-slack"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body = raw.decode("utf-8", errors="replace")

            # Signature verification (optional but strongly recommended)
            if signing_secret:
                ts = self.headers.get("X-Slack-Request-Timestamp", "")
                sig = self.headers.get("X-Slack-Signature", "")
                if not _verify_slack_signature(signing_secret, ts, body, sig):
                    self._respond(403, {"error": "Invalid Slack signature."})
                    return

            params = dict(urllib.parse.parse_qsl(body))
            text = params.get("text", "")
            response_url = params.get("response_url", "")
            user_name = params.get("user_name", "someone")

            payload = _route_command(db, project_id, text, user_name, response_url)
            self._respond(200, payload)

        def _respond(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:
            # Forward to Rich console instead of stderr
            console.print(
                f"  [dim]{self.address_string()} — {fmt % args}[/dim]"
            )

    return _SlackHandler


# ── CLI group ──────────────────────────────────────────────────────────────────


@click.group("slack")
def slack_cmd() -> None:
    """Slack slash-command bridge for nexus."""


@slack_cmd.command("serve")
@click.option(
    "--port", "-p",
    type=int,
    default=3000,
    show_default=True,
    help="TCP port to listen on.",
)
@click.option(
    "--secret",
    envvar="SLACK_SIGNING_SECRET",
    default=None,
    metavar="TOKEN",
    help=(
        "Slack signing secret for HMAC request verification "
        "(or SLACK_SIGNING_SECRET env var). "
        "Omit for dev/test mode — all requests accepted."
    ),
)
@click.option(
    "--project-id", "-P",
    type=int,
    default=None,
    envvar="NEXUS_PROJECT_ID",
    help="Project to target. Falls back to config default_project.",
)
@click.pass_obj
def slack_serve(
    db: Database,
    port: int,
    secret: Optional[str],
    project_id: Optional[int],
) -> None:
    """Start a local HTTP server that handles Slack slash commands.

    \b
    Configure your Slack app:
      Request URL → http://your-host:<port>
      (Use ngrok to expose localhost: ngrok http <port>)

    \b
    Slash command text:
      /nexus               health overview
      /nexus next [N]      N ready tasks
      /nexus add <title>   create a task
      /nexus done <id>     mark task done
      /nexus agent         AI scrum-master (async)
      /nexus help          usage reference

    Press Ctrl-C to stop.
    """
    # ── Resolve project ───────────────────────────────────────────────────────
    pid = project_id
    if pid is None:
        cfg = load_config()
        pid = cfg.get("default_project")
    if pid is None:
        print_error(
            "No project specified. Pass --project-id, "
            "or set: nexus config set default_project <id>"
        )
        raise SystemExit(1)

    project = db.get_project(pid)
    if not project:
        print_error(f"Project #{pid} not found.")
        raise SystemExit(1)

    # ── Start server ──────────────────────────────────────────────────────────
    handler_class = _make_handler(db, pid, secret)
    server = HTTPServer(("", port), handler_class)

    console.print()
    console.print(Rule("[nexus.title]nexus slack serve[/nexus.title]", style="cyan"))
    console.print(f"  Project   : [bold]#{project.id} · {project.name}[/bold]")
    console.print(f"  Listening : [bold]http://localhost:{port}[/bold]")
    console.print(
        f"  Signature : [bold]"
        f"{'✓ enabled' if secret else '✗ disabled (dev mode — accepts all requests)'}[/bold]"
    )
    console.print()
    console.print("  Configure your Slack app Request URL:")
    console.print(f"    [cyan]http://your-ngrok-host.ngrok.io[/cyan]")
    console.print()
    console.print("  Press [bold]Ctrl-C[/bold] to stop.\n")

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def _stop(sig, frame):  # noqa: ANN001
        server.shutdown()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        server.serve_forever()
    except Exception:
        pass

    console.print()
    console.print(Rule("[dim]nexus slack serve stopped[/dim]", style="dim"))
    console.print()


@slack_cmd.command("format")
@click.argument("project_id", type=int, required=False, default=None)
@click.pass_obj
def slack_format(db: Database, project_id: Optional[int]) -> None:
    """Print the Slack Block Kit JSON for a project status message.

    Useful for previewing output or building Slack app manifests.

    \b
    Pipe to clipboard:
      nexus slack format 1 | pbcopy   (macOS)
      nexus slack format 1 | xclip    (Linux)
    """
    pid = project_id
    if pid is None:
        cfg = load_config()
        pid = cfg.get("default_project")
    if pid is None:
        print_error(
            "No project specified. Pass a project_id or set: "
            "nexus config set default_project <id>"
        )
        raise SystemExit(1)

    payload = _cmd_status(db, pid)
    console.print(Syntax(json.dumps(payload, indent=2), "json", theme="monokai"))


@slack_cmd.command("ping")
@click.argument("webhook_url")
def slack_ping(webhook_url: str) -> None:
    """POST a test message to a Slack incoming webhook URL.

    Use this to verify your incoming webhook is configured correctly
    before setting up the slash command server.
    """
    payload = {
        "text": "👋 Hello from *nexus*! Your Slack webhook is configured correctly.",
        "blocks": [
            _header("👋 nexus ping"),
            _mrkdwn(
                "Your Slack webhook is configured correctly!\n"
                "Run `nexus slack serve` to start the slash command server."
            ),
        ],
    }
    print_info(f"Posting to {webhook_url!r} …")
    try:
        _post_to_slack(webhook_url, payload)
        print_info("✓ Message sent successfully!")
    except Exception as exc:
        print_error(f"Failed to post to Slack: {exc}")
        raise SystemExit(1)
