from __future__ import annotations
import importlib.metadata
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


def _installed_version() -> str:
    """Return the installed distribution version, or a stable fallback.

    ``importlib.metadata`` reads the same package metadata used by pip, wheels,
    and bundled applications, so the CLI cannot drift from ``pyproject.toml``.
    """
    try:
        return importlib.metadata.version("tiddl-elvigilante")
    except Exception:
        # --version must remain available even if installed metadata is missing
        # or malformed; it is also a primary troubleshooting command.
        return "unknown"


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


def _commit_datetime(commit: str) -> str:
    """When the commit was pushed, via the GitHub API (local time). Empty if
    offline / not found. Only called on `--version`, with a short timeout."""
    if not commit:
        return ""
    try:
        import urllib.request
        import json
        from datetime import datetime, timezone
        req = urllib.request.Request(
            f"https://api.github.com/repos/np3ir/tiddl-elvigilante/commits/{commit}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "tiddl"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.load(resp)
        iso = data["commit"]["committer"]["date"]  # e.g. 2026-07-28T08:00:00Z
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def version_callback(value: bool):
    if value:
        version = _installed_version()
        commit = _installed_commit()
        out = f"tiddl-elvigilante {version}"
        if commit:
            when = _commit_datetime(commit)
            out += f" ({commit}" + (f", {when}" if when else "") + ")"
        print(out)
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

    # Lightweight, read-only: registry status + entry count only, no hashing,
    # no destination I/O. Deep verification and any recovery only happen via
    # the explicit `tiddl recover` command. See
    # tiddl.core.utils.retained_registry.
    #
    # [P2, finding #14] Verified (not just claimed) via a CliRunner check:
    # this notice runs for ordinary subcommand invocations (e.g. `tiddl
    # recover`, `tiddl auth`), but NOT for `--help` — Click/Typer treats
    # `--help` as an eager option that prints help and exits during
    # parameter processing, before this group callback's body ever runs. An
    # earlier version of this comment claimed "safe on every invocation
    # including --help", which was never actually tested and is false.
    try:
        from tiddl.core.utils import retained_registry
        _retained_status = retained_registry.startup_status()
        if _retained_status.count:
            console.print(
                f"[yellow]{_retained_status.count} file(s) retained from a previous "
                "session's incomplete publish — run [bold]tiddl recover[/] to review.[/]"
            )
        elif _retained_status.status in ("corrupt", "unsupported_version"):
            console.print(
                f"[yellow]The retained-staging registry is {_retained_status.status} — "
                "run [bold]tiddl recover[/] for details.[/]"
            )
        elif _retained_status.status == "unreadable":
            # [P2, fourth audit finding #1] 'unreadable' is MORE serious
            # than 'corrupt'/'unsupported_version' (see
            # retained_registry.RegistryStatus's docstring: any mutating
            # `tiddl recover` command will refuse outright until this is
            # resolved), but an earlier version of this callback only
            # warned for the two less-serious statuses — a user who never
            # proactively runs `tiddl recover` would get no signal at all
            # that persistence is currently inaccessible. This stays
            # read-only/lightweight, same as the branches above: no deep
            # verification, no destination I/O, just surfacing what
            # `startup_status()` (itself lightweight) already found.
            console.print(
                "[red]The retained-staging registry could not be read — run "
                "[bold]tiddl recover[/] for details.[/]"
            )
    except Exception as e:
        log.debug(f"Skipping retained-staging startup notice: {e}")

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
