from __future__ import annotations
import typer
from time import time
from pathlib import Path

from rich.console import Console

from tiddl.core.api import TidalClientImproved, TidalAPI
from tiddl.cli.config import APP_PATH, CONFIG
from tiddl.core.auth import AuthAPI
from tiddl.core.auth.client import get_auth_client_for
from tiddl.cli.utils.auth.core import (
    load_auth_data,
    save_auth_data,
    AUTH_DATA_FILE,
    AUTH_FALLBACK_FILE,
)
from tiddl.cli.utils.resource import TidalResource


class ContextObject:
    console: Console
    resources: list[TidalResource]
    _api: TidalAPI | None
    _fallback_api: TidalAPI | None
    _fallback_built: bool
    api_omit_cache: bool
    debug_path: Path | None

    def __init__(
        self, api_omit_cache: bool, debug_path: Path | None, console: Console
    ) -> None:
        self.console = console
        self.resources = []
        self._api = None
        self._fallback_api = None
        self._fallback_built = False
        self.api_omit_cache = api_omit_cache
        self.debug_path = debug_path

    def _build_api(
        self, auth_file: Path, lock_name: str, cache_name: str, require: bool
    ) -> TidalAPI | None:
        """Construye un TidalAPI desde un archivo de auth, con auto-refresh que
        guarda de vuelta en ESE archivo. `require=False` devuelve None si no hay
        token (usado por el fallback opcional)."""
        auth_data = load_auth_data(file=auth_file)

        if not auth_data.token or not auth_data.user_id or not auth_data.country_code:
            if require:
                assert auth_data.token, "Auth Token is missing. Use `tiddl auth login`"
                assert auth_data.user_id, "User ID is missing. Use `tiddl auth login`"
                assert auth_data.country_code, "Country Code is missing. Use `tiddl auth login`"
            return None

        auth_api = AuthAPI(client=get_auth_client_for(auth_data.client_id))

        from filelock import FileLock
        refresh_lock = FileLock(APP_PATH / lock_name)

        def on_token_expiry(force_refresh: bool = False, min_validity: int = 60) -> tuple[str, int, str | None] | None:
            with refresh_lock:
                latest_auth = load_auth_data(file=auth_file)

                if not force_refresh and latest_auth.expires_at and latest_auth.expires_at > int(time()) + min_validity:
                    auth_data.token = latest_auth.token
                    auth_data.refresh_token = latest_auth.refresh_token
                    return latest_auth.token, latest_auth.expires_at, latest_auth.refresh_token

                current_refresh_token = latest_auth.refresh_token
                if not current_refresh_token:
                    return None

                auth_response = auth_api.refresh_token(current_refresh_token)
                latest_auth.token = auth_response.access_token
                latest_auth.expires_at = auth_response.expires_in + int(time())
                if auth_response.refresh_token:
                    latest_auth.refresh_token = auth_response.refresh_token

                save_auth_data(auth_data=latest_auth, file=auth_file)
                auth_data.token = latest_auth.token
                auth_data.refresh_token = latest_auth.refresh_token
                return auth_response.access_token, latest_auth.expires_at, latest_auth.refresh_token

        client = TidalClientImproved(
            token=auth_data.token,
            cache_name=APP_PATH / cache_name,
            omit_cache=self.api_omit_cache,
            debug_path=self.debug_path,
            on_token_expiry=on_token_expiry,
            refresh_token=auth_data.refresh_token,
            token_expiry=auth_data.expires_at,
            requests_per_minute=CONFIG.download.requests_per_minute,
        )

        return TidalAPI(client, auth_data.user_id, auth_data.country_code)

    @property
    def api(self) -> TidalAPI:
        if self._api is None:
            self._api = self._build_api(
                AUTH_DATA_FILE, "auth_refresh.lock", "api_cache", require=True
            )
        assert self._api is not None
        return self._api

    @property
    def fallback_api(self) -> TidalAPI | None:
        """Cliente TV (lossless) para el modo hibrido. None si no se configuro
        (`tiddl auth login-fallback`)."""
        if not self._fallback_built:
            self._fallback_built = True
            self._fallback_api = self._build_api(
                AUTH_FALLBACK_FILE, "auth_refresh_fallback.lock", "api_cache_fallback", require=False
            )
        return self._fallback_api


class Context(typer.Context):
    obj: ContextObject
