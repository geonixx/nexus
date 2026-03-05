"""Tests for M9: GitHub Issues sync + Workspace portfolio view.

Coverage areas
--------------
* Task model   — source / external_id fields with defaults
* Database     — migration idempotency, create_task with provenance,
                 get_task_by_external_id, update_task w/ new fields
* github.py    — _gh_label_to_priority, _next_link, _gh_fetch_all,
                 `nexus github sync` CLI (mocked urllib)
* workspace.py — `nexus workspace`, `nexus workspace next`
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.commands.github import _gh_label_to_priority, _next_link, _gh_fetch_all
from nexus.db import Database
from nexus.models import Priority, Status, Task


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(path=tmp_path / "nexus.db")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def invoke(runner: CliRunner, db: Database, *args):
    """Helper: invoke CLI with an isolated database."""
    return runner.invoke(cli, ["--db", str(db.path)] + list(args))


# ── Task model: source / external_id ─────────────────────────────────────────


class TestTaskProvenance:
    def test_defaults_are_empty_strings(self):
        t = Task(project_id=1, title="x")
        assert t.source == ""
        assert t.external_id == ""

    def test_source_and_external_id_set(self):
        t = Task(project_id=1, title="x", source="github", external_id="42")
        assert t.source == "github"
        assert t.external_id == "42"

    def test_model_dump_includes_provenance(self):
        t = Task(project_id=1, title="x", source="github", external_id="7")
        d = t.model_dump()
        assert d["source"] == "github"
        assert d["external_id"] == "7"


# ── Database: provenance columns ─────────────────────────────────────────────


class TestDatabaseProvenance:
    def test_create_task_default_provenance(self, db: Database):
        p = db.create_project("Alpha")
        t = db.create_task(p.id, "Plain task")
        assert t.source == ""
        assert t.external_id == ""

    def test_create_task_with_provenance(self, db: Database):
        p = db.create_project("Beta")
        t = db.create_task(p.id, "GH task", source="github", external_id="99")
        assert t.source == "github"
        assert t.external_id == "99"

    def test_get_task_by_external_id_found(self, db: Database):
        p = db.create_project("Gamma")
        db.create_task(p.id, "Issue #5", source="github", external_id="5")
        found = db.get_task_by_external_id("github", "5", p.id)
        assert found is not None
        assert found.title == "Issue #5"
        assert found.external_id == "5"

    def test_get_task_by_external_id_not_found(self, db: Database):
        p = db.create_project("Delta")
        result = db.get_task_by_external_id("github", "999", p.id)
        assert result is None

    def test_get_task_by_external_id_wrong_project(self, db: Database):
        p1 = db.create_project("P1")
        p2 = db.create_project("P2")
        db.create_task(p1.id, "Issue #1", source="github", external_id="1")
        # Same external_id but different project must return None
        result = db.get_task_by_external_id("github", "1", p2.id)
        assert result is None

    def test_get_task_preserves_provenance(self, db: Database):
        p = db.create_project("Epsilon")
        created = db.create_task(p.id, "Issue #77", source="github", external_id="77")
        fetched = db.get_task(created.id)
        assert fetched is not None
        assert fetched.source == "github"
        assert fetched.external_id == "77"

    def test_update_task_source_and_external_id(self, db: Database):
        p = db.create_project("Zeta")
        t = db.create_task(p.id, "Task")
        updated = db.update_task(t.id, source="github", external_id="42")
        assert updated.source == "github"
        assert updated.external_id == "42"

    def test_list_tasks_preserves_provenance(self, db: Database):
        p = db.create_project("Eta")
        db.create_task(p.id, "Issue #3", source="github", external_id="3")
        db.create_task(p.id, "Local task")
        tasks = db.list_tasks(project_id=p.id)
        gh_tasks = [t for t in tasks if t.source == "github"]
        local_tasks = [t for t in tasks if t.source == ""]
        assert len(gh_tasks) == 1
        assert len(local_tasks) == 1

    def test_migration_idempotent(self, tmp_path: Path):
        """Creating a second Database on the same file should not raise."""
        path = tmp_path / "idem.db"
        db1 = Database(path=path)
        db1.create_project("P")
        # Second init on same DB — migration try/except must be idempotent
        db2 = Database(path=path)
        assert db2.get_project_by_name("P") is not None


# ── GitHub helpers ────────────────────────────────────────────────────────────


class TestGhLabelToPriority:
    def test_no_labels_gives_medium(self):
        assert _gh_label_to_priority([]) == Priority.MEDIUM

    def test_bug_gives_high(self):
        assert _gh_label_to_priority([{"name": "bug"}]) == Priority.HIGH

    def test_critical_gives_critical(self):
        assert _gh_label_to_priority([{"name": "critical"}]) == Priority.CRITICAL

    def test_urgent_gives_critical(self):
        assert _gh_label_to_priority([{"name": "urgent"}]) == Priority.CRITICAL

    def test_low_priority_gives_low(self):
        assert _gh_label_to_priority([{"name": "low-priority"}]) == Priority.LOW

    def test_high_label_gives_high(self):
        assert _gh_label_to_priority([{"name": "high"}]) == Priority.HIGH

    def test_critical_beats_bug(self):
        labels = [{"name": "critical"}, {"name": "bug"}]
        assert _gh_label_to_priority(labels) == Priority.CRITICAL

    def test_p0_gives_critical(self):
        assert _gh_label_to_priority([{"name": "p0"}]) == Priority.CRITICAL

    def test_p1_gives_high(self):
        assert _gh_label_to_priority([{"name": "p1"}]) == Priority.HIGH

    def test_p3_gives_low(self):
        assert _gh_label_to_priority([{"name": "p3"}]) == Priority.LOW

    def test_enhancement_gives_medium(self):
        assert _gh_label_to_priority([{"name": "enhancement"}]) == Priority.MEDIUM


class TestNextLink:
    def test_no_header_returns_none(self):
        assert _next_link("") is None

    def test_parses_next_url(self):
        header = (
            '<https://api.github.com/repos/foo/bar/issues?page=2>; rel="next", '
            '<https://api.github.com/repos/foo/bar/issues?page=5>; rel="last"'
        )
        result = _next_link(header)
        assert result == "https://api.github.com/repos/foo/bar/issues?page=2"

    def test_returns_none_when_no_next(self):
        header = '<https://api.github.com/repos/foo/bar/issues?page=5>; rel="last"'
        assert _next_link(header) is None

    def test_single_page_no_link_header(self):
        assert _next_link(None) is None  # type: ignore[arg-type]


# ── Mock response helper ──────────────────────────────────────────────────────


def _mock_response(data: list | dict, link: str = "") -> MagicMock:
    """Build a mock context-manager urllib response."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode()
    mock.headers = {"Link": link}
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


SAMPLE_ISSUES = [
    {
        "number": 1,
        "title": "Fix login bug",
        "body": "Login fails on Safari.",
        "state": "open",
        "labels": [{"name": "bug"}],
    },
    {
        "number": 2,
        "title": "Add dark mode",
        "body": "Users want dark mode.",
        "state": "open",
        "labels": [],
    },
    {
        "number": 3,
        "title": "Old closed issue",
        "body": "Already done.",
        "state": "closed",
        "labels": [],
    },
]


# ── GitHub CLI: nexus github sync ─────────────────────────────────────────────


class TestGithubSync:
    def test_sync_creates_tasks(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("Web App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES)
            result = invoke(runner, db, "github", "sync", str(p.id), "owner/repo")

        assert result.exit_code == 0, result.output
        tasks = db.list_tasks(project_id=p.id)
        assert len(tasks) == 3

    def test_sync_sets_source_and_external_id(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES[:1])
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        t = db.get_task_by_external_id("github", "1", p.id)
        assert t is not None
        assert t.source == "github"
        assert t.external_id == "1"

    def test_sync_maps_bug_label_to_high(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES[:1])
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        t = db.get_task_by_external_id("github", "1", p.id)
        assert t is not None
        assert t.priority == Priority.HIGH

    def test_closed_issue_gets_done_status(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        closed = [SAMPLE_ISSUES[2]]  # state=closed
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(closed)
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        t = db.get_task_by_external_id("github", "3", p.id)
        assert t is not None
        assert t.status == Status.DONE

    def test_resync_updates_existing_task(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        # First sync
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES[:1])
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        # Second sync with updated title
        updated_issue = [{**SAMPLE_ISSUES[0], "title": "Fix login bug (revised)"}]
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(updated_issue)
            result = invoke(runner, db, "github", "sync", str(p.id), "o/r")

        assert result.exit_code == 0
        t = db.get_task_by_external_id("github", "1", p.id)
        assert t is not None
        assert t.title == "Fix login bug (revised)"
        # Only 1 task still (updated, not duplicated)
        assert len(db.list_tasks(project_id=p.id)) == 1

    def test_resync_output_shows_updated(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES[:1])
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES[:1])
            result = invoke(runner, db, "github", "sync", str(p.id), "o/r")

        assert "updated" in result.output

    def test_filters_pull_requests(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        issues_with_pr = SAMPLE_ISSUES + [
            {
                "number": 10,
                "title": "A pull request",
                "body": "",
                "state": "open",
                "labels": [],
                "pull_request": {"url": "https://example.com"},
            }
        ]
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(issues_with_pr)
            invoke(runner, db, "github", "sync", str(p.id), "o/r")

        tasks = db.list_tasks(project_id=p.id)
        # PR must be excluded — only 3 real issues
        assert len(tasks) == 3

    def test_bad_repo_format_exits_nonzero(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        result = invoke(runner, db, "github", "sync", str(p.id), "noslash")
        assert result.exit_code != 0

    def test_missing_project_exits_nonzero(
        self, db: Database, runner: CliRunner
    ):
        result = invoke(runner, db, "github", "sync", "9999", "o/r")
        assert result.exit_code != 0

    def test_http_error_exits_nonzero(
        self, db: Database, runner: CliRunner
    ):
        import urllib.error
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="", code=401, msg="Unauthorized", hdrs=None, fp=None
            )
            result = invoke(runner, db, "github", "sync", str(p.id), "o/r")
        assert result.exit_code != 0

    def test_max_issues_cap(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES)
            result = invoke(
                runner, db, "github", "sync", str(p.id), "o/r", "--max", "1"
            )
        assert result.exit_code == 0
        assert len(db.list_tasks(project_id=p.id)) == 1

    def test_sync_success_message(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response(SAMPLE_ISSUES)
            result = invoke(runner, db, "github", "sync", str(p.id), "o/r")
        assert "Synced" in result.output
        assert "new" in result.output

    def test_no_issues_returns_info(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("App")
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_response([])
            result = invoke(runner, db, "github", "sync", str(p.id), "o/r")
        assert result.exit_code == 0
        assert "No issues" in result.output

    def test_token_passed_in_auth_header(
        self, db: Database, runner: CliRunner
    ):
        """Ensure --token is forwarded to the Authorization header."""
        p = db.create_project("Private")
        captured_req = []

        def fake_urlopen(req, timeout=None):
            captured_req.append(req)
            return _mock_response([])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            invoke(runner, db, "github", "sync", str(p.id), "o/r", "--token", "tok123")

        assert captured_req, "urlopen was never called"
        auth = captured_req[0].get_header("Authorization")
        assert auth == "Bearer tok123"


# ── Workspace CLI: nexus workspace ───────────────────────────────────────────


class TestWorkspace:
    def test_workspace_no_projects(self, db: Database, runner: CliRunner):
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_workspace_shows_projects(self, db: Database, runner: CliRunner):
        db.create_project("Frontend")
        db.create_project("Backend")
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        assert "Frontend" in result.output
        assert "Backend" in result.output

    def test_workspace_shows_health_grade(self, db: Database, runner: CliRunner):
        p = db.create_project("Alpha")
        db.create_task(p.id, "T1")
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        # Grade or dash must be shown
        assert any(ch in result.output for ch in ["A", "B", "C", "D", "F", "—"])

    def test_workspace_empty_project_shows_dash(
        self, db: Database, runner: CliRunner
    ):
        db.create_project("Empty")
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        assert "—" in result.output

    def test_workspace_shows_done_count(self, db: Database, runner: CliRunner):
        p = db.create_project("Proj")
        t = db.create_task(p.id, "Task A")
        db.update_task(t.id, status=Status.DONE)
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        assert "1" in result.output  # done count

    def test_workspace_shows_blocked(self, db: Database, runner: CliRunner):
        p = db.create_project("Proj")
        t = db.create_task(p.id, "Stuck")
        db.update_task(t.id, status=Status.BLOCKED)
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0

    def test_workspace_multiple_projects_all_listed(
        self, db: Database, runner: CliRunner
    ):
        for name in ["AA", "BB", "CC"]:
            p = db.create_project(name)
            db.create_task(p.id, "Task")
        result = invoke(runner, db, "workspace")
        assert result.exit_code == 0
        for name in ["AA", "BB", "CC"]:
            assert name in result.output


class TestWorkspaceNext:
    def test_next_no_projects(self, db: Database, runner: CliRunner):
        result = invoke(runner, db, "workspace", "next")
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_next_no_actionable_tasks(self, db: Database, runner: CliRunner):
        p = db.create_project("Done Proj")
        t = db.create_task(p.id, "Completed")
        db.update_task(t.id, status=Status.DONE)
        result = invoke(runner, db, "workspace", "next")
        assert result.exit_code == 0
        assert "No actionable" in result.output

    def test_next_lists_tasks_across_projects(
        self, db: Database, runner: CliRunner
    ):
        p1 = db.create_project("Project One")
        p2 = db.create_project("Project Two")
        db.create_task(p1.id, "Task Alpha", priority=Priority.HIGH)
        db.create_task(p2.id, "Task Beta", priority=Priority.MEDIUM)
        result = invoke(runner, db, "workspace", "next")
        assert result.exit_code == 0
        assert "Task Alpha" in result.output
        assert "Task Beta" in result.output

    def test_next_critical_appears_first(
        self, db: Database, runner: CliRunner
    ):
        p1 = db.create_project("P1")
        p2 = db.create_project("P2")
        db.create_task(p1.id, "Medium task", priority=Priority.MEDIUM)
        db.create_task(p2.id, "Critical task", priority=Priority.CRITICAL)
        result = invoke(runner, db, "workspace", "next")
        assert result.exit_code == 0
        crit_pos = result.output.index("Critical task")
        med_pos = result.output.index("Medium task")
        assert crit_pos < med_pos

    def test_next_excludes_done_and_blocked(
        self, db: Database, runner: CliRunner
    ):
        p = db.create_project("Mixed")
        t_done = db.create_task(p.id, "Done task")
        t_blocked = db.create_task(p.id, "Blocked task")
        db.create_task(p.id, "Active task")
        db.update_task(t_done.id, status=Status.DONE)
        db.update_task(t_blocked.id, status=Status.BLOCKED)
        result = invoke(runner, db, "workspace", "next")
        assert "Done task" not in result.output
        assert "Blocked task" not in result.output
        assert "Active task" in result.output

    def test_next_limit_respected(self, db: Database, runner: CliRunner):
        p = db.create_project("Many")
        for i in range(10):
            db.create_task(p.id, f"Task {i}")
        result = invoke(runner, db, "workspace", "next", "--limit", "3")
        assert result.exit_code == 0
        assert "Showing 3 of 10" in result.output

    def test_next_shows_project_name(self, db: Database, runner: CliRunner):
        p = db.create_project("MySpecialProject")
        db.create_task(p.id, "Important work")
        result = invoke(runner, db, "workspace", "next")
        assert "MySpecialProject" in result.output

    def test_next_in_progress_included(self, db: Database, runner: CliRunner):
        p = db.create_project("Active")
        t = db.create_task(p.id, "In flight")
        db.update_task(t.id, status=Status.IN_PROGRESS)
        result = invoke(runner, db, "workspace", "next")
        assert "In flight" in result.output
        assert "in_progress" in result.output
