"""Tests for M13: AI Scrum Master.

Covers:
- ingest_task_prompt — prompt builder shape
- AGENT_TOOLS — presence of all expected tools
- agent_system_prompt — mentions project name
- nexus task ingest CLI — mock AI, parsing, task creation
- nexus agent run CLI — mock AI tool-use loop, dry-run, auto-yes, write actions
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.ai import AGENT_TOOLS, CHAT_TOOLS, agent_system_prompt, ingest_task_prompt
from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def project(db):
    return db.create_project("AgentTest", description="A project for agent testing")


@pytest.fixture
def runner():
    return CliRunner()


# ── ingest_task_prompt ─────────────────────────────────────────────────────────

class TestIngestTaskPrompt:
    def test_returns_tuple(self):
        system, user = ingest_task_prompt("fix the login button")
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_user_contains_input_text(self):
        text = "the payment form crashes on submit"
        _, user = ingest_task_prompt(text)
        assert text in user

    def test_system_mentions_json(self):
        system, _ = ingest_task_prompt("test")
        assert "JSON" in system

    def test_user_has_priority_guidelines(self):
        _, user = ingest_task_prompt("test")
        assert "critical" in user
        assert "high" in user

    def test_user_has_expected_json_shape(self):
        _, user = ingest_task_prompt("test")
        assert "title" in user
        assert "priority" in user
        assert "estimate_hours" in user


# ── agent_system_prompt ────────────────────────────────────────────────────────

class TestAgentSystemPrompt:
    def test_mentions_project_name(self):
        prompt = agent_system_prompt("My App", "A great app")
        assert "My App" in prompt

    def test_mentions_description(self):
        prompt = agent_system_prompt("MyApp", "A great description")
        assert "A great description" in prompt

    def test_no_desc_ok(self):
        prompt = agent_system_prompt("MyApp", "")
        assert "MyApp" in prompt

    def test_contains_review_instructions(self):
        prompt = agent_system_prompt("MyApp", "")
        assert "scrum" in prompt.lower() or "review" in prompt.lower()


# ── AGENT_TOOLS ─────────────────────────────────────────────────────────────────

class TestAgentTools:
    def test_is_superset_of_chat_tools(self):
        chat_names = {t["name"] for t in CHAT_TOOLS}
        agent_names = {t["name"] for t in AGENT_TOOLS}
        assert chat_names.issubset(agent_names), "AGENT_TOOLS must include all CHAT_TOOLS"

    def test_has_stale_tasks_tool(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert "get_stale_tasks" in names

    def test_has_ready_tasks_tool(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert "get_ready_tasks" in names

    def test_has_health_tool(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert "get_project_health" in names

    def test_has_add_note_tool(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert "add_task_note" in names

    def test_has_dependency_tool(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert "get_task_dependencies" in names

    def test_all_tools_have_required_keys(self):
        for tool in AGENT_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool


# ── nexus task ingest ─────────────────────────────────────────────────────────

class TestTaskIngest:
    def _invoke(self, runner, db, *args, **kwargs):
        return runner.invoke(cli, ["--db", str(db.path), *args], **kwargs)

    def _make_ai(self, parsed: dict):
        """Return a mock NexusAI whose .complete() returns JSON."""
        mock = MagicMock()
        mock.available = True
        mock.complete.return_value = json.dumps(parsed)
        return mock

    def test_basic_ingest_creates_task(self, runner, db, project, monkeypatch):
        ai_mock = self._make_ai({
            "title": "Fix login button",
            "priority": "high",
            "description": "Users can't log in on mobile.",
            "estimate_hours": 2.0,
            "rationale": "Blocking all mobile users.",
        })
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        # Use --add to skip the confirm prompt
        r = self._invoke(runner, db, "task", "ingest", str(project.id),
                         "login button broken", "--add")
        assert r.exit_code == 0
        assert "Fix login button" in r.output

        tasks = db.list_tasks(project_id=project.id)
        assert any(t.title == "Fix login button" for t in tasks)

    def test_ingest_shows_parsed_fields(self, runner, db, project, monkeypatch):
        ai_mock = self._make_ai({
            "title": "Add CSV export",
            "priority": "medium",
            "description": "Export data to CSV.",
            "estimate_hours": 3.0,
            "rationale": "Requested by users.",
        })
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        r = self._invoke(runner, db, "task", "ingest", str(project.id),
                         "add CSV export", "--add")
        assert r.exit_code == 0
        assert "Add CSV export" in r.output
        assert "medium" in r.output
        assert "3.0h" in r.output

    def test_ingest_no_add_skips_creation(self, runner, db, project, monkeypatch):
        ai_mock = self._make_ai({
            "title": "Fix thing",
            "priority": "low",
            "description": "Minor fix.",
            "estimate_hours": None,
            "rationale": "Small issue.",
        })
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        # Respond "n" to the confirmation prompt
        r = self._invoke(runner, db, "task", "ingest", str(project.id),
                         "minor fix", input="n\n")
        assert r.exit_code == 0
        assert "not created" in r.output.lower() or "Task not created" in r.output
        tasks = db.list_tasks(project_id=project.id)
        assert not tasks

    def test_ingest_handles_bad_json(self, runner, db, project, monkeypatch):
        ai_mock = MagicMock()
        ai_mock.available = True
        ai_mock.complete.return_value = "not json at all"
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        r = self._invoke(runner, db, "task", "ingest", str(project.id), "some text")
        assert r.exit_code != 0

    def test_ingest_handles_markdown_fenced_json(self, runner, db, project, monkeypatch):
        payload = {"title": "Clean up DB", "priority": "low",
                   "description": "Remove old data.", "estimate_hours": 1.0,
                   "rationale": "Maintenance."}
        ai_mock = MagicMock()
        ai_mock.available = True
        ai_mock.complete.return_value = "```json\n" + json.dumps(payload) + "\n```"
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        r = self._invoke(runner, db, "task", "ingest", str(project.id),
                         "clean up db", "--add")
        assert r.exit_code == 0
        tasks = db.list_tasks(project_id=project.id)
        assert any(t.title == "Clean up DB" for t in tasks)

    def test_ingest_missing_project(self, runner, db, monkeypatch):
        r = self._invoke(runner, db, "task", "ingest", "9999", "some text")
        assert r.exit_code != 0

    def test_ingest_no_ai_fails(self, runner, db, project, monkeypatch):
        ai_mock = MagicMock()
        ai_mock.available = False
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        r = self._invoke(runner, db, "task", "ingest", str(project.id), "test")
        assert r.exit_code != 0

    def test_ingest_priority_fallback(self, runner, db, project, monkeypatch):
        ai_mock = self._make_ai({
            "title": "Weird task",
            "priority": "superurgent",  # invalid
            "description": "Something.",
            "estimate_hours": None,
            "rationale": "Unknown priority.",
        })
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        r = self._invoke(runner, db, "task", "ingest", str(project.id),
                         "weird task", "--add")
        assert r.exit_code == 0
        tasks = db.list_tasks(project_id=project.id)
        assert tasks[0].priority == Priority.MEDIUM  # fallback


# ── nexus agent run ───────────────────────────────────────────────────────────

def _make_agent_ai(final_text: str = "Review complete. No issues found."):
    """Return a mock NexusAI for agent tests (chat_turn returns final text, no tool calls)."""
    mock = MagicMock()
    mock.available = True
    mock.supports_tools = True
    mock.chat_turn.return_value = (final_text, [])
    return mock


class TestAgentRun:
    def _invoke(self, runner, db, *args, input_text=None):
        return runner.invoke(cli, ["--db", str(db.path), *args], input=input_text)

    def test_basic_run(self, runner, db, project, monkeypatch):
        monkeypatch.setattr("nexus.commands.agent.NexusAI", lambda: _make_agent_ai())
        r = self._invoke(runner, db, "agent", "run", str(project.id))
        assert r.exit_code == 0
        assert "Review complete" in r.output

    def test_dry_run_mode(self, runner, db, project, monkeypatch):
        mock_ai = _make_agent_ai()
        monkeypatch.setattr("nexus.commands.agent.NexusAI", lambda: mock_ai)
        r = self._invoke(runner, db, "agent", "run", str(project.id), "--dry-run")
        assert r.exit_code == 0
        assert "dry-run" in r.output.lower() or "Dry-run" in r.output

    def test_missing_project_fails(self, runner, db, monkeypatch):
        r = self._invoke(runner, db, "agent", "run", "9999")
        assert r.exit_code != 0

    def test_no_ai_fails(self, runner, db, project, monkeypatch):
        mock = MagicMock()
        mock.available = False
        monkeypatch.setattr("nexus.commands.agent.NexusAI", lambda: mock)
        r = self._invoke(runner, db, "agent", "run", str(project.id))
        assert r.exit_code != 0

    def test_gemini_only_fails(self, runner, db, project, monkeypatch):
        mock = MagicMock()
        mock.available = True
        mock.supports_tools = False
        monkeypatch.setattr("nexus.commands.agent.NexusAI", lambda: mock)
        r = self._invoke(runner, db, "agent", "run", str(project.id))
        assert r.exit_code != 0

    def test_default_project_from_config(self, runner, db, project, monkeypatch):
        monkeypatch.setattr("nexus.commands.agent.NexusAI", lambda: _make_agent_ai())
        monkeypatch.setattr(
            "nexus.commands.agent.load_config",
            lambda: {"default_project": project.id},
        )
        r = self._invoke(runner, db, "agent", "run")
        assert r.exit_code == 0

    def test_no_default_project_fails(self, runner, db, project, monkeypatch):
        monkeypatch.setattr("nexus.commands.agent.load_config", lambda: {})
        r = self._invoke(runner, db, "agent", "run")
        assert r.exit_code != 0

    def test_agent_summary_shown(self, runner, db, project, monkeypatch):
        monkeypatch.setattr(
            "nexus.commands.agent.NexusAI",
            lambda: _make_agent_ai("Found 2 stale tasks. Added notes.")
        )
        r = self._invoke(runner, db, "agent", "run", str(project.id))
        assert r.exit_code == 0
        assert "Agent Summary" in r.output
        assert "Found 2 stale tasks" in r.output


# ── _handle_tool (unit tests) ─────────────────────────────────────────────────

class TestHandleTool:
    """Test the tool handler function in isolation."""

    def setup_method(self):
        from nexus.commands.agent import _handle_tool
        self._handle = _handle_tool

    def _call(self, db, project_id, name, inputs, *, dry_run=True, auto_yes=False):
        write_log: list[str] = []
        result = self._handle(
            name, inputs,
            db=db, project_id=project_id,
            dry_run=dry_run, auto_yes=auto_yes,
            write_log=write_log,
        )
        return result, write_log

    def test_list_tasks_empty(self, db, project):
        result, _ = self._call(db, project.id, "list_tasks", {})
        assert "No tasks" in result

    def test_list_tasks_with_tasks(self, db, project):
        db.create_task(project_id=project.id, title="Task A")
        result, _ = self._call(db, project.id, "list_tasks", {})
        assert "Task A" in result

    def test_get_task(self, db, project):
        t = db.create_task(project_id=project.id, title="My Task")
        result, _ = self._call(db, project.id, "get_task", {"task_id": t.id})
        assert "My Task" in result

    def test_get_task_missing(self, db, project):
        result, _ = self._call(db, project.id, "get_task", {"task_id": 9999})
        assert "not found" in result.lower()

    def test_get_project_stats(self, db, project):
        db.create_task(project_id=project.id, title="T1")
        db.create_task(project_id=project.id, title="T2")
        result, _ = self._call(db, project.id, "get_project_stats", {})
        assert "Total tasks: 2" in result

    def test_get_stale_tasks_none(self, db, project):
        result, _ = self._call(db, project.id, "get_stale_tasks", {"days": 3})
        assert "No stale tasks" in result

    def test_get_ready_tasks_none(self, db, project):
        result, _ = self._call(db, project.id, "get_ready_tasks", {})
        assert "No ready tasks" in result or "ready" in result

    def test_get_ready_tasks_lists_tasks(self, db, project):
        db.create_task(project_id=project.id, title="Ready Task")
        result, _ = self._call(db, project.id, "get_ready_tasks", {})
        assert "Ready Task" in result

    def test_get_project_health(self, db, project):
        # Add some tasks so health can compute
        for i in range(3):
            db.create_task(project_id=project.id, title=f"Task {i}", estimate_hours=2.0)
        result, _ = self._call(db, project.id, "get_project_health", {})
        assert "Health:" in result or "Insufficient" in result

    def test_get_task_dependencies(self, db, project):
        a = db.create_task(project_id=project.id, title="A")
        b = db.create_task(project_id=project.id, title="B")
        db.add_dependency(b.id, a.id)
        result, _ = self._call(db, project.id, "get_task_dependencies", {"task_id": b.id})
        assert "A" in result

    def test_create_task_dry_run(self, db, project):
        result, write_log = self._call(
            db, project.id, "create_task",
            {"title": "New Task", "priority": "high"},
            dry_run=True,
        )
        # Dry run: not created, write_log empty
        assert write_log == []
        assert not db.list_tasks(project_id=project.id)

    def test_create_task_auto_yes(self, db, project):
        result, write_log = self._call(
            db, project.id, "create_task",
            {"title": "Auto Task", "priority": "medium"},
            dry_run=False, auto_yes=True,
        )
        assert write_log
        tasks = db.list_tasks(project_id=project.id)
        assert any(t.title == "Auto Task" for t in tasks)

    def test_add_task_note_dry_run(self, db, project):
        t = db.create_task(project_id=project.id, title="T")
        result, write_log = self._call(
            db, project.id, "add_task_note",
            {"task_id": t.id, "note": "Follow up needed"},
            dry_run=True,
        )
        assert write_log == []
        assert not db.get_task_notes(t.id)

    def test_add_task_note_auto_yes(self, db, project):
        t = db.create_task(project_id=project.id, title="T")
        result, write_log = self._call(
            db, project.id, "add_task_note",
            {"task_id": t.id, "note": "Follow up needed"},
            dry_run=False, auto_yes=True,
        )
        assert write_log
        notes = db.get_task_notes(t.id)
        assert any("Follow up" in n.text for n in notes)

    def test_unknown_tool(self, db, project):
        result, _ = self._call(db, project.id, "nonexistent_tool", {})
        assert "Unknown tool" in result
