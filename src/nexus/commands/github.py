"""GitHub Issues sync command.

Pulls open (or closed/all) issues from a GitHub repository and upserts them
as Nexus tasks, preserving local edits on re-sync (title / description /
priority are refreshed; status is only changed when an issue is closed).

Usage:
    nexus github sync <project_id> owner/repo [--token TOKEN] [--state open]
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

import click

from ..db import Database
from ..models import Priority, Status
from ..ui import console, print_error, print_info, print_success

# ── GitHub helpers ─────────────────────────────────────────────────────────────


def _gh_label_to_priority(labels: list[dict]) -> Priority:
    """Map GitHub issue labels to a Nexus Priority.

    Mapping (first match wins, from highest → lowest):
        critical / urgent / p0          → CRITICAL
        bug / high / high-priority / p1 → HIGH
        low / low-priority / p3         → LOW
        everything else                 → MEDIUM
    """
    names = {lbl["name"].lower() for lbl in labels}
    if names & {"critical", "urgent", "p0"}:
        return Priority.CRITICAL
    if names & {"bug", "high", "high-priority", "p1"}:
        return Priority.HIGH
    if names & {"low", "low-priority", "p3"}:
        return Priority.LOW
    return Priority.MEDIUM


def _next_link(link_header: str) -> Optional[str]:
    """Parse the *next* URL from a GitHub ``Link:`` response header.

    Returns ``None`` when there is no next page.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = part.strip().split(";")
        url_part = segments[0].strip().strip("<>")
        for rel in segments[1:]:
            if rel.strip() == 'rel="next"':
                return url_part
    return None


def _gh_fetch_all(url: str, token: Optional[str]) -> list[dict]:
    """Fetch a (paginated) GitHub API endpoint, returning all results.

    Follows ``Link: rel="next"`` pagination automatically.

    Raises ``RuntimeError`` on HTTP errors or network failures so callers
    can handle them cleanly.
    """
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results: list[dict] = []
    current_url: Optional[str] = url

    while current_url:
        req = urllib.request.Request(current_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
                current_url = _next_link(resp.headers.get("Link", ""))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"GitHub API returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    return results


# ── Click command group ────────────────────────────────────────────────────────


@click.group("github")
def github_cmd():
    """GitHub integration commands."""


@github_cmd.command("sync")
@click.argument("project_id", type=int)
@click.argument("repo")  # "owner/repo"
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub personal access token (or set $GITHUB_TOKEN). "
         "Required for private repos; recommended to avoid rate limits.",
)
@click.option(
    "--state",
    type=click.Choice(["open", "closed", "all"]),
    default="open",
    show_default=True,
    help="Which issues to sync.",
)
@click.option(
    "--max",
    "max_issues",
    type=int,
    default=200,
    show_default=True,
    help="Maximum number of issues to import (after filtering PRs).",
)
@click.pass_obj
def github_sync(
    db: Database,
    project_id: int,
    repo: str,
    token: Optional[str],
    state: str,
    max_issues: int,
):
    """Sync GitHub issues into a Nexus project.

    REPO should be in ``owner/repo`` format, e.g. ``cli/cli``.

    On re-sync, existing tasks (matched by GitHub issue number) have their
    title, description, and priority refreshed.  A closed issue is marked
    DONE; re-opened issues are *not* reverted automatically so local work
    is preserved.
    """
    project = db.get_project(project_id)
    if not project:
        print_error(f"Project id={project_id} not found.")
        raise SystemExit(1)

    if "/" not in repo or repo.startswith("/") or repo.endswith("/"):
        print_error("REPO must be in 'owner/repo' format, e.g. cli/cli")
        raise SystemExit(1)

    url = (
        f"https://api.github.com/repos/{repo}/issues"
        f"?state={state}&per_page=100"
    )
    print_info(f"Fetching {state} issues from [bold]{repo}[/bold] …")

    try:
        raw = _gh_fetch_all(url, token)
    except RuntimeError as exc:
        print_error(str(exc))
        raise SystemExit(1)

    # /repos/{owner}/{repo}/issues returns PRs too — exclude them
    issues = [i for i in raw if "pull_request" not in i][:max_issues]

    if not issues:
        print_info("No issues found (the repo may be empty or all filtered as PRs).")
        return

    created = updated = 0

    for issue in issues:
        num = str(issue["number"])
        title = issue["title"]
        body = issue.get("body") or ""
        priority = _gh_label_to_priority(issue.get("labels", []))
        closed = issue.get("state") == "closed"

        existing = db.get_task_by_external_id("github", num, project_id)

        if existing:
            # Refresh metadata; only close if GitHub says closed
            update_kwargs: dict = {
                "title": title,
                "description": body,
                "priority": priority,
            }
            if closed and existing.status != Status.DONE:
                update_kwargs["status"] = Status.DONE
            db.update_task(existing.id, **update_kwargs)
            updated += 1
        else:
            task = db.create_task(
                project_id=project_id,
                title=title,
                description=body,
                priority=priority,
                source="github",
                external_id=num,
            )
            if closed:
                db.update_task(task.id, status=Status.DONE)
            created += 1

    print_success(
        f"Synced [bold]{len(issues)}[/bold] issue(s) from [bold]{repo}[/bold]  "
        f"([green]+{created} new[/green] · [cyan]{updated} updated[/cyan])"
    )
    console.print(
        f"  [dim]Project: {project.name} · "
        f"nexus task list --project {project_id}[/dim]"
    )
