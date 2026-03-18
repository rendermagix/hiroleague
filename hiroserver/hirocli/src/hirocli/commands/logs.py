"""Log reading subcommands — thin CLI layer over LogSearchTool and LogTailTool."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError
from ..tools.logs import LogSearchTool, LogTailTool


def register(logs_app: typer.Typer, console: Console) -> None:
    """Register log subcommands on *logs_app*."""

    @logs_app.command("search")
    def logs_search(
        query: Optional[str] = typer.Argument(
            None, help="Full-text search across message and extra fields."
        ),
        source: Optional[str] = typer.Option(
            None,
            "--source",
            "-s",
            help="Log source: server, plugins, gateway, or all (default: all).",
        ),
        level: Optional[str] = typer.Option(
            None,
            "--level",
            "-l",
            help="Minimum log level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
        ),
        module: Optional[str] = typer.Option(
            None,
            "--module",
            "-m",
            help="Filter by module name (substring match).",
        ),
        limit: Optional[int] = typer.Option(
            None,
            "--limit",
            "-n",
            help="Maximum rows to return (default: 200).",
        ),
        workspace: Optional[str] = typer.Option(
            None,
            "--workspace",
            "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Search log files for entries matching the given filters."""
        try:
            result = LogSearchTool().execute(
                source=source,
                level=level,
                module=module,
                query=query,
                limit=limit,
                workspace=workspace,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.rows:
            console.print("[dim]No matching log entries found.[/dim]")
            return

        table = Table(show_header=True, box=None)
        table.add_column("Time", style="dim", no_wrap=True)
        table.add_column("Lvl", no_wrap=True)
        table.add_column("Source", style="cyan", no_wrap=True)
        table.add_column("Module", style="magenta", no_wrap=True)
        table.add_column("Message")
        table.add_column("Extra", style="dim")

        _LEVEL_STYLES = {
            "DEBUG": "blue",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold magenta",
        }

        for row in result.rows:
            lvl = row.get("level", "")
            lvl_style = _LEVEL_STYLES.get(lvl, "")
            table.add_row(
                row.get("timestamp", ""),
                f"[{lvl_style}]{lvl}[/{lvl_style}]" if lvl_style else lvl,
                row.get("source", ""),
                row.get("module", ""),
                row.get("message", ""),
                row.get("extra", ""),
            )

        console.print(table)

        if result.truncated:
            console.print(
                f"[dim]Showing {len(result.rows)} of {result.total_matches} matches "
                f"— use --limit to increase.[/dim]"
            )

    @logs_app.command("tail")
    def logs_tail(
        lines: int = typer.Option(
            100,
            "--lines",
            "-n",
            help="Number of recent lines to show.",
        ),
        source: Optional[str] = typer.Option(
            None,
            "--source",
            "-s",
            help="Log source: server, plugins, gateway, or all (default: all).",
        ),
        workspace: Optional[str] = typer.Option(
            None,
            "--workspace",
            "-W",
            help="Workspace name (default: registry default).",
        ),
    ) -> None:
        """Show the most recent log entries."""
        try:
            result = LogTailTool().execute(
                source=source,
                lines=lines,
                workspace=workspace,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.rows:
            console.print("[dim]No log entries found.[/dim]")
            return

        _LEVEL_STYLES = {
            "DEBUG": "blue",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold magenta",
        }

        for row in result.rows:
            lvl = row.get("level", "")
            lvl_style = _LEVEL_STYLES.get(lvl, "")
            lvl_display = f"[{lvl_style}]{lvl[:3]}[/{lvl_style}]" if lvl_style else lvl[:3]
            console.print(
                f"[dim]{row.get('timestamp', '')}[/dim] "
                f"{lvl_display} "
                f"[cyan]{row.get('source', '')}[/cyan] "
                f"[magenta]{row.get('module', '')}[/magenta] "
                f"{row.get('message', '')} "
                f"[dim]{row.get('extra', '')}[/dim]"
            )
