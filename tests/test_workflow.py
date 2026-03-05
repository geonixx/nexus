"""Tests for M6 features: config, task next/bulk, report week."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.commands.config import _coerce, load_config, save_config
from nexus.db import Database
from nexus.models import Priority, Status


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args):
    return runner.invoke(cli, ["--db", db_path, *args], catch_exceptions=False)


# ── _coerce unit tests ────────────────────────────────────────────────────────

def test_coerce_int():
    assert _coerce("42") == 42
    assert isinstance(_coerce("42"), int)


def test_coerce_float():
    assert _coerce("3.14") == pytest.approx(3.14)


def test_coerce_bool():
    assert _coerce("true") is True
    assert _coerce("false") is False
    assert _coerce("True") is True


def test_coerce_string():
    assert _coerce("hello") == "hello"
    assert _coerce("my-project") == "my-project"


# ── config set / get / show / unset ──────────────────────────────────────────

def test_config_set_and_get(runner, db_path, tmp_path):
    cfg_path = tmp_path / "cfg.json"
    data = {}
    save_config({"default_project": 3}, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded["default_project"] == 3


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect CONFIG_PATH to a temp file for every test in this module."""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg)
    yield cfg


def test_config_set_via_cli(runner, db_path, _isolate_config):
    result = invoke(runner, db_path, "config", "set", "default_project", "7")
    assert result.exit_code == 0
    assert "default_project" in result.output
    assert load_config(_isolate_config)["default_project"] == 7


def test_config_get_missing_key(runner, db_path):
    result = invoke(runner, db_path, "config", "get", "nonexistent")
    assert result.exit_code == 1
    assert "not set" in result.output


def test_config_show_empty(runner, db_path):
    result = invoke(runner, db_path, "config", "show")
    assert result.exit_code == 0
    assert "No configuration" in result.output


def test_config_show_with_values(runner, db_path, _isolate_config):
    save_config({"default_project": 2, "ai_max_tokens": 2048}, _isolate_config)
    result = invoke(runner, db_path, "config", "show")
    assert result.exit_code == 0
    assert "default_project" in result.output
    assert "2" in result.output


def test_config_unset(runner, db_path, _isolate_config):
    save_config({"default_project": 1}, _isolate_config)
    result = invoke(runner, db_path, "config", "unset", "default_project")
    assert result.exit_code == 0
    assert load_config(_isolate_config).get("default_project") is None


def test_config_unset_missing_key(runner, db_path):
    result = invoke(runner, db_path, "config", "unset", "nope")
    assert result.exit_code == 1


# ── task next ────────────────────────────────────────────────────────────────

def test_task_next_shows_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "Alpha")
    invoke(runner, db_path, "task", "add", "1", "Low task", "-p", "low")
    invoke(runner, db_path, "task", "add", "1", "Critical task", "-p", "critical")
    invoke(runner, db_path, "task", "add", "1", "High task", "-p", "high")

    result = invoke(runner, db_path, "task", "next", "1")
    assert result.exit_code == 0
    assert "Critical task" in result.output
    # Critical should appear before high (higher priority)
    assert result.output.index("Critical task") < result.output.index("High task")


def test_task_next_in_progress_first(runner, db_path):
    invoke(runner, db_path, "project", "new", "Alpha")
    invoke(runner, db_path, "task", "add", "1", "Low todo", "-p", "low")
    invoke(runner, db_path, "task", "add", "1", "Active task", "-p", "low")
    invoke(runner, db_path, "task", "start", "2")

    result = invoke(runner, db_path, "task", "next", "1")
    assert result.exit_code == 0
    # In-progress should come first
    assert result.output.index("Active task") < result.output.index("Low todo")


def test_task_next_no_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "Empty")
    result = invoke(runner, db_path, "task", "next", "1")
    assert result.exit_code == 0
    assert "No actionable" in result.output


def test_task_next_missing_project(runner, db_path):
    result = invoke(runner, db_path, "task", "next", "999")
    assert result.exit_code == 1


def test_task_next_uses_default_project(runner, db_path, _isolate_config):
    # _isolate_config already redirects CONFIG_PATH; write default_project into it
    save_config({"default_project": 1}, _isolate_config)

    invoke(runner, db_path, "project", "new", "Beta")
    invoke(runner, db_path, "task", "add", "1", "Default project task")

    result = invoke(runner, db_path, "task", "next")
    assert result.exit_code == 0
    assert "Default project task" in result.output


def test_task_next_no_default_no_arg(runner, db_path):
    # _isolate_config fixture already gives an empty config file
    result = invoke(runner, db_path, "task", "next")
    assert result.exit_code == 1
    assert "default_project" in result.output


def test_task_next_count_option(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    for i in range(8):
        invoke(runner, db_path, "task", "add", "1", f"Task {i+1}")

    result = invoke(runner, db_path, "task", "next", "1", "-n", "3")
    assert result.exit_code == 0
    assert "more tasks" in result.output


# ── task bulk ────────────────────────────────────────────────────────────────

def test_task_bulk_done(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Task A")
    invoke(runner, db_path, "task", "add", "1", "Task B")
    invoke(runner, db_path, "task", "add", "1", "Task C")

    result = invoke(runner, db_path, "task", "bulk", "done", "1", "2", "3")
    assert result.exit_code == 0
    assert "3 task(s) marked done" in result.output

    db = Database(Path(db_path))
    for tid in [1, 2, 3]:
        assert db.get_task(tid).status == Status.DONE


def test_task_bulk_start(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "A")
    invoke(runner, db_path, "task", "add", "1", "B")

    result = invoke(runner, db_path, "task", "bulk", "start", "1", "2")
    assert result.exit_code == 0
    assert "2 task(s) started" in result.output


def test_task_bulk_sprint(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "sprint", "new", "1", "Sprint Alpha")
    invoke(runner, db_path, "task", "add", "1", "T1")
    invoke(runner, db_path, "task", "add", "1", "T2")
    invoke(runner, db_path, "task", "add", "1", "T3")

    result = invoke(runner, db_path, "task", "bulk", "sprint", "1", "1", "2", "3")
    assert result.exit_code == 0
    assert "3 task(s)" in result.output

    db = Database(Path(db_path))
    for tid in [1, 2, 3]:
        assert db.get_task(tid).sprint_id == 1


def test_task_bulk_sprint_missing_sprint(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "T1")
    result = invoke(runner, db_path, "task", "bulk", "sprint", "999", "1")
    assert result.exit_code == 1


def test_task_bulk_with_missing_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Real task")

    result = invoke(runner, db_path, "task", "bulk", "done", "1", "999")
    assert result.exit_code == 0
    assert "1 task(s) marked done" in result.output
    assert "skipped" in result.output


def test_task_bulk_sprint_needs_sprint_id(runner, db_path):
    result = invoke(runner, db_path, "task", "bulk", "sprint", "1")
    assert result.exit_code == 1
    assert "sprint_id" in result.output.lower() or "needs" in result.output.lower()


# ── db.time_entries_since / tasks_completed_since ────────────────────────────

def test_db_time_entries_since(tmp_path):
    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task X")
    entry = db.log_time(t.id, 2.0, "work")

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    results = db.time_entries_since(p.id, since)
    assert len(results) == 1
    assert results[0][0].hours == 2.0
    assert results[0][1] == "Task X"

    # Future since should return nothing
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert db.time_entries_since(p.id, future) == []


def test_db_tasks_completed_since(tmp_path):
    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Finish me")
    db.update_task(
        t.id,
        status=Status.DONE,
        completed_at=datetime.now(timezone.utc),
    )

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    results = db.tasks_completed_since(p.id, since)
    assert len(results) == 1
    assert results[0].title == "Finish me"

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert db.tasks_completed_since(p.id, future) == []


# ── report week ───────────────────────────────────────────────────────────────

def test_report_week_basic(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "T1")
    invoke(runner, db_path, "task", "log", "1", "2.0", "-n", "good work")
    invoke(runner, db_path, "task", "done", "1")

    result = invoke(runner, db_path, "report", "week", "1")
    assert result.exit_code == 0
    assert "Week Report" in result.output
    assert "2.0h" in result.output
    assert "T1" in result.output


def test_report_week_missing_project(runner, db_path):
    result = invoke(runner, db_path, "report", "week", "999")
    assert result.exit_code == 1


def test_report_week_empty(runner, db_path):
    invoke(runner, db_path, "project", "new", "Empty")
    result = invoke(runner, db_path, "report", "week", "1")
    assert result.exit_code == 0
    assert "0.0h" in result.output
    assert "(none)" in result.output


def test_report_week_ai_flag(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.text_stream = iter(["Great week! Keep it up."])
    mock_client.messages.stream.return_value = mock_ctx

    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Build thing")
    invoke(runner, db_path, "task", "done", "1")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "report", "week", "1", "--ai")

    assert result.exit_code == 0
    assert "AI narrative" in result.output or "Great week" in result.output


# ── weekly_report_prompt unit test ────────────────────────────────────────────

def test_weekly_report_prompt():
    from nexus.ai import weekly_report_prompt
    system, user = weekly_report_prompt(
        project_name="Nexus",
        period_label="Mar 1–7, 2026",
        hours_by_day=[("Mon", 3.0), ("Tue", 2.0), ("Wed", 0.0)],
        total_hours=5.0,
        tasks_completed=["Write tests", "Fix bug"],
        tasks_in_progress=["Build feature"],
        tasks_added=3,
    )
    assert "Nexus" in user
    assert "Mar 1–7" in user
    assert "5.0h" in user
    assert "Write tests" in user
    assert "Build feature" in user
    assert "3" in user  # tasks_added
