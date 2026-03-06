"""Tests for M19: nexus chat offline/advisory mode (Gemini / Ollama).

Covers:
  - offline_chat_system_prompt() prompt builder
  - _run_offline_chat() REPL: slash commands, streaming, history windowing
  - chat_cmd routing: Anthropic → tool mode, Gemini/Ollama → advisory mode
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args, **kwargs):
    return runner.invoke(
        cli, ["--db", db_path, *args], catch_exceptions=False, **kwargs
    )


def _make_offline_ai(chunks=None):
    """NexusAI mock configured for advisory/offline mode."""
    ai = MagicMock()
    ai.available = True
    ai.supports_tools = False
    ai.provider_name = "Gemini"
    ai.stream.return_value = iter(chunks or ["Advisory response."])
    return ai


# ── offline_chat_system_prompt ────────────────────────────────────────────────


class TestOfflineChatSystemPrompt:
    def test_returns_string_not_tuple(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt("P", "", "stats", "tasks", "stale", "ready")
        assert isinstance(result, str)

    def test_project_name_in_result(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "MyProject", "", "stats", "tasks", "stale", "ready"
        )
        assert "MyProject" in result

    def test_description_included_when_provided(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "P", "A great description", "stats", "tasks", "stale", "ready"
        )
        assert "A great description" in result

    def test_stats_line_in_result(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "P", "", "5 tasks 2 done", "tasks", "stale", "ready"
        )
        assert "5 tasks 2 done" in result

    def test_tasks_ctx_in_result(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "P", "", "stats", "#1 Build auth module", "stale", "ready"
        )
        assert "#1 Build auth module" in result

    def test_stale_ctx_in_result(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "P", "", "stats", "tasks", "stale: #3 stuck for 7d", "ready"
        )
        assert "stale: #3 stuck for 7d" in result

    def test_ready_ctx_in_result(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt(
            "P", "", "stats", "tasks", "stale", "ready: #2 Deploy feature"
        )
        assert "ready: #2 Deploy feature" in result

    def test_advisory_language_present(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt("P", "", "s", "t", "st", "r")
        lower = result.lower()
        assert "advisory" in lower or "read-only" in lower

    def test_nexus_cli_commands_mentioned(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt("P", "", "s", "t", "st", "r")
        assert "nexus" in result.lower()

    def test_result_is_non_empty(self):
        from nexus.ai import offline_chat_system_prompt

        result = offline_chat_system_prompt("P", "", "", "", "", "")
        assert len(result) > 50


# ── chat_cmd routing ──────────────────────────────────────────────────────────


class TestChatCmdRouting:
    def test_no_ai_exits_with_error(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)

        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "chat", "1")
        assert result.exit_code == 1

    def test_gemini_enters_advisory_mode(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Advisory mode" in result.output

    def test_ollama_enters_advisory_mode(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        mock_ai.provider_name = "Ollama (llama3.2)"
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Advisory mode" in result.output

    def test_anthropic_shows_full_tool_mode(self, runner, db_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = True
        mock_ai.provider_name = "Anthropic"
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Full tool mode" in result.output

    def test_provider_name_shown_in_banner(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        mock_ai.provider_name = "Gemini"
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/exit\n",
                catch_exceptions=False,
            )
        assert "Gemini" in result.output

    def test_invalid_project_exits(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = invoke(runner, db_path, "chat", "999")
        assert result.exit_code == 1

    def test_eof_exits_cleanly_in_advisory_mode(self, runner, db_path, monkeypatch):
        """No input → immediate EOF → advisory mode exits with code 0."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="",
                catch_exceptions=False,
            )
        assert result.exit_code == 0


# ── slash commands ────────────────────────────────────────────────────────────


class TestRunOfflineChatSlashCommands:
    def test_exit_exits_with_goodbye(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli, ["--db", db_path, "chat", "1"], input="/exit\n", catch_exceptions=False
            )
        assert result.exit_code == 0
        assert "Goodbye" in result.output

    def test_quit_exits(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli, ["--db", db_path, "chat", "1"], input="/quit\n", catch_exceptions=False
            )
        assert result.exit_code == 0
        assert "Goodbye" in result.output

    def test_help_shows_all_commands(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/help\n/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "/exit" in result.output
        assert "/context" in result.output
        assert "/clear" in result.output
        # AI should NOT be called for slash commands
        mock_ai.stream.assert_not_called()

    def test_context_shows_stats(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        invoke(runner, db_path, "task", "add", "1", "A task")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/context\n/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "refreshed" in result.output.lower()
        mock_ai.stream.assert_not_called()

    def test_clear_reports_history_cleared(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/clear\n/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "cleared" in result.output.lower()
        mock_ai.stream.assert_not_called()

    def test_empty_lines_skipped(self, runner, db_path, monkeypatch):
        """Blank input lines don't call the AI."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="\n   \n/exit\n",
                catch_exceptions=False,
            )
        mock_ai.stream.assert_not_called()

    def test_clear_is_offline_only_not_in_tool_chat(self, runner, db_path, monkeypatch):
        """/clear appears in advisory-mode /help but not in tool-mode /help."""
        # Anthropic tool-mode /help
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        mock_tool_ai = MagicMock()
        mock_tool_ai.available = True
        mock_tool_ai.supports_tools = True
        mock_tool_ai.provider_name = "Anthropic"
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_tool_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/help\n/exit\n",
                catch_exceptions=False,
            )
        assert "/clear" not in result.output


# ── streaming ─────────────────────────────────────────────────────────────────


class TestRunOfflineChatStreaming:
    def test_stream_chunks_appear_in_output(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai(["Hello, ", "this is ", "the response."])
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="What to work on?\n/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Hello, " in result.output
        assert "the response." in result.output

    def test_stream_called_with_user_message(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai(["ok"])
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="Tell me the status\n/exit\n",
                catch_exceptions=False,
            )
        assert mock_ai.stream.call_count == 1
        _system_arg, turn_user = mock_ai.stream.call_args[0]
        assert "Tell me the status" in turn_user

    def test_stream_called_with_system_containing_project_name(
        self, runner, db_path, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai(["ok"])
        invoke(runner, db_path, "project", "new", "UniqueProjectName")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="Hi\n/exit\n",
                catch_exceptions=False,
            )
        system_arg, _ = mock_ai.stream.call_args[0]
        assert "UniqueProjectName" in system_arg

    def test_stream_runtime_error_breaks_loop(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.stream.side_effect = RuntimeError("Connection refused")
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            result = runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="Hello\n/exit\n",
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Connection refused" in result.output
        # Should only call stream once (error breaks the loop)
        assert mock_ai.stream.call_count == 1

    def test_stream_not_called_for_slash_commands(self, runner, db_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_ai = _make_offline_ai()
        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="/help\n/context\n/clear\n/exit\n",
                catch_exceptions=False,
            )
        mock_ai.stream.assert_not_called()


# ── history windowing ─────────────────────────────────────────────────────────


class TestRunOfflineChatHistory:
    """Test the history windowing behavior of _run_offline_chat."""

    def _call_offline_chat(self, db, project_id, mock_ai, inputs, history_window=6):
        """Helper: call _run_offline_chat directly with mocked console.input."""
        from nexus.commands.chat import _run_offline_chat
        from nexus.ui import console

        project = db.get_project(project_id)
        stats = db.project_stats(project_id)

        idx = [0]

        def fake_input(prompt=""):
            if idx[0] >= len(inputs):
                raise EOFError
            val = inputs[idx[0]]
            idx[0] += 1
            return val

        with patch.object(console, "input", side_effect=fake_input):
            _run_offline_chat(db, project_id, mock_ai, project, stats, history_window=history_window)

    def test_first_turn_no_history_prefix(self, tmp_path):
        """First turn should not have 'Conversation so far' header."""
        db = Database(tmp_path / "test.db")
        p = db.create_project("P")

        all_turn_users = []

        def mock_stream(system, user):
            all_turn_users.append(user)
            return iter(["Response"])

        mock_ai = MagicMock()
        mock_ai.stream.side_effect = mock_stream

        self._call_offline_chat(db, p.id, mock_ai, ["First question"])

        assert len(all_turn_users) == 1
        assert "Conversation so far" not in all_turn_users[0]
        assert "First question" in all_turn_users[0]

    def test_second_turn_includes_first_exchange(self, tmp_path):
        """Second turn user string includes the first Q&A pair."""
        db = Database(tmp_path / "test.db")
        p = db.create_project("P")

        responses = ["Answer 1", "Answer 2"]
        idx = [0]

        def mock_stream(system, user):
            r = responses[idx[0]]
            idx[0] += 1
            return iter([r])

        mock_ai = MagicMock()
        mock_ai.stream.side_effect = mock_stream

        all_turn_users = []
        original_side_effect = mock_ai.stream.side_effect

        def capturing_stream(system, user):
            all_turn_users.append(user)
            return original_side_effect(system, user)

        mock_ai.stream.side_effect = capturing_stream

        self._call_offline_chat(db, p.id, mock_ai, ["First question", "Second question"])

        assert len(all_turn_users) == 2
        second_user = all_turn_users[1]
        assert "Conversation so far" in second_user
        assert "First question" in second_user
        assert "Answer 1" in second_user
        assert "Second question" in second_user

    def test_window_limits_old_history(self, tmp_path):
        """With history_window=1, only the most recent exchange is included."""
        db = Database(tmp_path / "test.db")
        p = db.create_project("P")

        responses = ["Resp A", "Resp B", "Resp C"]
        resp_idx = [0]
        all_turn_users = []

        def mock_stream(system, user):
            all_turn_users.append(user)
            r = responses[resp_idx[0]]
            resp_idx[0] += 1
            return iter([r])

        mock_ai = MagicMock()
        mock_ai.stream.side_effect = mock_stream

        self._call_offline_chat(
            db, p.id, mock_ai,
            ["Turn A", "Turn B", "Turn C"],
            history_window=1,
        )

        assert len(all_turn_users) == 3

        # Turn C (3rd call): window=1 → only Turn B/Resp B in history
        third_user = all_turn_users[2]
        assert "Turn C" in third_user
        assert "Turn B" in third_user
        assert "Resp B" in third_user
        # Turn A should have been evicted
        assert "Turn A" not in third_user

    def test_clear_resets_history(self, runner, db_path, monkeypatch):
        """After /clear, the next turn has no history prefix."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        all_turn_users = []
        call_idx = [0]
        responses = ["Resp before clear", "Resp after clear"]

        def stream_side_effect(system, user):
            all_turn_users.append(user)
            r = responses[call_idx[0]] if call_idx[0] < len(responses) else "ok"
            call_idx[0] += 1
            return iter([r])

        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.stream.side_effect = stream_side_effect

        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="Before clear\n/clear\nAfter clear\n/exit\n",
                catch_exceptions=False,
            )

        # Second AI call (after /clear): no history prefix, only "After clear"
        assert len(all_turn_users) == 2
        second_user = all_turn_users[1]
        assert "Conversation so far" not in second_user
        assert "Before clear" not in second_user
        assert "After clear" in second_user

    def test_history_grows_across_turns(self, tmp_path):
        """Each turn appends both the user message and response to history."""
        db = Database(tmp_path / "test.db")
        p = db.create_project("P")

        responses = ["Resp 1", "Resp 2"]
        resp_idx = [0]
        all_turn_users = []

        def mock_stream(system, user):
            all_turn_users.append(user)
            r = responses[resp_idx[0]]
            resp_idx[0] += 1
            return iter([r])

        mock_ai = MagicMock()
        mock_ai.stream.side_effect = mock_stream

        self._call_offline_chat(db, p.id, mock_ai, ["Q1", "Q2"])

        # After turn 1: history has (Q1, Resp 1)
        # Turn 2 prefix should have Q1 + Resp 1
        second_user = all_turn_users[1]
        assert "Q1" in second_user
        assert "Resp 1" in second_user

    def test_context_refresh_does_not_clear_history(self, runner, db_path, monkeypatch):
        """/context refreshes the system prompt but keeps conversation history."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        all_turn_users = []
        call_idx = [0]
        responses = ["Resp 1", "Resp 2"]

        def stream_side_effect(system, user):
            all_turn_users.append(user)
            r = responses[call_idx[0]] if call_idx[0] < len(responses) else "ok"
            call_idx[0] += 1
            return iter([r])

        mock_ai = MagicMock()
        mock_ai.available = True
        mock_ai.supports_tools = False
        mock_ai.provider_name = "Gemini"
        mock_ai.stream.side_effect = stream_side_effect

        invoke(runner, db_path, "project", "new", "Proj")
        with patch("nexus.ai.NexusAI", return_value=mock_ai):
            runner.invoke(
                cli,
                ["--db", db_path, "chat", "1"],
                input="Before context\n/context\nAfter context\n/exit\n",
                catch_exceptions=False,
            )

        # /context doesn't call AI, so we have exactly 2 stream calls
        assert len(all_turn_users) == 2
        # Second turn (after /context) should still carry history from first turn
        second_user = all_turn_users[1]
        assert "Before context" in second_user
        assert "Resp 1" in second_user


# ── import / export sanity ────────────────────────────────────────────────────


class TestOfflineChatExported:
    def test_offline_chat_system_prompt_importable(self):
        from nexus.ai import offline_chat_system_prompt

        assert callable(offline_chat_system_prompt)

    def test_run_offline_chat_importable(self):
        from nexus.commands.chat import _run_offline_chat

        assert callable(_run_offline_chat)
