"""Tests for M14: nexus watch — background project monitoring daemon.

Covers:
- _age helper — human-readable age formatting
- _prio helper — priority display with colour markup
- _check_project — stale task detection, blocked count, ready tasks info
- watch_cmd CLI — stops after one cycle via patched time.sleep + SIGINT
- _run_agent_pass — AI available, AI unavailable, Gemini-only skip, errors
"""

from __future__ import annotations

import signal
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status
from nexus.commands.watch import _age, _prio, _check_project, _run_agent_pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def project(db):
    return db.create_project("WatchTest", description="For watch tests")


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, db, *args, **kwargs):
    return runner.invoke(cli, ["--db", str(db.path), "watch", *args], **kwargs)


def _one_cycle(runner, db, *extra_args):
    """Run watch for exactly one cycle by triggering SIGINT on the first sleep."""

    def fake_sleep(secs):
        signal.raise_signal(signal.SIGINT)

    with patch("time.sleep", side_effect=fake_sleep):
        return _invoke(runner, db, *extra_args, "--interval", "1")


# ── _age ─────────────────────────────────────────────────────────────────────


class TestAge:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_just_now(self):
        now = self._now()
        assert _age(now - timedelta(seconds=30), now) == "just now"

    def test_hours_ago(self):
        now = self._now()
        assert "5h ago" in _age(now - timedelta(hours=5), now)

    def test_one_day_ago(self):
        now = self._now()
        assert _age(now - timedelta(days=1), now) == "1d ago"

    def test_many_days_ago(self):
        now = self._now()
        assert "14d ago" in _age(now - timedelta(days=14), now)


# ── _prio ─────────────────────────────────────────────────────────────────────


class TestPrio:
    def test_critical_has_markup(self):
        result = _prio(Priority.CRITICAL)
        assert "critical" in result
        assert "[" in result

    def test_high_has_markup(self):
        result = _prio(Priority.HIGH)
        assert "high" in result

    def test_medium_has_markup(self):
        result = _prio(Priority.MEDIUM)
        assert "medium" in result

    def test_low_has_markup(self):
        result = _prio(Priority.LOW)
        assert "low" in result

    def test_no_empty_closing_tag(self):
        """Guard against [/] with no opening tag (Rich MarkupError)."""
        for p in Priority:
            result = _prio(p)
            assert "[/]" not in result


# ── _check_project ─────────────────────────────────────────────────────────────


class TestCheckProject:
    def test_no_tasks_returns_zero(self, db, project):
        now = datetime.now(timezone.utc)
        assert _check_project(db, project, stale_days=3, now=now) == 0

    def test_fresh_todo_task_no_issues(self, db, project):
        """A brand-new TODO task should not be considered stale."""
        db.create_task(project_id=project.id, title="Fresh backlog")
        now = datetime.now(timezone.utc)
        assert _check_project(db, project, stale_days=3, now=now) == 0

    def test_in_progress_with_recent_log_not_stale(self, db, project):
        """In-progress task with a recent time log entry = healthy."""
        task = db.create_task(project_id=project.id, title="Active work")
        db.update_task(task.id, status=Status.IN_PROGRESS)
        db.log_time(task.id, 1.0, note="working on it")
        now = datetime.now(timezone.utc)
        assert _check_project(db, project, stale_days=3, now=now) == 0

    def test_stale_in_progress_no_log_counted(self, db, project):
        """In-progress task with NO time log → stale by definition."""
        task = db.create_task(project_id=project.id, title="Forgotten work")
        db.update_task(task.id, status=Status.IN_PROGRESS)
        # Intentionally no db.log_time() call — get_stale_tasks flags these
        now = datetime.now(timezone.utc)
        result = _check_project(db, project, stale_days=3, now=now)
        assert result >= 1

    def test_blocked_stale_counted(self, db, project):
        """A blocked task not updated for stale_days*2 days is an issue."""
        task = db.create_task(project_id=project.id, title="Blocked thing")
        db.update_task(task.id, status=Status.BLOCKED)
        now = datetime.now(timezone.utc) + timedelta(days=100)
        result = _check_project(db, project, stale_days=1, now=now)
        assert result >= 1

    def test_done_tasks_not_counted(self, db, project):
        """Completed tasks are never stale."""
        task = db.create_task(project_id=project.id, title="Finished")
        db.update_task(task.id, status=Status.DONE)
        now = datetime.now(timezone.utc) + timedelta(days=100)
        assert _check_project(db, project, stale_days=1, now=now) == 0

    def test_returns_int(self, db, project):
        now = datetime.now(timezone.utc)
        result = _check_project(db, project, stale_days=3, now=now)
        assert isinstance(result, int)


# ── watch_cmd CLI ─────────────────────────────────────────────────────────────


class TestWatchCmd:
    def test_basic_run_exits_cleanly(self, runner, db, project):
        r = _one_cycle(runner, db, str(project.id))
        assert r.exit_code == 0

    def test_output_mentions_project(self, runner, db, project):
        r = _one_cycle(runner, db, str(project.id))
        assert "WatchTest" in r.output

    def test_stopped_message_shown(self, runner, db, project):
        r = _one_cycle(runner, db, str(project.id))
        assert "stopped" in r.output.lower()

    def test_cycle_header_shown(self, runner, db, project):
        r = _one_cycle(runner, db, str(project.id))
        assert "Cycle 1" in r.output

    def test_healthy_project_shows_ok(self, runner, db, project):
        """A project with no stale tasks prints a healthy indicator."""
        r = _one_cycle(runner, db, str(project.id))
        assert r.exit_code == 0
        assert "healthy" in r.output.lower() or "✓" in r.output

    def test_missing_project_fails(self, runner, db):
        r = _invoke(runner, db, "9999", "--interval", "1")
        assert r.exit_code != 0

    def test_no_project_no_default_fails(self, runner, db, monkeypatch):
        monkeypatch.setattr("nexus.commands.watch.load_config", lambda: {})
        r = _invoke(runner, db, "--interval", "1")
        assert r.exit_code != 0
        assert "project" in r.output.lower()

    def test_default_project_from_config(self, runner, db, project, monkeypatch):
        monkeypatch.setattr(
            "nexus.commands.watch.load_config",
            lambda: {"default_project": project.id},
        )
        r = _one_cycle(runner, db)
        assert r.exit_code == 0

    def test_all_projects_flag(self, runner, db):
        db.create_project("Alpha")
        db.create_project("Beta")

        def fake_sleep(secs):
            signal.raise_signal(signal.SIGINT)

        with patch("time.sleep", side_effect=fake_sleep):
            r = _invoke(runner, db, "--all", "--interval", "1")
        assert r.exit_code == 0
        assert "Alpha" in r.output
        assert "Beta" in r.output

    def test_all_no_projects_fails(self, runner, db):
        r = _invoke(runner, db, "--all", "--interval", "1")
        assert r.exit_code != 0
        assert "no projects" in r.output.lower()

    def test_stale_task_appears_in_output(self, runner, db, project):
        """In-progress task with no time log flagged as stale issue."""
        task = db.create_task(project_id=project.id, title="Ancient task")
        db.update_task(task.id, status=Status.IN_PROGRESS)
        # No time logged → stale immediately

        def fake_sleep(secs):
            signal.raise_signal(signal.SIGINT)

        with patch("time.sleep", side_effect=fake_sleep):
            r = _invoke(runner, db, str(project.id), "--interval", "1")
        assert r.exit_code == 0
        assert "Ancient task" in r.output or "issue" in r.output.lower()

    def test_agent_flag_with_no_ai_does_not_crash(self, runner, db, project, monkeypatch):
        """--agent with no available AI key should print skip message and continue."""
        ai_mock = MagicMock()
        ai_mock.available = False
        ai_mock.supports_tools = False
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        def fake_sleep(secs):
            signal.raise_signal(signal.SIGINT)

        with patch("time.sleep", side_effect=fake_sleep):
            r = _invoke(runner, db, str(project.id), "--interval", "1", "--agent")
        assert r.exit_code == 0


# ── _run_agent_pass ───────────────────────────────────────────────────────────
#
# NexusAI is lazily imported inside _run_agent_pass, so patch nexus.ai.NexusAI
# (the source attribute) — NOT nexus.commands.watch.NexusAI.
# Similarly, _handle_tool is lazily imported from nexus.commands.agent.


class TestRunAgentPass:
    def _make_ai(self, available=True, supports_tools=True):
        mock = MagicMock()
        mock.available = available
        mock.supports_tools = supports_tools
        mock.chat_turn.return_value = ("All good.", [])
        return mock

    def test_skips_when_no_ai(self, db, project, monkeypatch):
        ai_mock = self._make_ai(available=False)
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        _run_agent_pass(db, [project], auto_yes=False)
        ai_mock.chat_turn.assert_not_called()

    def test_skips_when_gemini_only(self, db, project, monkeypatch):
        ai_mock = self._make_ai(available=True, supports_tools=False)
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        _run_agent_pass(db, [project], auto_yes=False)
        ai_mock.chat_turn.assert_not_called()

    def test_calls_chat_turn_when_available(self, db, project, monkeypatch):
        """When AI available and supports tools, chat_turn called once per project."""
        ai_mock = self._make_ai()
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        _run_agent_pass(db, [project], auto_yes=False)
        ai_mock.chat_turn.assert_called_once()

    def test_calls_chat_turn_for_each_project(self, db, monkeypatch):
        """chat_turn called once per project."""
        p1 = db.create_project("Alpha")
        p2 = db.create_project("Beta")
        ai_mock = self._make_ai()
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        _run_agent_pass(db, [p1, p2], auto_yes=False)
        assert ai_mock.chat_turn.call_count == 2

    def test_write_log_populated_via_tool_handler(self, db, project, monkeypatch):
        """When the agent's tool_handler is called, write_log is populated."""
        ai_mock = self._make_ai()

        def fake_chat_turn(messages, tools, handler, **kwargs):
            handler("create_task", {"title": "Auto task", "priority": "medium"})
            return "Done.", []

        ai_mock.chat_turn = fake_chat_turn
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        logged = []

        def fake_handle_tool(name, inputs, db_, project_id, write_log, **kwargs):
            entry = f"Created: {inputs.get('title', '')}"
            write_log.append(entry)
            logged.append(entry)
            return "created"

        monkeypatch.setattr("nexus.commands.agent._handle_tool", fake_handle_tool)
        _run_agent_pass(db, [project], auto_yes=True)
        assert len(logged) == 1

    def test_handles_agent_exception_gracefully(self, db, project, monkeypatch):
        """If chat_turn raises, _run_agent_pass prints error but does not crash."""
        ai_mock = self._make_ai()
        ai_mock.chat_turn.side_effect = RuntimeError("API down")
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        _run_agent_pass(db, [project], auto_yes=False)  # must not raise
