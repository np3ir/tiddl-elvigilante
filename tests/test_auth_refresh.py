"""Token-refresh coverage: the ctx auto-refresh closure, the `auth refresh`
command's 4xx handling, cross-process FileLock serialization, and client
selection. External HTTP is mocked with `responses`.
"""
from __future__ import annotations

import threading
from time import time

import pytest
import responses
from rich.console import Console
from typer.testing import CliRunner

from tiddl.cli.commands.auth import auth_command
from tiddl.cli.ctx import ContextObject
from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data
from tiddl.cli.utils.auth.models import AuthData
from tiddl.core.auth.client import (
    AUTH_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    TV_CREDENTIALS,
    get_auth_client_for,
)

runner = CliRunner()
TOKEN_URL = f"{AUTH_URL}/token"


def _auth_response(
    access_token: str = "new_at", expires_in: int = 86400, refresh_token=None
) -> dict:
    """A minimal but schema-valid TIDAL token/refresh response (AuthResponse)."""
    data = {
        "user": {
            "userId": 1, "email": "u@example.com", "countryCode": "US", "username": "u",
            "channelId": 1, "parentId": 0, "acceptedEULA": True, "created": 0, "updated": 0,
            "accountLinkCreated": True, "emailVerified": True, "newUser": False,
        },
        "scope": "r_usr", "clientName": "TV", "token_type": "Bearer",
        "access_token": access_token, "expires_in": expires_in, "user_id": 1,
    }
    if refresh_token is not None:
        data["refresh_token"] = refresh_token
    return data


def _seed_auth(auth_file, expires_at: int) -> None:
    save_auth_data(
        AuthData(
            token="AT1", refresh_token="RT1", expires_at=expires_at,
            user_id="1", country_code="US", client_id=TV_CREDENTIALS.client_id,
        ),
        file=auth_file,
    )


def _build_expiry_closure(tmp_path, monkeypatch, auth_file, lock="t.lock", cache="t_cache"):
    monkeypatch.setattr("tiddl.cli.ctx.APP_PATH", tmp_path)
    ctx = ContextObject(api_omit_cache=True, debug_path=None, console=Console())
    api = ctx._build_api(auth_file, lock, cache, require=True)
    assert api is not None
    return api.client.on_token_expiry


def test_get_auth_client_for_selects_tv_or_hires():
    tv = get_auth_client_for(TV_CREDENTIALS.client_id)
    assert (tv.client_id, tv.client_secret) == (
        TV_CREDENTIALS.client_id, TV_CREDENTIALS.client_secret
    )

    default = get_auth_client_for(None)
    assert (default.client_id, default.client_secret) == (CLIENT_ID, CLIENT_SECRET)

    unknown = get_auth_client_for("some-other-id")
    assert unknown.client_id == CLIENT_ID  # unknown client_id falls back to the HiRes default


@responses.activate
def test_refresh_updates_token_refresh_and_expiry(tmp_path, monkeypatch):
    responses.add(
        responses.POST, TOKEN_URL,
        json=_auth_response("AT2", expires_in=7200, refresh_token="RT2"), status=200,
    )
    auth_file = tmp_path / "auth.json"
    _seed_auth(auth_file, expires_at=int(time()) - 100)  # expired

    on_expiry = _build_expiry_closure(tmp_path, monkeypatch, auth_file)
    result = on_expiry(force_refresh=True)

    assert result is not None
    access_token, expires_at, refresh_token = result
    assert access_token == "AT2"
    assert refresh_token == "RT2"
    assert expires_at > int(time())

    persisted = load_auth_data(file=auth_file)
    assert persisted.token == "AT2"
    assert persisted.refresh_token == "RT2"
    assert persisted.expires_at > int(time())


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_refresh_command_4xx_preserves_session(status, monkeypatch):
    responses.add(responses.POST, TOKEN_URL, json={"error": "blocked"}, status=status)

    existing = AuthData(
        token="OLD", refresh_token="R", expires_at=int(time()) - 100,
        user_id="1", country_code="US", client_id=TV_CREDENTIALS.client_id,
    )
    monkeypatch.setattr("tiddl.cli.commands.auth.load_auth_data", lambda *a, **k: existing)
    saved: list = []
    monkeypatch.setattr(
        "tiddl.cli.commands.auth.save_auth_data", lambda ad, *a, **k: saved.append(ad)
    )

    result = runner.invoke(auth_command, ["refresh", "--force"])

    assert result.exit_code == 0, result.exception   # 4xx is handled, not a crash
    assert saved == []                               # existing session left intact


@responses.activate
def test_concurrent_refresh_respects_filelock(tmp_path, monkeypatch):
    # Two threads race the same FileLock-guarded closure with an expired token.
    # The lock serializes them; the second re-reads the freshly-saved token under
    # the lock and skips the network -> exactly ONE refresh request, no corruption.
    responses.add(
        responses.POST, TOKEN_URL,
        json=_auth_response("AT2", expires_in=86400, refresh_token="RT2"), status=200,
    )
    auth_file = tmp_path / "auth.json"
    _seed_auth(auth_file, expires_at=int(time()) - 100)

    on_expiry = _build_expiry_closure(tmp_path, monkeypatch, auth_file)

    start = threading.Barrier(2)
    results: list = []
    errors: list = []

    def worker():
        try:
            start.wait()
            results.append(on_expiry())  # force_refresh=False -> honors the double-check
        except BaseException as exc:  # surface any thread failure to the assertions
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "a refresh thread hung"
    assert errors == [], f"refresh thread(s) failed: {errors}"
    assert len(results) == 2

    token_calls = [c for c in responses.calls if c.request.url.rstrip("/") == TOKEN_URL.rstrip("/")]
    assert len(token_calls) == 1, f"expected exactly one refresh, got {len(token_calls)}"
    assert load_auth_data(file=auth_file).token == "AT2"
