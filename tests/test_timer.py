"""Tests for timer commands and sprint velocity/plan."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.commands.timer import _elapsed_str, _round_hours, _timer_path, _load_timer
from nexus.db import Database
from nexus.models import Status


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args):
    return runner.invoke(cli, ["--db", db_path, *args], catch_exceptions=False)


# ── _elapsed_str / _round_hours unit tests ────────────────────────────────────

def test_elapsed_str_zero():
    assert _elapsed_str(0) == "00:00:00"


def test_elapsed_str_components():
    assert _elapsed_str(3661) == "01:01:01"


def test_elapsed_str_hours():
    assert _elapsed_str(7200) == "02:00:00"


def test_round_hours_minimum():
    assert _round_hours(0.0) == 0.25
    assert _round_hours(0.1) == 0.25


def test_round_hours_quarter():
    assert _round_hours(0.26) == 0.25
    assert _round_hours(0.37) == 0.25  # rounds down to 0.25
    assert _round_hours(0.38) == 0.5   # rounds up to 0.5


def test_round_hours_normal():
    assert _round_hours(1.0) == 1.0
    assert _round_hours(1.6) == 1.5
    assert _round_hours(1.9) == 2.0


# ── timer start ───────────────────────────────────────────────────────────────

def test_timer_start_creates_state(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Write tests")
    result = invoke(runner, db_path, "timer", "start", "1")
    assert result.exit_code == 0
    assert "Timer started" in result.output

    db = Database(Path(db_path))
    state = _load_timer(db)
    assert state is not None
    assert state["task_id"] == 1
    assert "started_at" in state


def test_timer_start_missing_task(runner, db_path):
    result = invoke(runner, db_path, "timer", "start", "999")
    assert result.exit_code == 1


def test_timer_start_blocks_second_timer(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Task A")
    invoke(runner, db_path, "task", "add", "1", "Task B")
    invoke(runner, db_path, "timer", "start", "1")
    result = invoke(runner, db_path, "timer", "start", "2")
    assert result.exit_code == 1
    assert "already running" in result.output


# ── timer status ──────────────────────────────────────────────────────────────

def test_timer_status_no_timer(runner, db_path):
    result = invoke(runner, db_path, "timer", "status")
    assert result.exit_code == 0
    assert "No timer" in result.output


def test_timer_status_shows_running(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Code review")
    invoke(runner, db_path, "timer", "start", "1")
    result = invoke(runner, db_path, "timer", "status")
    assert result.exit_code == 0
    assert "Code review" in result.output


# ── timer cancel ──────────────────────────────────────────────────────────────

def test_timer_cancel_clears_state(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Spike")
    invoke(runner, db_path, "timer", "start", "1")
    result = invoke(runner, db_path, "timer", "cancel")
    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()

    db = Database(Path(db_path))
    assert _load_timer(db) is None


def test_timer_cancel_no_timer(runner, db_path):
    result = invoke(runner, db_path, "timer", "cancel")
    assert result.exit_code == 0  # just informs, no error


# ── timer stop ────────────────────────────────────────────────────────────────

def test_timer_stop_no_timer(runner, db_path):
    result = invoke(runner, db_path, "timer", "stop")
    assert result.exit_code == 1
    assert "No timer" in result.output


def test_timer_stop_logs_time(runner, db_path, tmp_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Refactor")
    invoke(runner, db_path, "timer", "start", "1")

    # Patch datetime to simulate 2h elapsed
    from datetime import datetime, timezone, timedelta
    from nexus.commands import timer as timer_mod

    past = datetime.now(timezone.utc) - timedelta(hours=2)
    state_path = _timer_path(Database(Path(db_path)))
    state_path.write_text(json.dumps({
        "task_id": 1,
        "started_at": past.isoformat(),
    }))

    result = invoke(runner, db_path, "timer", "stop", "-n", "big refactor")
    assert result.exit_code == 0
    assert "Logged" in result.output

    db = Database(Path(db_path))
    task = db.get_task(1)
    assert task.actual_hours == 2.0

    entries = db.list_time_entries(1)
    assert any(e.note == "big refactor" for e in entries)


def test_timer_stop_clears_state(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Review")
    invoke(runner, db_path, "timer", "start", "1")
    invoke(runner, db_path, "timer", "stop")

    db = Database(Path(db_path))
    assert _load_timer(db) is None


# ── sprint velocity ───────────────────────────────────────────────────────────

def test_sprint_velocity_no_sprints(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "sprint", "velocity", "1")
    assert result.exit_code == 0
    assert "No sprints" in result.output


def test_sprint_velocity_missing_project(runner, db_path):
    result = invoke(runner, db_path, "sprint", "velocity", "999")
    assert result.exit_code == 1


def test_sprint_velocity_shows_table(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "sprint", "new", "1", "Sprint 1")
    invoke(runner, db_path, "task", "add", "1", "Task A", "-e", "3.0", "-s", "1")
    invoke(runner, db_path, "task", "add", "1", "Task B", "-e", "2.0", "-s", "1")
    invoke(runner, db_path, "task", "done", "1")
    invoke(runner, db_path, "sprint", "close", "1")

    result = invoke(runner, db_path, "sprint", "velocity", "1")
    assert result.exit_code == 0
    assert "Sprint Velocity" in result.output
    assert "Sprint 1" in result.output
    assert "done" in result.output


def test_sprint_velocity_average_shown_for_multiple_completed(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")

    # Sprint 1
    invoke(runner, db_path, "sprint", "new", "1", "S1")
    invoke(runner, db_path, "task", "add", "1", "T1", "-e", "4.0", "-s", "1")
    invoke(runner, db_path, "task", "log", "1", "4.0")
    invoke(runner, db_path, "task", "done", "1")
    invoke(runner, db_path, "sprint", "close", "1")

    # Sprint 2
    invoke(runner, db_path, "sprint", "new", "1", "S2")
    invoke(runner, db_path, "task", "add", "1", "T2", "-e", "6.0", "-s", "2")
    invoke(runner, db_path, "task", "log", "2", "6.0")
    invoke(runner, db_path, "task", "done", "2")
    invoke(runner, db_path, "sprint", "close", "2")

    result = invoke(runner, db_path, "sprint", "velocity", "1")
    assert result.exit_code == 0
    assert "Average velocity" in result.output
    assert "5.0h" in result.output  # (4 + 6) / 2


# ── sprint plan (AI) ─────────────────────────────────────────────────────────

def _mock_ai_stream(chunks):
    mock_client = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.text_stream = iter(chunks)
    mock_client.messages.stream.return_value = mock_ctx
    return mock_client


def test_sprint_plan_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "sprint", "plan", "1")
    assert result.exit_code == 1
    assert "AI provider" in result.output or "KEY" in result.output


def test_sprint_plan_no_backlog(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "sprint", "plan", "1")
    assert result.exit_code == 0
    assert "No backlog" in result.output


def test_sprint_plan_streams_output(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = _mock_ai_stream([
        "**Recommended tasks:** #1 Build login, #2 Add tests\n",
        "**Sprint goal:** Ship auth module\n",
    ])
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Build login", "-p", "high", "-e", "3.0")
    invoke(runner, db_path, "task", "add", "1", "Add tests", "-p", "medium", "-e", "2.0")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "sprint", "plan", "1")

    assert result.exit_code == 0
    assert "Build login" in result.output or "Sprint goal" in result.output


# ── sprint_plan_prompt unit test ─────────────────────────────────────────────

def test_sprint_plan_prompt_includes_backlog():
    from nexus.ai import sprint_plan_prompt
    system, user = sprint_plan_prompt(
        project_name="MyApp",
        backlog=[(1, "Build login", "high", 3.0), (2, "Add tests", "medium", 2.0)],
        in_progress=[(3, "Setup CI")],
        capacity=10.0,
        past_velocity=8.0,
    )
    assert "MyApp" in user
    assert "Build login" in user
    assert "Setup CI" in user
    assert "10.0h" in user
    assert "8.0h" in user
