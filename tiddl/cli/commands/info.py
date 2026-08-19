from __future__ import annotations

import typer
from rich.syntax import Syntax
from typing_extensions import Annotated

from tiddl.cli.ctx import Context
from tiddl.cli.utils.resource import TidalResource
from tiddl.core.edition_resolver import SUPPORTED_QUALITIES, find_stereo_editions

info_command = typer.Typer(name="info", help="Show metadata for a resource.")


@info_command.command(
    name="editions",
    help="Find likely stereo editions of a TIDAL album without downloading anything.",
)
def info_editions(
    ctx: Context,
    album: Annotated[TidalResource, typer.Argument(parser=TidalResource.from_string)],
    quality: Annotated[
        str,
        typer.Option(
            "--quality",
            "-q",
            help="Required stereo quality: low, normal, high (Lossless), or max (HiRes Lossless).",
        ),
    ] = "max",
):
    """Read-only diagnostic for separately published Atmos/stereo editions."""
    if album.type != "album":
        raise typer.BadParameter("editions requires a TIDAL album URL")
    quality = quality.casefold()
    if quality not in SUPPORTED_QUALITIES:
        raise typer.BadParameter(
            "quality must be low, normal, high, or max", param_hint="--quality"
        )

    ctx.obj.console.print(
        f"[bold cyan]Dry run: checking {quality.upper()} stereo editions "
        f"for album {album.id}...[/]"
    )
    try:
        result = find_stereo_editions(
            ctx.obj.api, int(album.id), requested_quality=quality
        )
    except Exception as exc:
        ctx.obj.console.print(f"[red]Error checking editions:[/] {exc}")
        raise typer.Exit(1)

    source = result.source
    modes = ", ".join(getattr(source, "audioModes", []) or []) or "unknown"
    ctx.obj.console.print(
        f"Requested: [bold]{source.title}[/] (ID {source.id}) — {modes}, "
        f"{source.numberOfTracks} tracks"
    )
    if result.source_satisfies_request:
        ctx.obj.console.print(
            f"[green]The requested album already provides {quality.upper()} stereo; "
            "no replacement is needed.[/]"
        )
        ctx.obj.console.print(
            "[dim]Dry run only: no files were downloaded and no settings were changed.[/]"
        )
        return
    if not result.candidates:
        ctx.obj.console.print(
            f"[yellow]No sufficiently similar {quality.upper()} stereo edition was found.[/]"
        )
        ctx.obj.console.print("[dim]No files were downloaded and no settings were changed.[/]")
        return

    for index, candidate in enumerate(result.candidates, start=1):
        alternate = candidate.album
        quality_tags = getattr(getattr(alternate, "mediaMetadata", None), "tags", []) or []
        ctx.obj.console.print(
            f"\n[bold green]#{index} Stereo candidate:[/] {alternate.title} "
            f"(ID {alternate.id})"
        )
        ctx.obj.console.print(
            f"Score: {candidate.score:.1%} · track overlap: {candidate.track_overlap:.1%} · "
            f"quality: {', '.join(quality_tags) or alternate.audioQuality}"
        )
        if candidate.missing_tracks:
            ctx.obj.console.print(
                "[yellow]Missing from candidate:[/] " + ", ".join(candidate.missing_tracks)
            )
        if candidate.extra_tracks:
            ctx.obj.console.print(
                "[yellow]Additional in candidate:[/] " + ", ".join(candidate.extra_tracks)
            )
        if candidate.requires_confirmation:
            ctx.obj.console.print("[yellow]Confirmation would be required before substitution.[/]")
        else:
            ctx.obj.console.print(
                "[green]Track listing matches; safe for a future confirmed substitution.[/]"
            )
    ctx.obj.console.print(
        "\n[dim]Dry run only: no files were downloaded and no settings were changed.[/]"
    )


@info_command.command(name="url", help="Get metadata for Tidal URLs.")
def info_url(
    ctx: Context,
    urls: Annotated[
        list[TidalResource], typer.Argument(parser=TidalResource.from_string)
    ],
):
    """
    Get metadata for Tidal URLs.
    """
    for resource in urls:
        ctx.obj.console.print(
            f"\n[bold cyan]Fetching metadata for {resource.type} {resource.id}...[/]"
        )

        try:
            data = None
            if resource.type == "track":
                data = ctx.obj.api.get_track(resource.id)
            elif resource.type == "album":
                data = ctx.obj.api.get_album(resource.id)
            elif resource.type == "video":
                data = ctx.obj.api.get_video(resource.id)
            elif resource.type == "artist":
                data = ctx.obj.api.get_artist(resource.id)
            elif resource.type == "playlist":
                data = ctx.obj.api.get_playlist(resource.id)
            elif resource.type == "mix":
                ctx.obj.console.print("[yellow]Mix metadata not supported yet (only items).[/]")
                continue

            if data:
                # Convert Pydantic model to dict, then JSON
                # model_dump_json exists in Pydantic v2. For v1 use .json()
                # Let's check pydantic version or just try model_dump_json
                if hasattr(data, "model_dump_json"):
                    json_str = data.model_dump_json(indent=4)
                else:
                    json_str = data.json(indent=4)

                syntax = Syntax(json_str, "json", theme="monokai", word_wrap=True)
                ctx.obj.console.print(syntax)

        except Exception as e:
            ctx.obj.console.print(f"[red]Error fetching metadata:[/] {e}")
