"""Tests for M15: nexus slack — Slack slash-command bridge.

Covers:
- Block Kit helper functions (_header, _mrkdwn, _divider, _context, _ephemeral,
  _in_channel, _slack_prio)
- _verify_slack_signature — valid, invalid signature, stale timestamp
- _route_command — routing to each subcommand, unknown subcommand, empty text
- _cmd_status — healthy project, missing project, tasks with ready/blocked
- _cmd_next  — no ready tasks, with tasks, custom limit, priority ordering
- _cmd_add   — task creation and confirmation payload
- _cmd_done  — mark done, non-numeric id, not-found id
- _cmd_help  — ephemeral payload with all commands listed
- _async_agent — AI not available, Gemini skip, success, exception handling
- slack_format CLI — renders JSON, requires project_id
- slack_serve CLI — missing project errors; handler factory smoke test
- slack_ping CLI  — success and failure paths (mocked _post_to_slack)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status
from nexus.commands.slack import (
    _cmd_add,
    _cmd_done,
    _cmd_help,
    _cmd_next,
    _cmd_status,
    _context,
    _divider,
    _ephemeral,
    _header,
    _in_channel,
    _make_handler,
    _mrkdwn,
    _post_to_slack,
    _route_command,
    _slack_prio,
    _verify_slack_signature,
    _async_agent,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def project(db):
    return db.create_project("SlackTest", description="For Slack tests")


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, db, *args):
    return runner.invoke(cli, ["--db", str(db.path), "slack", *args])


# ── Block Kit helpers ──────────────────────────────────────────────────────────


class TestBlockKitHelpers:
    def test_header_type(self):
        result = _header("Hello")
        assert result["type"] == "header"
        assert result["text"]["text"] == "Hello"
        assert result["text"]["type"] == "plain_text"

    def test_mrkdwn_type(self):
        result = _mrkdwn("*bold*")
        assert result["type"] == "section"
        assert result["text"]["type"] == "mrkdwn"
        assert result["text"]["text"] == "*bold*"

    def test_divider_type(self):
        assert _divider() == {"type": "divider"}

    def test_context_type(self):
        result = _context("footer text")
        assert result["type"] == "context"
        assert result["elements"][0]["text"] == "footer text"

    def test_ephemeral_response_type(self):
        result = _ephemeral("private msg")
        assert result["response_type"] == "ephemeral"
        assert result["text"] == "private msg"

    def test_in_channel_response_type(self):
        blocks = [_header("x")]
        result = _in_channel(blocks)
        assert result["response_type"] == "in_channel"
        assert result["blocks"] == blocks

    def test_slack_prio_contains_value(self):
        for p in Priority:
            result = _slack_prio(p)
            assert p.value in result

    def test_slack_prio_has_emoji(self):
        assert "🔴" in _slack_prio(Priority.CRITICAL)
        assert "🟠" in _slack_prio(Priority.HIGH)
        assert "🟡" in _slack_prio(Priority.MEDIUM)
        assert "⚪" in _slack_prio(Priority.LOW)


# ── _verify_slack_signature ────────────────────────────────────────────────────


class TestVerifySlackSignature:
    _SECRET = "secret_signing_key"

    def _make_sig(self, secret: str, timestamp: str, body: str) -> str:
        base = f"v0:{timestamp}:{body}"
        mac = hmac.new(secret.encode(), base.encode(), digestmod=hashlib.sha256)
        return "v0=" + mac.hexdigest()

    def test_valid_signature(self):
        ts = str(int(time.time()))
        body = "command=/nexus&text=status"
        sig = self._make_sig(self._SECRET, ts, body)
        assert _verify_slack_signature(self._SECRET, ts, body, sig) is True

    def test_wrong_secret_fails(self):
        ts = str(int(time.time()))
        body = "command=/nexus&text=status"
        sig = self._make_sig("wrong_secret", ts, body)
        assert _verify_slack_signature(self._SECRET, ts, body, sig) is False

    def test_tampered_body_fails(self):
        ts = str(int(time.time()))
        sig = self._make_sig(self._SECRET, ts, "original_body")
        assert _verify_slack_signature(self._SECRET, ts, "tampered_body", sig) is False

    def test_stale_timestamp_fails(self):
        ts = str(int(time.time()) - 400)  # >5 minutes ago
        body = "command=/nexus"
        sig = self._make_sig(self._SECRET, ts, body)
        assert _verify_slack_signature(self._SECRET, ts, body, sig) is False

    def test_malformed_timestamp_fails(self):
        assert _verify_slack_signature(self._SECRET, "not-a-number", "body", "v0=abc") is False

    def test_empty_inputs_fail(self):
        assert _verify_slack_signature(self._SECRET, "", "", "") is False


# ── _cmd_status ────────────────────────────────────────────────────────────────


class TestCmdStatus:
    def test_missing_project_returns_ephemeral(self, db):
        result = _cmd_status(db, 9999)
        assert result["response_type"] == "ephemeral"
        assert "not found" in result["text"]

    def test_valid_project_in_channel(self, db, project):
        result = _cmd_status(db, project.id)
        assert result["response_type"] == "in_channel"

    def test_blocks_present(self, db, project):
        result = _cmd_status(db, project.id)
        assert "blocks" in result
        assert len(result["blocks"]) > 0

    def test_header_contains_project_name(self, db, project):
        result = _cmd_status(db, project.id)
        header_block = result["blocks"][0]
        assert header_block["type"] == "header"
        assert "SlackTest" in header_block["text"]["text"]

    def test_health_grade_in_output(self, db, project):
        payload_str = json.dumps(_cmd_status(db, project.id))
        assert "/" in payload_str  # e.g. "A (90/100)"

    def test_ready_tasks_shown(self, db, project):
        task = db.create_task(project_id=project.id, title="Urgent work")
        result = _cmd_status(db, project.id)
        payload_str = json.dumps(result)
        assert "Ready to start" in payload_str or "Urgent" in payload_str

    def test_blocked_tasks_shown(self, db, project):
        task = db.create_task(project_id=project.id, title="Stuck task")
        db.update_task(task.id, status=Status.BLOCKED)
        result = _cmd_status(db, project.id)
        payload_str = json.dumps(result)
        assert "Blocked" in payload_str or "Stuck task" in payload_str

    def test_context_footer_present(self, db, project):
        result = _cmd_status(db, project.id)
        # Last block should be context with timestamp
        last_block = result["blocks"][-1]
        assert last_block["type"] == "context"


# ── _cmd_next ─────────────────────────────────────────────────────────────────


class TestCmdNext:
    def test_no_ready_tasks_ephemeral(self, db, project):
        result = _cmd_next(db, project.id)
        assert result["response_type"] == "ephemeral"

    def test_ready_tasks_in_channel(self, db, project):
        db.create_task(project_id=project.id, title="Do something")
        result = _cmd_next(db, project.id)
        assert result["response_type"] == "in_channel"

    def test_tasks_appear_in_output(self, db, project):
        db.create_task(project_id=project.id, title="Important task")
        payload_str = json.dumps(_cmd_next(db, project.id))
        assert "Important task" in payload_str

    def test_limit_respected(self, db, project):
        for i in range(10):
            db.create_task(project_id=project.id, title=f"Task {i}")
        result = _cmd_next(db, project.id, limit=3)
        payload_str = json.dumps(result)
        # Should show ≤3 tasks; context shows "Showing 3 of 10"
        assert "Showing 3" in payload_str

    def test_priority_ordering_critical_first(self, db, project):
        db.create_task(project_id=project.id, title="Low thing", priority=Priority.LOW)
        db.create_task(project_id=project.id, title="Critical thing", priority=Priority.CRITICAL)
        result = _cmd_next(db, project.id)
        payload_str = json.dumps(result)
        critical_pos = payload_str.find("Critical thing")
        low_pos = payload_str.find("Low thing")
        assert critical_pos < low_pos

    def test_header_block_type(self, db, project):
        db.create_task(project_id=project.id, title="Task A")
        result = _cmd_next(db, project.id)
        assert result["blocks"][0]["type"] == "header"


# ── _cmd_add ──────────────────────────────────────────────────────────────────


class TestCmdAdd:
    def test_creates_task(self, db, project):
        before = len(db.list_tasks(project_id=project.id))
        _cmd_add(db, project.id, "Build the thing", "alice")
        after = len(db.list_tasks(project_id=project.id))
        assert after == before + 1

    def test_returns_in_channel(self, db, project):
        result = _cmd_add(db, project.id, "New task", "bob")
        assert result["response_type"] == "in_channel"

    def test_title_in_payload(self, db, project):
        result = _cmd_add(db, project.id, "My cool task", "charlie")
        payload_str = json.dumps(result)
        assert "My cool task" in payload_str

    def test_user_name_in_payload(self, db, project):
        result = _cmd_add(db, project.id, "Task", "diana")
        payload_str = json.dumps(result)
        assert "diana" in payload_str

    def test_task_id_in_payload(self, db, project):
        result = _cmd_add(db, project.id, "Another task", "eve")
        payload_str = json.dumps(result)
        assert "#" in payload_str  # e.g. "Task #1 created"


# ── _cmd_done ─────────────────────────────────────────────────────────────────


class TestCmdDone:
    def test_marks_task_done(self, db, project):
        task = db.create_task(project_id=project.id, title="Finish me")
        _cmd_done(db, project.id, str(task.id))
        updated = db.get_task(task.id)
        assert updated.status == Status.DONE

    def test_returns_in_channel_on_success(self, db, project):
        task = db.create_task(project_id=project.id, title="Finish me")
        result = _cmd_done(db, project.id, str(task.id))
        assert result["response_type"] == "in_channel"

    def test_task_title_in_success_payload(self, db, project):
        task = db.create_task(project_id=project.id, title="Close this out")
        result = _cmd_done(db, project.id, str(task.id))
        payload_str = json.dumps(result)
        assert "Close this out" in payload_str

    def test_hash_prefix_accepted(self, db, project):
        task = db.create_task(project_id=project.id, title="Hash prefix")
        result = _cmd_done(db, project.id, f"#{task.id}")
        assert result["response_type"] == "in_channel"

    def test_non_numeric_id_ephemeral(self, db, project):
        result = _cmd_done(db, project.id, "abc")
        assert result["response_type"] == "ephemeral"
        assert "Usage" in result["text"]

    def test_not_found_id_ephemeral(self, db, project):
        result = _cmd_done(db, project.id, "9999")
        assert result["response_type"] == "ephemeral"
        assert "not found" in result["text"]


# ── _cmd_help ─────────────────────────────────────────────────────────────────


class TestCmdHelp:
    def test_returns_ephemeral(self):
        result = _cmd_help()
        assert result["response_type"] == "ephemeral"

    def test_lists_all_subcommands(self):
        text = _cmd_help()["text"]
        for sub in ("status", "next", "add", "done", "agent", "help"):
            assert sub in text


# ── _route_command ─────────────────────────────────────────────────────────────


class TestRouteCommand:
    _URL = "https://hooks.slack.com/response/fake"

    def test_empty_text_routes_to_status(self, db, project):
        result = _route_command(db, project.id, "", "alice", self._URL)
        # status returns in_channel with blocks
        assert result["response_type"] == "in_channel"

    def test_status_subcommand(self, db, project):
        result = _route_command(db, project.id, "status", "alice", self._URL)
        assert result["response_type"] == "in_channel"

    def test_next_subcommand(self, db, project):
        db.create_task(project_id=project.id, title="Next task")
        result = _route_command(db, project.id, "next", "alice", self._URL)
        assert result["response_type"] == "in_channel"

    def test_next_with_limit(self, db, project):
        for i in range(5):
            db.create_task(project_id=project.id, title=f"T{i}")
        result = _route_command(db, project.id, "next 3", "alice", self._URL)
        assert "Showing 3" in json.dumps(result)

    def test_add_subcommand_creates_task(self, db, project):
        _route_command(db, project.id, "add Buy milk", "alice", self._URL)
        tasks = db.list_tasks(project_id=project.id)
        assert any("Buy milk" in t.title for t in tasks)

    def test_add_without_title_ephemeral(self, db, project):
        result = _route_command(db, project.id, "add", "alice", self._URL)
        assert result["response_type"] == "ephemeral"

    def test_done_subcommand(self, db, project):
        task = db.create_task(project_id=project.id, title="Done task")
        result = _route_command(db, project.id, f"done {task.id}", "alice", self._URL)
        assert result["response_type"] == "in_channel"

    def test_done_without_arg_ephemeral(self, db, project):
        result = _route_command(db, project.id, "done", "alice", self._URL)
        assert result["response_type"] == "ephemeral"

    def test_agent_spawns_thread_and_returns_immediately(self, db, project):
        result = _route_command(db, project.id, "agent", "alice", self._URL)
        assert result["response_type"] == "ephemeral"
        assert "Running" in result["text"] or "AI" in result["text"]

    def test_agent_no_response_url_ephemeral(self, db, project):
        result = _route_command(db, project.id, "agent", "alice", "")
        assert result["response_type"] == "ephemeral"

    def test_help_subcommand(self, db, project):
        result = _route_command(db, project.id, "help", "alice", self._URL)
        assert result["response_type"] == "ephemeral"

    def test_unknown_subcommand_ephemeral(self, db, project):
        result = _route_command(db, project.id, "bogus", "alice", self._URL)
        assert result["response_type"] == "ephemeral"
        assert "Unknown" in result["text"]

    def test_case_insensitive_routing(self, db, project):
        result = _route_command(db, project.id, "STATUS", "alice", self._URL)
        assert result["response_type"] == "in_channel"


# ── _async_agent ───────────────────────────────────────────────────────────────


class TestAsyncAgent:
    def _make_ai(self, available=True, supports_tools=True):
        mock = MagicMock()
        mock.available = available
        mock.supports_tools = supports_tools
        mock.chat_turn.return_value = ("All good.", [])
        return mock

    def test_skips_and_posts_when_no_ai(self, db, project, monkeypatch):
        ai_mock = self._make_ai(available=False)
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")
        ai_mock.chat_turn.assert_not_called()
        assert any("not available" in p.get("text", "") for p in posted)

    def test_skips_when_gemini_only(self, db, project, monkeypatch):
        ai_mock = self._make_ai(available=True, supports_tools=False)
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")
        ai_mock.chat_turn.assert_not_called()
        assert any("Gemini" in p.get("text", "") for p in posted)

    def test_missing_project_posts_error(self, db, monkeypatch):
        ai_mock = self._make_ai()
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, 9999, "http://fake")
        assert any("not found" in p.get("text", "") for p in posted)

    def test_calls_chat_turn_when_available(self, db, project, monkeypatch):
        ai_mock = self._make_ai()
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")
        ai_mock.chat_turn.assert_called_once()

    def test_no_changes_posts_healthy_message(self, db, project, monkeypatch):
        ai_mock = self._make_ai()
        ai_mock.chat_turn.return_value = ("All good.", [])
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")
        text = " ".join(p.get("text", "") for p in posted)
        assert "no changes" in text.lower() or "✓" in text

    def test_write_log_reported(self, db, project, monkeypatch):
        ai_mock = self._make_ai()

        def fake_chat_turn(messages, tools, handler, **kwargs):
            handler("create_task", {"title": "Auto task", "priority": "medium"})
            return "Done.", []

        ai_mock.chat_turn = fake_chat_turn
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)

        def fake_handle_tool(name, inputs, db_, pid, write_log, **kwargs):
            write_log.append(f"Created: {inputs.get('title', '')}")
            return "created"

        monkeypatch.setattr("nexus.commands.agent._handle_tool", fake_handle_tool)
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")
        text = " ".join(p.get("text", "") for p in posted)
        assert "1 change" in text or "Auto task" in text

    def test_exception_handled_gracefully(self, db, project, monkeypatch):
        ai_mock = self._make_ai()
        ai_mock.chat_turn.side_effect = RuntimeError("API down")
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: ai_mock)
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        posted = []
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: posted.append(p))
        _async_agent(db, project.id, "http://fake")  # must not raise
        assert any("error" in p.get("text", "").lower() for p in posted)


# ── _make_handler (smoke test) ─────────────────────────────────────────────────


class TestMakeHandler:
    def test_returns_class(self, db, project):
        handler_cls = _make_handler(db, project.id, None)
        assert issubclass(handler_cls, BaseHTTPRequestHandler)

    def test_returns_class_with_secret(self, db, project):
        handler_cls = _make_handler(db, project.id, "s3cr3t")
        assert issubclass(handler_cls, BaseHTTPRequestHandler)


try:
    from http.server import BaseHTTPRequestHandler
    _HAS_BASE_HANDLER = True
except ImportError:
    _HAS_BASE_HANDLER = False


# ── slack format CLI ───────────────────────────────────────────────────────────


class TestSlackFormatCmd:
    def test_format_prints_json(self, runner, db, project):
        r = _invoke(runner, db, "format", str(project.id))
        assert r.exit_code == 0
        # Output should be valid JSON
        output = r.output.strip()
        # Rich Syntax adds ANSI codes, so just check key strings
        assert "response_type" in output or "in_channel" in output or "blocks" in output

    def test_format_no_project_fails(self, runner, db, monkeypatch):
        monkeypatch.setattr("nexus.commands.slack.load_config", lambda: {})
        r = _invoke(runner, db, "format")
        assert r.exit_code != 0

    def test_format_bad_project_exits_ok_but_shows_ephemeral(self, runner, db):
        r = _invoke(runner, db, "format", "9999")
        # _cmd_status returns ephemeral for missing project; format still prints it
        assert r.exit_code == 0
        assert "not found" in r.output.lower() or "ephemeral" in r.output.lower()

    def test_format_uses_default_project(self, runner, db, project, monkeypatch):
        monkeypatch.setattr(
            "nexus.commands.slack.load_config",
            lambda: {"default_project": project.id},
        )
        r = _invoke(runner, db, "format")
        assert r.exit_code == 0


# ── slack serve CLI ────────────────────────────────────────────────────────────


class TestSlackServeCmd:
    """Tests for `nexus slack serve`.

    We mock `nexus.commands.slack.HTTPServer` entirely so no real socket is
    bound — HTTPServer.__init__ would otherwise grab a port even when
    serve_forever is stubbed, causing "Address already in use" between tests.
    """

    def _mock_server(self, monkeypatch):
        """Replace HTTPServer with a MagicMock so no real socket is created."""
        monkeypatch.setattr("nexus.commands.slack.HTTPServer", MagicMock)

    def test_missing_project_fails(self, runner, db, monkeypatch):
        self._mock_server(monkeypatch)
        monkeypatch.setattr("nexus.commands.slack.load_config", lambda: {})
        r = _invoke(runner, db, "serve", "--project-id", "9999")
        assert r.exit_code != 0

    def test_no_project_no_default_fails(self, runner, db, monkeypatch):
        self._mock_server(monkeypatch)
        monkeypatch.setattr("nexus.commands.slack.load_config", lambda: {})
        r = _invoke(runner, db, "serve")
        assert r.exit_code != 0

    def test_serve_starts_and_stops(self, runner, db, project, monkeypatch):
        """Server should start and immediately stop when HTTPServer is mocked."""
        self._mock_server(monkeypatch)
        r = _invoke(runner, db, "serve", "--project-id", str(project.id), "--port", "19999")
        assert r.exit_code == 0
        assert "localhost" in r.output

    def test_serve_shows_project_name(self, runner, db, project, monkeypatch):
        self._mock_server(monkeypatch)
        r = _invoke(runner, db, "serve", "--project-id", str(project.id))
        assert "SlackTest" in r.output

    def test_serve_shows_signature_disabled(self, runner, db, project, monkeypatch):
        self._mock_server(monkeypatch)
        r = _invoke(runner, db, "serve", "--project-id", str(project.id))
        assert r.exit_code == 0
        assert "disabled" in r.output.lower() or "dev mode" in r.output.lower()

    def test_serve_shows_signature_enabled(self, runner, db, project, monkeypatch):
        self._mock_server(monkeypatch)
        r = _invoke(
            runner, db, "serve",
            "--project-id", str(project.id),
            "--secret", "mysecret",
        )
        assert r.exit_code == 0
        assert "enabled" in r.output.lower()

    def test_default_project_from_config(self, runner, db, project, monkeypatch):
        self._mock_server(monkeypatch)
        monkeypatch.setattr(
            "nexus.commands.slack.load_config",
            lambda: {"default_project": project.id},
        )
        r = _invoke(runner, db, "serve")
        assert r.exit_code == 0


# ── slack ping CLI ─────────────────────────────────────────────────────────────


class TestSlackPingCmd:
    def test_ping_success(self, runner, db, monkeypatch):
        monkeypatch.setattr("nexus.commands.slack._post_to_slack", lambda url, p: None)
        r = _invoke(runner, db, "ping", "https://hooks.slack.com/fake")
        assert r.exit_code == 0
        assert "sent" in r.output.lower() or "success" in r.output.lower()

    def test_ping_failure_exits_nonzero(self, runner, db, monkeypatch):
        def _fail(url, p):
            raise ConnectionError("timeout")

        monkeypatch.setattr("nexus.commands.slack._post_to_slack", _fail)
        r = _invoke(runner, db, "ping", "https://hooks.slack.com/fake")
        assert r.exit_code != 0

    def test_ping_failure_shows_error(self, runner, db, monkeypatch):
        def _fail(url, p):
            raise ConnectionError("timeout")

        monkeypatch.setattr("nexus.commands.slack._post_to_slack", _fail)
        r = _invoke(runner, db, "ping", "https://hooks.slack.com/fake")
        assert "failed" in r.output.lower() or "error" in r.output.lower()
