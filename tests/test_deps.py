"""Tests for M11: Task Dependency Graph.

Covers:
- Database layer: add/remove/get dependencies, cycle detection, ready tasks,
  has_unmet_dependencies
- CLI: nexus task depend, nexus task undepend, nexus task graph
- nexus task show dependency section
- nexus workspace next dependency filtering
"""

from __future__ import annotations

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
    return db.create_project("DepTest")


@pytest.fixture
def runner():
    return CliRunner()


def _task(db, project, title="Task", *, priority=Priority.MEDIUM, status=None):
    t = db.create_task(project_id=project.id, title=title, priority=priority)
    if status:
        db.update_task(t.id, status=status)
        t = db.get_task(t.id)
    return t


# ── DB: add_dependency ─────────────────────────────────────────────────────────

class TestAddDependency:
    def test_basic_add(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        result = db.add_dependency(a.id, b.id)
        assert result is True

    def test_idempotent_add(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        # Second call — INSERT OR IGNORE makes this a no-op, returns True
        # (no cycle, no missing tasks — just a duplicate that is silently ignored)
        result = db.add_dependency(a.id, b.id)
        assert result is True  # no error, just idempotent

    def test_self_dependency_blocked(self, db, project):
        a = _task(db, project, "A")
        assert db.add_dependency(a.id, a.id) is False

    def test_missing_task_blocked(self, db, project):
        a = _task(db, project, "A")
        assert db.add_dependency(a.id, 9999) is False
        assert db.add_dependency(9999, a.id) is False

    def test_direct_cycle_blocked(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)   # a depends on b
        # Adding b depends on a would create a cycle
        assert db.add_dependency(b.id, a.id) is False

    def test_indirect_cycle_blocked(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        db.add_dependency(a.id, b.id)   # a → b
        db.add_dependency(b.id, c.id)   # b → c
        # Adding c → a would close the cycle
        assert db.add_dependency(c.id, a.id) is False

    def test_deep_chain_no_cycle(self, db, project):
        tasks = [_task(db, project, f"T{i}") for i in range(5)]
        # 0 → 1 → 2 → 3 → 4 (chain)
        for i in range(4):
            assert db.add_dependency(tasks[i].id, tasks[i + 1].id) is True
        # Adding 4 → 0 would cycle
        assert db.add_dependency(tasks[4].id, tasks[0].id) is False
        # Adding 3 → 0 would also cycle (0 is reachable from 3 via nothing in reverse... wait)
        # Actually 3 depends on 4, so adding 3 → 0 means 0 can reach 3 via 0→1→2→3
        assert db.add_dependency(tasks[3].id, tasks[0].id) is False

    def test_diamond_dep_ok(self, db, project):
        """A→B, A→C, B→D, C→D — diamond shape is valid (no cycle)."""
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        d = _task(db, project, "D")
        assert db.add_dependency(a.id, b.id) is True
        assert db.add_dependency(a.id, c.id) is True
        assert db.add_dependency(b.id, d.id) is True
        assert db.add_dependency(c.id, d.id) is True


# ── DB: remove_dependency ──────────────────────────────────────────────────────

class TestRemoveDependency:
    def test_remove_existing(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        assert db.remove_dependency(a.id, b.id) is True
        assert db.get_dependencies(a.id) == []

    def test_remove_nonexistent(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        assert db.remove_dependency(a.id, b.id) is False

    def test_remove_correct_direction(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)  # a depends on b
        # Removing in wrong direction should fail
        assert db.remove_dependency(b.id, a.id) is False
        # Original dep still intact
        deps = db.get_dependencies(a.id)
        assert any(d.id == b.id for d in deps)


# ── DB: get_dependencies / get_dependents ─────────────────────────────────────

class TestGetDependencies:
    def test_empty(self, db, project):
        a = _task(db, project, "A")
        assert db.get_dependencies(a.id) == []
        assert db.get_dependents(a.id) == []

    def test_single_dep(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)  # a depends on b
        deps = db.get_dependencies(a.id)
        assert len(deps) == 1
        assert deps[0].id == b.id

        dependents = db.get_dependents(b.id)
        assert len(dependents) == 1
        assert dependents[0].id == a.id

    def test_multiple_deps(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        db.add_dependency(a.id, b.id)
        db.add_dependency(a.id, c.id)
        deps = db.get_dependencies(a.id)
        dep_ids = {d.id for d in deps}
        assert dep_ids == {b.id, c.id}

    def test_cascade_on_delete(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        db.delete_task(b.id)
        # Dependency should be gone via ON DELETE CASCADE
        deps = db.get_dependencies(a.id)
        assert deps == []


# ── DB: get_ready_tasks ────────────────────────────────────────────────────────

class TestGetReadyTasks:
    def test_no_deps_all_ready(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        ready = db.get_ready_tasks(project.id)
        ready_ids = {t.id for t in ready}
        assert a.id in ready_ids
        assert b.id in ready_ids

    def test_unfinished_dep_blocks(self, db, project):
        a = _task(db, project, "A")  # depends on b
        b = _task(db, project, "B")  # not done yet
        db.add_dependency(a.id, b.id)
        ready = db.get_ready_tasks(project.id)
        ready_ids = {t.id for t in ready}
        assert b.id in ready_ids    # b has no deps, is ready
        assert a.id not in ready_ids  # a is blocked by b

    def test_done_dep_unblocks(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        db.update_task(b.id, status=Status.DONE)
        ready = db.get_ready_tasks(project.id)
        ready_ids = {t.id for t in ready}
        assert a.id in ready_ids

    def test_cancelled_dep_unblocks(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        db.update_task(b.id, status=Status.CANCELLED)
        ready = db.get_ready_tasks(project.id)
        ready_ids = {t.id for t in ready}
        assert a.id in ready_ids

    def test_done_tasks_not_in_ready(self, db, project):
        a = _task(db, project, "A", status=Status.DONE)
        ready = db.get_ready_tasks(project.id)
        assert not any(t.id == a.id for t in ready)

    def test_chained_blocked(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        db.add_dependency(a.id, b.id)  # a needs b
        db.add_dependency(b.id, c.id)  # b needs c
        # Only c is ready; b is blocked by c; a is blocked by b
        ready = db.get_ready_tasks(project.id)
        ready_ids = {t.id for t in ready}
        assert c.id in ready_ids
        assert b.id not in ready_ids
        assert a.id not in ready_ids


# ── DB: has_unmet_dependencies ─────────────────────────────────────────────────

class TestHasUnmetDeps:
    def test_no_deps(self, db, project):
        a = _task(db, project, "A")
        assert db.has_unmet_dependencies(a.id) is False

    def test_unfinished_dep(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        assert db.has_unmet_dependencies(a.id) is True

    def test_finished_dep(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B", status=Status.DONE)
        db.add_dependency(a.id, b.id)
        assert db.has_unmet_dependencies(a.id) is False

    def test_partial_done(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B", status=Status.DONE)
        c = _task(db, project, "C")
        db.add_dependency(a.id, b.id)
        db.add_dependency(a.id, c.id)
        # c is still todo, so a has unmet deps
        assert db.has_unmet_dependencies(a.id) is True


# ── CLI: nexus task depend (display mode) ─────────────────────────────────────

class TestTaskDependDisplay:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_no_deps_message(self, runner, db, project):
        a = _task(db, project, "A")
        r = self._invoke(runner, db, "task", "depend", str(a.id))
        assert r.exit_code == 0
        assert "No dependencies" in r.output or "no dependencies" in r.output.lower()

    def test_shows_dependency(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        r = self._invoke(runner, db, "task", "depend", str(a.id))
        assert r.exit_code == 0
        assert f"#{b.id}" in r.output

    def test_shows_dependents(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(b.id, a.id)  # b depends on a
        r = self._invoke(runner, db, "task", "depend", str(a.id))
        assert r.exit_code == 0
        assert f"#{b.id}" in r.output

    def test_missing_task(self, runner, db, project):
        r = self._invoke(runner, db, "task", "depend", "9999")
        assert r.exit_code != 0


# ── CLI: nexus task depend --on (add mode) ────────────────────────────────────

class TestTaskDependAdd:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_add_dep(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        r = self._invoke(runner, db, "task", "depend", str(a.id), "--on", str(b.id))
        assert r.exit_code == 0
        deps = db.get_dependencies(a.id)
        assert any(d.id == b.id for d in deps)

    def test_add_multiple_deps(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        r = self._invoke(
            runner, db,
            "task", "depend", str(a.id),
            "--on", str(b.id), "--on", str(c.id),
        )
        assert r.exit_code == 0
        dep_ids = {d.id for d in db.get_dependencies(a.id)}
        assert b.id in dep_ids
        assert c.id in dep_ids

    def test_already_dep_skipped(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        r = self._invoke(runner, db, "task", "depend", str(a.id), "--on", str(b.id))
        assert r.exit_code == 0
        assert "already" in r.output

    def test_cycle_rejected(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)  # a depends on b
        r = self._invoke(runner, db, "task", "depend", str(b.id), "--on", str(a.id))
        assert r.exit_code == 0
        assert "cycle" in r.output.lower() or "circular" in r.output.lower()

    def test_missing_dep_task(self, runner, db, project):
        a = _task(db, project, "A")
        r = self._invoke(runner, db, "task", "depend", str(a.id), "--on", "9999")
        assert r.exit_code == 0
        assert "not found" in r.output

    def test_missing_task_errors(self, runner, db, project):
        r = self._invoke(runner, db, "task", "depend", "9999", "--on", "1")
        assert r.exit_code != 0


# ── CLI: nexus task undepend ──────────────────────────────────────────────────

class TestTaskUndepend:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_remove_dep(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        r = self._invoke(runner, db, "task", "undepend", str(a.id), "--from", str(b.id))
        assert r.exit_code == 0
        assert db.get_dependencies(a.id) == []

    def test_nonexistent_dep_fails(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        r = self._invoke(runner, db, "task", "undepend", str(a.id), "--from", str(b.id))
        assert r.exit_code != 0

    def test_missing_task_fails(self, runner, db, project):
        r = self._invoke(runner, db, "task", "undepend", "9999", "--from", "1")
        assert r.exit_code != 0

    def test_missing_dep_task_fails(self, runner, db, project):
        a = _task(db, project, "A")
        r = self._invoke(runner, db, "task", "undepend", str(a.id), "--from", "9999")
        assert r.exit_code != 0


# ── CLI: nexus task graph ─────────────────────────────────────────────────────

class TestTaskGraph:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_no_tasks(self, runner, db, project):
        r = self._invoke(runner, db, "task", "graph", str(project.id))
        assert r.exit_code == 0
        assert "No tasks" in r.output

    def test_no_deps_message(self, runner, db, project):
        _task(db, project, "A")
        _task(db, project, "B")
        r = self._invoke(runner, db, "task", "graph", str(project.id))
        assert r.exit_code == 0
        assert "No dependencies" in r.output

    def test_shows_tasks_in_tree(self, runner, db, project):
        a = _task(db, project, "Alpha")
        b = _task(db, project, "Beta")
        db.add_dependency(b.id, a.id)  # b depends on a → a is root, b is child
        r = self._invoke(runner, db, "task", "graph", str(project.id))
        assert r.exit_code == 0
        assert "Alpha" in r.output
        assert "Beta" in r.output

    def test_missing_project(self, runner, db, project):
        r = self._invoke(runner, db, "task", "graph", "9999")
        assert r.exit_code != 0

    def test_summary_line(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(b.id, a.id)
        r = self._invoke(runner, db, "task", "graph", str(project.id))
        assert r.exit_code == 0
        # Footer shows dep count and ready count
        assert "edge" in r.output
        assert "ready" in r.output

    def test_diamond_renders(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        d = _task(db, project, "D")
        db.add_dependency(b.id, a.id)  # b needs a
        db.add_dependency(c.id, a.id)  # c needs a
        db.add_dependency(d.id, b.id)  # d needs b
        db.add_dependency(d.id, c.id)  # d needs c
        r = self._invoke(runner, db, "task", "graph", str(project.id))
        assert r.exit_code == 0
        assert "A" in r.output
        assert "D" in r.output


# ── CLI: nexus task show — dependency section ─────────────────────────────────

class TestTaskShowDeps:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_show_no_deps(self, runner, db, project):
        a = _task(db, project, "A")
        r = self._invoke(runner, db, "task", "show", str(a.id))
        assert r.exit_code == 0
        # No dep section shown when there are none
        assert "Depends on:" not in r.output

    def test_show_depends_on(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)
        r = self._invoke(runner, db, "task", "show", str(a.id))
        assert r.exit_code == 0
        assert "Depends on:" in r.output
        assert f"#{b.id}" in r.output

    def test_show_needed_by(self, runner, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(b.id, a.id)  # b depends on a
        r = self._invoke(runner, db, "task", "show", str(a.id))
        assert r.exit_code == 0
        assert "Needed by:" in r.output
        assert f"#{b.id}" in r.output


# ── CLI: nexus workspace next — dep filtering ─────────────────────────────────

class TestWorkspaceNextDepFilter:
    def _invoke(self, runner, db, *args):
        return runner.invoke(cli, ["--db", str(db.path), *args])

    def test_unmet_dep_hidden(self, runner, db):
        p = db.create_project("Proj")
        a = _task(db, p, "Prereq")
        b = _task(db, p, "Blocked")
        db.add_dependency(b.id, a.id)  # b depends on a (not done)
        r = self._invoke(runner, db, "workspace", "next")
        assert r.exit_code == 0
        # a should appear, b should NOT (it has unmet dep)
        assert "Prereq" in r.output
        assert "Blocked" not in r.output

    def test_done_dep_shows_task(self, runner, db):
        p = db.create_project("Proj")
        a = _task(db, p, "Prereq", status=Status.DONE)
        b = _task(db, p, "Unlocked")
        db.add_dependency(b.id, a.id)
        r = self._invoke(runner, db, "workspace", "next")
        assert r.exit_code == 0
        # b's dep is done, so b should appear
        assert "Unlocked" in r.output

    def test_dep_count_in_footer(self, runner, db):
        p = db.create_project("Proj")
        a = _task(db, p, "Prereq")
        b = _task(db, p, "Blocked A")
        c = _task(db, p, "Blocked B")
        db.add_dependency(b.id, a.id)
        db.add_dependency(c.id, a.id)
        r = self._invoke(runner, db, "workspace", "next")
        assert r.exit_code == 0
        # Footer should mention 2 hidden tasks
        assert "2" in r.output
        assert "waiting" in r.output or "hidden" in r.output

    def test_no_tasks_with_deps_all_blocked(self, runner, db):
        p = db.create_project("Proj")
        a = _task(db, p, "Prereq")
        b = _task(db, p, "Blocked")
        db.add_dependency(b.id, a.id)
        # Mark a as done so only b with unmet deps... but a is todo so b is blocked
        # b won't show; a will show
        r = self._invoke(runner, db, "workspace", "next")
        assert r.exit_code == 0
        assert "Prereq" in r.output


# ── DB: _would_create_cycle (unit) ────────────────────────────────────────────

class TestWouldCreateCycle:
    def test_self(self, db, project):
        a = _task(db, project, "A")
        assert db._would_create_cycle(a.id, a.id) is True

    def test_no_cycle(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        assert db._would_create_cycle(a.id, b.id) is False

    def test_existing_dep_creates_cycle(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        db.add_dependency(a.id, b.id)  # a depends on b
        # Would adding b → a create cycle?
        assert db._would_create_cycle(b.id, a.id) is True

    def test_transitive_cycle(self, db, project):
        a = _task(db, project, "A")
        b = _task(db, project, "B")
        c = _task(db, project, "C")
        db.add_dependency(a.id, b.id)
        db.add_dependency(b.id, c.id)
        # c → a would close the loop
        assert db._would_create_cycle(c.id, a.id) is True
        # a → c would also close it (a→b→c, then c→a)
        # Actually: would_create_cycle(a.id, c.id) asks if depends_on_id=c can reach a.id=a
        # c has no outgoing deps, so no cycle
        assert db._would_create_cycle(a.id, c.id) is False
