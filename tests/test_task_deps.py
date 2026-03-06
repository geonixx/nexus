"""Tests for M21: Task Dependencies — enhanced CLI, task next filtering,
dashboard indicators, AI context, same-project validation, Task.depends_on field.

Complements tests/test_deps.py (M11 DB layer + original task depend/undepend/graph).
This file covers M21-specific additions only.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status, Task


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(path=tmp_path / "test.db")


@pytest.fixture
def project(db):
    return db.create_project("Alpha")


@pytest.fixture
def project2(db):
    return db.create_project("Beta")


@pytest.fixture
def runner():
    return CliRunner()


def _task(db, proj, title, *, priority=Priority.MEDIUM, status=None):
    t = db.create_task(proj.id, title, priority=priority)
    if status:
        db.update_task(t.id, status=status)
        t = db.get_task(t.id)
    return t


def _invoke(runner, db, *args):
    return runner.invoke(cli, ["--db", str(db.path), *args], catch_exceptions=False)


# ── TestSameProjectValidation ─────────────────────────────────────────────────


class TestSameProjectValidation:
    def test_same_project_allowed(self, db, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        assert db.add_dependency(t2.id, t1.id) is True

    def test_cross_project_blocked(self, db, project, project2):
        t1 = _task(db, project, "A")
        t2 = _task(db, project2, "B")
        assert db.add_dependency(t2.id, t1.id) is False

    def test_cross_project_cli_error(self, db, runner, project, project2):
        t1 = _task(db, project, "A")
        t2 = _task(db, project2, "B")
        result = _invoke(runner, db, "task", "dep", "add", str(t2.id), str(t1.id))
        assert result.exit_code == 1
        assert "different projects" in result.output


# ── TestTaskDependsOnField ────────────────────────────────────────────────────


class TestTaskDependsOnField:
    def test_default_empty(self):
        t = Task(project_id=1, title="test")
        assert t.depends_on == []

    def test_field_can_be_set(self):
        t = Task(project_id=1, title="test", depends_on=[3, 7])
        assert t.depends_on == [3, 7]

    def test_model_dump_includes_field(self):
        t = Task(project_id=1, title="test")
        d = t.model_dump()
        assert "depends_on" in d
        assert d["depends_on"] == []


# ── TestGetDependencyGraph ────────────────────────────────────────────────────


class TestGetDependencyGraph:
    def test_empty_project(self, db, project):
        graph = db.get_dependency_graph(project.id)
        assert graph == {}

    def test_no_deps_all_empty_lists(self, db, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        graph = db.get_dependency_graph(project.id)
        assert set(graph.keys()) == {t1.id, t2.id}
        assert graph[t1.id] == []
        assert graph[t2.id] == []

    def test_single_edge(self, db, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        db.add_dependency(t2.id, t1.id)
        graph = db.get_dependency_graph(project.id)
        assert graph[t2.id] == [t1.id]
        assert graph[t1.id] == []

    def test_cross_project_edge_excluded(self, db, project, project2):
        t1 = _task(db, project, "A")
        t2 = _task(db, project2, "B")
        # Even if somehow inserted directly, cross-project edges shouldn't appear
        # (add_dependency now blocks this, but test graph filtering too)
        graph = db.get_dependency_graph(project.id)
        # t2 belongs to project2, so it won't be in project's graph
        assert t2.id not in graph

    def test_diamond_graph(self, db, project):
        # A → B, A → C, B → D, C → D
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        d = _task(db, project, "D")
        db.add_dependency(b.id, a.id)  # B depends on A
        db.add_dependency(c.id, a.id)  # C depends on A
        db.add_dependency(d.id, b.id)  # D depends on B
        db.add_dependency(d.id, c.id)  # D depends on C
        graph = db.get_dependency_graph(project.id)
        assert a.id in graph[b.id]
        assert a.id in graph[c.id]
        assert b.id in graph[d.id]
        assert c.id in graph[d.id]
        assert graph[a.id] == []


# ── TestTaskDepAddCLI ─────────────────────────────────────────────────────────


class TestTaskDepAddCLI:
    def test_add_dep_success(self, db, runner, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        result = _invoke(runner, db, "task", "dep", "add", str(t2.id), str(t1.id))
        assert result.exit_code == 0
        assert db.has_unmet_dependencies(t2.id)

    def test_add_dep_success_message(self, db, runner, project):
        t1 = _task(db, project, "Alpha Task")
        t2 = _task(db, project, "Beta Task")
        result = _invoke(runner, db, "task", "dep", "add", str(t2.id), str(t1.id))
        assert result.exit_code == 0
        assert "Alpha Task" in result.output or str(t1.id) in result.output

    def test_already_exists_is_idempotent(self, db, runner, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "add", str(t2.id), str(t1.id))
        assert result.exit_code == 0  # idempotent, not an error

    def test_self_dep_error(self, db, runner, project):
        t1 = _task(db, project, "A")
        result = _invoke(runner, db, "task", "dep", "add", str(t1.id), str(t1.id))
        assert result.exit_code == 1

    def test_missing_task_error(self, db, runner, project):
        t1 = _task(db, project, "A")
        result = _invoke(runner, db, "task", "dep", "add", "9999", str(t1.id))
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_missing_dep_task_error(self, db, runner, project):
        t1 = _task(db, project, "A")
        result = _invoke(runner, db, "task", "dep", "add", str(t1.id), "9999")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_cycle_error(self, db, runner, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        db.add_dependency(t2.id, t1.id)  # B depends on A
        result = _invoke(runner, db, "task", "dep", "add", str(t1.id), str(t2.id))  # A depends on B → cycle
        assert result.exit_code == 1
        assert "circular" in result.output.lower()

    def test_cross_project_dep_error(self, db, runner, project, project2):
        t1 = _task(db, project, "A")
        t2 = _task(db, project2, "B")
        result = _invoke(runner, db, "task", "dep", "add", str(t2.id), str(t1.id))
        assert result.exit_code == 1
        assert "different projects" in result.output


# ── TestTaskDepRemoveCLI ──────────────────────────────────────────────────────


class TestTaskDepRemoveCLI:
    def test_remove_success(self, db, runner, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "remove", str(t2.id), str(t1.id))
        assert result.exit_code == 0
        assert not db.has_unmet_dependencies(t2.id)

    def test_remove_success_message(self, db, runner, project):
        t1 = _task(db, project, "Prereq Task")
        t2 = _task(db, project, "Dependent Task")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "remove", str(t2.id), str(t1.id))
        assert result.exit_code == 0
        assert "Prereq Task" in result.output or str(t1.id) in result.output

    def test_remove_nonexistent_dep_fails(self, db, runner, project):
        t1 = _task(db, project, "A")
        t2 = _task(db, project, "B")
        # No dependency added first
        result = _invoke(runner, db, "task", "dep", "remove", str(t2.id), str(t1.id))
        assert result.exit_code == 1

    def test_remove_missing_task_fails(self, db, runner, project):
        t1 = _task(db, project, "A")
        result = _invoke(runner, db, "task", "dep", "remove", "9999", str(t1.id))
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_remove_missing_dep_task_fails(self, db, runner, project):
        t1 = _task(db, project, "A")
        result = _invoke(runner, db, "task", "dep", "remove", str(t1.id), "9999")
        assert result.exit_code == 1
        assert "not found" in result.output


# ── TestTaskDepListCLI ────────────────────────────────────────────────────────


class TestTaskDepListCLI:
    def test_list_no_deps_shows_none(self, db, runner, project):
        t1 = _task(db, project, "Standalone Task")
        result = _invoke(runner, db, "task", "dep", "list", str(t1.id))
        assert result.exit_code == 0
        assert "none" in result.output.lower() or "(none" in result.output

    def test_list_shows_prerequisites(self, db, runner, project):
        t1 = _task(db, project, "Must Do First")
        t2 = _task(db, project, "Do Second")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "list", str(t2.id))
        assert result.exit_code == 0
        assert "Must Do First" in result.output

    def test_list_shows_dependents(self, db, runner, project):
        t1 = _task(db, project, "Unblock Others")
        t2 = _task(db, project, "Waiting Task")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "list", str(t1.id))
        assert result.exit_code == 0
        assert "Waiting Task" in result.output

    def test_list_done_dep_still_shown(self, db, runner, project):
        t1 = _task(db, project, "Already Done", status=Status.DONE)
        t2 = _task(db, project, "Blocked By Done")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "dep", "list", str(t2.id))
        assert result.exit_code == 0
        assert "Already Done" in result.output

    def test_list_missing_task_fails(self, db, runner, project):
        result = _invoke(runner, db, "task", "dep", "list", "9999")
        assert result.exit_code == 1
        assert "not found" in result.output


# ── TestTaskNextDepFiltering ──────────────────────────────────────────────────


class TestTaskNextDepFiltering:
    def test_dep_blocked_task_excluded(self, db, runner, project):
        blocker = _task(db, project, "Blocker", status=Status.TODO)
        blocked = _task(db, project, "Must Wait", status=Status.TODO)
        db.add_dependency(blocked.id, blocker.id)
        result = _invoke(runner, db, "task", "next", str(project.id))
        assert result.exit_code == 0
        # The blocker should appear; the blocked task should NOT (its dep is unmet)
        assert "Must Wait" not in result.output

    def test_dep_satisfied_task_included(self, db, runner, project):
        blocker = _task(db, project, "Done Blocker", status=Status.DONE)
        unblocked = _task(db, project, "Now Free", status=Status.TODO)
        db.add_dependency(unblocked.id, blocker.id)
        result = _invoke(runner, db, "task", "next", str(project.id))
        assert result.exit_code == 0
        assert "Now Free" in result.output

    def test_in_progress_shown_regardless(self, db, runner, project):
        blocker = _task(db, project, "Blocker")
        active = _task(db, project, "Active", status=Status.IN_PROGRESS)
        db.add_dependency(active.id, blocker.id)
        result = _invoke(runner, db, "task", "next", str(project.id))
        assert result.exit_code == 0
        assert "Active" in result.output

    def test_dep_blocked_count_in_footer(self, db, runner, project):
        blocker = _task(db, project, "Blocker")
        t1 = _task(db, project, "Wait1")
        t2 = _task(db, project, "Wait2")
        db.add_dependency(t1.id, blocker.id)
        db.add_dependency(t2.id, blocker.id)
        result = _invoke(runner, db, "task", "next", str(project.id))
        assert result.exit_code == 0
        # Footer should mention the 2 dep-blocked tasks
        assert "2" in result.output
        assert "dep" in result.output.lower()

    def test_all_todos_dep_blocked_message(self, db, runner, project):
        blocker = _task(db, project, "Big Blocker")
        t1 = _task(db, project, "Wait1")
        db.add_dependency(t1.id, blocker.id)
        # blocker itself is TODO with no deps — it should appear
        result = _invoke(runner, db, "task", "next", str(project.id))
        assert result.exit_code == 0
        assert "Big Blocker" in result.output  # the blocker is ready

    def test_tag_filter_with_deps(self, db, runner, project):
        t1 = _task(db, project, "Tagged Blocker")
        t2 = _task(db, project, "Tagged Blocked")
        db.add_tag(t1.id, "ui")
        db.add_tag(t2.id, "ui")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "task", "next", str(project.id), "--tag", "ui")
        assert result.exit_code == 0
        assert "Tagged Blocked" not in result.output
        assert "Tagged Blocker" in result.output


# ── TestDashboardDepIndicators ────────────────────────────────────────────────


class TestDashboardDepIndicators:
    def test_no_deps_no_indicator(self, db, runner, project):
        _task(db, project, "Solo Task")
        result = _invoke(runner, db, "dashboard", str(project.id))
        assert result.exit_code == 0
        assert "deps:" not in result.output

    def test_open_dep_shows_indicator(self, db, runner, project):
        t1 = _task(db, project, "Blocker")
        t2 = _task(db, project, "Waiting")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "dashboard", str(project.id))
        assert result.exit_code == 0
        assert "deps:" in result.output
        assert f"#{t1.id}" in result.output

    def test_done_dep_no_indicator(self, db, runner, project):
        t1 = _task(db, project, "Finished", status=Status.DONE)
        t2 = _task(db, project, "Now Free")
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "dashboard", str(project.id))
        assert result.exit_code == 0
        # dep is done → not shown as blocking
        assert "deps:" not in result.output

    def test_multiple_open_deps_shown(self, db, runner, project):
        t1 = _task(db, project, "Dep One")
        t2 = _task(db, project, "Dep Two")
        t3 = _task(db, project, "Waiter")
        db.add_dependency(t3.id, t1.id)
        db.add_dependency(t3.id, t2.id)
        result = _invoke(runner, db, "dashboard", str(project.id))
        assert result.exit_code == 0
        assert f"#{t1.id}" in result.output
        assert f"#{t2.id}" in result.output

    def test_in_progress_column_no_dep_indicator(self, db, runner, project):
        t1 = _task(db, project, "Dep")
        t2 = _task(db, project, "Active", status=Status.IN_PROGRESS)
        db.add_dependency(t2.id, t1.id)
        result = _invoke(runner, db, "dashboard", str(project.id))
        assert result.exit_code == 0
        # The dep indicator is only in the TODO column, not IN PROGRESS
        # t2 is in IN_PROGRESS so its card won't have deps: indicator
        # t1 is in TODO with no unmet deps, so also no indicator
        assert "deps:" not in result.output


# ── TestAIContextDeps ─────────────────────────────────────────────────────────


class TestAIContextDeps:
    def test_offline_agent_prompt_includes_deps_section(self):
        from nexus.ai import offline_agent_prompt
        _, user = offline_agent_prompt(
            project_name="Test",
            project_desc="",
            stats_line="1/2",
            tasks_ctx="tasks",
            stale_ctx="none",
            ready_ctx="none",
            valid_task_ids=[1, 2],
            deps_ctx="#2 'Deploy' needs: #1 (todo)",
        )
        assert "dependency" in user.lower()
        assert "#2" in user

    def test_offline_chat_prompt_includes_deps_section(self):
        from nexus.ai import offline_chat_system_prompt
        result = offline_chat_system_prompt(
            project_name="Test",
            project_desc="",
            stats_line="0/1",
            tasks_ctx="tasks",
            stale_ctx="none",
            ready_ctx="none",
            deps_ctx="#3 'Ship' needs: #2 (todo)",
        )
        assert "dependency" in result.lower()
        assert "#3" in result

    def test_deps_ctx_no_chains_default_message(self, db, project):
        from nexus.commands.agent import _build_offline_context
        _task(db, project, "Solo")  # no deps
        ctx = _build_offline_context(db, project.id)
        assert ctx["deps_ctx"] == "(no blocked dependency chains)"

    def test_deps_ctx_blocked_chain_listed(self, db, project):
        from nexus.commands.agent import _build_offline_context
        t1 = _task(db, project, "Prereq")
        t2 = _task(db, project, "Depends On Prereq")
        db.add_dependency(t2.id, t1.id)
        ctx = _build_offline_context(db, project.id)
        assert str(t2.id) in ctx["deps_ctx"]
        assert str(t1.id) in ctx["deps_ctx"]


# ── TestTaskDepGroupHelp ──────────────────────────────────────────────────────


class TestTaskDepGroupHelp:
    def test_dep_group_exists(self, db, runner):
        result = _invoke(runner, db, "task", "dep", "--help")
        assert result.exit_code == 0

    def test_dep_subcommands_listed_in_help(self, db, runner):
        result = _invoke(runner, db, "task", "dep", "--help")
        assert "add" in result.output
        assert "remove" in result.output
        assert "list" in result.output
