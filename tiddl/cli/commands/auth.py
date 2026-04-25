from __future__ import annotations
import typer
from datetime import datetime
from time import time, sleep
from rich.console import Console

from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data, AuthData
from tiddl.core.auth import AuthAPI, AuthClientError
from tiddl.core.auth.client import get_auth_client_for, TV_CREDENTIALS

from typing_extensions import Annotated

console = Console()

auth_command = typer.Typer(
    name="auth", help="Manage Tidal authentication.", no_args_is_help=True
)


# TODO add context and load auth data from ctx
@auth_command.command(help="Login with your Tidal account.")
def login(
    TV: Annotated[
        bool,
        typer.Option("--tv", help="Use TV device flow (alternative client, works when default is blocked)."),
    ] = False,
):
    loaded_auth_data = load_auth_data()

    if loaded_auth_data.token:
        console.print("[cyan bold]Already logged in.")
        raise typer.Exit()

    from tiddl.core.auth.client import AuthClient
    credentials = TV_CREDENTIALS if TV else None
    auth_api = AuthAPI(client=AuthClient(credentials=credentials))
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
                    client_id=credentials.client_id if credentials else None,
                )
                save_auth_data(auth_data)
                status.console.print("[bold green]Logged in!")
                break

            except AuthClientError as e:
                if e.error == "authorization_pending":
                    time_left = auth_end_at - time()
                    minutes, seconds = time_left // 60, int(time_left % 60)
                    status.update(
                        f"{status_text} time left: {minutes:.0f}:{seconds:02d}"
                    )
                    continue

                if e.error == "expired_token":
                    status.console.print(
                        "\n[bold red]Time for authentication has expired."
                    )
                    break


@auth_command.command(help="Logout and remove token from app.")
def logout():
    loaded_auth_data = load_auth_data()

    if loaded_auth_data.token:
        auth_api = AuthAPI()
        auth_api.logout_token(loaded_auth_data.token)

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

    if loaded_auth_data.refresh_token is None:
        console.print("[bold red]Not logged in.")
        raise typer.Exit()

    if time() < (loaded_auth_data.expires_at - EARLY_EXPIRE_TIME) and not FORCE:
        expiry_time = datetime.fromtimestamp(loaded_auth_data.expires_at)
        remaining = expiry_time - datetime.now()
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        console.print(
            f"[green]Auth token expires in {remaining.days}d {hours}h {minutes}m"
        )
        return

    auth_api = AuthAPI(client=get_auth_client_for(loaded_auth_data.client_id))
    auth_data = auth_api.refresh_token(loaded_auth_data.refresh_token)

    loaded_auth_data.token = auth_data.access_token
    loaded_auth_data.expires_at = auth_data.expires_in + int(time())

    save_auth_data(loaded_auth_data)

    console.print("[bold green]Auth token has been refreshed!")
