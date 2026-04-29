from __future__ import annotations
import typer
from typing_extensions import Annotated
from rich.console import Console
from rich.table import Table

from tiddl.cli.ctx import Context

search_subcommand = typer.Typer()
console = Console()


@search_subcommand.command(no_args_is_help=True)
def search(
    ctx: Context,
    query: Annotated[str, typer.Argument(help="Search query")],
    limit: Annotated[int, typer.Option("--limit", "-l", min=1, max=50)] = 10,
):
    """
    Search TIDAL for tracks, albums and artists.
    Results show IDs ready to use with: tiddl download url track/ID
    """
    results = ctx.obj.api.get_search(query)

    # Top Hit
    if hasattr(results, "topHit") and results.topHit:
        hit = results.topHit
        hit_type = getattr(hit, "type", "")
        hit_val = getattr(hit, "value", None)
        if hit_val:
            name = getattr(hit_val, "title", None) or getattr(hit_val, "name", "")
            hit_id = getattr(hit_val, "id", "")
            console.print(f"\n[bold yellow]Top Hit:[/] [{hit_type.lower()}] {name} [dim](ID: {hit_id})[/]")
            console.print(f"[dim]  tiddl download url {hit_type.lower()}/{hit_id}[/]\n")

    # Tracks
    if results.tracks and results.tracks.items:
        table = Table(title="Tracks", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=12)
        table.add_column("Title")
        table.add_column("Artist")
        table.add_column("Album")
        table.add_column("Quality", width=10)
        for track in results.tracks.items[:limit]:
            artist = (track.artist.name if track.artist else
                      ", ".join(a.name for a in track.artists) if getattr(track, "artists", None) else "")
            album = track.album.title if track.album else ""
            quality = getattr(track, "audioQuality", "") or ""
            table.add_row(str(track.id), track.title, artist, album, quality)
        console.print(table)
        console.print("[dim]Download: tiddl download url track/{ID}[/]\n")

    # Albums
    if results.albums and results.albums.items:
        table = Table(title="Albums", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="dim", width=12)
        table.add_column("Title")
        table.add_column("Artist")
        table.add_column("Year", width=6)
        table.add_column("Quality", width=10)
        for album in results.albums.items[:limit]:
            artist = (album.artist.name if album.artist else
                      ", ".join(a.name for a in album.artists) if getattr(album, "artists", None) else "")
            year = str(album.releaseDate)[:4] if album.releaseDate else ""
            quality = getattr(album, "audioQuality", "") or ""
            table.add_row(str(album.id), album.title, artist, year, quality)
        console.print(table)
        console.print("[dim]Download: tiddl download url album/{ID}[/]\n")

    # Artists
    if results.artists and results.artists.items:
        table = Table(title="Artists", show_header=True, header_style="bold green")
        table.add_column("ID", style="dim", width=12)
        table.add_column("Name")
        table.add_column("Popularity", width=12)
        for artist in results.artists.items[:limit]:
            pop = str(getattr(artist, "popularity", ""))
            table.add_row(str(artist.id), artist.name, pop)
        console.print(table)
        console.print("[dim]Download: tiddl download url artist/{ID}[/]\n")
