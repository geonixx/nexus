"""Tests for M20: nexus claude-init — CLAUDE.md snippet generator."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.commands.config import save_config
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


# ── build_claude_md unit tests ────────────────────────────────────────────────


class TestBuildClaudeMd:
    """Pure function tests — no DB, no CLI."""

    def _build(self, **kwargs):
        from nexus.commands.claude_init import build_claude_md

        defaults = dict(
            project_name="TestApp",
            project_id=1,
            nexus_db_path="/home/user/.nexus/test.db",
            test_cmd="pytest",
        )
        defaults.update(kwargs)
        return build_claude_md(**defaults)

    def test_returns_string(self):
        assert isinstance(self._build(), str)

    def test_project_name_in_output(self):
        result = self._build(project_name="MyAwesomeProject")
        assert "MyAwesomeProject" in result

    def test_project_id_in_output(self):
        result = self._build(project_id=42)
        assert "42" in result

    def test_db_path_in_output(self):
        result = self._build(nexus_db_path="/custom/path/nexus.db")
        assert "/custom/path/nexus.db" in result

    def test_default_test_cmd_is_pytest(self):
        result = self._build()
        assert "pytest" in result

    def test_custom_test_cmd_in_output(self):
        result = self._build(test_cmd="uv run pytest")
        assert "uv run pytest" in result

    def test_forbidden_section_present(self):
        result = self._build()
        assert "nexus agent run" in result
        assert "Rule" in result or "Do not" in result or "Never" in result

    def test_quick_reference_present(self):
        result = self._build()
        assert "task next" in result
        assert "task done" in result
        assert "task log" in result

    def test_before_and_after_sections_present(self):
        result = self._build()
        assert "Before starting work" in result
        assert "After completing work" in result

    def test_project_id_appears_in_nexus_commands(self):
        result = self._build(project_id=7)
        # Should appear in multiple commands (task next, task list, dashboard, task add)
        assert result.count("7") >= 3


# ── stdout output ─────────────────────────────────────────────────────────────


class TestClaudeInitStdout:
    def test_basic_stdout(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "TestApp")
        result = invoke(runner, db_path, "claude-init", "1")
        assert result.exit_code == 0
        assert "TestApp" in result.output

    def test_stdout_contains_db_path(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert result.exit_code == 0
        # The active --db path should be embedded
        assert db_path in result.output

    def test_stdout_contains_forbidden_section(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert "nexus agent run" in result.output

    def test_stdout_custom_test_cmd(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1", "--test-cmd", "uv run pytest")
        assert result.exit_code == 0
        assert "uv run pytest" in result.output

    def test_stdout_custom_db_path(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(
            runner, db_path, "claude-init", "1", "--db-path", "/custom/nexus.db"
        )
        assert result.exit_code == 0
        assert "/custom/nexus.db" in result.output

    def test_stdout_default_test_cmd_is_pytest(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert "pytest" in result.output


# ── file output ───────────────────────────────────────────────────────────────


class TestClaudeInitFileOutput:
    def test_writes_to_file(self, runner, db_path, tmp_path):
        invoke(runner, db_path, "project", "new", "TestApp")
        out_file = tmp_path / "CLAUDE.md"
        result = invoke(
            runner, db_path, "claude-init", "1", "--output", str(out_file)
        )
        assert result.exit_code == 0
        assert out_file.exists()
        assert "TestApp" in out_file.read_text()

    def test_file_content_complete(self, runner, db_path, tmp_path):
        invoke(runner, db_path, "project", "new", "Proj")
        out_file = tmp_path / "CLAUDE.md"
        invoke(runner, db_path, "claude-init", "1", "--output", str(out_file))
        content = out_file.read_text()
        assert "Before starting work" in content
        assert "After completing work" in content
        assert "nexus agent run" in content
        assert "Quick reference" in content

    def test_output_creates_parent_dirs(self, runner, db_path, tmp_path):
        invoke(runner, db_path, "project", "new", "Proj")
        nested = tmp_path / ".claude" / "CLAUDE.md"
        result = invoke(
            runner, db_path, "claude-init", "1", "--output", str(nested)
        )
        assert result.exit_code == 0
        assert nested.exists()

    def test_success_message_shown(self, runner, db_path, tmp_path):
        invoke(runner, db_path, "project", "new", "Proj")
        out_file = tmp_path / "CLAUDE.md"
        result = invoke(
            runner, db_path, "claude-init", "1", "--output", str(out_file)
        )
        # Success message should mention project name and file path
        assert "Proj" in result.output
        assert "CLAUDE.md" in result.output

    def test_output_shortflag(self, runner, db_path, tmp_path):
        invoke(runner, db_path, "project", "new", "Proj")
        out_file = tmp_path / "out.md"
        result = invoke(runner, db_path, "claude-init", "1", "-o", str(out_file))
        assert result.exit_code == 0
        assert out_file.exists()


# ── default_project fallback ──────────────────────────────────────────────────


class TestClaudeInitDefaultProject:
    def test_uses_default_project_from_config(
        self, runner, db_path, tmp_path, monkeypatch
    ):
        cfg_path = tmp_path / "config.json"
        save_config({"default_project": 1}, cfg_path)
        monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg_path)

        invoke(runner, db_path, "project", "new", "DefaultProj")
        result = invoke(runner, db_path, "claude-init")  # no project_id arg
        assert result.exit_code == 0
        assert "DefaultProj" in result.output

    def test_no_project_id_no_config_errors(
        self, runner, db_path, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "nexus.commands.config.CONFIG_PATH", tmp_path / "nonexistent.json"
        )
        result = invoke(runner, db_path, "claude-init")
        assert result.exit_code == 1
        assert "default_project" in result.output

    def test_explicit_id_overrides_default_project(
        self, runner, db_path, tmp_path, monkeypatch
    ):
        cfg_path = tmp_path / "config.json"
        save_config({"default_project": 2}, cfg_path)
        monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg_path)

        invoke(runner, db_path, "project", "new", "ProjectOne")  # id=1
        invoke(runner, db_path, "project", "new", "ProjectTwo")  # id=2
        result = invoke(runner, db_path, "claude-init", "1")  # explicit wins
        assert result.exit_code == 0
        assert "ProjectOne" in result.output
        assert "ProjectTwo" not in result.output


# ── error cases ───────────────────────────────────────────────────────────────


class TestClaudeInitErrors:
    def test_missing_project_exits(self, runner, db_path):
        result = invoke(runner, db_path, "claude-init", "999")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_default_project_pointing_to_missing_project(
        self, runner, db_path, tmp_path, monkeypatch
    ):
        cfg_path = tmp_path / "config.json"
        save_config({"default_project": 999}, cfg_path)
        monkeypatch.setattr("nexus.commands.config.CONFIG_PATH", cfg_path)

        result = invoke(runner, db_path, "claude-init")
        assert result.exit_code == 1
        assert "not found" in result.output


# ── template content ──────────────────────────────────────────────────────────


class TestClaudeInitContent:
    def test_all_nexus_read_commands_present(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert "task next" in result.output
        assert "task list" in result.output
        assert "dashboard" in result.output

    def test_all_nexus_write_commands_present(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert "task done" in result.output
        assert "task log" in result.output
        assert "task start" in result.output

    def test_nexus_db_env_var_used_in_commands(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        assert "NEXUS_DB=" in result.output

    def test_project_id_embedded_in_commands(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(runner, db_path, "claude-init", "1")
        # Commands like "nexus task next 1" should include the project id
        assert "task next 1" in result.output or "next 1" in result.output

    def test_custom_db_path_appears_in_nexus_db_var(self, runner, db_path):
        invoke(runner, db_path, "project", "new", "Proj")
        result = invoke(
            runner, db_path, "claude-init", "1", "--db-path", "/my/project.db"
        )
        assert "NEXUS_DB=/my/project.db" in result.output
