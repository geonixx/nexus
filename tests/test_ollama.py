"""Tests for Ollama AI provider (M17).

All network calls are mocked — no real Ollama daemon is required.
Tests cover:
  - _OllamaProvider availability detection
  - 3-second health-check timeout behaviour
  - stream() NDJSON parsing
  - complete() non-streaming response parsing
  - Error handling (URLError, JSON decode errors)
  - NexusAI provider chain (Ollama selected when no cloud keys)
  - provider_name, supports_tools, chat_turn error message
  - CLI commands that work with Ollama (suggest, estimate, digest)
  - CLI commands that reject Ollama gracefully (chat, agent run)
  - nexus init Ollama detection block
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.ai import (
    OLLAMA_DEFAULT_HOST,
    OLLAMA_DEFAULT_MODEL,
    NexusAI,
    _OllamaProvider,
)
from nexus.cli import cli


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_health_resp(status: int = 200):
    """Return a context-manager mock that looks like a 200 /api/tags response."""
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _ndjson_stream(chunks: list[str]) -> list[bytes]:
    """Build NDJSON lines as Ollama would stream them."""
    lines = []
    for i, chunk in enumerate(chunks):
        done = i == len(chunks) - 1
        obj = {"message": {"role": "assistant", "content": chunk}, "done": done}
        lines.append(json.dumps(obj).encode() + b"\n")
    return lines


def _mock_stream_resp(chunks: list[str]):
    """Return a context-manager mock for a streaming /api/chat response."""
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.__iter__ = lambda s: iter(_ndjson_stream(chunks))
    return resp


def _mock_complete_resp(content: str):
    """Return a context-manager mock for a non-streaming /api/chat response."""
    body = json.dumps({"message": {"role": "assistant", "content": content}, "done": True})
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = body.encode()
    return resp


# ── _OllamaProvider: availability ────────────────────────────────────────────


class TestOllamaProviderAvailability:
    def test_not_available_when_no_model_env(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        p = _OllamaProvider()
        assert p.available is False

    def test_not_available_when_model_empty(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "   ")
        p = _OllamaProvider()
        assert p.available is False

    def test_available_when_model_set_and_daemon_healthy(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            p = _OllamaProvider()
            assert p.available is True

    def test_not_available_when_daemon_unreachable(self, monkeypatch):
        import urllib.error
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            p = _OllamaProvider()
            assert p.available is False

    def test_not_available_when_daemon_returns_error_status(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(500)):
            p = _OllamaProvider()
            assert p.available is False

    def test_health_check_result_is_cached(self, monkeypatch):
        """urlopen should only be called once even if available is read twice."""
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        call_count = 0

        def _urlopen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_health_resp(200)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            p = _OllamaProvider()
            _ = p.available
            _ = p.available
        assert call_count == 1

    def test_custom_host_from_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "mistral")
        monkeypatch.setenv("OLLAMA_HOST", "http://myserver:11434")
        p = _OllamaProvider()
        assert p._host == "http://myserver:11434"
        assert p._model == "mistral"

    def test_trailing_slash_stripped_from_host(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434/")
        p = _OllamaProvider()
        assert p._host == "http://localhost:11434"

    def test_default_host_used_when_env_not_set(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        p = _OllamaProvider()
        assert p._host == OLLAMA_DEFAULT_HOST

    def test_model_name_stored(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder")
        p = _OllamaProvider()
        assert p._model == "qwen2.5-coder"


# ── _OllamaProvider: stream() ────────────────────────────────────────────────


class TestOllamaStream:
    def test_stream_yields_chunks(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        chunks = ["Hello", ", ", "world", "!"]
        with patch("urllib.request.urlopen", return_value=_mock_stream_resp(chunks)):
            p = _OllamaProvider()
            result = list(p.stream("sys", "user"))
        assert result == chunks

    def test_stream_sends_system_and_user_messages(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        captured_payload = {}

        def fake_urlopen(req, timeout=None):
            captured_payload["data"] = json.loads(req.data)
            return _mock_stream_resp(["hi"])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p = _OllamaProvider()
            list(p.stream("system prompt", "user question"))

        msgs = captured_payload["data"]["messages"]
        assert msgs[0] == {"role": "system", "content": "system prompt"}
        assert msgs[1] == {"role": "user", "content": "user question"}

    def test_stream_skips_empty_system(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        captured_payload = {}

        def fake_urlopen(req, timeout=None):
            captured_payload["data"] = json.loads(req.data)
            return _mock_stream_resp(["hi"])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p = _OllamaProvider()
            list(p.stream("", "user question"))

        msgs = captured_payload["data"]["messages"]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_stream_sends_correct_model(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "mistral")
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data)
            return _mock_stream_resp(["ok"])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p = _OllamaProvider()
            list(p.stream("s", "u"))

        assert captured["data"]["model"] == "mistral"
        assert captured["data"]["stream"] is True

    def test_stream_raises_runtime_error_on_url_error(self, monkeypatch):
        import urllib.error
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            p = _OllamaProvider()
            with pytest.raises(RuntimeError, match="Ollama connection error"):
                list(p.stream("s", "u"))

    def test_stream_skips_malformed_json_lines(self, monkeypatch):
        """Garbled lines should be silently skipped."""
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")

        bad_lines = [
            b"not-json\n",
            json.dumps({"message": {"content": "good"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ]
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.__iter__ = lambda s: iter(bad_lines)

        with patch("urllib.request.urlopen", return_value=resp):
            p = _OllamaProvider()
            result = list(p.stream("s", "u"))

        assert result == ["good"]

    def test_stream_stops_at_done_true(self, monkeypatch):
        """Lines after done=true should not be yielded.
        The content on the done=true line itself IS yielded (it's the last token).
        """
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")

        lines = [
            json.dumps({"message": {"content": "A"}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": "B"}, "done": True}).encode() + b"\n",
            # This line should never be yielded — we break after done=true
            json.dumps({"message": {"content": "C"}, "done": False}).encode() + b"\n",
        ]
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.__iter__ = lambda s: iter(lines)

        with patch("urllib.request.urlopen", return_value=resp):
            p = _OllamaProvider()
            result = list(p.stream("s", "u"))

        # A and B are yielded (B is the final token before done=true)
        assert result == ["A", "B"]
        # C must NOT appear — we stopped reading after done=true
        assert "C" not in result


# ── _OllamaProvider: complete() ──────────────────────────────────────────────


class TestOllamaComplete:
    def test_complete_returns_message_content(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_complete_resp("The answer")):
            p = _OllamaProvider()
            result = p.complete("sys", "user")
        assert result == "The answer"

    def test_complete_sends_stream_false(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data)
            return _mock_complete_resp("ok")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p = _OllamaProvider()
            p.complete("sys", "user")

        assert captured["data"]["stream"] is False

    def test_complete_raises_on_url_error(self, monkeypatch):
        import urllib.error
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
            p = _OllamaProvider()
            with pytest.raises(RuntimeError, match="Ollama connection error"):
                p.complete("s", "u")


# ── NexusAI provider chain ────────────────────────────────────────────────────


class TestNexusAIProviderChain:
    def _no_cloud(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def test_ollama_selected_when_no_cloud_keys(self, monkeypatch):
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            ai = NexusAI()
        assert isinstance(ai._provider, _OllamaProvider)

    def test_anthropic_takes_priority_over_ollama(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        try:
            import anthropic  # noqa: F401
            ai = NexusAI()
            assert not isinstance(ai._provider, _OllamaProvider)
        except ImportError:
            pytest.skip("anthropic not installed")

    def test_gemini_takes_priority_over_ollama(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        ai = NexusAI()
        assert not isinstance(ai._provider, _OllamaProvider)

    def test_ollama_not_selected_when_daemon_unreachable(self, monkeypatch):
        import urllib.error
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            ai = NexusAI()
            # Check available INSIDE the patch so the cached health-check uses the mock
            assert ai.available is False

    def test_provider_name_includes_model(self, monkeypatch):
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "mistral")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            ai = NexusAI()
        assert ai.provider_name == "Ollama (mistral)"

    def test_supports_tools_is_false_for_ollama(self, monkeypatch):
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            ai = NexusAI()
        assert ai.supports_tools is False

    def test_chat_turn_raises_helpful_error_for_ollama(self, monkeypatch):
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            ai = NexusAI()
        with pytest.raises(RuntimeError, match="Ollama"):
            ai.chat_turn([], [], lambda n, i: "")

    def test_chat_turn_error_names_the_active_provider(self, monkeypatch):
        """The error should say which provider is active, not just 'Gemini'."""
        self._no_cloud(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder")
        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            ai = NexusAI()
        with pytest.raises(RuntimeError, match="Ollama \\(qwen2.5-coder\\)"):
            ai.chat_turn([], [], lambda n, i: "")

    def test_not_available_when_no_providers(self, monkeypatch):
        self._no_cloud(monkeypatch)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        ai = NexusAI()
        assert ai.available is False


# ── CLI: commands that work with Ollama ───────────────────────────────────────


class TestOllamaCLI:
    """Smoke-test that AI CLI commands route through Ollama correctly."""

    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        return str(tmp_path / "nexus.db")

    def test_task_suggest_uses_ollama(self, monkeypatch, tmp_path):
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()

        # Create a project first
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])

        with patch("urllib.request.urlopen") as mock_open:
            # First call = health check, subsequent calls = stream
            mock_open.side_effect = [
                _mock_health_resp(200),
                _mock_stream_resp(["**[medium]** Set up CI (2h) — important"]),
            ]
            result = runner.invoke(cli, ["--db", db_path, "task", "suggest", "1"])

        assert result.exit_code == 0

    def test_report_digest_uses_ollama(self, monkeypatch, tmp_path):
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = [
                _mock_health_resp(200),
                _mock_stream_resp(["Good progress.", " On track.", " Ship soon."]),
            ]
            result = runner.invoke(cli, ["--db", db_path, "report", "digest", "1"])

        assert result.exit_code == 0

    def test_chat_rejects_ollama_with_helpful_message(self, monkeypatch, tmp_path):
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])

        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            result = runner.invoke(cli, ["--db", db_path, "chat", "1"], input="hello\n/exit\n")

        # chat_turn raises RuntimeError which surfaces as an error message
        assert "Ollama" in result.output or result.exit_code != 0

    def test_agent_run_rejects_ollama_with_helpful_message(self, monkeypatch, tmp_path):
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])

        with patch("urllib.request.urlopen", return_value=_mock_health_resp(200)):
            result = runner.invoke(cli, ["--db", db_path, "agent", "run", "1"])

        # Agent run checks supports_tools and prints a skip message
        assert result.exit_code == 0 or "tool" in result.output.lower() or "Ollama" in result.output

    def test_task_estimate_uses_ollama_complete(self, monkeypatch, tmp_path):
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])
        runner.invoke(cli, ["--db", db_path, "task", "add", "1", "Implement auth"])

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = [
                _mock_health_resp(200),
                _mock_stream_resp(["**Estimate:** 3 hours\n**Reasoning:** Moderate complexity."]),
            ]
            result = runner.invoke(cli, ["--db", db_path, "task", "estimate", "1"])

        assert result.exit_code == 0

    def test_no_ai_message_when_ollama_daemon_down(self, monkeypatch, tmp_path):
        import urllib.error
        db_path = self._setup(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["--db", db_path, "project", "new", "TestProj"])

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = runner.invoke(cli, ["--db", db_path, "task", "suggest", "1"])

        # When no AI is available nexus task suggest exits non-zero with a helpful message.
        # Verify there's no unhandled traceback and the output is user-readable.
        assert "Traceback" not in (result.output or "")
        assert "AI" in result.output or "key" in result.output.lower() or "api" in result.output.lower()


# ── nexus init: Ollama detection ─────────────────────────────────────────────


class TestInitOllamaDetection:
    def _base(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        return str(tmp_path / "nexus.db")

    def test_init_shows_ollama_configured_when_model_set(self, monkeypatch, tmp_path):
        db_path = self._base(monkeypatch, tmp_path)
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
        runner = CliRunner()
        with patch("shutil.which", return_value="/usr/local/bin/ollama"):
            result = runner.invoke(
                cli, ["--db", db_path, "init"], input="n\n"
            )
        assert "llama3.2" in result.output
        assert "✓" in result.output or "Ollama" in result.output

    def test_init_shows_ollama_hint_when_bin_found_but_no_model(self, monkeypatch, tmp_path):
        db_path = self._base(monkeypatch, tmp_path)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        runner = CliRunner()
        with patch("shutil.which", return_value="/usr/local/bin/ollama"):
            result = runner.invoke(
                cli, ["--db", db_path, "init"], input="n\n"
            )
        assert "OLLAMA_MODEL" in result.output

    def test_init_suggests_ollama_install_when_no_providers(self, monkeypatch, tmp_path):
        db_path = self._base(monkeypatch, tmp_path)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        runner = CliRunner()
        with patch("shutil.which", return_value=None):
            result = runner.invoke(
                cli, ["--db", db_path, "init"], input="n\n"
            )
        assert "ollama.com" in result.output or "Ollama" in result.output

    def test_init_shows_no_providers_warning_without_any_ai(self, monkeypatch, tmp_path):
        db_path = self._base(monkeypatch, tmp_path)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        runner = CliRunner()
        with patch("shutil.which", return_value=None):
            result = runner.invoke(
                cli, ["--db", db_path, "init"], input="n\n"
            )
        assert "No AI" in result.output or "providers" in result.output.lower()
