"""Integration tests for the CLI."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from nexus.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def invoke(runner, db_path, *args):
    return runner.invoke(cli, ["--db", db_path, *args], catch_exceptions=False)


# ── Info ──────────────────────────────────────────────────────────────────────

def test_info(runner, db_path):
    result = invoke(runner, db_path, "info")
    assert result.exit_code == 0
    assert "NEXUS" in result.output


def test_version(runner, db_path):
    result = invoke(runner, db_path, "--version")
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# ── Project commands ──────────────────────────────────────────────────────────

def test_project_new(runner, db_path):
    result = invoke(runner, db_path, "project", "new", "MyApp", "-d", "A test app")
    assert result.exit_code == 0
    assert "MyApp" in result.output


def test_project_new_duplicate(runner, db_path):
    invoke(runner, db_path, "project", "new", "Dup")
    result = invoke(runner, db_path, "project", "new", "Dup")
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_project_list(runner, db_path):
    invoke(runner, db_path, "project", "new", "Alpha")
    invoke(runner, db_path, "project", "new", "Beta")
    result = invoke(runner, db_path, "project", "list")
    assert result.exit_code == 0
    assert "Alpha" in result.output
    assert "Beta" in result.output


def test_project_show(runner, db_path):
    invoke(runner, db_path, "project", "new", "ShowMe")
    result = invoke(runner, db_path, "project", "show", "1")
    assert result.exit_code == 0
    assert "ShowMe" in result.output


def test_project_show_missing(runner, db_path):
    result = invoke(runner, db_path, "project", "show", "999")
    assert result.exit_code == 1


def test_project_update(runner, db_path):
    invoke(runner, db_path, "project", "new", "OldName")
    result = invoke(runner, db_path, "project", "update", "1", "-n", "NewName")
    assert result.exit_code == 0
    assert "Updated" in result.output


# ── Task commands ─────────────────────────────────────────────────────────────

def test_task_add_and_list(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "First task", "-p", "high", "-e", "2.5")
    result = invoke(runner, db_path, "task", "list", "1")
    assert result.exit_code == 0
    assert "First task" in result.output
    assert "high" in result.output


def test_task_done(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Complete me")
    result = invoke(runner, db_path, "task", "done", "1")
    assert result.exit_code == 0
    assert "done" in result.output.lower()


def test_task_start(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Start me")
    result = invoke(runner, db_path, "task", "start", "1")
    assert result.exit_code == 0
    assert "in progress" in result.output.lower()


def test_task_log_time(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Long work")
    result = invoke(runner, db_path, "task", "log", "1", "3.5", "-n", "big session")
    assert result.exit_code == 0
    assert "3.5" in result.output


def test_task_add_missing_project(runner, db_path):
    result = invoke(runner, db_path, "task", "add", "999", "Orphan")
    assert result.exit_code == 1


# ── Sprint commands ───────────────────────────────────────────────────────────

def test_sprint_new_and_list(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "sprint", "new", "1", "Sprint 1", "-g", "Ship v1")
    result = invoke(runner, db_path, "sprint", "list", "1")
    assert result.exit_code == 0
    assert "Sprint 1" in result.output


def test_sprint_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "sprint", "new", "1", "Sprint 1")
    invoke(runner, db_path, "task", "add", "1", "Sprint task", "-s", "1")
    result = invoke(runner, db_path, "sprint", "tasks", "1")
    assert result.exit_code == 0
    assert "Sprint task" in result.output


# ── Report commands ───────────────────────────────────────────────────────────

def test_report_standup(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "In flight")
    invoke(runner, db_path, "task", "start", "1")
    result = invoke(runner, db_path, "report", "standup", "1")
    assert result.exit_code == 0
    assert "Standup" in result.output
    assert "In flight" in result.output


def test_report_summary(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    result = invoke(runner, db_path, "report", "summary", "1")
    assert result.exit_code == 0
    assert "Proj" in result.output


# ── task show ─────────────────────────────────────────────────────────────────

def test_task_show(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Detail me", "-d", "Some description", "-e", "5.0")
    result = invoke(runner, db_path, "task", "show", "1")
    assert result.exit_code == 0
    assert "Detail me" in result.output
    assert "Some description" in result.output
    assert "5.0" in result.output


def test_task_show_with_time_log(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Tracked task")
    invoke(runner, db_path, "task", "log", "1", "1.5", "-n", "morning session")
    invoke(runner, db_path, "task", "log", "1", "2.0", "-n", "afternoon push")
    result = invoke(runner, db_path, "task", "show", "1")
    assert result.exit_code == 0
    assert "morning session" in result.output
    assert "afternoon push" in result.output
    assert "1.5" in result.output


def test_task_show_missing(runner, db_path):
    result = invoke(runner, db_path, "task", "show", "999")
    assert result.exit_code == 1


# ── --json flags ──────────────────────────────────────────────────────────────

def test_project_list_json(runner, db_path):
    import json
    invoke(runner, db_path, "project", "new", "Alpha")
    invoke(runner, db_path, "project", "new", "Beta")
    result = invoke(runner, db_path, "project", "list", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2
    names = {p["name"] for p in data}
    assert names == {"Alpha", "Beta"}


def test_task_list_json(runner, db_path):
    import json
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "T1")
    invoke(runner, db_path, "task", "add", "1", "T2", "-p", "high")
    result = invoke(runner, db_path, "task", "list", "1", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    titles = {t["title"] for t in data}
    assert titles == {"T1", "T2"}


# ── project search ────────────────────────────────────────────────────────────

def test_project_search_finds_project(runner, db_path):
    invoke(runner, db_path, "project", "new", "Unicorn App", "-d", "magical stuff")
    invoke(runner, db_path, "project", "new", "Boring Corp")
    result = invoke(runner, db_path, "project", "search", "unicorn")
    assert result.exit_code == 0
    assert "Unicorn App" in result.output
    assert "Boring Corp" not in result.output


def test_project_search_finds_task(runner, db_path):
    invoke(runner, db_path, "project", "new", "Proj")
    invoke(runner, db_path, "task", "add", "1", "Implement OAuth login")
    invoke(runner, db_path, "task", "add", "1", "Write unit tests")
    result = invoke(runner, db_path, "project", "search", "oauth")
    assert result.exit_code == 0
    assert "OAuth" in result.output
    assert "unit tests" not in result.output


def test_project_search_no_results(runner, db_path):
    invoke(runner, db_path, "project", "new", "SomeProject")
    result = invoke(runner, db_path, "project", "search", "zzznomatch")
    assert result.exit_code == 0
    assert "No results" in result.output


# ── dashboard ─────────────────────────────────────────────────────────────────

def test_dashboard_empty_project(runner, db_path):
    invoke(runner, db_path, "project", "new", "Clean Slate")
    result = invoke(runner, db_path, "dashboard", "1")
    assert result.exit_code == 0
    assert "Clean Slate" in result.output
    assert "TODO" in result.output
    assert "IN PROGRESS" in result.output
    assert "DONE" in result.output


def test_dashboard_with_tasks(runner, db_path):
    invoke(runner, db_path, "project", "new", "Full Board")
    invoke(runner, db_path, "sprint", "new", "1", "Sprint 1", "-g", "Ship features")
    invoke(runner, db_path, "sprint", "start", "1")
    invoke(runner, db_path, "task", "add", "1", "Todo work", "-s", "1")
    invoke(runner, db_path, "task", "add", "1", "Active work", "-s", "1")
    invoke(runner, db_path, "task", "add", "1", "Finished work", "-s", "1")
    invoke(runner, db_path, "task", "start", "2")
    invoke(runner, db_path, "task", "done", "3")
    result = invoke(runner, db_path, "dashboard", "1")
    assert result.exit_code == 0
    assert "Full Board" in result.output
    assert "Sprint 1" in result.output
    assert "Ship features" in result.output
    assert "Todo work" in result.output
    assert "Active work" in result.output
    assert "Finished work" in result.output


def test_dashboard_missing_project(runner, db_path):
    result = invoke(runner, db_path, "dashboard", "999")
    assert result.exit_code == 1
