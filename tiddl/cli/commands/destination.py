"""`tiddl destination trust/status/forget` — administer destination-volume
identity trust records (see `tiddl.core.utils.destination_anchor`).

Deliberately the ONLY place that mutates anchor state. A download or
`tiddl recover` never creates, replaces, adopts, or rotates an anchor,
under any flag, in any mode (PROPOSAL_destination_volume_identity_v2_1.md
§2, kept local/untracked) — enforced by construction: no code path outside
this module calls `establish_anchor`/`adopt_anchor`/`forget_anchor`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from tiddl.core.utils import destination_anchor as da

console = Console()

destination_command = typer.Typer(
    name="destination",
    help="Manage destination-volume identity trust records.",
    no_args_is_help=True,
)


def _print_state_status_warning(status: str) -> None:
    # Mirrors cli/commands/recover.py's _print_registry_status_warning: this
    # describes only what has verifiably happened (a read-only listing never
    # mutates the file), matching retained_registry's own precedent.
    if status == "corrupt":
        console.print(
            f"[yellow]⚠️  The destination-anchor local state at {da.anchor_state_path()} "
            "could not be parsed. It has NOT been modified by this listing; a future "
            "trust/forget will back it up before writing a fresh one.[/]"
        )
    elif status == "unsupported_version":
        console.print(
            "[yellow]⚠️  The destination-anchor local state is from a newer/unknown "
            "version of tiddl. It has NOT been modified by this listing.[/]"
        )
    elif status == "unreadable":
        console.print(
            f"[red]⚠️  The destination-anchor local state at {da.anchor_state_path()} "
            "could not be read (see the logs for the exact I/O error). It has NOT been "
            "modified. Any trust/forget will refuse until this is resolved.[/]"
        )


_CONFIRM_PROMPT = (
    "Only continue if you've confirmed this is the real, currently-mounted "
    "destination — not a fallback local directory. Proceed?"
)


@destination_command.command()
def trust(
    path: Annotated[Path, typer.Argument(help="The destination root to trust.")],
    confirm_mounted: Annotated[
        bool,
        typer.Option(
            "--confirm-mounted",
            help="Skip the confirmation prompt (scripted/unattended use).",
        ),
    ] = False,
    adopt_existing: Annotated[
        bool,
        typer.Option(
            "--adopt-existing",
            help=(
                "Adopt an anchor another installation already created at this root, "
                "instead of creating a new one. Never modifies the destination."
            ),
        ),
    ] = False,
):
    """Explicitly trust PATH as a real destination root.

    Never run automatically by a download or by `tiddl recover` — this is a
    deliberate administrative act, exactly like `tiddl auth import-orpheus
    --trust-pickle` is for a different kind of trust decision in this project.
    """
    root = Path(path)

    if not root.exists():
        console.print(
            f"[red]'{root}' does not exist. 'trust' never creates the destination — "
            "create/mount it yourself first, then re-run this command.[/]"
        )
        raise typer.Exit(1)
    if not root.is_dir():
        console.print(f"[red]'{root}' is not a directory.[/]")
        raise typer.Exit(1)

    marker_status, marker_anchor_id, marker_detail = da.read_marker(root)

    if marker_status in ("unreadable", "invalid"):
        console.print(
            f"[red]The existing marker at {da.marker_path(root)} is {marker_status} "
            f"({marker_detail}). Never silently adopted or overwritten — resolve this "
            "manually (e.g. delete a corrupted marker) before trusting this root.[/]"
        )
        raise typer.Exit(1)

    if marker_status == "trusted":
        state = da.read_state()
        if state.status == "unreadable":
            console.print(
                f"[red]Local anchor state at {da.anchor_state_path()} could not be "
                "read — refusing to proceed until this is resolved.[/]"
            )
            raise typer.Exit(1)

        record = None
        if state.status == "valid":
            record = da.find_record(state.records, da.root_key(root))
        if record is not None and record.anchor_id == marker_anchor_id:
            console.print(
                f"[green]'{root}' is already trusted (anchor {marker_anchor_id[:8]}...). "
                "Nothing to do.[/]"
            )
            return

        if not adopt_existing:
            console.print(
                f"[yellow]A marker already exists at {da.marker_path(root)}, but it "
                "doesn't match what this machine has recorded (or nothing is recorded "
                "here yet). If this is genuinely a shared root another installation "
                "already trusts, re-run with [bold]--adopt-existing[/].[/]"
            )
            raise typer.Exit(1)

        console.print(f"About to adopt the existing anchor at {da.marker_path(root)} for '{root}'.")
        if not confirm_mounted and not typer.confirm(_CONFIRM_PROMPT):
            console.print("[yellow]Aborted — nothing changed.[/]")
            raise typer.Exit(1)
        try:
            anchor_id = da.adopt_anchor(root)
        except (
            da.LocalStateReadError,
            da.LocalStateLockTimeout,
            da.LocalStatePreservationError,
            ValueError,
        ) as e:
            console.print(f"[red]Could not adopt the existing anchor: {e}[/]")
            raise typer.Exit(1)
        console.print(f"[green]Adopted anchor {anchor_id[:8]}... for '{root}'.[/]")
        return

    # marker_status == "absent": genuinely establishing a new anchor.
    console.print(f"About to trust '{root}' as a real destination root.")
    if not confirm_mounted and not typer.confirm(_CONFIRM_PROMPT):
        console.print("[yellow]Aborted — nothing changed.[/]")
        raise typer.Exit(1)
    try:
        anchor_id = da.establish_anchor(root)
    except da.AnchorAlreadyExists:
        console.print(
            f"[red]A marker appeared at {da.marker_path(root)} while confirming (a race "
            f"with another process) — re-run 'tiddl destination trust {root}' to pick it up.[/]"
        )
        raise typer.Exit(1)
    except (da.LocalStateReadError, da.LocalStateLockTimeout, da.LocalStatePreservationError) as e:
        # Partial-failure rule (PROPOSAL v2.1 §13): the marker is the
        # authoritative artifact and is left in place even though recording
        # it locally failed — never deleted to "undo" this.
        console.print(
            f"[yellow]The destination marker was created, but recording it locally "
            f"failed ({e}). The marker is intact — re-run "
            f"'tiddl destination trust {root} --adopt-existing' to pick it up.[/]"
        )
        raise typer.Exit(1)
    console.print(f"[green]Trusted '{root}' (anchor {anchor_id[:8]}...).[/]")


@destination_command.command()
def status(
    path: Annotated[
        Optional[Path],
        typer.Argument(help="A specific root to check. Omit to list every known root."),
    ] = None,
):
    """Read-only. Reports the live anchor-check reason for one root, or
    every root this machine currently has local trust state for. No writes,
    no locks held beyond the read."""
    state = da.read_state()
    _print_state_status_warning(state.status)

    if path is not None:
        check = da.anchor_status(Path(path))
        detail = f" ({check.detail})" if check.detail else ""
        color = "green" if check.reason == "trusted" else "red"
        console.print(f"{path}: [{color}]{check.reason}[/]{detail}")
        return

    if state.status == "missing" or (state.status == "valid" and not state.records):
        console.print("[green]No roots trusted yet.[/]")
        return
    if state.status != "valid":
        return

    table = Table(title="Trusted destination roots")
    table.add_column("root")
    table.add_column("live status")
    table.add_column("trusted_at")
    for record in state.records:
        check = da.anchor_status(Path(record.root_display))
        color = "green" if check.reason == "trusted" else "red"
        table.add_row(record.root_display, f"[{color}]{check.reason}[/]", record.trusted_at)
    console.print(table)


@destination_command.command()
def forget(
    path: Annotated[
        Path,
        typer.Argument(help="The root to remove from THIS machine's local trust state."),
    ],
):
    """Removes PATH from local trust state only. Never touches the shared
    `.tiddl-anchor` marker on the destination — another installation, or
    this same machine later, may still depend on it existing."""
    try:
        removed = da.forget_anchor(Path(path))
    except (da.LocalStateReadError, da.LocalStateLockTimeout, da.LocalStatePreservationError) as e:
        console.print(f"[red]Could not forget '{path}': {e}[/]")
        raise typer.Exit(1)
    if removed:
        console.print(
            f"[green]Forgot '{path}' (local state only — the marker on the destination "
            "is untouched).[/]"
        )
    else:
        console.print(f"[yellow]'{path}' was not in local trust state — nothing to do.[/]")
