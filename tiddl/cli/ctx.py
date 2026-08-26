from __future__ import annotations
import typer
from time import time
from pathlib import Path

# Top-level (not lazy inside _build_api): a lazy `from filelock import FileLock`
# is invisible to static import analysis, so bundlers that prune unreferenced
# packages (serious_python on macOS, PyInstaller) drop filelock and the app
# dies at download time with "No module named 'filelock'". Import it up here so
# every packager sees the dependency.
from filelock import FileLock
from rich.console import Console

from tiddl.core.api import TidalClientImproved, TidalAPI
from tiddl.core.api.budget import SharedRequestBudget
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
    _hires_api: TidalAPI | None
    _hires_built: bool
    _request_budget: SharedRequestBudget | None
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
        self._hires_api = None
        self._hires_built = False
        self.api_omit_cache = api_omit_cache
        self.debug_path = debug_path
        # ONE shared request budget for THIS run/context: the primary client, the
        # LOSSLESS fallback (HiRes mode) and the secondary HiRes client (per-track
        # `max` ascent in TV mode) all draw from it, so their COMBINED traffic
        # stays within requests_per_minute. Per-context (NOT process-global): a new
        # run starts clean and Cancel/401/429 cleanup just drops the context.
        #
        # Created LAZILY (see the `request_budget` property) so it captures the
        # EFFECTIVE requests_per_minute — the download command applies any `--rpm`
        # CLI override to CONFIG and then calls `configure_request_budget()` BEFORE
        # the first client is built. Building it eagerly here would freeze the
        # pre-override config value and silently ignore `--rpm`.
        self._request_budget = None
        # Which client_id backs the PRIMARY api. True = HiRes (fX2Jxdmnt): 24-bit
        # but a STRICT TIDAL rate limit (429 on big lists). False = TV
        # (4N3n6Q1x95LL5K7p): LOSSLESS 16-bit but lenient. The download command
        # sets this from config `hires_client` + the requested -q. Default True
        # for back-compat (auth/other commands keep using the primary token).
        self.prefer_hires = True

    @property
    def request_budget(self) -> SharedRequestBudget:
        """The ONE shared budget for this run, created on first access from the
        EFFECTIVE requests_per_minute in CONFIG. The download command resolves the
        effective RPM (config + optional `--rpm`) and calls
        `configure_request_budget()` before any client is built, so both clients
        get a budget spaced at the effective rate. Commands that never touch
        `--rpm` simply read the config value here."""
        if self._request_budget is None:
            self._request_budget = SharedRequestBudget(
                CONFIG.download.requests_per_minute
            )
        return self._request_budget

    def configure_request_budget(self, requests_per_minute: int) -> None:
        """(Re)create the shared budget from the EFFECTIVE requests_per_minute.

        Called by the download command AFTER applying any `--rpm` CLI override to
        CONFIG and BEFORE the first client is constructed (clients capture the
        budget object at build time). Recreating — rather than mutating — keeps
        the object immutable once handed to a client, and starts the run's spacing
        clock clean."""
        self._request_budget = SharedRequestBudget(requests_per_minute)

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
            budget=self.request_budget,
        )

        return TidalAPI(client, auth_data.user_id, auth_data.country_code)

    @property
    def api(self) -> TidalAPI:
        if self._api is None:
            if self.prefer_hires:
                # HiRes client (fX2Jxdmnt) — 24-bit, strict rate limit.
                self._api = self._build_api(
                    AUTH_DATA_FILE, "auth_refresh.lock", "api_cache", require=True
                )
            else:
                # TV client (4N3n6Q1x95LL5K7p) — LOSSLESS, lenient rate limit
                # (no 429 on big lists). Falls back to the HiRes token only if
                # the TV token was never set up.
                self._api = self._build_api(
                    AUTH_FALLBACK_FILE, "auth_refresh_fallback.lock",
                    "api_cache_fallback", require=False,
                ) or self._build_api(
                    AUTH_DATA_FILE, "auth_refresh.lock", "api_cache", require=True
                )
        assert self._api is not None
        return self._api

    @property
    def fallback_api(self) -> TidalAPI | None:
        """LOSSLESS re-request client, used only in HiRes mode: the HiRes client
        degrades some lossless-only tracks to 320, and this TV token fixes them.
        In TV-primary mode the primary already yields LOSSLESS, so no fallback."""
        if not self.prefer_hires:
            return None
        if not self._fallback_built:
            self._fallback_built = True
            self._fallback_api = self._build_api(
                AUTH_FALLBACK_FILE, "auth_refresh_fallback.lock", "api_cache_fallback", require=False
            )
        return self._fallback_api

    @property
    def hires_api(self) -> TidalAPI | None:
        """SECONDARY HiRes client for the per-track ``max`` ascent in TV-primary
        mode — an Atmos track whose only FLAC is the 24-bit HI_RES_LOSSLESS tier.

        DISTINCT from ``fallback_api`` (which is the TV client used to fix HiRes
        degradation when HiRes is primary): this is the HiRes client used only for
        the occasional per-track HI_RES_LOSSLESS request while TV backs the run.
        It shares this run's request budget. The caller must NOT touch it when
        ``hires_client='never'`` and does not need it when HiRes is already the
        primary (``max``/``always`` — then ``api`` handles HI_RES_LOSSLESS).
        ``require=False`` so it is ``None`` when no HiRes token exists."""
        if not self._hires_built:
            self._hires_built = True
            self._hires_api = self._build_api(
                AUTH_DATA_FILE, "auth_refresh.lock", "api_cache", require=False
            )
        return self._hires_api


class Context(typer.Context):
    obj: ContextObject
