from __future__ import annotations
import sys
import typer
import logging
from rich.console import Console
from rich.logging import RichHandler

# Force UTF-8 output on Windows so Rich's Braille spinners and Unicode
# characters in file paths don't crash with cp1252 UnicodeEncodeError.
# reconfigure() is the safe way; falls back silently if not available
# (e.g. when stdout is already a binary pipe or non-reconfigurable stream).
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from typing_extensions import Annotated

from tiddl.cli.config import APP_PATH, CONFIG
from tiddl.cli.ctx import ContextObject, Context
from tiddl.cli.commands import register_commands
from tiddl.core.utils.ffmpeg import is_ffmpeg_installed as ifs

log = logging.getLogger("tiddl")

app = typer.Typer(name="tiddl", no_args_is_help=True, rich_markup_mode="rich")
register_commands(app)


def version_callback(value: bool):
    if value:
        print("elvigilante-enero-2026")
        raise typer.Exit()


@app.callback()
def callback(
    ctx: Context,
    OMIT_CACHE: Annotated[
        bool,
        typer.Option(
            "--omit-cache",
        ),
    ] = not CONFIG.enable_cache,
    DEBUG: Annotated[
        bool,
        typer.Option(
            "--debug",
        ),
    ] = CONFIG.debug,
    VERSION: Annotated[
        bool,
        typer.Option(
            "--version",
            "-v",
            callback=version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
):
    """
    tiddl - download tidal tracks \u266b

    [link=https://github.com/oskvr37/tiddl]github[/link]
    [link=https://buymeacoffee.com/oskvr][yellow]buy me a coffee[/link] \u2764
    """
    
    # force_terminal=True + legacy_windows=False: force ANSI renderer and
    # disable the legacy Windows renderer which encodes via cp1252 and crashes
    # on any non-latin character in paths (e.g. ／ U+FF0F in album names).
    console = Console(force_terminal=True, legacy_windows=False)
    
    # Configure logging with RichHandler to ensure messages appear above progress bars
    log_level = logging.DEBUG if DEBUG else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, markup=True, show_path=DEBUG, level=log_level)]
    )

    log.debug(f"{ctx.params=}")

    is_ffmpeg_installed = ifs()
    log.debug(f"{is_ffmpeg_installed=}")

    if DEBUG:
        debug_path = APP_PATH / "api_debug"
    else:
        debug_path = None

    ctx.obj = ContextObject(
        api_omit_cache=OMIT_CACHE, console=console, debug_path=debug_path
    )

    if not is_ffmpeg_installed:
        ctx.obj.console.print(
            "[yellow]WARNING ffmpeg is not installed, tiddl might not work properly, "
            + "[link=https://github.com/oskvr37/tiddl/blob/main/README.md#installation]read README.md[/]"
        )


def main():
    """Entry point for pip installation."""
    app()
