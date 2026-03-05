"""Nexus CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__
from .commands.agent import agent_cmd
from .commands.chat import chat_cmd
from .commands.config import config_cmd
from .commands.init import init_cmd
from .commands.dashboard import dashboard_cmd
from .commands.export import export_cmd
from .commands.github import github_cmd
from .commands.project import project_cmd
from .commands.security import security_cmd
from .commands.report import report_cmd
from .commands.sprint import sprint_cmd
from .commands.task import task_cmd
from .commands.timer import timer_cmd
from .commands.watch import watch_cmd
from .commands.workspace import workspace_cmd
from .db import DEFAULT_DB_PATH, Database
from .ui import nexus_banner


@click.group()
@click.version_option(__version__, prog_name="nexus")
@click.option(
    "--db",
    "db_path",
    default=None,
    type=click.Path(),
    envvar="NEXUS_DB",
    help="Path to the Nexus database file.",
)
@click.pass_context
def cli(ctx: click.Context, db_path: str | None) -> None:
    """Nexus — local-first project and task intelligence."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    ctx.ensure_object(dict)
    ctx.obj = Database(path=path)


@cli.command("info")
@click.pass_obj
def info_cmd(db: Database):
    """Show Nexus info and database location."""
    nexus_banner()
    click.echo(f"  Version : {__version__}")
    click.echo(f"  Database: {db.path}")
    click.echo()


cli.add_command(agent_cmd)
cli.add_command(chat_cmd)
cli.add_command(config_cmd)
cli.add_command(init_cmd)
cli.add_command(github_cmd)
cli.add_command(project_cmd)
cli.add_command(task_cmd)
cli.add_command(sprint_cmd)
cli.add_command(report_cmd)
cli.add_command(dashboard_cmd)
cli.add_command(export_cmd)
cli.add_command(security_cmd)
cli.add_command(timer_cmd)
cli.add_command(watch_cmd)
cli.add_command(workspace_cmd)
