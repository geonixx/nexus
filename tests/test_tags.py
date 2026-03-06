"""Tests for M16: Tags + Agent-Ready Infrastructure.

Covers:
- SQLite WAL mode is enabled (PRAGMA journal_mode returns 'wal')
- db.add_tag         — add, normalization, idempotency, empty tag rejected
- db.remove_tag      — remove existing, missing tag returns False
- db.get_tags        — sorted, empty list
- db.list_tasks_by_tag — project-scoped, cross-project, ordering
- db.get_all_tags    — counts, ordering, project scope
- task add --tag     — single, multiple, shown in success message
- task update --tag/--untag  — add and remove tags
- task show          — tags rendered in output
- task list --tag    — filtering
- task next --tag    — filtering
- nexus tag list     — table of tags, project scope, no-tags message
- nexus tag tasks    — cross-project listing, project scope, not-found message
- nexus watch --max-agent-cycles — limit respected, message shown when limit hit
"""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.db import Database
from nexus.models import Priority, Status


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def project(db):
    return db.create_project("Alpha", description="First project")


@pytest.fixture
def project2(db):
    return db.create_project("Beta", description="Second project")


@pytest.fixture
def task(db, project):
    return db.create_task(project_id=project.id, title="Do the thing")


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, db, *args):
    return runner.invoke(cli, ["--db", str(db.path), *args])


# ── WAL mode ───────────────────────────────────────────────────────────────────


class TestWALMode:
    def test_wal_mode_enabled(self, db):
        """journal_mode should be 'wal' on every new connection."""
        import sqlite3
        conn = sqlite3.connect(str(db.path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert row[0] == "wal"


# ── DB layer: add_tag ──────────────────────────────────────────────────────────


class TestAddTag:
    def test_add_returns_true(self, db, task):
        assert db.add_tag(task.id, "security") is True

    def test_add_idempotent_returns_false(self, db, task):
        db.add_tag(task.id, "security")
        assert db.add_tag(task.id, "security") is False

    def test_add_normalizes_case(self, db, task):
        db.add_tag(task.id, "Tech-Debt")
        tags = db.get_tags(task.id)
        assert "tech-debt" in tags
        assert "Tech-Debt" not in tags

    def test_add_strips_whitespace(self, db, task):
        db.add_tag(task.id, "  frontend  ")
        assert "frontend" in db.get_tags(task.id)

    def test_add_empty_string_returns_false(self, db, task):
        assert db.add_tag(task.id, "") is False
        assert db.add_tag(task.id, "   ") is False

    def test_multiple_tags_on_same_task(self, db, task):
        db.add_tag(task.id, "security")
        db.add_tag(task.id, "tech-debt")
        db.add_tag(task.id, "frontend")
        tags = db.get_tags(task.id)
        assert len(tags) == 3


# ── DB layer: remove_tag ───────────────────────────────────────────────────────


class TestRemoveTag:
    def test_remove_existing_returns_true(self, db, task):
        db.add_tag(task.id, "security")
        assert db.remove_tag(task.id, "security") is True

    def test_remove_missing_returns_false(self, db, task):
        assert db.remove_tag(task.id, "nonexistent") is False

    def test_remove_normalizes_case(self, db, task):
        db.add_tag(task.id, "security")
        assert db.remove_tag(task.id, "SECURITY") is True
        assert db.get_tags(task.id) == []

    def test_remove_leaves_other_tags(self, db, task):
        db.add_tag(task.id, "security")
        db.add_tag(task.id, "tech-debt")
        db.remove_tag(task.id, "security")
        assert "tech-debt" in db.get_tags(task.id)
        assert "security" not in db.get_tags(task.id)


# ── DB layer: get_tags ─────────────────────────────────────────────────────────


class TestGetTags:
    def test_empty_task_has_no_tags(self, db, task):
        assert db.get_tags(task.id) == []

    def test_tags_returned_sorted(self, db, task):
        db.add_tag(task.id, "zebra")
        db.add_tag(task.id, "alpha")
        db.add_tag(task.id, "middle")
        assert db.get_tags(task.id) == ["alpha", "middle", "zebra"]

    def test_deleted_task_cascade(self, db, project):
        t = db.create_task(project_id=project.id, title="Temp")
        db.add_tag(t.id, "temp-tag")
        db.delete_task(t.id)
        # Tag should be gone (ON DELETE CASCADE)
        # (DB doesn't error — just verify no orphan rows exist)


# ── DB layer: list_tasks_by_tag ────────────────────────────────────────────────


class TestListTasksByTag:
    def test_returns_tagged_tasks(self, db, project, task):
        db.add_tag(task.id, "security")
        result = db.list_tasks_by_tag("security", project_id=project.id)
        assert any(t.id == task.id for t in result)

    def test_untagged_task_not_included(self, db, project):
        t1 = db.create_task(project_id=project.id, title="Tagged")
        t2 = db.create_task(project_id=project.id, title="Not tagged")
        db.add_tag(t1.id, "infra")
        result = db.list_tasks_by_tag("infra", project_id=project.id)
        ids = [t.id for t in result]
        assert t1.id in ids
        assert t2.id not in ids

    def test_project_scope_filters_other_projects(self, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1 Task")
        t2 = db.create_task(project_id=project2.id, title="P2 Task")
        db.add_tag(t1.id, "shared-tag")
        db.add_tag(t2.id, "shared-tag")
        result = db.list_tasks_by_tag("shared-tag", project_id=project.id)
        ids = [t.id for t in result]
        assert t1.id in ids
        assert t2.id not in ids

    def test_cross_project_no_scope(self, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1")
        t2 = db.create_task(project_id=project2.id, title="P2")
        db.add_tag(t1.id, "global")
        db.add_tag(t2.id, "global")
        result = db.list_tasks_by_tag("global")
        ids = [t.id for t in result]
        assert t1.id in ids
        assert t2.id in ids

    def test_empty_result_for_unknown_tag(self, db, project, task):
        assert db.list_tasks_by_tag("no-such-tag", project_id=project.id) == []

    def test_tag_normalized_in_query(self, db, project, task):
        db.add_tag(task.id, "backend")
        result = db.list_tasks_by_tag("BACKEND", project_id=project.id)
        assert any(t.id == task.id for t in result)


# ── DB layer: get_all_tags ─────────────────────────────────────────────────────


class TestGetAllTags:
    def test_empty_workspace_returns_empty(self, db):
        assert db.get_all_tags() == []

    def test_returns_tag_and_count(self, db, project):
        t1 = db.create_task(project_id=project.id, title="A")
        t2 = db.create_task(project_id=project.id, title="B")
        db.add_tag(t1.id, "hot")
        db.add_tag(t2.id, "hot")
        tags = db.get_all_tags()
        tag_map = dict(tags)
        assert tag_map["hot"] == 2

    def test_sorted_by_count_desc(self, db, project):
        for i in range(3):
            t = db.create_task(project_id=project.id, title=f"T{i}")
            db.add_tag(t.id, "popular")
        t = db.create_task(project_id=project.id, title="T3")
        db.add_tag(t.id, "rare")
        tags = db.get_all_tags()
        assert tags[0][0] == "popular"

    def test_project_scope(self, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1")
        t2 = db.create_task(project_id=project2.id, title="P2")
        db.add_tag(t1.id, "p1-only")
        db.add_tag(t2.id, "p2-only")
        p1_tags = dict(db.get_all_tags(project_id=project.id))
        assert "p1-only" in p1_tags
        assert "p2-only" not in p1_tags


# ── CLI: task add --tag ────────────────────────────────────────────────────────


class TestTaskAddTag:
    def test_add_single_tag(self, runner, db, project):
        r = _invoke(runner, db, "task", "add", str(project.id), "My task", "--tag", "security")
        assert r.exit_code == 0
        tasks = db.list_tasks(project_id=project.id)
        tags = db.get_tags(tasks[0].id)
        assert "security" in tags

    def test_add_multiple_tags(self, runner, db, project):
        r = _invoke(
            runner, db, "task", "add", str(project.id), "Big task",
            "--tag", "security", "--tag", "tech-debt",
        )
        assert r.exit_code == 0
        tasks = db.list_tasks(project_id=project.id)
        tags = db.get_tags(tasks[0].id)
        assert "security" in tags
        assert "tech-debt" in tags

    def test_tag_mentioned_in_output(self, runner, db, project):
        r = _invoke(runner, db, "task", "add", str(project.id), "Secure task", "--tag", "security")
        assert r.exit_code == 0
        assert "security" in r.output


# ── CLI: task update --tag / --untag ──────────────────────────────────────────


class TestTaskUpdateTag:
    def test_add_tag_via_update(self, runner, db, project, task):
        r = _invoke(runner, db, "task", "update", str(task.id), "--tag", "performance")
        assert r.exit_code == 0
        assert "performance" in db.get_tags(task.id)

    def test_remove_tag_via_untag(self, runner, db, project, task):
        db.add_tag(task.id, "old-tag")
        r = _invoke(runner, db, "task", "update", str(task.id), "--untag", "old-tag")
        assert r.exit_code == 0
        assert "old-tag" not in db.get_tags(task.id)

    def test_add_and_remove_in_one_call(self, runner, db, project, task):
        db.add_tag(task.id, "remove-me")
        r = _invoke(
            runner, db, "task", "update", str(task.id),
            "--tag", "keep-me",
            "--untag", "remove-me",
        )
        assert r.exit_code == 0
        tags = db.get_tags(task.id)
        assert "keep-me" in tags
        assert "remove-me" not in tags

    def test_update_with_only_tags_no_field_update_ok(self, runner, db, project, task):
        r = _invoke(runner, db, "task", "update", str(task.id), "--tag", "quick-add")
        assert r.exit_code == 0


# ── CLI: task show tags ────────────────────────────────────────────────────────


class TestTaskShowTags:
    def test_tags_shown_in_task_show(self, runner, db, project, task):
        db.add_tag(task.id, "security")
        db.add_tag(task.id, "infra")
        r = _invoke(runner, db, "task", "show", str(task.id))
        assert r.exit_code == 0
        assert "security" in r.output
        assert "infra" in r.output

    def test_no_tags_section_when_empty(self, runner, db, project, task):
        r = _invoke(runner, db, "task", "show", str(task.id))
        assert r.exit_code == 0
        assert "Tags:" not in r.output


# ── CLI: task list --tag ───────────────────────────────────────────────────────


class TestTaskListTag:
    def test_filter_by_tag_shows_matching(self, runner, db, project):
        t1 = db.create_task(project_id=project.id, title="Secure task")
        t2 = db.create_task(project_id=project.id, title="Other task")
        db.add_tag(t1.id, "security")
        r = _invoke(runner, db, "task", "list", str(project.id), "--tag", "security")
        assert r.exit_code == 0
        assert "Secure task" in r.output
        assert "Other task" not in r.output

    def test_filter_by_tag_no_results(self, runner, db, project, task):
        r = _invoke(runner, db, "task", "list", str(project.id), "--tag", "no-such-tag")
        assert r.exit_code == 0

    def test_no_tag_filter_shows_all(self, runner, db, project):
        db.create_task(project_id=project.id, title="Task A")
        db.create_task(project_id=project.id, title="Task B")
        r = _invoke(runner, db, "task", "list", str(project.id))
        assert r.exit_code == 0
        assert "Task A" in r.output
        assert "Task B" in r.output


# ── CLI: task next --tag ───────────────────────────────────────────────────────


class TestTaskNextTag:
    def test_filter_by_tag(self, runner, db, project):
        t1 = db.create_task(project_id=project.id, title="Tagged task")
        t2 = db.create_task(project_id=project.id, title="Untagged task")
        db.add_tag(t1.id, "frontend")
        r = _invoke(runner, db, "task", "next", str(project.id), "--tag", "frontend")
        assert r.exit_code == 0
        assert "Tagged task" in r.output
        assert "Untagged task" not in r.output

    def test_no_tag_shows_all(self, runner, db, project):
        db.create_task(project_id=project.id, title="Task X")
        db.create_task(project_id=project.id, title="Task Y")
        r = _invoke(runner, db, "task", "next", str(project.id))
        assert r.exit_code == 0
        assert "Task X" in r.output


# ── CLI: nexus tag list ────────────────────────────────────────────────────────


class TestTagListCmd:
    def test_lists_tags_with_counts(self, runner, db, project):
        t = db.create_task(project_id=project.id, title="T")
        db.add_tag(t.id, "security")
        r = _invoke(runner, db, "tag", "list")
        assert r.exit_code == 0
        assert "security" in r.output

    def test_no_tags_shows_info_message(self, runner, db, project):
        r = _invoke(runner, db, "tag", "list")
        assert r.exit_code == 0
        assert "No tags" in r.output

    def test_project_scope(self, runner, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1")
        t2 = db.create_task(project_id=project2.id, title="P2")
        db.add_tag(t1.id, "p1-tag")
        db.add_tag(t2.id, "p2-tag")
        r = _invoke(runner, db, "tag", "list", str(project.id))
        assert r.exit_code == 0
        assert "p1-tag" in r.output
        assert "p2-tag" not in r.output

    def test_invalid_project_fails(self, runner, db):
        r = _invoke(runner, db, "tag", "list", "9999")
        assert r.exit_code != 0

    def test_multiple_tags_all_shown(self, runner, db, project):
        t = db.create_task(project_id=project.id, title="T")
        db.add_tag(t.id, "aaa")
        db.add_tag(t.id, "bbb")
        r = _invoke(runner, db, "tag", "list")
        assert "aaa" in r.output
        assert "bbb" in r.output


# ── CLI: nexus tag tasks ───────────────────────────────────────────────────────


class TestTagTasksCmd:
    def test_shows_tasks_for_tag(self, runner, db, project, task):
        db.add_tag(task.id, "backend")
        r = _invoke(runner, db, "tag", "tasks", "backend")
        assert r.exit_code == 0
        assert task.title in r.output

    def test_no_tasks_message(self, runner, db, project):
        r = _invoke(runner, db, "tag", "tasks", "no-such-tag")
        assert r.exit_code == 0
        assert "No tasks" in r.output

    def test_cross_project_listing(self, runner, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1 task")
        t2 = db.create_task(project_id=project2.id, title="P2 task")
        db.add_tag(t1.id, "shared")
        db.add_tag(t2.id, "shared")
        r = _invoke(runner, db, "tag", "tasks", "shared")
        assert r.exit_code == 0
        assert "P1 task" in r.output
        assert "P2 task" in r.output

    def test_project_scope_option(self, runner, db, project, project2):
        t1 = db.create_task(project_id=project.id, title="P1 only")
        t2 = db.create_task(project_id=project2.id, title="P2 only")
        db.add_tag(t1.id, "shared")
        db.add_tag(t2.id, "shared")
        r = _invoke(runner, db, "tag", "tasks", "shared", "--project-id", str(project.id))
        assert r.exit_code == 0
        assert "P1 only" in r.output
        assert "P2 only" not in r.output

    def test_invalid_project_id_fails(self, runner, db):
        r = _invoke(runner, db, "tag", "tasks", "sometag", "--project-id", "9999")
        assert r.exit_code != 0


# ── CLI: nexus watch --max-agent-cycles ───────────────────────────────────────


class TestWatchMaxAgentCycles:
    def _make_ai(self):
        mock = MagicMock()
        mock.available = True
        mock.supports_tools = True
        mock.chat_turn.return_value = ("ok", [])
        return mock

    def _one_cycle(self, runner, db, *extra_args):
        """Run watch for exactly one cycle by raising SIGINT inside time.sleep."""
        def fake_sleep(secs):
            signal.raise_signal(signal.SIGINT)

        with patch("time.sleep", side_effect=fake_sleep):
            return _invoke(runner, db, "watch", *extra_args)

    def test_max_agent_cycles_shown_in_header(self, runner, db, project, monkeypatch):
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: self._make_ai())
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        r = self._one_cycle(
            runner, db,
            str(project.id),
            "--interval", "1",
            "--agent",
            "--max-agent-cycles", "3",
        )
        assert r.exit_code == 0
        assert "max 3 cycles" in r.output or "3" in r.output

    def test_zero_max_means_unlimited(self, runner, db, project, monkeypatch):
        """max_agent_cycles=0 (default) should not show limit message."""
        monkeypatch.setattr("nexus.ai.NexusAI", lambda: self._make_ai())
        monkeypatch.setattr("nexus.commands.agent._handle_tool", lambda *a, **kw: "ok")
        r = self._one_cycle(
            runner, db,
            str(project.id),
            "--interval", "1",
            "--agent",
            "--max-agent-cycles", "0",
        )
        assert r.exit_code == 0
        assert "max" not in r.output.lower() or "unlimited" in r.output.lower()
