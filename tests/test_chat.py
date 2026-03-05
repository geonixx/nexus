"""Tests for M7: nexus chat (tool use) and nexus standup --ai."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
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


# ── standup_prompt unit tests ─────────────────────────────────────────────────


def test_standup_prompt_contains_project_name():
    from nexus.ai import standup_prompt

    system, user = standup_prompt(
        project_name="Nexus",
        yesterday_completed=["Fix login bug", "Write tests"],
        yesterday_hours=4.5,
        in_progress=[(3, "Build auth"), (4, "API integration")],
        blocked=[(7, "Waiting for review")],
        top_next=[(1, "Write docs"), (2, "Deploy to prod")],
    )
    assert "Nexus" in user
    assert "4.5h" in user


def test_standup_prompt_contains_tasks():
    from nexus.ai import standup_prompt

    _, user = standup_prompt(
        project_name="Proj",
        yesterday_completed=["Fix login bug"],
        yesterday_hours=2.0,
        in_progress=[(3, "Build auth")],
        blocked=[(7, "Review pending")],
        top_next=[(1, "Write docs")],
    )
    assert "Fix login bug" in user
    assert "Build auth" in user
    assert "Review pending" in user
    assert "Write docs" in user


def test_standup_prompt_empty_lists():
    from nexus.ai import standup_prompt

    system, user = standup_prompt(
        project_name="Empty",
        yesterday_completed=[],
        yesterday_hours=0.0,
        in_progress=[],
        blocked=[],
        top_next=[],
    )
    assert "Empty" in user
    assert "0.0h" in user
    # Should still produce valid prompts with placeholder text
    assert system
    assert user


def test_standup_prompt_returns_tuple():
    from nexus.ai import standup_prompt

    result = standup_prompt(
        project_name="P",
        yesterday_completed=[],
        yesterday_hours=0.0,
        in_progress=[],
        blocked=[],
        top_next=[],
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(s, str) for s in result)


# ── standup command (no --ai) ─────────────────────────────────────────────────


def test_report_standup_basic(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "In progress task")
    invoke(runner, db_path, "task", "start", "1")

    result = invoke(runner, db_path, "report", "standup", "1")
    assert result.exit_code == 0
    assert "In progress task" in result.output


def test_report_standup_missing_project(runner, db_path):
    result = invoke(runner, db_path, "report", "standup", "999")
    assert result.exit_code == 1


def test_report_standup_shows_sections(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Todo item")

    result = invoke(runner, db_path, "report", "standup", "1")
    assert result.exit_code == 0
    assert "Todo item" in result.output


# ── standup --ai flag ─────────────────────────────────────────────────────────


def test_report_standup_ai_flag(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.text_stream = iter(
        ["**Yesterday**: Fixed login bug.\n**Today**: Auth module.\n**Blockers**: None."]
    )
    mock_client.messages.stream.return_value = mock_ctx

    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Login bug fix")
    invoke(runner, db_path, "task", "done", "1")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "report", "standup", "1", "--ai")

    assert result.exit_code == 0


def test_report_standup_ai_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "report", "standup", "1", "--ai")
    assert result.exit_code == 1


# ── CHAT_TOOLS structure ──────────────────────────────────────────────────────


def test_chat_tools_is_list():
    from nexus.ai import CHAT_TOOLS

    assert isinstance(CHAT_TOOLS, list)
    assert len(CHAT_TOOLS) >= 5


def test_chat_tools_required_names():
    from nexus.ai import CHAT_TOOLS

    names = {t["name"] for t in CHAT_TOOLS}
    assert "list_tasks" in names
    assert "get_task" in names
    assert "update_task_status" in names
    assert "create_task" in names
    assert "log_time" in names
    assert "get_project_stats" in names


def test_chat_tools_valid_structure():
    from nexus.ai import CHAT_TOOLS

    for tool in CHAT_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


# ── NexusAI.supports_tools ────────────────────────────────────────────────────


def test_supports_tools_with_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("anthropic.Anthropic"):
        from nexus.ai import NexusAI

        ai = NexusAI()
    assert ai.supports_tools is True


def test_no_tools_with_gemini_only(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-test")
    from nexus.ai import NexusAI

    ai = NexusAI()
    assert ai.supports_tools is False


def test_no_tools_when_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from nexus.ai import NexusAI

    ai = NexusAI()
    assert ai.supports_tools is False


# ── NexusAI.chat_turn ─────────────────────────────────────────────────────────


def _make_mock_text_response(text: str):
    """Build a mock Anthropic messages.create() response with a single text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


def _make_mock_tool_response(tool_name: str, tool_id: str, tool_input: dict):
    """Build a mock response requesting a tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.id = tool_id
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    return response


def test_chat_turn_simple_text_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_text_response("Hello! How can I help?")

    with patch("anthropic.Anthropic", return_value=mock_client):
        from nexus.ai import NexusAI

        ai = NexusAI()
        text, updated = ai.chat_turn(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
            tool_handler=lambda name, inputs: "unused",
            system="You are a test assistant.",
        )

    assert "Hello" in text
    # messages should have grown (user + assistant at minimum)
    assert len(updated) >= 2


def test_chat_turn_executes_tool(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_mock_tool_response("list_tasks", "tool_abc", {}),
        _make_mock_text_response("You have 3 tasks."),
    ]

    tool_called = []

    def handler(name, inputs):
        tool_called.append(name)
        return "#1 [todo] Build feature"

    with patch("anthropic.Anthropic", return_value=mock_client):
        from nexus.ai import NexusAI

        ai = NexusAI()
        text, updated = ai.chat_turn(
            messages=[{"role": "user", "content": "list my tasks"}],
            tools=[],
            tool_handler=handler,
        )

    assert "3 tasks" in text
    assert "list_tasks" in tool_called
    # Should have called messages.create twice (once for tool, once for final)
    assert mock_client.messages.create.call_count == 2


def test_chat_turn_multiple_tools_in_sequence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_mock_tool_response("get_project_stats", "t1", {}),
        _make_mock_tool_response("list_tasks", "t2", {"status": "in_progress"}),
        _make_mock_text_response("Project looks healthy!"),
    ]

    tools_called = []

    def handler(name, inputs):
        tools_called.append(name)
        return "some result"

    with patch("anthropic.Anthropic", return_value=mock_client):
        from nexus.ai import NexusAI

        ai = NexusAI()
        text, _ = ai.chat_turn(
            messages=[{"role": "user", "content": "How's the project?"}],
            tools=[],
            tool_handler=handler,
        )

    assert "healthy" in text
    assert "get_project_stats" in tools_called
    assert "list_tasks" in tools_called


def test_chat_turn_requires_anthropic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-test")

    from nexus.ai import NexusAI

    ai = NexusAI()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ai.chat_turn(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
            tool_handler=lambda n, i: "x",
        )


def test_chat_turn_passes_system_prompt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_text_response("Ok!")

    with patch("anthropic.Anthropic", return_value=mock_client):
        from nexus.ai import NexusAI

        ai = NexusAI()
        ai.chat_turn(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[],
            tool_handler=lambda n, i: "x",
            system="Custom system prompt here.",
        )

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs.get("system") == "Custom system prompt here."


# ── _make_tool_handler integration ───────────────────────────────────────────


def test_tool_list_tasks(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    db.create_task(p.id, "Task A", priority=Priority.HIGH)
    db.create_task(p.id, "Task B", priority=Priority.LOW)

    handler = _make_tool_handler(db, p.id)
    result = handler("list_tasks", {})
    assert "Task A" in result
    assert "Task B" in result


def test_tool_list_tasks_filtered_by_status(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t1 = db.create_task(p.id, "Todo task")
    t2 = db.create_task(p.id, "Done task")
    db.update_task(t2.id, status=Status.DONE)

    handler = _make_tool_handler(db, p.id)
    result = handler("list_tasks", {"status": "todo"})
    assert "Todo task" in result
    assert "Done task" not in result


def test_tool_list_tasks_empty(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    handler = _make_tool_handler(db, p.id)
    result = handler("list_tasks", {})
    assert "No tasks" in result


def test_tool_get_task(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "My task", description="Some details", estimate_hours=2.0)
    db.log_time(t.id, 1.5, "initial work")

    handler = _make_tool_handler(db, p.id)
    result = handler("get_task", {"task_id": t.id})
    assert "My task" in result
    assert "Some details" in result
    assert "1.5h" in result


def test_tool_get_task_not_found(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    handler = _make_tool_handler(db, p.id)
    result = handler("get_task", {"task_id": 9999})
    assert "not found" in result.lower()


def test_tool_update_task_status_done(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Finish me")

    handler = _make_tool_handler(db, p.id)
    result = handler("update_task_status", {"task_id": t.id, "status": "done"})
    assert "done" in result

    updated = db.get_task(t.id)
    assert updated.status == Status.DONE
    assert updated.completed_at is not None


def test_tool_update_task_status_in_progress(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Start me")

    handler = _make_tool_handler(db, p.id)
    handler("update_task_status", {"task_id": t.id, "status": "in_progress"})

    updated = db.get_task(t.id)
    assert updated.status == Status.IN_PROGRESS


def test_tool_update_task_not_found(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    handler = _make_tool_handler(db, p.id)
    result = handler("update_task_status", {"task_id": 9999, "status": "done"})
    assert "not found" in result.lower()


def test_tool_create_task(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")

    handler = _make_tool_handler(db, p.id)
    result = handler("create_task", {"title": "Brand new task", "priority": "high"})
    assert "Brand new task" in result

    tasks = db.list_tasks(project_id=p.id)
    assert len(tasks) == 1
    assert tasks[0].title == "Brand new task"
    assert tasks[0].priority == Priority.HIGH


def test_tool_create_task_with_estimate(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")

    handler = _make_tool_handler(db, p.id)
    handler(
        "create_task",
        {"title": "Estimated task", "priority": "medium", "estimate_hours": 3.0},
    )

    tasks = db.list_tasks(project_id=p.id)
    assert tasks[0].estimate_hours == 3.0


def test_tool_create_task_default_priority(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")

    handler = _make_tool_handler(db, p.id)
    handler("create_task", {"title": "Default priority task"})

    tasks = db.list_tasks(project_id=p.id)
    assert tasks[0].priority == Priority.MEDIUM


def test_tool_log_time(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "Work task")

    handler = _make_tool_handler(db, p.id)
    result = handler("log_time", {"task_id": t.id, "hours": 2.5, "note": "solid progress"})
    assert "2.5h" in result

    entries = db.list_time_entries(t.id)
    assert len(entries) == 1
    assert entries[0].hours == 2.5
    assert entries[0].note == "solid progress"


def test_tool_log_time_task_not_found(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    handler = _make_tool_handler(db, p.id)
    result = handler("log_time", {"task_id": 9999, "hours": 1.0})
    assert "not found" in result.lower()


def test_tool_get_project_stats(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("MyProject")
    db.create_task(p.id, "T1")
    db.create_task(p.id, "T2")

    handler = _make_tool_handler(db, p.id)
    result = handler("get_project_stats", {})
    assert "MyProject" in result
    assert "2" in result  # 2 total tasks


def test_tool_unknown_name(tmp_path):
    from nexus.commands.chat import _make_tool_handler

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    handler = _make_tool_handler(db, p.id)
    result = handler("totally_unknown", {})
    assert "Unknown" in result or "Error" in result


# ── nexus chat CLI command ────────────────────────────────────────────────────


def test_chat_no_key_exits(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "chat", "1")
    assert result.exit_code == 1


def test_chat_gemini_only_exits_with_message(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-test")

    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "chat", "1")
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output or "Anthropic" in result.output


def test_chat_missing_project(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("anthropic.Anthropic"):
        result = invoke(runner, db_path, "chat", "999")
    assert result.exit_code == 1


def test_chat_exit_on_slash_exit(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")

    with patch("anthropic.Anthropic"):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat", "1"],
            input="/exit\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "Goodbye" in result.output


def test_chat_exit_on_quit(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")

    with patch("anthropic.Anthropic"):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat", "1"],
            input="/quit\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0


def test_chat_help_command(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")

    with patch("anthropic.Anthropic"):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat", "1"],
            input="/help\n/exit\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "/exit" in result.output


def test_chat_context_command(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Some task")

    with patch("anthropic.Anthropic"):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat", "1"],
            input="/context\n/exit\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "Proj" in result.output


def test_chat_one_turn(runner, db_path, monkeypatch):
    """Full chat turn: user message → AI response → exit."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_text_response(
        "You have 1 task to work on."
    )

    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Build feature")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat", "1"],
            input="What should I work on?\n/exit\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "1 task" in result.output


def test_chat_uses_default_project(runner, db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    # Redirect CONFIG_PATH so load_config() runtime-lookup picks up our temp file
    from nexus.commands.config import save_config

    cfg_path = tmp_path / "config.json"
    save_config({"default_project": 1}, cfg_path)
    monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg_path)

    invoke(runner, db_path, "project", "new", "Proj")

    with patch("anthropic.Anthropic"):
        result = runner.invoke(
            cli,
            ["--db", db_path, "chat"],
            input="/exit\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0


def test_chat_no_default_no_arg(runner, db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    # Redirect CONFIG_PATH to a non-existent file → empty config
    monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", tmp_path / "empty.json")

    with patch("anthropic.Anthropic"):
        result = invoke(runner, db_path, "chat")
    assert result.exit_code == 1


# ── _build_system_prompt ──────────────────────────────────────────────────────


def test_build_system_prompt_contains_project(tmp_path):
    from nexus.commands.chat import _build_system_prompt

    db = Database(tmp_path / "test.db")
    p = db.create_project("AwesomeProject")
    db.create_task(p.id, "Task Alpha")

    prompt = _build_system_prompt(db, p.id)
    assert "AwesomeProject" in prompt
    assert "Task Alpha" in prompt


def test_build_system_prompt_missing_project(tmp_path):
    from nexus.commands.chat import _build_system_prompt

    db = Database(tmp_path / "test.db")
    prompt = _build_system_prompt(db, 9999)
    assert prompt == ""


def test_build_system_prompt_includes_stats(tmp_path):
    from nexus.commands.chat import _build_system_prompt

    db = Database(tmp_path / "test.db")
    p = db.create_project("P")
    t = db.create_task(p.id, "T1")
    db.update_task(t.id, status=Status.DONE)
    db.create_task(p.id, "T2")

    prompt = _build_system_prompt(db, p.id)
    assert "2" in prompt  # total_tasks
    assert "1" in prompt  # done_tasks
