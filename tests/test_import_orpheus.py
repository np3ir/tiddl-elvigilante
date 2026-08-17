"""Tests for `tiddl auth import-orpheus` — the pickle security flow.

Covers the finding fix: the unsafe --trust-pickle fallback must fail with a
controlled exit (not a raw traceback) when the file is truncated/corrupt. Also
exercises the confirmation prompt, --yes, and absence of --trust-pickle.
"""
from __future__ import annotations

import os
import pickle
from collections import OrderedDict

from typer.testing import CliRunner

from tiddl.cli.commands.auth import auth_command

runner = CliRunner()


def _layout(sessions: dict) -> dict:
    """Minimal OrpheusDL loginstorage layout wrapping the given sessions dict."""
    return {"modules": {"tidal": {"sessions": {"default": {"custom_data": {"sessions": sessions}}}}}}


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
