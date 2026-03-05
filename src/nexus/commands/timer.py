"""Timer commands — live stopwatch for task time tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click

from ..db import Database
from ..ui import console, print_error, print_info, print_success


def _timer_path(db: Database) -> Path:
    """Return the timer state file path (lives next to the database)."""
    return db.path.parent / "timer.json"


def _load_timer(db: Database) -> dict | None:
    p = _timer_path(db)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_timer(db: Database, data: dict) -> None:
    p = _timer_path(db)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def _clear_timer(db: Database) -> None:
    p = _timer_path(db)
    if p.exists():
        p.unlink()


def _elapsed_str(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _round_hours(raw_hours: float) -> float:
    """Round to nearest 0.25h (15 min), minimum 0.25h."""
    rounded = round(raw_hours * 4) / 4
    return max(rounded, 0.25)


@click.group("timer")
def timer_cmd():
    """Live stopwatch for task time tracking."""


@timer_cmd.command("start")
@click.argument("task_id", type=int)
@click.pass_obj
def timer_start(db: Database, task_id: int):
    """Start the timer for a task."""
    existing = _load_timer(db)
    if existing:
        running_id = existing["task_id"]
        running_task = db.get_task(running_id)
        name = running_task.title if running_task else f"#{running_id}"
        started = datetime.fromisoformat(existing["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        print_error(
            f"Timer already running for '{name}' ({_elapsed_str(elapsed)}). "
            "Stop it first with [bold]nexus timer stop[/bold]."
        )
        raise SystemExit(1)

    task = db.get_task(task_id)
    if not task:
        print_error(f"Task id={task_id} not found.")
        raise SystemExit(1)

    _save_timer(db, {
        "task_id": task_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    print_success(f"Timer started for task [bold]#{task_id}[/bold] '{task.title}'")


@timer_cmd.command("stop")
@click.option("-n", "--note", default="", help="Optional note for the time entry.")
@click.pass_obj
def timer_stop(db: Database, note: str):
    """Stop the timer and log the elapsed time."""
    state = _load_timer(db)
    if not state:
        print_error("No timer is running.")
        raise SystemExit(1)

    task_id = state["task_id"]
    started = datetime.fromisoformat(state["started_at"])
    raw_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    hours = _round_hours(raw_hours)

    task = db.get_task(task_id)
    if not task:
        _clear_timer(db)
        print_error(f"Task #{task_id} no longer exists. Timer cleared.")
        raise SystemExit(1)

    db.log_time(task_id, hours, note)
    _clear_timer(db)

    new_task = db.get_task(task_id)
    elapsed_str = _elapsed_str(raw_hours * 3600)
    print_success(
        f"Logged [bold]{hours:.2f}h[/bold] on task [bold]#{task_id}[/bold] '{task.title}'  "
        f"[dim](elapsed {elapsed_str} → total {new_task.actual_hours:.1f}h)[/dim]"
    )


@timer_cmd.command("status")
@click.pass_obj
def timer_status(db: Database):
    """Show the current running timer."""
    state = _load_timer(db)
    if not state:
        print_info("No timer is running.")
        return

    task_id = state["task_id"]
    started = datetime.fromisoformat(state["started_at"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    task = db.get_task(task_id)
    task_name = task.title if task else f"Task #{task_id}"

    console.print(f"\n  ● [bold cyan]{task_name}[/bold cyan]  [dim](#{task_id})[/dim]")
    console.print(f"  [bold yellow]{_elapsed_str(elapsed)}[/bold yellow]  elapsed")
    started_local = started.strftime("%H:%M:%S")
    console.print(f"  [dim]Started at {started_local} UTC[/dim]\n")


@timer_cmd.command("cancel")
@click.pass_obj
def timer_cancel(db: Database):
    """Cancel the running timer without logging any time."""
    state = _load_timer(db)
    if not state:
        print_info("No timer is running.")
        return

    task_id = state["task_id"]
    task = db.get_task(task_id)
    name = task.title if task else f"#{task_id}"
    _clear_timer(db)
    print_info(f"Timer for '{name}' cancelled (no time logged).")
