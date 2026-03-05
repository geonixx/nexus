"""Pydantic data models for Nexus."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Project(BaseModel):
    id: int = 0
    name: str
    description: str = ""
    status: Status = Status.TODO
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")


class Sprint(BaseModel):
    id: int = 0
    project_id: int
    name: str
    goal: str = ""
    status: Status = Status.TODO
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(BaseModel):
    id: int = 0
    project_id: int
    sprint_id: Optional[int] = None
    title: str
    description: str = ""
    status: Status = Status.TODO
    priority: Priority = Priority.MEDIUM
    estimate_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    # External provenance — e.g. GitHub issue sync
    source: str = ""       # "github" | "" for local tasks
    external_id: str = ""  # e.g. "42" for GitHub issue #42


class TimeEntry(BaseModel):
    id: int = 0
    task_id: int
    hours: float
    note: str = ""
    logged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskNote(BaseModel):
    id: int = 0
    task_id: int
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectStats(BaseModel):
    project: Project
    total_tasks: int
    done_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    total_hours_logged: float
    completion_pct: float
