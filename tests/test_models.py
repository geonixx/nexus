"""Tests for Pydantic models."""

import pytest
from nexus.models import Priority, Project, Sprint, Status, Task, TimeEntry


def test_project_defaults():
    p = Project(name="Alpha")
    assert p.status == Status.TODO
    assert p.description == ""
    assert p.id == 0


def test_project_slug():
    p = Project(name="My Cool Project")
    assert p.slug == "my-cool-project"


def test_task_defaults():
    t = Task(project_id=1, title="Write docs")
    assert t.status == Status.TODO
    assert t.priority == Priority.MEDIUM
    assert t.estimate_hours is None
    assert t.sprint_id is None


def test_sprint_defaults():
    s = Sprint(project_id=1, name="Sprint 1")
    assert s.status == Status.TODO
    assert s.starts_at is None
    assert s.ends_at is None


def test_status_enum_values():
    assert Status.TODO.value == "todo"
    assert Status.IN_PROGRESS.value == "in_progress"
    assert Status.DONE.value == "done"
    assert Status.BLOCKED.value == "blocked"
    assert Status.CANCELLED.value == "cancelled"


def test_priority_enum_values():
    assert Priority.LOW.value == "low"
    assert Priority.MEDIUM.value == "medium"
    assert Priority.HIGH.value == "high"
    assert Priority.CRITICAL.value == "critical"


def test_time_entry():
    e = TimeEntry(task_id=5, hours=2.5, note="deep work")
    assert e.hours == 2.5
    assert e.note == "deep work"
