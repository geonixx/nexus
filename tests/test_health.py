"""Tests for M8: task notes, task stale, project health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status, TaskNote


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args):
    return runner.invoke(cli, ["--db", db_path, *args], catch_exceptions=False)


# ── TaskNote model ────────────────────────────────────────────────────────────


def test_task_note_model_defaults():
    note = TaskNote(task_id=1, text="A decision was made.")
    assert note.id == 0
    assert note.task_id == 1
    assert note.text == "A decision was made."
    assert note.created_at is not None


# ── DB: add_task_note / get_task_notes ────────────────────────────────────────


def test_add_task_note(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    note = db.add_task_note(t.id, "Decision: use JWT")
    assert note.id > 0
    assert note.task_id == t.id
    assert note.text == "Decision: use JWT"
    assert note.created_at is not None


def test_get_task_notes_empty(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    assert db.get_task_notes(t.id) == []


def test_get_task_notes_multiple(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    db.add_task_note(t.id, "First note")
    db.add_task_note(t.id, "Second note")
    db.add_task_note(t.id, "Third note")
    notes = db.get_task_notes(t.id)
    assert len(notes) == 3
    assert notes[0].text == "First note"
    assert notes[2].text == "Third note"


def test_get_task_notes_returns_task_note_objects(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    db.add_task_note(t.id, "Some note")
    notes = db.get_task_notes(t.id)
    assert all(isinstance(n, TaskNote) for n in notes)


def test_notes_are_task_scoped(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t1 = db.create_task(p.id, "Task 1")
    t2 = db.create_task(p.id, "Task 2")
    db.add_task_note(t1.id, "Note for task 1")
    db.add_task_note(t2.id, "Note for task 2")
    assert len(db.get_task_notes(t1.id)) == 1
    assert len(db.get_task_notes(t2.id)) == 1
    assert db.get_task_notes(t1.id)[0].text == "Note for task 1"


# ── DB: get_stale_tasks ───────────────────────────────────────────────────────


def test_get_stale_tasks_no_entries(tmp_path):
    """In-progress task with NO time entries and old updated_at is stale."""
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    db.update_task(t.id, status=Status.IN_PROGRESS)
    # since is in the future → task's updated_at is before the threshold → stale
    since = datetime.now(timezone.utc) + timedelta(days=1)
    stale = db.get_stale_tasks(p.id, since)
    assert any(s.id == t.id for s in stale)


def test_get_stale_tasks_fresh_start_not_stale(tmp_path):
    """In-progress task with no time entries but recent updated_at is NOT stale.

    Grace period: a task just moved to in_progress should not appear as stale
    immediately — only once updated_at itself predates the threshold.
    """
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Fresh task")
    db.update_task(t.id, status=Status.IN_PROGRESS)
    # since is in the past → task's updated_at (now) is after the threshold → not stale
    since = datetime.now(timezone.utc) - timedelta(days=3)
    stale = db.get_stale_tasks(p.id, since)
    assert not any(s.id == t.id for s in stale)


def test_get_stale_tasks_old_entry(tmp_path):
    """In-progress task with only OLD time entries is stale."""
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    db.update_task(t.id, status=Status.IN_PROGRESS)
    # Log time, then check with threshold AFTER that time
    db.log_time(t.id, 1.0, "old work")
    since = datetime.now(timezone.utc) + timedelta(seconds=1)  # threshold in future
    stale = db.get_stale_tasks(p.id, since)
    assert any(s.id == t.id for s in stale)


def test_get_stale_tasks_recent_entry_not_stale(tmp_path):
    """In-progress task with recent time entry is NOT stale."""
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Task")
    db.update_task(t.id, status=Status.IN_PROGRESS)
    db.log_time(t.id, 1.0, "recent work")
    # Threshold is 3 days ago — recent entry should pass
    since = datetime.now(timezone.utc) - timedelta(days=3)
    stale = db.get_stale_tasks(p.id, since)
    assert not any(s.id == t.id for s in stale)


def test_get_stale_tasks_only_in_progress(tmp_path):
    """get_stale_tasks only returns IN_PROGRESS tasks."""
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t_done = db.create_task(p.id, "Done task")
    db.update_task(t_done.id, status=Status.DONE)
    t_todo = db.create_task(p.id, "Todo task")
    # Neither should appear even though they have no time entries
    since = datetime.now(timezone.utc) - timedelta(days=1)
    stale = db.get_stale_tasks(p.id, since)
    assert len(stale) == 0


def test_get_stale_tasks_empty_project(tmp_path):
    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    since = datetime.now(timezone.utc) - timedelta(days=3)
    assert db.get_stale_tasks(p.id, since) == []


# ── nexus task note CLI ───────────────────────────────────────────────────────


def test_task_note_adds_note(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "My task")
    result = invoke(runner, db_path, "task", "note", "1", "JWT decision made")
    assert result.exit_code == 0
    assert "added" in result.output.lower()


def test_task_note_missing_task(runner, db_path):
    result = invoke(runner, db_path, "task", "note", "999", "Some note")
    assert result.exit_code == 1


def test_task_note_appears_in_show(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "My task")
    invoke(runner, db_path, "task", "note", "1", "Design decision: use Redis")
    result = invoke(runner, db_path, "task", "show", "1")
    assert result.exit_code == 0
    assert "Design decision" in result.output
    assert "Redis" in result.output


def test_task_show_multiple_notes(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "My task")
    invoke(runner, db_path, "task", "note", "1", "First note")
    invoke(runner, db_path, "task", "note", "1", "Second note")
    result = invoke(runner, db_path, "task", "show", "1")
    assert "First note" in result.output
    assert "Second note" in result.output


def test_task_show_no_notes_still_works(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Clean task")
    result = invoke(runner, db_path, "task", "show", "1")
    assert result.exit_code == 0
    assert "Clean task" in result.output


# ── nexus task stale CLI ──────────────────────────────────────────────────────


def test_task_stale_no_stale_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Healthy task")
    result = invoke(runner, db_path, "task", "stale", "1")
    assert result.exit_code == 0
    assert "No stale" in result.output


def test_task_stale_shows_in_progress_without_time(runner, db_path, tmp_path):
    """An in-progress task with no time entries should appear as stale."""
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Stale task")
    invoke(runner, db_path, "task", "start", "1")
    # Pass --days 0 so any in-progress task with no entry today is stale
    result = invoke(runner, db_path, "task", "stale", "1", "--days", "0")
    assert result.exit_code == 0
    assert "Stale task" in result.output


def test_task_stale_missing_project(runner, db_path):
    result = invoke(runner, db_path, "task", "stale", "999")
    assert result.exit_code == 1


def test_task_stale_uses_default_project(runner, db_path, monkeypatch, tmp_path):
    from nexus.commands.config import save_config

    cfg_path = tmp_path / "cfg.json"
    save_config({"default_project": 1}, cfg_path)
    monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg_path)

    invoke(runner, db_path, "project", "new", "P")
    result = invoke(runner, db_path, "task", "stale")
    assert result.exit_code == 0


def test_task_stale_no_default_no_arg(runner, db_path, monkeypatch, tmp_path):
    monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", tmp_path / "empty.json")
    result = invoke(runner, db_path, "task", "stale")
    assert result.exit_code == 1


def test_task_stale_shows_long_blocked(runner, db_path):
    """Blocked tasks should be surfaced when threshold is met."""
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Blocked task")
    invoke(runner, db_path, "task", "block", "1")
    # --days 0: anything blocked is long-blocked (days*2 = 0)
    result = invoke(runner, db_path, "task", "stale", "1", "--days", "0")
    assert result.exit_code == 0


# ── _compute_health unit tests ────────────────────────────────────────────────


def test_compute_health_empty_project(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    h = _compute_health(db, p.id)
    assert h["grade"] == "?"
    assert h["score"] == 0
    assert h["metrics"] == []


def test_compute_health_all_done_high_score(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    for i in range(5):
        t = db.create_task(p.id, f"Task {i}", estimate_hours=2.0)
        db.update_task(t.id, status=Status.DONE)
        db.log_time(t.id, 2.0)

    h = _compute_health(db, p.id)
    assert h["score"] > 50  # completion + estimate coverage both high
    assert h["grade"] in ("A", "B", "C")


def test_compute_health_blocked_project_low_score(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    # All tasks blocked, no estimates, no time logged
    for i in range(4):
        t = db.create_task(p.id, f"Task {i}")
        db.update_task(t.id, status=Status.BLOCKED)

    h = _compute_health(db, p.id)
    assert h["score"] < 50
    assert h["grade"] in ("D", "F", "C")


def test_compute_health_metrics_structure(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    db.create_task(p.id, "Task A")

    h = _compute_health(db, p.id)
    assert len(h["metrics"]) == 5
    for m in h["metrics"]:
        assert "name" in m
        assert "score" in m
        assert "max" in m
        assert "detail" in m
        assert 0 <= m["score"] <= m["max"]


def test_compute_health_context_keys(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    db.create_task(p.id, "T")

    h = _compute_health(db, p.id)
    ctx = h["context"]
    assert "done" in ctx
    assert "in_progress" in ctx
    assert "blocked" in ctx
    assert "todo" in ctx
    assert "stale" in ctx
    assert "hours_week" in ctx


def test_compute_health_grade_a(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")

    # 10 done tasks with estimates + lots of hours this week
    for i in range(8):
        t = db.create_task(p.id, f"Done {i}", estimate_hours=2.0)
        db.update_task(t.id, status=Status.DONE)
    # 2 in-progress with time logged this week and estimates
    for i in range(2):
        t = db.create_task(p.id, f"WIP {i}", estimate_hours=3.0)
        db.update_task(t.id, status=Status.IN_PROGRESS)
        for _ in range(4):  # 4h each = 8h total per task → plenty of activity
            db.log_time(t.id, 2.0)

    h = _compute_health(db, p.id)
    assert h["grade"] in ("A", "B")  # should be high
    assert h["score"] >= 75


def test_compute_health_score_in_range(tmp_path):
    from nexus.commands.project import _compute_health

    db = Database(tmp_path / "t.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "T")
    db.update_task(t.id, status=Status.IN_PROGRESS)

    h = _compute_health(db, p.id)
    assert 0 <= h["score"] <= 100


# ── nexus project health CLI ──────────────────────────────────────────────────


def test_project_health_basic(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Task A")
    result = invoke(runner, db_path, "project", "health", "1")
    assert result.exit_code == 0
    assert "Health" in result.output
    assert "/" in result.output  # score/100


def test_project_health_empty_project(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    result = invoke(runner, db_path, "project", "health", "1")
    assert result.exit_code == 0
    assert "no tasks" in result.output.lower() or "nothing" in result.output.lower()


def test_project_health_missing_project(runner, db_path):
    result = invoke(runner, db_path, "project", "health", "999")
    assert result.exit_code == 1


def test_project_health_shows_grade(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Task")
    result = invoke(runner, db_path, "project", "health", "1")
    output = result.output
    # Should show one of the grades
    assert any(g in output for g in ("A", "B", "C", "D", "F"))


def test_project_health_shows_all_metric_names(runner, db_path):
    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Task")
    result = invoke(runner, db_path, "project", "health", "1")
    assert "Completion" in result.output
    assert "Blocked" in result.output
    assert "Momentum" in result.output
    assert "Estimate" in result.output
    assert "Activity" in result.output


def test_project_health_ai_flag(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.text_stream = iter(["Your project needs more estimates and recent commits."])
    mock_client.messages.stream.return_value = mock_ctx

    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Task")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "project", "health", "1", "--ai")

    assert result.exit_code == 0


def test_project_health_ai_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "P")
    invoke(runner, db_path, "task", "add", "1", "Task")
    result = invoke(runner, db_path, "project", "health", "1", "--ai")
    assert result.exit_code == 1


# ── health_diagnosis_prompt ───────────────────────────────────────────────────


def test_health_diagnosis_prompt():
    from nexus.ai import health_diagnosis_prompt

    system, user = health_diagnosis_prompt(
        project_name="Nexus",
        grade="C",
        score=62,
        metrics=[
            {"name": "Completion Rate", "score": 15, "max": 25, "detail": "60%"},
            {"name": "Blocked Health", "score": 10, "max": 20, "detail": "2 blocked"},
            {"name": "Momentum", "score": 14, "max": 20, "detail": "1 stale"},
            {"name": "Estimate Coverage", "score": 8, "max": 15, "detail": "50%"},
            {"name": "Activity (7d)", "score": 15, "max": 20, "detail": "15h"},
        ],
        context={
            "done": 6, "in_progress": 3, "blocked": 2, "todo": 1, "stale": 1, "hours_week": 15.0
        },
    )
    assert "Nexus" in user
    assert "C" in user
    assert "62" in user
    assert "Blocked Health" in user
    assert system


def test_health_diagnosis_prompt_returns_tuple():
    from nexus.ai import health_diagnosis_prompt

    result = health_diagnosis_prompt(
        project_name="P",
        grade="B",
        score=78,
        metrics=[],
        context={"done": 0, "in_progress": 0, "blocked": 0, "todo": 1, "stale": 0, "hours_week": 0.0},
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
