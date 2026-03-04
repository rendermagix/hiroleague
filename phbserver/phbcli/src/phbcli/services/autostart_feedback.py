"""User-facing auto-start register/unregister flows with rich output."""

from __future__ import annotations

import sys

from rich.console import Console

from ..autostart import (
    register_autostart,
    register_autostart_elevated,
    unregister_autostart,
    unregister_autostart_elevated,
)


def register_autostart_with_feedback(console: Console, *, elevated: bool = False) -> None:
    """Register auto-start and print a user-friendly summary."""
    if elevated and sys.platform == "win32":
        console.print(
            "[dim]Requesting UAC elevation to create a high-privilege task…[/dim]"
        )
        try:
            accepted = register_autostart_elevated()
        except RuntimeError as exc:
            console.print(f"[yellow]Elevated task creation failed: {exc}[/yellow]")
            accepted = False

        if accepted:
            console.print(
                "[green]Auto-start registered[/green] via Task Scheduler "
                "(elevated, run-level: HIGHEST)."
            )
        else:
            console.print(
                "[yellow]UAC prompt was cancelled or failed. "
                "Falling back to standard auto-start…[/yellow]"
            )
            register_autostart_standard(console)
    else:
        register_autostart_standard(console)


def register_autostart_standard(console: Console) -> None:
    """Try schtasks (LIMITED), fall back to registry, and report method."""
    try:
        method = register_autostart()
    except NotImplementedError as exc:
        console.print(f"[yellow]Auto-start skipped: {exc}[/yellow]")
        return
    except Exception as exc:
        console.print(f"[yellow]Auto-start registration failed: {exc}[/yellow]")
        return

    if method == "schtasks":
        console.print(
            "[green]Auto-start registered[/green] via Task Scheduler "
            "(run-level: LIMITED, no elevation needed)."
        )
    elif method == "registry":
        console.print(
            "[green]Auto-start registered[/green] via Registry Run key "
            "[dim](Task Scheduler was unavailable — registry fallback used)[/dim]."
        )
    else:
        console.print("[yellow]Auto-start method unknown.[/yellow]")


def unregister_autostart_with_feedback(
    console: Console, *, elevated: bool = False
) -> None:
    """Unregister auto-start and print a user-friendly summary."""
    if elevated and sys.platform == "win32":
        console.print(
            "[dim]Requesting UAC elevation to delete high-privilege task…[/dim]"
        )
        try:
            accepted = unregister_autostart_elevated()
        except RuntimeError as exc:
            console.print(f"[yellow]Elevated teardown failed: {exc}[/yellow]")
            accepted = False

        if accepted:
            console.print(
                "[green]Auto-start removed[/green] via elevated Task Scheduler delete."
            )
        else:
            console.print(
                "[yellow]UAC prompt was cancelled. "
                "Falling back to standard unregister…[/yellow]"
            )
            unregister_autostart_standard(console)
    else:
        unregister_autostart_standard(console)


def unregister_autostart_standard(console: Console) -> None:
    """Remove auto-start registrations and print outcome."""
    try:
        unregister_autostart()
        console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
    except NotImplementedError as exc:
        console.print(f"[yellow]Auto-start removal skipped: {exc}[/yellow]")
    except Exception as exc:
        console.print(f"[yellow]Auto-start removal failed: {exc}[/yellow]")
