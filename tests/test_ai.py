"""Tests for AI features — all API calls are mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.ai import (
    NexusAI,
    digest_prompt,
    estimate_task_prompt,
    suggest_tasks_prompt,
)
from nexus.cli import cli


# ── NexusAI unit tests ────────────────────────────────────────────────────────

def test_nexusai_unavailable_without_any_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    ai = NexusAI()
    assert ai.available is False


def test_nexusai_available_with_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("anthropic.Anthropic"):
        ai = NexusAI()
        assert ai.available is True
        assert ai.provider_name == "Anthropic"


def test_nexusai_available_with_gemini_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-gemini-key")
    ai = NexusAI()
    assert ai.available is True
    assert ai.provider_name == "Gemini"


def test_nexusai_prefers_anthropic_over_gemini(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-gemini-key")
    with patch("anthropic.Anthropic"):
        ai = NexusAI()
        assert ai.provider_name == "Anthropic"


def test_nexusai_stream_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    ai = NexusAI()
    with pytest.raises(RuntimeError):
        list(ai.stream("sys", "user"))


def test_nexusai_complete_returns_joined_chunks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = MagicMock()
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.text_stream = iter(["Hello", " ", "world"])
    mock_client.messages.stream.return_value = mock_stream_ctx

    with patch("anthropic.Anthropic", return_value=mock_client):
        ai = NexusAI()
        result = ai.complete("sys", "user")
    assert result == "Hello world"


# ── Prompt builder tests ──────────────────────────────────────────────────────

def test_suggest_tasks_prompt_includes_project():
    system, user = suggest_tasks_prompt("MyApp", "A web app", ["Existing task"])
    assert "MyApp" in user
    assert "A web app" in user
    assert "Existing task" in user


def test_suggest_tasks_prompt_handles_no_tasks():
    system, user = suggest_tasks_prompt("Proj", "", [])
    assert "none yet" in user


def test_estimate_task_prompt_includes_task():
    system, user = estimate_task_prompt("Write tests", "Unit tests for core module", [("Build API", 3.0)])
    assert "Write tests" in user
    assert "Unit tests for core module" in user
    assert "Build API" in user
    assert "3.0h" in user


def test_estimate_task_prompt_no_similar():
    system, user = estimate_task_prompt("Quick fix", "", [])
    assert "no completed tasks" in user


def test_digest_prompt_includes_stats():
    system, user = digest_prompt(
        project_name="Alpha",
        project_desc="A cool project",
        total=10,
        done=5,
        in_prog=2,
        blocked=1,
        hours=20.0,
        done_titles=["Task A", "Task B"],
        in_prog_titles=["Task C"],
        sprint_name="Sprint 1",
        sprint_goal="Ship v1",
    )
    assert "Alpha" in user
    assert "5/10" in user
    assert "Sprint 1" in user
    assert "Ship v1" in user
    assert "Task A" in user
    assert "Task C" in user


def test_digest_prompt_handles_no_sprint():
    system, user = digest_prompt(
        project_name="Beta", project_desc="", total=0, done=0,
        in_prog=0, blocked=0, hours=0.0,
        done_titles=[], in_prog_titles=[],
        sprint_name=None, sprint_goal=None,
    )
    assert "Beta" in user
    assert "sprint" not in user.lower()


# ── CLI integration tests (fully mocked) ─────────────────────────────────────

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args):
    return runner.invoke(cli, ["--db", db_path, *args], catch_exceptions=False)


def _mock_ai_stream(chunks: list[str]):
    """Return a context manager mock that streams the given chunks via Anthropic."""
    mock_client = MagicMock()
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.text_stream = iter(chunks)
    mock_client.messages.stream.return_value = mock_stream_ctx
    return mock_client


# task suggest ─────────────────────────────────────────────────────────────────

def test_task_suggest_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "task", "suggest", "1")
    assert result.exit_code == 1
    assert "AI provider" in result.output or "KEY" in result.output


def test_task_suggest_missing_project(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = invoke(runner, db_path, "task", "suggest", "999")
    assert result.exit_code == 1


def test_task_suggest_streams_output(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = _mock_ai_stream([
        "**[high]** Write unit tests (2h) — critical for reliability\n",
        "**[medium]** Add logging (1h) — observability matters\n",
    ])
    invoke(runner, db_path, "project", "new", "MyApp", "-d", "A great app")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "task", "suggest", "1")

    assert result.exit_code == 0
    assert "Write unit tests" in result.output
    assert "Add logging" in result.output


def test_task_suggest_add_flag(runner, db_path, monkeypatch):
    """--add flag should prompt user and create tasks from parsed suggestions."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    suggestion = "**[high]** Implement auth (3h) — security first\n"
    mock_client = _mock_ai_stream([suggestion])
    invoke(runner, db_path, "project", "new", "Proj")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = runner.invoke(
            cli,
            ["--db", db_path, "task", "suggest", "1", "--add"],
            input="all\n",
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    # Verify task was created
    from nexus.db import Database
    db = Database(Path(db_path))
    tasks = db.list_tasks(project_id=1)
    titles = [t.title for t in tasks]
    assert "Implement auth" in titles


# task estimate ────────────────────────────────────────────────────────────────

def test_task_estimate_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Build feature")
    result = invoke(runner, db_path, "task", "estimate", "1")
    assert result.exit_code == 1
    assert "AI provider" in result.output or "KEY" in result.output


def test_task_estimate_missing_task(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = invoke(runner, db_path, "task", "estimate", "999")
    assert result.exit_code == 1


def test_task_estimate_streams_output(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = _mock_ai_stream([
        "**Estimate:** 3 hours\n",
        "**Reasoning:** Moderate complexity.\n",
        "**Confidence:** medium",
    ])
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Build cache layer")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "task", "estimate", "1")

    assert result.exit_code == 0
    assert "Estimate" in result.output or "Build cache layer" in result.output


# report digest ────────────────────────────────────────────────────────────────

def test_report_digest_no_key(runner, db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "report", "digest", "1")
    assert result.exit_code == 1
    assert "AI provider" in result.output or "KEY" in result.output


def test_report_digest_missing_project(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = invoke(runner, db_path, "report", "digest", "999")
    assert result.exit_code == 1


def test_report_digest_streams_output(runner, db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mock_client = _mock_ai_stream([
        "The project is progressing well. ",
        "Three tasks are complete and two are in progress. ",
        "Next up: finishing the dashboard.",
    ])
    invoke(runner, db_path, "project", "new", "MyProj", "-d", "A cool project")
    invoke(runner, db_path, "task", "add", "1", "Task A")
    invoke(runner, db_path, "task", "done", "1")

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = invoke(runner, db_path, "report", "digest", "1")

    assert result.exit_code == 0
    assert "progressing well" in result.output or "MyProj" in result.output
