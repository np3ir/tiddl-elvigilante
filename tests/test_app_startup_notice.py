"""[P2, audit finding #14] Regression coverage for the root callback's
retained-staging startup notice (`tiddl/cli/app.py`).

An earlier version of this code's comment claimed the notice was "safe on
every invocation, including --help" — that claim was never actually tested,
and is false: Click/Typer's `--help` is an eager option that exits during
parameter processing, before the group callback's body (where this notice
lives) ever runs. This file pins the VERIFIED behavior instead of the
previously-unverified claim: the notice fires for an ordinary subcommand
invocation, but not for `--help`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tiddl.core.utils.retained_registry as reg
from tiddl.cli.app import app

runner = CliRunner()


def _write_registry_with_one_entry(app_path):
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "retained_staging.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "abc123",
                        "reason": "publish_pending",
                        "staging_path": "/tmp/x.bin",
                        "output_path": "/tmp/y.bin",
                        "observed_size": 1,
                        "observed_hash": "aa",
                        "hash_algorithm": "sha256",
                        "track_title": "t",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "quarantined": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def _isolated_tiddl_path(tmp_path, monkeypatch):
    # `tiddl.cli.const.APP_PATH` is resolved once at import time and consumed
    # by name in each module that needs it (see test_recover_cli.py's
    # equivalent fixture) — patching the retained_registry module's own copy
    # directly, rather than the TIDDL_PATH env var, is what actually affects
    # `retained_registry.startup_status()` as called from `app.py`'s
    # callback.
    app_path = tmp_path / "_app"
    _write_registry_with_one_entry(app_path)
    monkeypatch.setattr(reg, "APP_PATH", app_path)
    return app_path


def test_startup_notice_appears_on_ordinary_subcommand(_isolated_tiddl_path):
    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert "retained from a previous" in result.output


def test_startup_notice_does_not_appear_on_help(_isolated_tiddl_path):
    """This is the specific claim the audit found unverified/false: --help
    exits eagerly and never reaches the root callback's notice code."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "retained from a previous" not in result.output


def test_startup_notice_warns_on_unreadable_registry(tmp_path, monkeypatch):
    """[P2, fourth audit finding #1] 'unreadable' is MORE serious than
    'corrupt'/'unsupported_version' (any mutating `tiddl recover` command
    refuses outright until it's resolved — see RegistryReadError), but an
    earlier version of the root callback only warned for the two
    less-serious statuses. A user who never proactively runs
    `tiddl recover` would get no signal at all, on any ordinary command,
    that persistence is currently inaccessible. This must warn too — still
    read-only/lightweight, no deep verification, no destination I/O."""
    app_path = tmp_path / "_app"
    app_path.mkdir(parents=True, exist_ok=True)
    registry_path = app_path / "retained_staging.json"
    registry_path.write_text('{"version": 1, "entries": []}', encoding="utf-8")
    monkeypatch.setattr(reg, "APP_PATH", app_path)

    real_read_bytes = Path.read_bytes

    def _boom_read_bytes(self, *a, **kw):
        if self == registry_path:
            raise OSError("simulated permission/sharing-violation error")
        return real_read_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", _boom_read_bytes)

    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    # `tiddl recover`'s own read-only listing ALSO prints a distinct
    # "could not be read" warning for 'unreadable' (see
    # `_print_registry_status_warning` in recover.py) — checking for "for
    # details" alongside it specifically pins the root callback's OWN
    # message (app.py's corrupt/unsupported_version/unreadable branches are
    # the only ones that say "for details"; recover.py's own messages never
    # do), so this genuinely proves the startup notice fired, not just that
    # SOME warning about the registry appeared somewhere in the output.
    normalized_output = " ".join(result.output.split()).lower()
    assert "could not be read" in normalized_output
    assert "for details" in normalized_output
