from __future__ import annotations
import typer
from rich.syntax import Syntax
from typing_extensions import Annotated

from tiddl.cli.ctx import Context
from tiddl.cli.utils.resource import TidalResource

info_command = typer.Typer(name="info", help="Show metadata for a resource.")


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
        ctx.obj.console.print(f"\n[bold cyan]Fetching metadata for {resource.type} {resource.id}...[/]")

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
