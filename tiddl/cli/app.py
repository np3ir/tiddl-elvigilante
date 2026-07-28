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


def _installed_commit() -> str:
    """Short git commit of the installed tiddl-elvigilante (empty if unknown).
    Read from the pip direct_url.json written for git installs; works both for
    the CLI and the flet-bundled GUI (the dist-info ships in the bundle)."""
    try:
        import importlib.metadata as _md
        import json
        raw = _md.distribution("tiddl-elvigilante").read_text("direct_url.json")
        if raw:
            return (json.loads(raw).get("vcs_info") or {}).get("commit_id", "")[:8]
    except Exception:
        pass
    return ""


def version_callback(value: bool):
    if value:
        commit = _installed_commit()
        print("elvigilante-julio-2026" + (f" ({commit})" if commit else ""))
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


def _reorder_download_options(argv: list[str]) -> list[str]:
    """Acepta opciones del grupo `download` escritas después del subcomando.

    Los docs (y el instinto de todo el mundo) escriben
    `tiddl download url --track-quality max <url>`, pero Click exige las
    opciones del grupo ANTES del subcomando. Este shim mueve las opciones
    que pertenecen al grupo download (y no al subcomando) a su posición
    correcta, así ambos órdenes funcionan. Opciones propias del subcomando
    (p.ej. `-t/--types` de fav, `-l/--limit` de search) se quedan donde están.
    """
    from typer.main import get_command

    try:
        root = get_command(app)
        group = root.commands.get("download")
        if group is None:
            return argv
    except Exception:
        return argv

    def option_table(cmd) -> dict[str, bool]:
        """Mapa opción -> toma_valor para todas las opciones de un comando."""
        import click

        table: dict[str, bool] = {}
        for param in cmd.params:
            if isinstance(param, click.Option):
                for name in list(param.opts) + list(param.secondary_opts):
                    table[name] = not param.is_flag
        return table

    group_opts = option_table(group)

    # Localizar el token "download" (las opciones globales del app son flags,
    # así que el primer token que no empieza con "-" es el comando).
    cmd_idx = None
    for i, token in enumerate(argv[1:], start=1):
        if not token.startswith("-"):
            if token == "download":
                cmd_idx = i
            break
    if cmd_idx is None:
        return argv

    # Localizar el subcomando, saltando opciones del grupo y sus valores.
    i = cmd_idx + 1
    while i < len(argv):
        token = argv[i]
        base = token.split("=", 1)[0]
        if base in group_opts:
            i += 2 if (group_opts[base] and "=" not in token) else 1
        elif token.startswith("-"):
            return argv  # opción desconocida: que Click dé su error normal
        else:
            break
        continue
    if i >= len(argv) or argv[i] not in group.commands:
        return argv

    sub_idx = i
    sub_opts = option_table(group.commands[argv[sub_idx]])

    moved: list[str] = []
    stay: list[str] = []
    j = sub_idx + 1
    while j < len(argv):
        token = argv[j]
        if token == "--":
            stay.extend(argv[j:])
            break
        base = token.split("=", 1)[0]
        if base in sub_opts:
            stay.append(token)
            if sub_opts[base] and "=" not in token and j + 1 < len(argv):
                j += 1
                stay.append(argv[j])
        elif base in group_opts:
            moved.append(token)
            if group_opts[base] and "=" not in token and j + 1 < len(argv):
                j += 1
                moved.append(argv[j])
        else:
            stay.append(token)
        j += 1

    if not moved:
        return argv

    return argv[:sub_idx] + moved + [argv[sub_idx]] + stay


def main():
    """Entry point for pip installation."""
    sys.argv = _reorder_download_options(sys.argv)
    app()
