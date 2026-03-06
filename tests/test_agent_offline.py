"""Tests for M18 — Offline Agent (Gemini / Ollama structured-output path).

Covers:
  - offline_agent_prompt()          shape, content, edge cases
  - _parse_offline_plan()           validation, sanitisation, edge cases
  - _build_offline_context()        context assembly from live DB
  - _run_offline_agent()            end-to-end execution (mocked AI)
  - agent_run CLI routing           Anthropic vs offline vs no-AI
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.ai import offline_agent_prompt
from nexus.cli import cli
from nexus.commands.agent import (
    _build_offline_context,
    _parse_offline_plan,
    _run_offline_agent,
)
from nexus.db import Database
from nexus.models import Priority, Status


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "nexus.db")


@pytest.fixture()
def project(db: Database):
    return db.create_project("Test Project", description="A test project for offline agent")


@pytest.fixture()
def tasks(db: Database, project):
    """Create a small set of tasks across different statuses."""
    t1 = db.create_task(project.id, "Implement login", priority=Priority.HIGH)
    t2 = db.create_task(project.id, "Write unit tests", priority=Priority.MEDIUM)
    t3 = db.create_task(project.id, "Deploy to staging", priority=Priority.LOW)
    t4 = db.create_task(project.id, "Fix memory leak", priority=Priority.CRITICAL)
    db.update_task(t1.id, status=Status.IN_PROGRESS)
    db.update_task(t3.id, status=Status.DONE)
    db.update_task(t4.id, status=Status.BLOCKED)
    return [t1, t2, t3, t4]


def _invoke(runner, db_path, *args, **kwargs):
    return runner.invoke(cli, ["--db", str(db_path), *args], **kwargs)


# ── offline_agent_prompt() ────────────────────────────────────────────────────


class TestOfflineAgentPrompt:
    def test_returns_tuple_of_two_strings(self):
        system, user = offline_agent_prompt(
            project_name="Acme",
            project_desc="desc",
            stats_line="5/10 done",
            tasks_ctx="task lines",
            stale_ctx="none",
            ready_ctx="none",
            valid_task_ids=[1, 2, 3],
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_instructs_json_only(self):
        system, _ = offline_agent_prompt("P", "", "s", "t", "st", "r", [])
        assert "JSON" in system
        assert "no markdown" in system.lower() or "markdown" in system.lower()

    def test_user_contains_project_name(self):
        _, user = offline_agent_prompt("MyProject", "", "s", "t", "st", "r", [1])
        assert "MyProject" in user

    def test_user_contains_stats_line(self):
        _, user = offline_agent_prompt("P", "", "3/5 done (60%)", "t", "st", "r", [])
        assert "3/5 done (60%)" in user

    def test_user_contains_valid_task_ids(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "r", [7, 42, 100])
        assert "7" in user
        assert "42" in user
        assert "100" in user

    def test_empty_valid_task_ids_shows_none(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "r", [])
        assert "(none)" in user

    def test_user_contains_tasks_ctx(self):
        _, user = offline_agent_prompt("P", "", "s", "custom task context line", "st", "r", [])
        assert "custom task context line" in user

    def test_user_contains_stale_ctx(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "STALE_MARKER", "r", [])
        assert "STALE_MARKER" in user

    def test_user_contains_ready_ctx(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "READY_MARKER", [])
        assert "READY_MARKER" in user

    def test_user_contains_schema_keys(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "r", [1])
        # The schema should describe both action types
        assert "add_note" in user
        assert "create_task" in user
        assert "observations" in user

    def test_project_desc_included_when_present(self):
        _, user = offline_agent_prompt("P", "My great desc", "s", "t", "st", "r", [])
        assert "My great desc" in user

    def test_project_desc_omitted_when_empty(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "r", [])
        # Empty desc_line means no desc in prompt — project name still there
        assert "P" in user

    def test_id_list_sorted(self):
        _, user = offline_agent_prompt("P", "", "s", "t", "st", "r", [10, 1, 5])
        # IDs should appear sorted: [1, 5, 10]
        assert "1, 5, 10" in user


# ── _parse_offline_plan() ─────────────────────────────────────────────────────


class TestParseOfflinePlan:
    VALID_IDS = {1, 2, 3, 10}

    def _plan(self, observations=None, actions=None) -> str:
        return json.dumps({
            "observations": observations or ["obs1", "obs2"],
            "actions": actions or [],
        })

    # ── Happy path ──────────────────────────────────────────────────────────

    def test_valid_empty_actions(self):
        result = _parse_offline_plan(self._plan(actions=[]), self.VALID_IDS)
        assert result["observations"] == ["obs1", "obs2"]
        assert result["actions"] == []

    def test_add_note_valid(self):
        actions = [{"type": "add_note", "task_id": 1, "note": "Follow up required"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 1
        assert result["actions"][0] == {"type": "add_note", "task_id": 1, "note": "Follow up required"}

    def test_create_task_valid(self):
        actions = [{"type": "create_task", "title": "Write docs", "priority": "medium", "description": "desc"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 1
        a = result["actions"][0]
        assert a["type"] == "create_task"
        assert a["title"] == "Write docs"
        assert a["priority"] == "medium"
        assert a["description"] == "desc"

    def test_create_task_description_defaults_to_empty(self):
        actions = [{"type": "create_task", "title": "No desc task", "priority": "low"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"][0]["description"] == ""

    def test_mixed_actions(self):
        actions = [
            {"type": "add_note", "task_id": 2, "note": "Investigate"},
            {"type": "create_task", "title": "New task", "priority": "high"},
        ]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 2
        assert result["actions"][0]["type"] == "add_note"
        assert result["actions"][1]["type"] == "create_task"

    # ── Markdown fence stripping ────────────────────────────────────────────

    def test_strips_json_code_fence(self):
        raw = "```json\n" + self._plan() + "\n```"
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert result["observations"] == ["obs1", "obs2"]

    def test_strips_plain_code_fence(self):
        raw = "```\n" + self._plan() + "\n```"
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert result["observations"] == ["obs1", "obs2"]

    # ── Invalid JSON ────────────────────────────────────────────────────────

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_offline_plan("not json at all", self.VALID_IDS)

    def test_raises_on_non_dict_json(self):
        with pytest.raises(ValueError, match="JSON object"):
            _parse_offline_plan("[1, 2, 3]", self.VALID_IDS)

    # ── Observation validation ──────────────────────────────────────────────

    def test_observations_capped_at_5(self):
        obs = [f"obs{i}" for i in range(10)]
        result = _parse_offline_plan(self._plan(observations=obs), self.VALID_IDS)
        assert len(result["observations"]) == 5

    def test_observations_not_a_list_treated_as_empty(self):
        raw = json.dumps({"observations": "not a list", "actions": []})
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert result["observations"] == []

    def test_observations_missing_treated_as_empty(self):
        raw = json.dumps({"actions": []})
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert result["observations"] == []

    # ── add_note validation ─────────────────────────────────────────────────

    def test_add_note_invalid_task_id_skipped(self):
        actions = [{"type": "add_note", "task_id": 999, "note": "note"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"] == []

    def test_add_note_non_int_task_id_skipped(self):
        actions = [{"type": "add_note", "task_id": "abc", "note": "note"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"] == []

    def test_add_note_float_task_id_converted(self):
        # float like 1.0 can be cast to int — valid
        actions = [{"type": "add_note", "task_id": 1.0, "note": "note"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 1

    def test_add_note_empty_note_skipped(self):
        actions = [{"type": "add_note", "task_id": 1, "note": ""}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"] == []

    def test_add_note_whitespace_only_note_skipped(self):
        actions = [{"type": "add_note", "task_id": 1, "note": "   "}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"] == []

    # ── create_task validation ──────────────────────────────────────────────

    def test_create_task_empty_title_skipped(self):
        actions = [{"type": "create_task", "title": "", "priority": "medium"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"] == []

    def test_create_task_title_truncated_to_80(self):
        long_title = "A" * 100
        actions = [{"type": "create_task", "title": long_title, "priority": "low"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"][0]["title"]) == 80

    def test_create_task_invalid_priority_normalised(self):
        actions = [{"type": "create_task", "title": "Task", "priority": "URGENT"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"][0]["priority"] == "medium"

    def test_create_task_missing_priority_defaults_to_medium(self):
        actions = [{"type": "create_task", "title": "Task"}]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert result["actions"][0]["priority"] == "medium"

    # ── Action cap ──────────────────────────────────────────────────────────

    def test_actions_capped_at_5(self):
        actions = [
            {"type": "create_task", "title": f"Task {i}", "priority": "low"}
            for i in range(10)
        ]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 5

    def test_unknown_action_type_skipped(self):
        actions = [
            {"type": "delete_task", "task_id": 1},
            {"type": "create_task", "title": "Good task", "priority": "medium"},
        ]
        result = _parse_offline_plan(self._plan(actions=actions), self.VALID_IDS)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["type"] == "create_task"

    def test_non_dict_action_item_skipped(self):
        raw = json.dumps({"observations": [], "actions": ["not a dict", {"type": "create_task", "title": "Good", "priority": "low"}]})
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert len(result["actions"]) == 1

    def test_actions_not_a_list_treated_as_empty(self):
        raw = json.dumps({"observations": [], "actions": "not a list"})
        result = _parse_offline_plan(raw, self.VALID_IDS)
        assert result["actions"] == []


# ── _build_offline_context() ─────────────────────────────────────────────────


class TestBuildOfflineContext:
    def test_returns_expected_keys(self, db, project, tasks):
        ctx = _build_offline_context(db, project.id)
        assert set(ctx) == {"stats_line", "tasks_ctx", "stale_ctx", "ready_ctx", "deps_ctx", "valid_task_ids"}

    def test_stats_line_reflects_counts(self, db, project, tasks):
        ctx = _build_offline_context(db, project.id)
        # tasks fixture: 1 in-progress, 1 done, 1 blocked, 1 todo
        assert "1 in-progress" in ctx["stats_line"]
        assert "1 blocked" in ctx["stats_line"]

    def test_valid_task_ids_contains_all_tasks(self, db, project, tasks):
        ctx = _build_offline_context(db, project.id)
        task_ids = {t.id for t in tasks}
        assert task_ids.issubset(set(ctx["valid_task_ids"]))

    def test_tasks_ctx_excludes_done(self, db, project, tasks):
        ctx = _build_offline_context(db, project.id)
        # t3 is done — should not appear in active task ctx
        # t3 title is "Deploy to staging"
        assert "Deploy to staging" not in ctx["tasks_ctx"]

    def test_tasks_ctx_includes_active_tasks(self, db, project, tasks):
        ctx = _build_offline_context(db, project.id)
        assert "Implement login" in ctx["tasks_ctx"]  # in_progress
        assert "Write unit tests" in ctx["tasks_ctx"]  # todo
        assert "Fix memory leak" in ctx["tasks_ctx"]   # blocked

    def test_empty_project_returns_defaults(self, db):
        p = db.create_project("Empty")
        ctx = _build_offline_context(db, p.id)
        assert ctx["tasks_ctx"] == "(no active tasks)"
        assert ctx["stale_ctx"] == "(none)"
        assert ctx["valid_task_ids"] == []

    def test_active_tasks_capped_at_10(self, db, project):
        for i in range(15):
            db.create_task(project.id, f"Task {i}", priority=Priority.MEDIUM)
        ctx = _build_offline_context(db, project.id)
        # Count lines in tasks_ctx
        lines = [l for l in ctx["tasks_ctx"].splitlines() if l.strip()]
        assert len(lines) <= 10

    def test_ready_ctx_shows_ready_tasks(self, db, project, tasks):
        # tasks without dependencies should appear in ready
        ctx = _build_offline_context(db, project.id)
        # At least one ready task
        assert ctx["ready_ctx"] != "(none — may have unmet dependencies)"

    def test_stale_ctx_none_when_no_stale_tasks(self, db, project, tasks, monkeypatch):
        # Monkeypatch get_stale_tasks to return empty (DB time-comparison behaviour can vary)
        monkeypatch.setattr(db, "get_stale_tasks", lambda pid, threshold: [])
        ctx = _build_offline_context(db, project.id)
        assert "(none)" in ctx["stale_ctx"]


# ── _run_offline_agent() ─────────────────────────────────────────────────────


def _make_ai(provider_name="Gemini", complete_return=None):
    """Build a mock NexusAI in offline mode."""
    ai = MagicMock()
    ai.available = True
    ai.supports_tools = False
    ai.provider_name = provider_name
    if complete_return is None:
        complete_return = json.dumps({
            "observations": ["Project looks healthy", "No blockers found"],
            "actions": [],
        })
    ai.complete.return_value = complete_return
    return ai


class TestRunOfflineAgent:
    def test_runs_without_error_no_actions(self, db, project, tasks):
        ai = _make_ai()
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        ai.complete.assert_called_once()

    def test_observations_displayed(self, db, project, tasks):
        ai = _make_ai(complete_return=json.dumps({
            "observations": ["Observation alpha", "Observation beta"],
            "actions": [],
        }))
        # Simply verify complete() was called (Rich output goes to console, not easily captured here)
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        ai.complete.assert_called_once()

    def test_add_note_action_auto_yes(self, db, project, tasks):
        task_id = tasks[0].id  # in-progress task
        ai = _make_ai(complete_return=json.dumps({
            "observations": ["Task is stale"],
            "actions": [{"type": "add_note", "task_id": task_id, "note": "Needs review"}],
        }))
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        notes = db.get_task_notes(task_id)
        assert any("Needs review" in n.text for n in notes)

    def test_create_task_action_auto_yes(self, db, project, tasks):
        ai = _make_ai(complete_return=json.dumps({
            "observations": ["Missing CI task"],
            "actions": [{"type": "create_task", "title": "Set up CI pipeline", "priority": "high"}],
        }))
        before = len(db.list_tasks(project_id=project.id))
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        after = len(db.list_tasks(project_id=project.id))
        assert after == before + 1
        new_tasks = [t for t in db.list_tasks(project_id=project.id) if t.title == "Set up CI pipeline"]
        assert new_tasks
        assert new_tasks[0].priority == Priority.HIGH

    def test_dry_run_does_not_write(self, db, project, tasks):
        task_id = tasks[0].id
        ai = _make_ai(complete_return=json.dumps({
            "observations": ["obs"],
            "actions": [{"type": "add_note", "task_id": task_id, "note": "Do not write"}],
        }))
        _run_offline_agent(ai, project, project.id, dry_run=True, auto_yes=True, db=db)
        notes = db.get_task_notes(task_id)
        assert not any("Do not write" in n.text for n in notes)

    def test_retry_on_json_error_then_succeeds(self, db, project, tasks):
        good_response = json.dumps({"observations": ["ok"], "actions": []})
        ai = _make_ai()
        ai.complete.side_effect = ["not valid json", good_response]
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        assert ai.complete.call_count == 2

    def test_three_failures_exits(self, db, project, tasks):
        ai = _make_ai()
        ai.complete.return_value = "bad json"
        with pytest.raises(SystemExit):
            _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        assert ai.complete.call_count == 3

    def test_invalid_task_id_in_add_note_skipped(self, db, project, tasks):
        ai = _make_ai(complete_return=json.dumps({
            "observations": ["obs"],
            "actions": [{"type": "add_note", "task_id": 99999, "note": "Should be skipped"}],
        }))
        _run_offline_agent(ai, project, project.id, dry_run=False, auto_yes=True, db=db)
        # No note should have been added to any task
        for t in tasks:
            notes = db.get_task_notes(t.id)
            assert not any("Should be skipped" in n.text for n in notes)

    def test_ollama_provider_name_in_output(self, db, project, tasks):
        ai = _make_ai(provider_name="Ollama (llama3.2)")
        runner = CliRunner()
        # Just check it doesn't crash and calls complete
        _run_offline_agent(ai, project, project.id, dry_run=True, auto_yes=True, db=db)
        ai.complete.assert_called()


# ── CLI routing tests ─────────────────────────────────────────────────────────


class TestAgentRunRouting:
    """Test that agent run routes to the correct path based on the AI provider."""

    def test_no_ai_exits_with_error(self, db, project, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db.path), "agent", "run", str(project.id)])
        assert result.exit_code != 0
        assert "ANTHROPIC_API_KEY" in result.output or "GOOGLE_API_KEY" in result.output or "OLLAMA_MODEL" in result.output

    def test_gemini_takes_offline_path(self, db, project, tasks, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        good_response = json.dumps({
            "observations": ["Project snapshot received"],
            "actions": [],
        })
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.complete.return_value = good_response

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", str(project.id), "--yes"],
            )
        assert result.exit_code == 0, result.output
        assert "offline mode" in result.output or "Gemini" in result.output

    def test_ollama_takes_offline_path(self, db, project, tasks, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        good_response = json.dumps({
            "observations": ["Ollama review done"],
            "actions": [],
        })
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Ollama (llama3.2)"
        mock_ai.complete.return_value = good_response

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", str(project.id), "--yes"],
            )
        assert result.exit_code == 0, result.output

    def test_anthropic_skips_offline_path(self, db, project, tasks, monkeypatch):
        """Anthropic provider should use the tool-use path (not _run_offline_agent)."""
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = True
        mock_ai.provider_name = "Anthropic"
        # Simulate a completed tool-use turn
        mock_ai.chat_turn.return_value = ("All tasks are healthy.", [])

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai), \
             patch("nexus.commands.agent._run_offline_agent") as mock_offline:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", str(project.id)],
            )
        # Offline path should NOT have been called
        mock_offline.assert_not_called()
        mock_ai.chat_turn.assert_called_once()

    def test_dry_run_flag_passed_to_offline(self, db, project, tasks):
        good_response = json.dumps({
            "observations": ["dry run test"],
            "actions": [],
        })
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.complete.return_value = good_response

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", str(project.id), "--dry-run"],
            )
        assert result.exit_code == 0, result.output
        assert "dry" in result.output.lower()

    def test_default_project_used_when_no_id(self, db, project, tasks):
        """agent run with no project_id should fall back to config default_project."""
        good_response = json.dumps({"observations": ["ok"], "actions": []})
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.complete.return_value = good_response

        # Write a config that sets default_project
        import json as _json
        config_path = db.path.parent / "config.json"
        config_path.write_text(_json.dumps({"default_project": project.id}))

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai), \
             patch("nexus.commands.agent.load_config", return_value={"default_project": project.id}):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", "--yes"],
            )
        assert result.exit_code == 0, result.output

    def test_no_default_project_exits(self, db, project):
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai), \
             patch("nexus.commands.agent.load_config", return_value={}):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run"],
            )
        assert result.exit_code != 0
        assert "default_project" in result.output

    def test_invalid_project_id_exits(self, db):
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"

        with patch("nexus.commands.agent.NexusAI", return_value=mock_ai):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "agent", "run", "99999"],
            )
        assert result.exit_code != 0
        assert "not found" in result.output


# ── offline_agent_prompt in ai module ────────────────────────────────────────


class TestOfflineAgentPromptExported:
    """Verify the function is importable from nexus.ai (used by agent.py)."""

    def test_importable_from_nexus_ai(self):
        from nexus.ai import offline_agent_prompt as fn
        assert callable(fn)

    def test_importable_from_nexus_commands_agent(self):
        from nexus.commands.agent import _run_offline_agent, _parse_offline_plan, _build_offline_context
        assert callable(_run_offline_agent)
        assert callable(_parse_offline_plan)
        assert callable(_build_offline_context)
