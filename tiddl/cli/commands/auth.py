from __future__ import annotations
import typer
from datetime import datetime
from pathlib import Path
from time import time, sleep
from typing import Optional
from rich.console import Console

from requests.exceptions import HTTPError

from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data, AuthData
from tiddl.core.auth import AuthAPI, AuthClientError
from tiddl.core.auth.client import get_auth_client_for, TV_CREDENTIALS, AuthClient
from tiddl.cli.commands.web_login import web_login as _web_login, launch_chrome as _launch_chrome

from typing_extensions import Annotated

console = Console()

auth_command = typer.Typer(
    name="auth", help="Manage Tidal authentication.", no_args_is_help=True
)

auth_command.command(name="web-login", help="Captura token desde Chrome (CDP) o Chromium.")(_web_login)
auth_command.command(name="launch-chrome", help="Lanza Chrome con remote debugging para web-login.")(_launch_chrome)


# TODO add context and load auth data from ctx
@auth_command.command(help="Login with your Tidal account via TV device flow.")
def login():
    loaded_auth_data = load_auth_data()

    if loaded_auth_data.token:
        console.print("[cyan bold]Already logged in.")
        raise typer.Exit()

    auth_api = AuthAPI(client=AuthClient(credentials=TV_CREDENTIALS))
    device_auth = auth_api.get_device_auth()

    uri = f"https://{device_auth.verificationUriComplete}"
    typer.launch(uri)

    console.print(f"Go to '{uri}' and complete authentication!")

    auth_end_at = time() + device_auth.expiresIn
    status_text = "Authenticating..."

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
                    client_id=TV_CREDENTIALS.client_id,
                )
                save_auth_data(auth_data)
                status.console.print("[bold green]Logged in!")
                break

            except AuthClientError as e:
                if e.error == "authorization_pending":
                    time_left = auth_end_at - time()
                    minutes, seconds = time_left // 60, int(time_left % 60)
                    status.update(f"{status_text} time left: {minutes:.0f}:{seconds:02d}")
                    continue

                if e.error == "expired_token":
                    status.console.print("\n[bold red]Time for authentication has expired.")
                    break


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


@auth_command.command(name="import-orpheus", help="Import TIDAL session from OrpheusDL loginstorage.bin.")
def import_orpheus(
    path: Annotated[Optional[Path], typer.Option("--path", "-p", help="OrpheusDL directory (default: C:/OrpheusDL).")] = None,
):
    import pickle

    search_dirs = [path, Path("C:/OrpheusDL"), Path.home() / "OrpheusDL"]
    bin_path: Optional[Path] = None
    for d in search_dirs:
        if d:
            candidate = d / "config" / "loginstorage.bin"
            if candidate.exists():
                bin_path = candidate
                break

    if not bin_path:
        console.print("[bold red]Could not find loginstorage.bin. Use --path to specify the OrpheusDL directory.")
        raise typer.Exit(1)

    try:
        with bin_path.open("rb") as f:
            storage = pickle.load(f)
        sessions = storage["modules"]["tidal"]["sessions"]["default"]["custom_data"]["sessions"]
    except Exception as e:
        console.print(f"[bold red]Failed to read Orpheus session storage: {e}")
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
    loaded_auth_data = load_auth_data()

    if loaded_auth_data.token:
        try:
            auth_api = AuthAPI()
            auth_api.logout_token(loaded_auth_data.token)
        except Exception:
            pass  # Token already expired or invalid on TIDAL's side — clear locally anyway

    save_auth_data(AuthData())

    console.print("[bold green]Logged out!")


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
                "Run [bold]tiddl auth login --tv[/bold] when it expires."
            )
        else:
            raise
