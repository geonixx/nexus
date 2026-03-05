"""nexus security — security health check for your Nexus installation.

Checks
------
1.  ~/.nexus/ directory permissions      (should be 700)
2.  Database file permissions            (should be 600)
3.  Config file permissions              (should be 600)
4.  Secrets in config.json              (none should be stored there)
5.  Database tracked by git             (should not be)
6.  Config tracked by git               (warn if it is)
7.  API key environment-variable audit  (presence only — never prints values)

Pass --fix to automatically tighten permissions (items 1–3).
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from rich import box
from rich.rule import Rule
from rich.table import Table

from ..commands.config import CONFIG_PATH, load_config
from ..db import Database
from ..security import (
    file_permission_mode,
    fix_permissions,
    is_git_tracked,
    is_too_permissive,
    scan_config_secrets,
)
from ..ui import console

# Recommended permission modes
_DIR_MODE  = 0o700   # ~/.nexus/ — only the owning user can enter
_FILE_MODE = 0o600   # DB + config — only the owning user can read/write


# ── CLI command ────────────────────────────────────────────────────────────────


@click.command("security")
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Automatically fix file permission issues (items 1–3).",
)
@click.pass_obj
def security_cmd(db: Database, fix: bool):
    """Run a security health check on your Nexus installation.

    Verifies file permissions, scans config for accidentally stored secrets,
    checks whether sensitive files are git-tracked, and audits API key
    environment variables.

    \b
    Exit codes:
      0  All checks passed (warnings are OK)
      1  One or more checks failed
    """
    console.print(Rule("[nexus.title]Nexus Security Check[/nexus.title]", style="cyan"))
    console.print()

    checks = _run_checks(db.path, CONFIG_PATH, fix=fix)

    table = Table(box=box.SIMPLE, show_header=False, expand=False, padding=(0, 1))
    table.add_column("Icon",  justify="center", width=3)
    table.add_column("Check", width=34)
    table.add_column("Detail")

    pass_count = warn_count = fail_count = 0

    for check in checks:
        status = check["status"]
        if status == "pass":
            icon = "[green]✓[/green]"
            pass_count += 1
        elif status == "warn":
            icon = "[yellow]⚠[/yellow]"
            warn_count += 1
        else:
            icon = "[red]✗[/red]"
            fail_count += 1
        table.add_row(icon, check["name"], check["detail"])

    console.print(table)

    # Summary
    parts = []
    if pass_count:
        parts.append(f"[green]{pass_count} passed[/green]")
    if warn_count:
        parts.append(f"[yellow]{warn_count} warning(s)[/yellow]")
    if fail_count:
        parts.append(f"[red]{fail_count} failed[/red]")

    console.print("  " + " · ".join(parts))

    if (fail_count or warn_count) and not fix:
        console.print(
            "  [dim]Run [bold]nexus security --fix[/bold] to automatically "
            "correct permission issues.[/dim]"
        )

    console.print()

    if fail_count:
        raise SystemExit(1)


# ── Internal helpers ───────────────────────────────────────────────────────────


def _run_checks(db_path: Path, config_path: Path, *, fix: bool) -> list[dict]:
    """Execute all security checks; return a list of result dicts.

    Each dict has keys: ``status`` ("pass" | "warn" | "fail"),
    ``name`` (short label), ``detail`` (one-line description).

    Extracted as a standalone function for testability.
    """
    results: list[dict] = []
    nexus_dir = db_path.parent

    # ── 1. ~/.nexus/ directory permissions ────────────────────────────────────
    if nexus_dir.exists():
        mode = file_permission_mode(nexus_dir)
        if is_too_permissive(nexus_dir, expected=_DIR_MODE):
            if fix:
                fix_permissions(nexus_dir, _DIR_MODE)
                results.append(_r(
                    "pass",
                    "Nexus directory permissions",
                    f"Fixed → chmod 700  {nexus_dir}",
                ))
            else:
                results.append(_r(
                    "fail",
                    "Nexus directory permissions",
                    f"Mode {oct(mode)} (want 700) · {nexus_dir}",
                ))
        else:
            results.append(_r(
                "pass",
                "Nexus directory permissions",
                f"700 ✓  ({nexus_dir})",
            ))
    else:
        results.append(_r("pass", "Nexus directory permissions", "Directory not yet created"))

    # ── 2. Database file permissions ──────────────────────────────────────────
    if db_path.exists():
        mode = file_permission_mode(db_path)
        if is_too_permissive(db_path, expected=_FILE_MODE):
            if fix:
                fix_permissions(db_path, _FILE_MODE)
                results.append(_r(
                    "pass",
                    "Database file permissions",
                    f"Fixed → chmod 600  {db_path.name}",
                ))
            else:
                results.append(_r(
                    "fail",
                    "Database file permissions",
                    f"Mode {oct(mode)} (want 600) · {db_path.name}",
                ))
        else:
            results.append(_r("pass", "Database file permissions", f"600 ✓  ({db_path.name})"))
    else:
        results.append(_r("pass", "Database file permissions", "Database not yet created"))

    # ── 3. Config file permissions ────────────────────────────────────────────
    if config_path.exists():
        mode = file_permission_mode(config_path)
        if is_too_permissive(config_path, expected=_FILE_MODE):
            if fix:
                fix_permissions(config_path, _FILE_MODE)
                results.append(_r(
                    "pass",
                    "Config file permissions",
                    f"Fixed → chmod 600  {config_path.name}",
                ))
            else:
                results.append(_r(
                    "fail",
                    "Config file permissions",
                    f"Mode {oct(mode)} (want 600) · {config_path.name}",
                ))
        else:
            results.append(_r("pass", "Config file permissions", f"600 ✓  ({config_path.name})"))
    else:
        results.append(_r("pass", "Config file permissions", "Config not yet created"))

    # ── 4. Secrets in config ──────────────────────────────────────────────────
    config = load_config()
    secret_keys = scan_config_secrets(config)
    if secret_keys:
        joined = ", ".join(f"[bold]{k}[/bold]" for k in secret_keys)
        results.append(_r(
            "fail",
            "Secrets in config.json",
            f"Potential secret(s) detected: {joined}  →  use env vars instead",
        ))
    else:
        results.append(_r("pass", "Secrets in config.json", "No secrets found"))

    # ── 5. Database git-tracking check ────────────────────────────────────────
    if db_path.exists() and is_git_tracked(db_path):
        results.append(_r(
            "fail",
            "Database git tracking",
            f"{db_path.name} is tracked by git — add to .gitignore immediately",
        ))
    else:
        results.append(_r("pass", "Database git tracking", "Not tracked by git ✓"))

    # ── 6. Config git-tracking check ─────────────────────────────────────────
    if config_path.exists() and is_git_tracked(config_path):
        results.append(_r(
            "warn",
            "Config git tracking",
            f"{config_path.name} is tracked by git — consider adding to .gitignore",
        ))
    else:
        results.append(_r("pass", "Config git tracking", "Not tracked by git ✓"))

    # ── 7. API key environment-variable audit (presence only) ─────────────────
    env_audit = [
        ("ANTHROPIC_API_KEY", "Anthropic Claude"),
        ("GOOGLE_API_KEY",    "Google Gemini"),
        ("GITHUB_TOKEN",      "GitHub API"),
    ]
    configured  = [label for var, label in env_audit if os.environ.get(var)]
    missing     = [label for var, label in env_audit if not os.environ.get(var)]

    if configured:
        detail = "Configured: " + ", ".join(configured)
        if missing:
            detail += f"  ·  Not set: {', '.join(missing)}"
        results.append(_r("pass", "API key env vars", detail))
    else:
        results.append(_r(
            "warn",
            "API key env vars",
            "No API keys in environment — AI features will be unavailable",
        ))

    return results


def _r(status: str, name: str, detail: str) -> dict:
    return {"status": status, "name": name, "detail": detail}
