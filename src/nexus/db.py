"""SQLite database layer for Nexus."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional

from .models import Priority, Project, ProjectStats, Sprint, Status, Task, TaskNote, TimeEntry

DEFAULT_DB_PATH = Path.home() / ".nexus" / "nexus.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sprints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    name        TEXT NOT NULL,
    goal        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    starts_at   TEXT,
    ends_at     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(id),
    sprint_id      INTEGER REFERENCES sprints(id),
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'todo',
    priority       TEXT NOT NULL DEFAULT 'medium',
    estimate_hours REAL,
    actual_hours   REAL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    completed_at   TEXT,
    source         TEXT NOT NULL DEFAULT '',
    external_id    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS time_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id),
    hours      REAL NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    logged_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    UNIQUE(task_id, depends_on_id)
);
"""


def _dt(val: Optional[str]) -> Optional[datetime]:
    if val is None:
        return None
    return datetime.fromisoformat(val)


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=Status(row["status"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _row_to_sprint(row: sqlite3.Row) -> Sprint:
    return Sprint(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        goal=row["goal"],
        status=Status(row["status"]),
        starts_at=_dt(row["starts_at"]),
        ends_at=_dt(row["ends_at"]),
        created_at=_dt(row["created_at"]),
    )


def _row_to_task(row: sqlite3.Row) -> Task:
    cols = row.keys()
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        sprint_id=row["sprint_id"],
        title=row["title"],
        description=row["description"],
        status=Status(row["status"]),
        priority=Priority(row["priority"]),
        estimate_hours=row["estimate_hours"],
        actual_hours=row["actual_hours"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        completed_at=_dt(row["completed_at"]),
        source=row["source"] if "source" in cols else "",
        external_id=row["external_id"] if "external_id" in cols else "",
    )


def _row_to_time_entry(row: sqlite3.Row) -> TimeEntry:
    return TimeEntry(
        id=row["id"],
        task_id=row["task_id"],
        hours=row["hours"],
        note=row["note"],
        logged_at=_dt(row["logged_at"]),
    )


def _row_to_task_note(row: sqlite3.Row) -> TaskNote:
    return TaskNote(
        id=row["id"],
        task_id=row["task_id"],
        text=row["text"],
        created_at=_dt(row["created_at"]),
    )


class Database:
    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # M10: tighten directory permissions so only the owning user can browse it
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass  # no-op on Windows or Docker setups where chmod is restricted
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # M9 migration: add external-provenance columns to existing DBs.
            # CREATE TABLE IF NOT EXISTS won't add new columns to existing tables,
            # so we ALTER TABLE with try/except for idempotency.
            for col, coldef in [
                ("source", "TEXT NOT NULL DEFAULT ''"),
                ("external_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {coldef}")
                except sqlite3.OperationalError:
                    pass  # column already exists
            # M11 migration: task_dependencies table for existing DBs.
            # The CREATE TABLE IF NOT EXISTS in SCHEMA handles new databases;
            # this covers databases created before M11.
            conn.execute(
                """CREATE TABLE IF NOT EXISTS task_dependencies (
                       id            INTEGER PRIMARY KEY AUTOINCREMENT,
                       task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                       depends_on_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                       created_at    TEXT NOT NULL,
                       UNIQUE(task_id, depends_on_id)
                   )"""
            )
        # M10: tighten DB file permissions so only the owning user can read it
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ── Projects ──────────────────────────────────────────────────────────

    def create_project(self, name: str, description: str = "") -> Project:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                (name, description, Status.TODO.value, now, now),
            )
            return Project(
                id=cur.lastrowid,
                name=name,
                description=description,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )

    def get_project(self, project_id: int) -> Optional[Project]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return _row_to_project(row) if row else None

    def get_project_by_name(self, name: str) -> Optional[Project]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
        return _row_to_project(row) if row else None

    def list_projects(self, status: Optional[Status] = None) -> List[Project]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM projects WHERE status=? ORDER BY updated_at DESC", (status.value,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [_row_to_project(r) for r in rows]

    def update_project(self, project_id: int, **kwargs) -> Optional[Project]:
        allowed = {"name", "description", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_project(project_id)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "status" in updates and isinstance(updates["status"], Status):
            updates["status"] = updates["status"].value
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [project_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE projects SET {set_clause} WHERE id=?", values)
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return cur.rowcount > 0

    # ── Sprints ───────────────────────────────────────────────────────────

    def create_sprint(
        self,
        project_id: int,
        name: str,
        goal: str = "",
        starts_at: Optional[datetime] = None,
        ends_at: Optional[datetime] = None,
    ) -> Sprint:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sprints (project_id, name, goal, status, starts_at, ends_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    project_id,
                    name,
                    goal,
                    Status.TODO.value,
                    starts_at.isoformat() if starts_at else None,
                    ends_at.isoformat() if ends_at else None,
                    now,
                ),
            )
            return Sprint(
                id=cur.lastrowid,
                project_id=project_id,
                name=name,
                goal=goal,
                starts_at=starts_at,
                ends_at=ends_at,
                created_at=datetime.fromisoformat(now),
            )

    def list_sprints(self, project_id: int) -> List[Sprint]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sprints WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
        return [_row_to_sprint(r) for r in rows]

    def get_sprint(self, sprint_id: int) -> Optional[Sprint]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
        return _row_to_sprint(row) if row else None

    def update_sprint(self, sprint_id: int, **kwargs) -> Optional[Sprint]:
        allowed = {"name", "goal", "status", "starts_at", "ends_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_sprint(sprint_id)
        if "status" in updates and isinstance(updates["status"], Status):
            updates["status"] = updates["status"].value
        for dt_field in ("starts_at", "ends_at"):
            if dt_field in updates and isinstance(updates[dt_field], datetime):
                updates[dt_field] = updates[dt_field].isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [sprint_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE sprints SET {set_clause} WHERE id=?", values)
        return self.get_sprint(sprint_id)

    # ── Tasks ─────────────────────────────────────────────────────────────

    def create_task(
        self,
        project_id: int,
        title: str,
        description: str = "",
        priority: Priority = Priority.MEDIUM,
        estimate_hours: Optional[float] = None,
        sprint_id: Optional[int] = None,
        source: str = "",
        external_id: str = "",
    ) -> Task:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO tasks
                   (project_id, sprint_id, title, description, status, priority,
                    estimate_hours, created_at, updated_at, source, external_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id,
                    sprint_id,
                    title,
                    description,
                    Status.TODO.value,
                    priority.value,
                    estimate_hours,
                    now,
                    now,
                    source,
                    external_id,
                ),
            )
            return Task(
                id=cur.lastrowid,
                project_id=project_id,
                sprint_id=sprint_id,
                title=title,
                description=description,
                priority=priority,
                estimate_hours=estimate_hours,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
                source=source,
                external_id=external_id,
            )

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(
        self,
        project_id: Optional[int] = None,
        sprint_id: Optional[int] = None,
        status: Optional[Status] = None,
    ) -> List[Task]:
        clauses, params = [], []
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(project_id)
        if sprint_id is not None:
            clauses.append("sprint_id=?")
            params.append(sprint_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status.value)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at", params
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_task_by_external_id(
        self, source: str, external_id: str, project_id: int
    ) -> Optional["Task"]:
        """Find a task by its external provenance (e.g. a GitHub issue number)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE project_id=? AND source=? AND external_id=?",
                (project_id, source, external_id),
            ).fetchone()
        return _row_to_task(row) if row else None

    def update_task(self, task_id: int, **kwargs) -> Optional[Task]:
        allowed = {
            "title", "description", "status", "priority",
            "estimate_hours", "actual_hours", "sprint_id", "completed_at",
            "source", "external_id",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        for enum_field in ("status", "priority"):
            if enum_field in updates and hasattr(updates[enum_field], "value"):
                updates[enum_field] = updates[enum_field].value
        if "completed_at" in updates and isinstance(updates["completed_at"], datetime):
            updates["completed_at"] = updates["completed_at"].isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id=?", values)
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return cur.rowcount > 0

    # ── Time Entries ──────────────────────────────────────────────────────

    def log_time(self, task_id: int, hours: float, note: str = "") -> TimeEntry:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO time_entries (task_id, hours, note, logged_at) VALUES (?,?,?,?)",
                (task_id, hours, note, now),
            )
            entry = TimeEntry(
                id=cur.lastrowid,
                task_id=task_id,
                hours=hours,
                note=note,
                logged_at=datetime.fromisoformat(now),
            )
            # Update actual_hours on task
            conn.execute(
                "UPDATE tasks SET actual_hours = COALESCE(actual_hours, 0) + ?, updated_at=? WHERE id=?",
                (hours, now, task_id),
            )
        return entry

    def list_time_entries(self, task_id: int) -> List[TimeEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM time_entries WHERE task_id=? ORDER BY logged_at", (task_id,)
            ).fetchall()
        return [_row_to_time_entry(r) for r in rows]

    # ── Task Notes ────────────────────────────────────────────────────────

    def add_task_note(self, task_id: int, text: str) -> TaskNote:
        """Append a timestamped note to a task."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO task_notes (task_id, text, created_at) VALUES (?,?,?)",
                (task_id, text, now),
            )
            return TaskNote(
                id=cur.lastrowid,
                task_id=task_id,
                text=text,
                created_at=datetime.fromisoformat(now),
            )

    def get_task_notes(self, task_id: int) -> List[TaskNote]:
        """Return all notes for a task in chronological order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_notes WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [_row_to_task_note(r) for r in rows]

    # ── Task Dependencies ─────────────────────────────────────────────────

    def _dep_ids_of(self, task_id: int) -> List[int]:
        """Return the IDs of tasks that *task_id* directly depends on."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT depends_on_id FROM task_dependencies WHERE task_id=?",
                (task_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def _would_create_cycle(self, task_id: int, depends_on_id: int) -> bool:
        """Return True if adding the edge task_id→depends_on_id would form a cycle.

        A cycle exists if *depends_on_id* can reach *task_id* by following
        existing "depends_on" edges — i.e., *depends_on_id* already
        (transitively) depends on *task_id*.

        Uses iterative DFS to avoid Python recursion limits on deep graphs.
        """
        if task_id == depends_on_id:
            return True  # self-dependency
        visited: set[int] = set()
        stack = [depends_on_id]
        while stack:
            current = stack.pop()
            if current == task_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(self._dep_ids_of(current))
        return False

    def add_dependency(self, task_id: int, depends_on_id: int) -> bool:
        """Declare that *task_id* depends on *depends_on_id*.

        Returns True on success, False if:
        * either task does not exist,
        * the dependency already exists (idempotent),
        * or it would create a circular dependency.
        """
        if not self.get_task(task_id) or not self.get_task(depends_on_id):
            return False
        if self._would_create_cycle(task_id, depends_on_id):
            return False
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO task_dependencies"
                    " (task_id, depends_on_id, created_at) VALUES (?,?,?)",
                    (task_id, depends_on_id, now),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def remove_dependency(self, task_id: int, depends_on_id: int) -> bool:
        """Remove the dependency edge task_id→depends_on_id.

        Returns True if the row existed and was deleted, False otherwise.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM task_dependencies WHERE task_id=? AND depends_on_id=?",
                (task_id, depends_on_id),
            )
        return cur.rowcount > 0

    def get_dependencies(self, task_id: int) -> List[Task]:
        """Return the tasks that *task_id* directly depends on (prerequisites)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tasks t
                   JOIN task_dependencies d ON t.id = d.depends_on_id
                   WHERE d.task_id = ?
                   ORDER BY t.priority DESC, t.id""",
                (task_id,),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_dependents(self, task_id: int) -> List[Task]:
        """Return the tasks that directly depend on *task_id* (downstream tasks)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tasks t
                   JOIN task_dependencies d ON t.id = d.task_id
                   WHERE d.depends_on_id = ?
                   ORDER BY t.priority DESC, t.id""",
                (task_id,),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_ready_tasks(self, project_id: int) -> List[Task]:
        """Return TODO / IN_PROGRESS tasks whose dependencies are all DONE or CANCELLED.

        A task with no dependencies is always "ready".  A task with at least
        one unfinished dependency is excluded.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*
                   FROM tasks t
                   WHERE t.project_id = ?
                     AND t.status IN ('todo', 'in_progress')
                     AND NOT EXISTS (
                         SELECT 1 FROM task_dependencies d
                         JOIN tasks dep ON dep.id = d.depends_on_id
                         WHERE d.task_id = t.id
                           AND dep.status NOT IN ('done', 'cancelled')
                     )
                   ORDER BY t.priority DESC, t.created_at""",
                (project_id,),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def has_unmet_dependencies(self, task_id: int) -> bool:
        """Return True if *task_id* has at least one dependency not yet done/cancelled."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM task_dependencies d
                   JOIN tasks dep ON dep.id = d.depends_on_id
                   WHERE d.task_id = ?
                     AND dep.status NOT IN ('done', 'cancelled')
                   LIMIT 1""",
                (task_id,),
            ).fetchone()
        return row is not None

    # ── Health / Staleness ────────────────────────────────────────────────

    def get_stale_tasks(self, project_id: int, since: datetime) -> List[Task]:
        """Return in_progress tasks with no time entry logged after `since`.

        A task is "stale" if it's been in_progress but nobody has logged any
        time on it in the last N days — either it has no time entries at all,
        or the most recent entry predates `since`.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*
                   FROM tasks t
                   LEFT JOIN time_entries te ON te.task_id = t.id
                   WHERE t.project_id = ? AND t.status = ?
                   GROUP BY t.id
                   HAVING MAX(te.logged_at) < ? OR MAX(te.logged_at) IS NULL
                   ORDER BY t.updated_at""",
                (project_id, Status.IN_PROGRESS.value, since.isoformat()),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    # ── Weekly activity ───────────────────────────────────────────────────

    def time_entries_since(
        self, project_id: int, since: datetime
    ) -> List[tuple[TimeEntry, str]]:
        """Return (TimeEntry, task_title) pairs for a project since `since`.

        Useful for weekly/period reports — joins time_entries with tasks so
        callers don't need a second query per entry.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT te.id, te.task_id, te.hours, te.note, te.logged_at,
                          t.title AS task_title
                   FROM time_entries te
                   JOIN tasks t ON te.task_id = t.id
                   WHERE t.project_id = ? AND te.logged_at >= ?
                   ORDER BY te.logged_at""",
                (project_id, since.isoformat()),
            ).fetchall()
        result = []
        for row in rows:
            entry = TimeEntry(
                id=row["id"],
                task_id=row["task_id"],
                hours=row["hours"],
                note=row["note"],
                logged_at=_dt(row["logged_at"]),
            )
            result.append((entry, row["task_title"]))
        return result

    def tasks_completed_since(self, project_id: int, since: datetime) -> List[Task]:
        """Return tasks completed (status=done) since `since` for a project."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM tasks
                   WHERE project_id = ? AND status = ? AND completed_at >= ?
                   ORDER BY completed_at""",
                (project_id, Status.DONE.value, since.isoformat()),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, query: str) -> dict:
        """Full-text search across projects and tasks. Returns dict with 'projects' and 'tasks'."""
        q = f"%{query.lower()}%"
        with self._conn() as conn:
            project_rows = conn.execute(
                "SELECT * FROM projects WHERE lower(name) LIKE ? OR lower(description) LIKE ? ORDER BY updated_at DESC",
                (q, q),
            ).fetchall()
            task_rows = conn.execute(
                "SELECT * FROM tasks WHERE lower(title) LIKE ? OR lower(description) LIKE ? ORDER BY updated_at DESC",
                (q, q),
            ).fetchall()
        return {
            "projects": [_row_to_project(r) for r in project_rows],
            "tasks": [_row_to_task(r) for r in task_rows],
        }

    # ── Stats ─────────────────────────────────────────────────────────────

    def project_stats(self, project_id: int) -> Optional[ProjectStats]:
        project = self.get_project(project_id)
        if not project:
            return None
        tasks = self.list_tasks(project_id=project_id)
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == Status.DONE)
        in_prog = sum(1 for t in tasks if t.status == Status.IN_PROGRESS)
        blocked = sum(1 for t in tasks if t.status == Status.BLOCKED)
        hours = sum(t.actual_hours or 0 for t in tasks)
        pct = (done / total * 100) if total else 0.0
        return ProjectStats(
            project=project,
            total_tasks=total,
            done_tasks=done,
            in_progress_tasks=in_prog,
            blocked_tasks=blocked,
            total_hours_logged=hours,
            completion_pct=pct,
        )
