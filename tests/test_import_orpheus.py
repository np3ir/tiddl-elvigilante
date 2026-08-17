"""Tests for `tiddl auth import-orpheus` — the pickle security flow.

Covers the finding fix: the unsafe --trust-pickle fallback must fail with a
controlled exit (not a raw traceback) when the file is truncated/corrupt. Also
exercises the confirmation prompt, --yes, and absence of --trust-pickle.
"""
from __future__ import annotations

import os
import pickle
from collections import OrderedDict

import responses
from typer.testing import CliRunner

from tiddl.cli.commands.auth import auth_command
from tiddl.core.auth.client import AUTH_URL, TV_CREDENTIALS

runner = CliRunner()

TOKEN_URL = f"{AUTH_URL}/token"


def _layout(sessions: dict) -> dict:
    """Minimal OrpheusDL loginstorage layout wrapping the given sessions dict."""
    return {
        "modules": {"tidal": {"sessions": {"default": {"custom_data": {"sessions": sessions}}}}}
    }


def _write_pickle(path, obj) -> None:
    path.write_bytes(pickle.dumps(obj))


def _controlled(result) -> bool:
    """A controlled failure exits 1 without leaking a non-SystemExit exception
    (i.e. no unhandled traceback reached the user)."""
    exc = result.exception
    return result.exit_code == 1 and (exc is None or isinstance(exc, SystemExit))


def test_global_pickle_rejected_without_trust(tmp_path):
    # A pickle that references a GLOBAL (os.system) is refused by the restricted
    # loader; without --trust-pickle that must be a controlled refusal.
    p = tmp_path / "loginstorage.bin"
    p.write_bytes(pickle.dumps(os.system))
    result = runner.invoke(auth_command, ["import-orpheus", "--path", str(p), "--yes"])
    assert _controlled(result), f"leaked: {result.exception!r}"


def test_corrupt_file_with_trust_pickle_is_controlled(tmp_path):
    # THE finding: the restricted loader hits the GLOBAL and raises
    # UnpicklingError (entering the --trust-pickle branch), then the full loader
    # fails on the truncation. It must exit cleanly, not raise EOFError.
    p = tmp_path / "loginstorage.bin"
    p.write_bytes(pickle.dumps(os.system)[:-1])  # drop STOP -> full pickle.load raises
    result = runner.invoke(
        auth_command, ["import-orpheus", "--path", str(p), "--trust-pickle", "--yes"]
    )
    assert _controlled(result), f"leaked: {result.exception!r}"


def test_valid_with_trust_pickle_loads_then_handles_missing_session(tmp_path):
    # OrderedDict is a GLOBAL -> restricted loader refuses, full pickle loads it.
    # With no refresh_token the command reaches a controlled "no valid session"
    # exit — proving the trust-pickle load succeeded and flowed into normal logic.
    p = tmp_path / "loginstorage.bin"
    p.write_bytes(pickle.dumps(OrderedDict(_layout({"TV": {"access_token": "x"}}))))
    result = runner.invoke(
        auth_command, ["import-orpheus", "--path", str(p), "--trust-pickle", "--yes"]
    )
    assert _controlled(result), f"leaked: {result.exception!r}"


def test_confirmation_declined_aborts(tmp_path):
    # Plain-data file (restricted loader would accept it), but the confirmation
    # prompt is declined -> abort before doing anything.
    p = tmp_path / "loginstorage.bin"
    p.write_bytes(pickle.dumps(_layout({"TV": {"access_token": "x"}})))
    result = runner.invoke(auth_command, ["import-orpheus", "--path", str(p)], input="n\n")
    assert _controlled(result), f"leaked: {result.exception!r}"


def test_missing_file_is_controlled(tmp_path):
    result = runner.invoke(
        auth_command, ["import-orpheus", "--path", str(tmp_path / "nope.bin"), "--yes"]
    )
    assert _controlled(result), f"leaked: {result.exception!r}"


@responses.activate
def test_import_success_refreshes_and_persists(tmp_path, monkeypatch):
    # Full happy path: valid OrpheusDL TV session -> TV-credential refresh (mocked)
    # -> AuthData persisted with the refreshed token + imported identity.
    responses.add(
        responses.POST, TOKEN_URL,
        json={"access_token": "new_at", "expires_in": 3600, "refresh_token": "new_rt"},
        status=200,
    )
    saved: list = []
    monkeypatch.setattr(
        "tiddl.cli.commands.auth.save_auth_data", lambda ad, *a, **k: saved.append(ad)
    )

    p = tmp_path / "loginstorage.bin"
    _write_pickle(p, _layout({"TV": {"refresh_token": "r0", "user_id": 42, "country_code": "US"}}))

    result = runner.invoke(auth_command, ["import-orpheus", "--path", str(p), "--yes"])
    assert result.exit_code == 0, result.exception
    assert len(saved) == 1
    ad = saved[0]
    assert ad.token == "new_at"
    assert ad.refresh_token == "new_rt"
    assert ad.user_id == "42"
    assert ad.country_code == "US"
    assert ad.client_id == TV_CREDENTIALS.client_id


def test_import_invalid_layout_is_controlled(tmp_path):
    # Loads fine (plain dict), but the OrpheusDL structure is missing -> controlled exit.
    p = tmp_path / "loginstorage.bin"
    _write_pickle(p, {"not": "an orpheus storage"})
    result = runner.invoke(auth_command, ["import-orpheus", "--path", str(p), "--yes"])
    assert _controlled(result), f"leaked: {result.exception!r}"


@responses.activate
def test_import_path_as_directory_resolves_bin(tmp_path, monkeypatch):
    # --path may be the OrpheusDL directory; the command resolves
    # <dir>/config/loginstorage.bin. A successful persist proves resolution worked.
    responses.add(
        responses.POST, TOKEN_URL,
        json={"access_token": "at", "expires_in": 3600}, status=200,
    )
    saved: list = []
    monkeypatch.setattr(
        "tiddl.cli.commands.auth.save_auth_data", lambda ad, *a, **k: saved.append(ad)
    )

    cfg = tmp_path / "config"
    cfg.mkdir()
    _write_pickle(
        cfg / "loginstorage.bin",
        _layout({"TV": {"refresh_token": "r0", "user_id": 7, "country_code": "PR"}}),
    )

    result = runner.invoke(auth_command, ["import-orpheus", "--path", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.exception
    assert len(saved) == 1 and saved[0].user_id == "7"  # dir -> config/loginstorage.bin resolved
