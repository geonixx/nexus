"""Global configuration management for Nexus.

Config is stored as JSON at ~/.nexus/config.json (next to the default DB).

Supported keys (all optional):
  default_project   int    Project ID used when no project_id argument is given
  ai_max_tokens     int    Override the AI MAX_TOKENS value (default: 1024)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.table import Table

from ..db import DEFAULT_DB_PATH
from ..security import is_secret_value, mask_secret
from ..ui import console, print_error, print_info, print_success

CONFIG_PATH: Path = DEFAULT_DB_PATH.parent / "config.json"

_KNOWN_KEYS = {
    "default_project": ("int", "Project ID used as the default when none is supplied"),
    "ai_max_tokens":   ("int", "Override AI token limit (default: 1024)"),
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read config from disk; returns {} if missing or corrupted.

    Uses the global CONFIG_PATH when *path* is None (runtime lookup so
    monkeypatching CONFIG_PATH in tests works correctly).
    """
    p = path if path is not None else CONFIG_PATH
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(data: dict[str, Any], path: Path | None = None) -> None:
    p = path if path is not None else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")
    # M10: tighten permissions so only the owning user can read the config
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass  # non-fatal on Windows / restricted environments


def _coerce(value: str) -> Any:
    """Convert string value to the most appropriate Python type."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


@click.group("config")
def config_cmd():
    """View and update Nexus configuration."""


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    Examples:
      nexus config set default_project 3
      nexus config set ai_max_tokens 2048
    """
    # M10: warn loudly if the value looks like an API key or secret token.
    # Config is stored as plaintext JSON — secrets should live in env vars.
    if is_secret_value(value):
        console.print(
            "[yellow bold]⚠  Security warning:[/yellow bold] "
            "this value looks like an API key or secret token.\n"
            "   Nexus config is stored as [bold]plaintext JSON[/bold] "
            f"at {CONFIG_PATH}\n"
            "   Use an environment variable instead — it is never written to disk:\n"
            f"   [dim]export {key.upper()}={value[:4]}…[/dim]"
        )
        raise SystemExit(1)
    coerced = _coerce(value)
    data = load_config()
    data[key] = coerced
    save_config(data)
    print_success(f"[bold]{key}[/bold] = {coerced}")


@config_cmd.command("get")
@click.argument("key")
def config_get(key: str):
    """Get a single configuration value."""
    data = load_config()
    if key not in data:
        print_error(f"Key '{key}' is not set.")
        raise SystemExit(1)
    console.print(str(data[key]))


@config_cmd.command("unset")
@click.argument("key")
def config_unset(key: str):
    """Remove a configuration key."""
    data = load_config()
    if key not in data:
        print_error(f"Key '{key}' is not set.")
        raise SystemExit(1)
    del data[key]
    save_config(data)
    print_info(f"Unset '{key}'.")


@config_cmd.command("show")
def config_show():
    """Display all configuration values.

    Values that look like API keys or secret tokens are masked automatically.
    Run 'nexus security' to audit your full security posture.
    """
    data = load_config()
    if not data:
        print_info(f"No configuration set. File: {CONFIG_PATH}")
        return

    table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_column("Description", style="dim")

    masked_count = 0
    for key in sorted(data):
        raw = str(data[key])
        desc = _KNOWN_KEYS.get(key, ("", ""))[1]
        # M10: mask any value that looks like a secret
        if is_secret_value(raw):
            display = f"[yellow]{mask_secret(raw)}[/yellow]  [dim](masked)[/dim]"
            masked_count += 1
        else:
            display = raw
        table.add_row(key, display, desc)

    console.print(table)
    console.print(f"  [dim]Config file: {CONFIG_PATH}[/dim]")
    if masked_count:
        console.print(
            f"  [yellow]⚠  {masked_count} secret-looking value(s) masked. "
            "Run [bold]nexus security[/bold] for details.[/yellow]"
        )
