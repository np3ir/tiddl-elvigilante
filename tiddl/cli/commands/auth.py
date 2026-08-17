from __future__ import annotations
import typer
from datetime import datetime
from pathlib import Path
from time import time, sleep
from rich.console import Console

from requests.exceptions import HTTPError

from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data, AuthData, AUTH_DATA_FILE, AUTH_FALLBACK_FILE
from tiddl.core.auth import AuthAPI, AuthClientError
from tiddl.core.auth.client import get_auth_client_for, TV_CREDENTIALS, AuthClient, CLIENT_ID
from tiddl.cli.commands.web_login import web_login as _web_login, launch_chrome as _launch_chrome

from typing_extensions import Annotated

console = Console()

auth_command = typer.Typer(
    name="auth", help="Manage Tidal authentication.", no_args_is_help=True
)

auth_command.command(name="web-login", help="Captura token desde Chrome (CDP) o Chromium.")(_web_login)
auth_command.command(name="launch-chrome", help="Lanza Chrome con remote debugging para web-login.")(_launch_chrome)


def _device_flow(auth_client: "AuthClient", client_id_to_save: str, target_file: Path, label: str) -> bool:
    """Ejecuta el device flow de TIDAL con un cliente concreto y guarda el token
    en `target_file`. Devuelve True si logueo, False si expiro. Headless salvo el
    navegador que abre una sola vez para aprobar el codigo."""
    auth_api = AuthAPI(client=auth_client)
    device_auth = auth_api.get_device_auth()

    uri = f"https://{device_auth.verificationUriComplete}"
    typer.launch(uri)
    console.print(f"[{label}] Ve a '{uri}' y aprueba el acceso.")

    auth_end_at = time() + device_auth.expiresIn
    status_text = f"[{label}] Authenticating..."
    with console.status(status_text) as status:
        while True:
            sleep(device_auth.interval)
            try:
                auth = auth_api.get_auth(device_auth.deviceCode)
                auth_data = AuthData(
                    token=auth.access_token,
                    refresh_token=auth.refresh_token,
                    expires_at=auth.expires_in + int(time()),
                    user_id=str(auth.user_id),
                    country_code=auth.user.countryCode,
                    client_id=client_id_to_save,
                )
                save_auth_data(auth_data, file=target_file)
                status.console.print(f"[bold green][{label}] Logged in!")
                return True
            except AuthClientError as e:
                if e.error == "authorization_pending":
                    time_left = auth_end_at - time()
                    minutes, seconds = time_left // 60, int(time_left % 60)
                    status.update(f"{status_text} time left: {minutes:.0f}:{seconds:02d}")
                    continue
                if e.error == "expired_token":
                    status.console.print(f"\n[bold red][{label}] Time for authentication has expired.")
                    return False


# TODO add context and load auth data from ctx
@auth_command.command(help="Login hibrido: cliente HiRes (24-bit) + TV (fallback LOSSLESS). Ambos device flow, headless.")
def login():
    primary = load_auth_data()
    fallback = load_auth_data(file=AUTH_FALLBACK_FILE)

    if primary.token and fallback.token:
        console.print("[cyan bold]Ya logueado (hibrido: HiRes + fallback LOSSLESS).")
        raise typer.Exit()

    # 1) Primario: cliente HiRes (fX2JxdmntZWK0ixT) -> 24-bit donde exista.
    if not primary.token:
        console.print("[bold]Paso 1/2 — cliente HiRes (24-bit)[/]")
        _device_flow(AuthClient(), CLIENT_ID, AUTH_DATA_FILE, "HiRes")

    # 2) Fallback: cliente TV -> LOSSLESS 16-bit en los tracks donde el HiRes
    #    degrada a 320. Ambos tokens se auto-refrescan; no hay que re-loguear.
    if not load_auth_data(file=AUTH_FALLBACK_FILE).token:
        console.print("[bold]Paso 2/2 — cliente TV (fallback LOSSLESS)[/]")
        _device_flow(AuthClient(credentials=TV_CREDENTIALS), TV_CREDENTIALS.client_id, AUTH_FALLBACK_FILE, "Fallback")

    console.print("[bold green]Hibrido listo: HiRes 24-bit + fallback LOSSLESS, headless con auto-refresh.")


@auth_command.command(name="login-fallback", help="(Re)configura solo el token fallback TV (LOSSLESS) del modo hibrido.")
def login_fallback():
    _device_flow(AuthClient(credentials=TV_CREDENTIALS), TV_CREDENTIALS.client_id, AUTH_FALLBACK_FILE, "Fallback")


@auth_command.command(name="mobile-login", help="Login with username and password (mobile OAuth, fallback).")
def mobile_login(
    atmos: Annotated[bool, typer.Option("--atmos", help="Use Mobile Atmos client (km8T1xS355y7dd3H).")] = False,
):
    from tiddl.core.auth.client import MobileAuthClient, MOBILE_ATMOS_CLIENT_ID

    loaded_auth_data = load_auth_data()
    if loaded_auth_data.token:
        console.print("[cyan bold]Already logged in. Run 'tiddl auth logout' first.")
        raise typer.Exit()

    username = typer.prompt("TIDAL email")
    password = typer.prompt("Password", hide_input=True)

    client_id = MOBILE_ATMOS_CLIENT_ID if atmos else None
    mobile = MobileAuthClient(client_id=client_id) if client_id else MobileAuthClient()

    with console.status("Authenticating..."):
        try:
            data = mobile.auth(username, password)
        except AuthClientError as e:
            console.print(f"[bold red]Authentication failed: {e.error} — {e.error_description}")
            raise typer.Exit(1)

    auth_data = AuthData(
        token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=data.get("expires_in", 86400) + int(time()),
        user_id=str(data.get("user_id", "")),
        country_code=data.get("country_code", ""),
        client_id=mobile.client_id,
    )
    save_auth_data(auth_data)
    console.print(f"[bold green]Logged in via Mobile OAuth! User: {auth_data.user_id} ({auth_data.country_code})")


@auth_command.command(
    name="import-orpheus",
    help="Import a TIDAL session from an OrpheusDL loginstorage.bin (requires an explicit --path).",
)
def import_orpheus(
    path: Annotated[
        Path,
        typer.Option(
            "--path", "-p",
            help="Path to loginstorage.bin, or the OrpheusDL directory containing config/loginstorage.bin.",
        ),
    ],
    trust_pickle: Annotated[
        bool,
        typer.Option(
            "--trust-pickle",
            help="Fall back to the full (unsafe) pickle loader if the restricted one rejects the file. "
                 "Only for a file you created yourself.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the security confirmation prompt."),
    ] = False,
):
    import pickle
    from tiddl.core.utils.safe_pickle import safe_load

    # Never auto-discover pickle files: the caller must point at one explicitly.
    candidate = path
    if candidate.is_dir():
        candidate = candidate / "config" / "loginstorage.bin"
    if not candidate.is_file():
        console.print(
            f"[bold red]No loginstorage.bin at '{candidate}'. "
            "Pass --path to the file or the OrpheusDL directory."
        )
        raise typer.Exit(1)
    bin_path = candidate.resolve()

    # A pickle file can execute arbitrary code when opened with the stdlib loader.
    # We load it through a restricted unpickler (data types only) and require the
    # user to confirm the source first.
    console.print(
        "[yellow]⚠ Security notice:[/] OrpheusDL session files are Python pickles. "
        "tiddl reads this one with a restricted loader that blocks code execution.\n"
        f"  File: [bold]{bin_path}[/]"
    )
    if not yes and not typer.confirm("Only continue if you trust the origin of this file. Proceed?"):
        raise typer.Exit(1)

    try:
        storage = safe_load(bin_path)
    except pickle.UnpicklingError as e:
        if not trust_pickle:
            console.print(
                f"[bold red]Refused to load '{bin_path}': {e}.[/]\n"
                "The file contains non-data Python objects. If you created it yourself and "
                "fully trust it, re-run with [bold]--trust-pickle[/] to use the full loader."
            )
            raise typer.Exit(1)
        console.print("[yellow]Restricted loader rejected the file; using full pickle as requested (--trust-pickle).")
        try:
            with bin_path.open("rb") as f:
                storage = pickle.load(f)  # nosec B301 - explicit, user-confirmed opt-in
        except Exception as e:
            # The unsafe fallback can still fail (truncated/corrupt file). Fail
            # with a controlled message + exit code instead of a raw traceback.
            console.print(f"[bold red]Full pickle load also failed (file truncated or corrupt): {e}")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[bold red]Failed to read Orpheus session storage: {e}")
        raise typer.Exit(1)

    try:
        sessions = storage["modules"]["tidal"]["sessions"]["default"]["custom_data"]["sessions"]
    except Exception as e:
        console.print(f"[bold red]Unexpected OrpheusDL storage layout: {e}")
        raise typer.Exit(1)

    # Prefer TV session, fallback to MOBILE_DEFAULT
    session = sessions.get("TV") or sessions.get("MOBILE_DEFAULT")
    if not session or not session.get("refresh_token"):
        console.print("[bold red]No valid TIDAL session with refresh_token found in OrpheusDL storage.")
        raise typer.Exit(1)

    refresh_tok: str = session["refresh_token"]
    user_id = str(session.get("user_id", ""))
    country_code = str(session.get("country_code", ""))

    with console.status("Refreshing token with TV credentials..."):
        try:
            client = AuthClient(credentials=TV_CREDENTIALS)
            raw = client.refresh_token(refresh_tok)
            auth_data = AuthData(
                token=raw["access_token"],
                refresh_token=raw.get("refresh_token", refresh_tok),
                expires_at=raw.get("expires_in", 86400) + int(time()),
                user_id=user_id,
                country_code=country_code,
                client_id=TV_CREDENTIALS.client_id,
            )
        except Exception as e:
            console.print(f"[yellow]Refresh failed ({e}), saving with stale access token.")
            auth_data = AuthData(
                token=session.get("access_token", ""),
                refresh_token=refresh_tok,
                expires_at=0,
                user_id=user_id,
                country_code=country_code,
                client_id=TV_CREDENTIALS.client_id,
            )

    save_auth_data(auth_data)
    console.print(f"[bold green]Orpheus session imported! User: {auth_data.user_id} ({auth_data.country_code})")


@auth_command.command(help="Logout and remove token from app.")
def logout():
    # Limpia primario + fallback del modo hibrido.
    for _file in (AUTH_DATA_FILE, AUTH_FALLBACK_FILE):
        ad = load_auth_data(file=_file)
        if ad.token:
            try:
                AuthAPI().logout_token(ad.token)
            except Exception:
                pass  # Token already expired or invalid on TIDAL's side — clear locally anyway
        save_auth_data(AuthData(), file=_file)

    console.print("[bold green]Logged out (primario + fallback)!")


@auth_command.command(help="Refreshes your token in app.")
def refresh(
    FORCE: Annotated[
        bool,
        typer.Option(
            "--force", "-f", help="Refresh token even when it is still valid."
        ),
    ] = False,
    EARLY_EXPIRE_TIME: Annotated[
        int,
        typer.Option(
            "--early-expire",
            "-e",
            help="Time to expire the token earlier",
            metavar="seconds",
        ),
    ] = 0,
):
    loaded_auth_data = load_auth_data()

    if loaded_auth_data.token is None:
        console.print("[bold red]Not logged in.")
        raise typer.Exit()

    # Web-imported token: no refresh_token available, just check expiry
    if loaded_auth_data.refresh_token is None:
        if time() < loaded_auth_data.expires_at:
            expiry_time = datetime.fromtimestamp(loaded_auth_data.expires_at)
            remaining = expiry_time - datetime.now()
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            console.print(
                f"[green]Auth token expires in {remaining.days}d {hours}h {minutes}m [dim](web token, no refresh)[/]"
            )
        else:
            console.print("[yellow]Web token expired. Extract a new one from tidal.com DevTools.")
        return

    if time() < (loaded_auth_data.expires_at - EARLY_EXPIRE_TIME) and not FORCE:
        expiry_time = datetime.fromtimestamp(loaded_auth_data.expires_at)
        remaining = expiry_time - datetime.now()
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        console.print(
            f"[green]Auth token expires in {remaining.days}d {hours}h {minutes}m"
        )
        return

    try:
        auth_api = AuthAPI(client=get_auth_client_for(loaded_auth_data.client_id))
        auth_data = auth_api.refresh_token(loaded_auth_data.refresh_token)
        loaded_auth_data.token = auth_data.access_token
        loaded_auth_data.expires_at = auth_data.expires_in + int(time())
        save_auth_data(loaded_auth_data)
        console.print("[bold green]Auth token has been refreshed!")
    except HTTPError as e:
        if e.response is not None and 400 <= e.response.status_code < 500:
            console.print(
                "[yellow]Token refresh blocked by TIDAL — continuing with current token. "
                "Run [bold]tiddl auth login[/bold] when it expires."
            )
        else:
            raise
