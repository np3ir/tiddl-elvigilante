"""Regression coverage for `save_auth_data`/`load_auth_data` after extracting
the temp+fsync+replace dance into `tiddl.core.utils.fsio.atomic_write_bytes`
(see tests/test_fsio.py for the generic helper coverage). This file exists to
prove the extraction changed nothing observable about the auth file: still
atomic, still owner-only on POSIX, still leaves no temp litter, still
survives a corrupt/missing file on read.
"""
from __future__ import annotations

import os

import pytest

from tiddl.cli.utils.auth.core import load_auth_data, save_auth_data
from tiddl.cli.utils.auth.models import AuthData


def test_save_then_load_roundtrip(tmp_path):
    f = tmp_path / "auth.json"
    data = AuthData(token="t", refresh_token="r", expires_at=123, user_id="u", country_code="US")
    save_auth_data(data, file=f)
    loaded = load_auth_data(file=f)
    assert loaded == data


def test_load_missing_file_returns_empty_auth_data(tmp_path):
    loaded = load_auth_data(file=tmp_path / "does_not_exist.json")
    assert loaded == AuthData()


def test_load_corrupt_file_returns_empty_auth_data_not_raise(tmp_path):
    f = tmp_path / "auth.json"
    f.write_text("{not valid json")
    loaded = load_auth_data(file=f)
    assert loaded == AuthData()


def test_save_creates_parent_directory(tmp_path):
    f = tmp_path / "nested" / "dir" / "auth.json"
    save_auth_data(AuthData(token="t"), file=f)
    assert f.exists()


def test_save_no_temp_file_left_behind(tmp_path):
    f = tmp_path / "auth.json"
    save_auth_data(AuthData(token="t"), file=f)
    leftovers = [p for p in tmp_path.iterdir() if p != f]
    assert leftovers == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod semantics")
def test_save_applies_owner_only_permissions_on_posix(tmp_path):
    f = tmp_path / "auth.json"
    save_auth_data(AuthData(token="secret-token"), file=f)
    mode = f.stat().st_mode & 0o777
    assert mode == 0o600


def test_save_failure_does_not_corrupt_existing_file(tmp_path, monkeypatch):
    """A crash/failure mid-save must never leave a truncated auth.json — the
    exact regression atomic_write_bytes exists to prevent (see its docstring:
    'which used to wipe the user's session and force a re-login')."""
    f = tmp_path / "auth.json"
    original = AuthData(token="original-token", refresh_token="orig-refresh")
    save_auth_data(original, file=f)

    def boom_replace(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError):
        save_auth_data(AuthData(token="new-token"), file=f)

    # The file on disk must still be the ORIGINAL, fully-formed data.
    reloaded = load_auth_data(file=f)
    assert reloaded == original
    leftovers = [p for p in tmp_path.iterdir() if p != f]
    assert leftovers == []  # temp file cleaned up despite the failure
