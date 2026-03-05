"""Tests for the Database layer."""

import tempfile
from pathlib import Path

import pytest

from nexus.db import Database
from nexus.models import Priority, Status


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Database(path=Path(tmpdir) / "test.db")


# ── Projects ──────────────────────────────────────────────────────────────────

def test_create_project(db):
    p = db.create_project("Alpha", "First project")
    assert p.id > 0
    assert p.name == "Alpha"
    assert p.description == "First project"
    assert p.status == Status.TODO


def test_get_project(db):
    p = db.create_project("Beta")
    fetched = db.get_project(p.id)
    assert fetched is not None
    assert fetched.name == "Beta"


def test_get_project_missing(db):
    assert db.get_project(9999) is None


def test_get_project_by_name(db):
    db.create_project("Gamma")
    p = db.get_project_by_name("Gamma")
    assert p is not None
    assert p.name == "Gamma"


def test_list_projects(db):
    db.create_project("A")
    db.create_project("B")
    db.create_project("C")
    projects = db.list_projects()
    assert len(projects) == 3


def test_list_projects_filter_status(db):
    p1 = db.create_project("Active")
    db.create_project("Inactive")
    db.update_project(p1.id, status=Status.IN_PROGRESS)
    active = db.list_projects(status=Status.IN_PROGRESS)
    assert len(active) == 1
    assert active[0].name == "Active"


def test_update_project(db):
    p = db.create_project("Before")
    updated = db.update_project(p.id, name="After", status=Status.IN_PROGRESS)
    assert updated.name == "After"
    assert updated.status == Status.IN_PROGRESS


def test_delete_project(db):
    p = db.create_project("Temp")
    assert db.delete_project(p.id) is True
    assert db.get_project(p.id) is None


# ── Sprints ───────────────────────────────────────────────────────────────────

def test_create_sprint(db):
    p = db.create_project("Proj")
    s = db.create_sprint(p.id, "Sprint 1", goal="Ship MVP")
    assert s.id > 0
    assert s.name == "Sprint 1"
    assert s.goal == "Ship MVP"
    assert s.project_id == p.id


def test_list_sprints(db):
    p = db.create_project("Proj")
    db.create_sprint(p.id, "S1")
    db.create_sprint(p.id, "S2")
    assert len(db.list_sprints(p.id)) == 2


def test_update_sprint_status(db):
    p = db.create_project("Proj")
    s = db.create_sprint(p.id, "S1")
    db.update_sprint(s.id, status=Status.IN_PROGRESS)
    updated = db.get_sprint(s.id)
    assert updated.status == Status.IN_PROGRESS


# ── Tasks ─────────────────────────────────────────────────────────────────────

def test_create_task(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Write tests", priority=Priority.HIGH, estimate_hours=3.0)
    assert t.id > 0
    assert t.title == "Write tests"
    assert t.priority == Priority.HIGH
    assert t.estimate_hours == 3.0


def test_list_tasks(db):
    p = db.create_project("Proj")
    db.create_task(p.id, "T1")
    db.create_task(p.id, "T2")
    db.create_task(p.id, "T3")
    tasks = db.list_tasks(project_id=p.id)
    assert len(tasks) == 3


def test_list_tasks_filter_status(db):
    p = db.create_project("Proj")
    t1 = db.create_task(p.id, "Done task")
    db.create_task(p.id, "Todo task")
    db.update_task(t1.id, status=Status.DONE)
    done = db.list_tasks(project_id=p.id, status=Status.DONE)
    assert len(done) == 1
    assert done[0].title == "Done task"


def test_update_task(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Original")
    updated = db.update_task(t.id, title="Renamed", status=Status.IN_PROGRESS)
    assert updated.title == "Renamed"
    assert updated.status == Status.IN_PROGRESS


def test_delete_task(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Ephemeral")
    assert db.delete_task(t.id) is True
    assert db.get_task(t.id) is None


def test_task_assigned_to_sprint(db):
    p = db.create_project("Proj")
    s = db.create_sprint(p.id, "S1")
    t = db.create_task(p.id, "Sprint task", sprint_id=s.id)
    sprint_tasks = db.list_tasks(sprint_id=s.id)
    assert len(sprint_tasks) == 1
    assert sprint_tasks[0].id == t.id


# ── Time Entries ──────────────────────────────────────────────────────────────

def test_log_time(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Implement feature")
    entry = db.log_time(t.id, 2.5, "First session")
    assert entry.hours == 2.5
    task_after = db.get_task(t.id)
    assert task_after.actual_hours == 2.5


def test_log_time_accumulates(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Big feature")
    db.log_time(t.id, 1.0)
    db.log_time(t.id, 2.0)
    db.log_time(t.id, 0.5)
    task = db.get_task(t.id)
    assert task.actual_hours == pytest.approx(3.5)


def test_list_time_entries(db):
    p = db.create_project("Proj")
    t = db.create_task(p.id, "Work")
    db.log_time(t.id, 1.0, "morning")
    db.log_time(t.id, 1.5, "afternoon")
    entries = db.list_time_entries(t.id)
    assert len(entries) == 2


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_project_stats_empty(db):
    p = db.create_project("Empty")
    stats = db.project_stats(p.id)
    assert stats.total_tasks == 0
    assert stats.completion_pct == 0.0
    assert stats.total_hours_logged == 0.0


def test_project_stats_with_tasks(db):
    p = db.create_project("Active")
    t1 = db.create_task(p.id, "T1")
    t2 = db.create_task(p.id, "T2")
    t3 = db.create_task(p.id, "T3")
    db.update_task(t1.id, status=Status.DONE)
    db.update_task(t2.id, status=Status.IN_PROGRESS)
    db.log_time(t1.id, 3.0)
    db.log_time(t2.id, 1.0)
    stats = db.project_stats(p.id)
    assert stats.total_tasks == 3
    assert stats.done_tasks == 1
    assert stats.in_progress_tasks == 1
    assert stats.completion_pct == pytest.approx(100 / 3)
    assert stats.total_hours_logged == pytest.approx(4.0)


def test_project_stats_missing(db):
    assert db.project_stats(9999) is None


# ── Search ────────────────────────────────────────────────────────────────────

def test_search_finds_project_by_name(db):
    db.create_project("Unicorn App", "magical")
    db.create_project("Boring Corp")
    results = db.search("unicorn")
    assert len(results["projects"]) == 1
    assert results["projects"][0].name == "Unicorn App"


def test_search_finds_project_by_description(db):
    db.create_project("Alpha", "a really cool microservice")
    db.create_project("Beta", "nothing interesting")
    results = db.search("microservice")
    assert len(results["projects"]) == 1
    assert results["projects"][0].name == "Alpha"


def test_search_finds_task_by_title(db):
    p = db.create_project("Proj")
    db.create_task(p.id, "Implement OAuth login")
    db.create_task(p.id, "Write unit tests")
    results = db.search("oauth")
    assert len(results["tasks"]) == 1
    assert results["tasks"][0].title == "Implement OAuth login"


def test_search_case_insensitive(db):
    db.create_project("MyProject")
    results = db.search("MYPROJECT")
    assert len(results["projects"]) == 1


def test_search_no_results(db):
    db.create_project("Something")
    results = db.search("zzznomatch")
    assert results["projects"] == []
    assert results["tasks"] == []


def test_search_returns_both_projects_and_tasks(db):
    p = db.create_project("keyword project")
    db.create_task(p.id, "a task with keyword inside")
    results = db.search("keyword")
    assert len(results["projects"]) == 1
    assert len(results["tasks"]) == 1
