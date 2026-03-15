from __future__ import annotations
import typer
from time import time
from pathlib import Path

from rich.console import Console

from tiddl.core.api import TidalClientImproved, TidalAPI
from tiddl.cli.config import APP_PATH, CONFIG
from tiddl.core.auth import AuthAPI
from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data
from tiddl.cli.utils.resource import TidalResource


class ContextObject:
    console: Console
    resources: list[TidalResource]
    auth_api: AuthAPI
    _api: TidalAPI | None
    api_omit_cache: bool
    debug_path: Path | None

    def __init__(
        self, api_omit_cache: bool, debug_path: Path | None, console: Console
    ) -> None:
        self.console = console
        self.resources = []
        self.auth_api = AuthAPI()
        self._api = None
        self.api_omit_cache = api_omit_cache
        self.debug_path = debug_path

    @property
    def api(self):
        if self._api is not None:
            return self._api

        auth_data = load_auth_data()

        assert auth_data.token, "Auth Token is missing. Use `tiddl auth login`"
        assert auth_data.user_id, "User ID is missing. Use `tiddl auth login`"
        assert auth_data.country_code, "Country Code is missing. Use `tiddl auth login`"

        refresh_token = auth_data.refresh_token
        assert refresh_token, "Refresh Token is missing. Use `tiddl auth login`"

        from filelock import FileLock
        refresh_lock = FileLock(APP_PATH / "auth_refresh.lock")

        def on_token_expiry(force_refresh: bool = False, min_validity: int = 60) -> tuple[str, int, str | None] | None:
            with refresh_lock:
                # Reload auth data to get the latest state (in case another thread/process updated it)
                latest_auth = load_auth_data()
                
                # Check if token is already valid (refreshed by another thread/process)
                # We add a buffer of min_validity seconds (default 60, but caller might want more)
                # Skip check if force_refresh is True
                if not force_refresh and latest_auth.expires_at and latest_auth.expires_at > int(time()) + min_validity:
                    # Update local auth_data reference if needed
                    auth_data.token = latest_auth.token
                    auth_data.refresh_token = latest_auth.refresh_token
                    return latest_auth.token, latest_auth.expires_at, latest_auth.refresh_token

                # Perform refresh
                current_refresh_token = latest_auth.refresh_token
                # Ensure we have a refresh token to use
                if not current_refresh_token:
                     return None
                     
                try:
                    auth_response = self.auth_api.refresh_token(current_refresh_token)
                    
                    latest_auth.token = auth_response.access_token
                    latest_auth.expires_at = auth_response.expires_in + int(time())
                    
                    if auth_response.refresh_token:
                        latest_auth.refresh_token = auth_response.refresh_token
                        
                    save_auth_data(auth_data=latest_auth)
                    
                    # Update closure variable
                    auth_data.token = latest_auth.token
                    auth_data.refresh_token = latest_auth.refresh_token
    
                    return auth_response.access_token, latest_auth.expires_at, latest_auth.refresh_token
                except Exception:
                    # If refresh fails, we can't do much. 
                    # Returning None (or raising) will let the caller handle the 401.
                    raise

        client = TidalClientImproved(
            token=auth_data.token,
            cache_name=APP_PATH / "api_cache",
            omit_cache=self.api_omit_cache,
            debug_path=self.debug_path,
            on_token_expiry=on_token_expiry,
            refresh_token=auth_data.refresh_token,
            token_expiry=auth_data.expires_at,
            requests_per_minute=CONFIG.download.requests_per_minute,
        )

        self._api = TidalAPI(client, auth_data.user_id, auth_data.country_code)

        return self._api


class Context(typer.Context):
    obj: ContextObject
