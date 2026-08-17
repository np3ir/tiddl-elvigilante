"""End-to-end coverage for `tiddl recover` — the offline recovery CLI over
`tiddl.core.utils.retained_registry` + `tiddl.core.utils.publish`.

Uses Typer's CliRunner against the real `app`, isolated to a tmp_path-backed
APP_PATH (via `TIDDL_PATH`, see `tiddl/cli/const.py`) so nothing here ever
touches the real ~/.tiddl. No TIDAL auth/network is involved anywhere in
this file — that is itself the point of `tiddl recover` being a top-level
command (see cli/commands/recover.py's module docstring).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import tiddl.core.utils.retained_registry as reg
from tiddl.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "APP_PATH", tmp_path / "_app")
    # cli/const.py's APP_PATH is resolved at import time (module-level
    # create_app_path()) and consumed by name in a couple of other modules;
    # recover.py only ever reaches the registry through `reg.*`, so
    # patching the registry module's own APP_PATH (as above) is sufficient
    # for everything this test file exercises.
    return tmp_path / "_app"


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _make_retained(
    tmp_path, reason, *, content=b"\x00" * 5000, track_title="T", create_dest_dir=True
):
    """`create_dest_dir=True` (the default) pre-creates `dest`'s parent
    directory, mirroring what the live download path always does before
    ever staging a download — this is realistic test setup, not a
    convenience shortcut, since [P1, third audit finding #2]
    `publish_verified_file` deliberately no longer creates the destination
    directory itself (see `tiddl/core/utils/publish.py`). Pass
    `create_dest_dir=False` for tests that specifically exercise that
    refusal behavior."""
    staging = tmp_path / f"src-{track_title}.bin"
    staging.write_bytes(content)
    dest = tmp_path / "dest" / f"{track_title}.bin"
    if create_dest_dir:
        dest.parent.mkdir(parents=True, exist_ok=True)
    result = _run(reg.register_retained_file(staging, dest, reason, track_title=track_title))
    assert result.persisted, "test setup expects registration to succeed"
    return result.entry, dest


def test_recover_offline_no_entries_lists_nothing():
    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert "Nothing retained" in result.output


def test_recover_list_shows_ok_entry(tmp_path):
    entry, dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Alpha")
    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert entry.id[:8] in result.output
    assert "publish_pending" in result.output
    assert "Alpha" in result.output


def test_recover_publish_pending_success_removes_entry(tmp_path):
    entry, dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Beta")
    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    assert result.exit_code == 0
    assert dest.exists()
    assert dest.stat().st_size == 5000
    assert reg.read_entries().entries == []


def test_recover_publish_success_but_source_cleanup_fails_is_not_fully_resolved(
    tmp_path, monkeypatch
):
    """[P1, fourth audit finding #3] A publish that succeeds but can't clean
    up the now-redundant local copy afterward (a best-effort delete
    failure) is a "needs a later retry" outcome, not a fully-resolved
    success. An earlier version of `_recover_one_inner` printed a green
    checkmark and returned True for exactly this case regardless — letting
    a single `--publish` or a batch `--all` report success (exit 0) while
    real `cleanup_pending` work was silently left outstanding in the
    registry, with nothing in the exit code telling the caller anything
    still needed attention."""
    import tiddl.core.utils.publish as publishmod

    # Force the cross-volume branch (only that branch can independently
    # fail to delete `source` after a successful publish — the same-volume
    # branch is a single atomic rename with no separate cleanup step) and
    # make the post-publish source deletion fail.
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: False)
    monkeypatch.setattr(publishmod, "_safe_unlink", lambda path: False)

    entry, dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Delta")
    staging_path = Path(entry.staging_path)

    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])

    assert result.exit_code != 0  # not fully resolved -> non-zero
    assert dest.exists() and dest.stat().st_size == 5000  # destination WAS published
    assert staging_path.exists()  # local copy retained (best-effort cleanup failed)

    remaining = reg.read_entries().entries
    assert len(remaining) == 1
    assert remaining[0].reason == reg.RetainReason.CLEANUP_PENDING  # demoted, not dropped

    normalized_output = " ".join(result.output.split())
    assert "published" in normalized_output.lower()
    assert "cleanup" in normalized_output.lower()


def test_recover_publish_pending_destination_dir_missing_is_refused_not_created(tmp_path):
    """[P1, third audit finding #2] `publish_verified_file` must NOT create
    the destination directory — an earlier version tried a single-level
    `mkdir` as a "safe enough" middle ground, but directory depth says
    nothing about whether the expected filesystem (e.g. a NAS share) is
    actually mounted; a missing destination folder could just as easily
    mean an unmounted share as a genuinely-safe-to-recreate reorganized
    library folder. Recovery must refuse and leave everything untouched
    rather than guess. The retained copy must survive this refusal
    (nothing is lost — just not auto-published) so a later retry, once the
    real destination is confirmed available, can still succeed."""
    entry, dest = _make_retained(
        tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Gamma", create_dest_dir=False
    )
    assert not dest.parent.exists()
    quarantined_path = Path(entry.staging_path)

    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])

    # [P2, third audit finding #7] Not fully resolved -> non-zero exit.
    assert result.exit_code != 0
    assert not dest.exists()  # nothing was published...
    # Rich word-wraps output at the detected console width, which varies
    # with how the test runner is invoked and can split a literal phrase
    # like "does not exist" across a line break — normalize whitespace
    # before substring-checking so this isn't flaky across environments.
    normalized_output = " ".join(result.output.split())
    assert "does not exist" in normalized_output  # ...and it says why...
    assert quarantined_path.exists()  # ...and the retained copy is untouched.
    assert len(reg.read_entries().entries) == 1  # still recoverable later


def test_recover_cleanup_pending_destination_matches_deletes_local_copy(tmp_path):
    content = b"\x22" * 3000
    dest = tmp_path / "dest.bin"
    dest.write_bytes(content)
    entry, _ = _make_retained(
        tmp_path, reg.RetainReason.CLEANUP_PENDING, content=content, track_title="Delta"
    )
    # register_retained_file always computes a fresh dest under tmp_path/dest/<title>.bin;
    # override the entry's output_path to point at our pre-existing correct dest.
    reg.update_entry(entry.id, output_path=str(dest))

    quarantined_path = Path(entry.staging_path)
    assert quarantined_path.exists()

    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    assert result.exit_code == 0
    assert "removed the redundant local copy" in result.output
    assert not quarantined_path.exists()  # local copy deleted
    assert dest.read_bytes() == content   # destination untouched/correct
    assert reg.read_entries().entries == []


def test_recover_cleanup_pending_destination_missing_is_promoted_to_publish_pending(tmp_path):
    """[P1] cleanup_pending must never blindly delete the retained copy when
    the destination is missing/invalid — it must promote to publish_pending
    instead and require an explicit publish."""
    entry, dest = _make_retained(tmp_path, reg.RetainReason.CLEANUP_PENDING, track_title="Epsilon")
    assert not dest.exists()  # destination was never actually created in this test

    quarantined_path = Path(entry.staging_path)
    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    # [P2, third audit finding #7] Promoted, not fully resolved -> non-zero.
    assert result.exit_code != 0
    assert "promoted to publish_pending" in result.output
    assert quarantined_path.exists()  # local copy NEVER deleted

    updated = reg.read_entries().entries[0]
    assert updated.reason == reg.RetainReason.PUBLISH_PENDING

    # And a second recovery pass now actually publishes it.
    result2 = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    assert result2.exit_code == 0
    assert dest.exists()
    assert reg.read_entries().entries == []


def test_recover_cleanup_pending_destination_corrupted_is_promoted_not_deleted(tmp_path):
    dest = tmp_path / "dest.bin"
    dest.write_bytes(b"WRONG CONTENT ENTIRELY")
    entry, _ = _make_retained(tmp_path, reg.RetainReason.CLEANUP_PENDING, track_title="Zeta")
    reg.update_entry(entry.id, output_path=str(dest))
    quarantined_path = Path(entry.staging_path)

    result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    # [P2, third audit finding #7] Promoted, not fully resolved -> non-zero.
    assert result.exit_code != 0
    assert "promoted to publish_pending" in result.output
    assert quarantined_path.exists()
    assert dest.read_bytes() == b"WRONG CONTENT ENTIRELY"  # never overwritten by this step


def test_recover_all_without_yes_is_refused(tmp_path):
    _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Eta")
    result = runner.invoke(app, ["recover", "--all"])
    assert result.exit_code != 0
    assert "--yes" in result.output
    # nothing touched:
    assert len(reg.read_entries().entries) == 1


def test_recover_all_with_yes_recovers_every_ok_entry(tmp_path):
    e1, d1 = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Theta1")
    e2, d2 = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Theta2")
    result = runner.invoke(app, ["recover", "--all", "--yes"])
    assert result.exit_code == 0
    assert d1.exists() and d2.exists()
    assert reg.read_entries().entries == []


def test_recover_publish_unknown_id_errors(tmp_path):
    result = runner.invoke(app, ["recover", "--publish", "doesnotexist"])
    assert result.exit_code != 0


def _entry_for_ambiguity(entry_id):
    return reg.RetainedEntry(
        id=entry_id, reason=reg.RetainReason.PUBLISH_PENDING,
        staging_path="/tmp/x", output_path="/tmp/y",
        observed_size=1, observed_hash="a",
    )


def test_recover_publish_ambiguous_prefix_errors(tmp_path):
    reg.add_entry(_entry_for_ambiguity("aaaaaaaa1"))
    reg.add_entry(_entry_for_ambiguity("aaaaaaaa2"))
    result = runner.invoke(app, ["recover", "--publish", "aaaaaaaa"])
    assert result.exit_code != 0


def test_recover_purge_gone_entry(tmp_path):
    reg.add_entry(reg.RetainedEntry(
        id="ghost1", reason=reg.RetainReason.PUBLISH_PENDING,
        staging_path=str(tmp_path / "nope.bin"), output_path=str(tmp_path / "dest.bin"),
        observed_size=1, observed_hash="a",
    ))
    result = runner.invoke(app, ["recover", "--purge", "ghost1"])
    assert result.exit_code == 0
    assert reg.read_entries().entries == []


def test_recover_purge_ok_entry_is_refused(tmp_path):
    """[P2] Purge must never silently discard a still-recoverable entry."""
    entry, _dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Iota")
    result = runner.invoke(app, ["recover", "--purge", entry.id[:8]])
    assert result.exit_code != 0
    assert len(reg.read_entries().entries) == 1  # untouched


def test_recover_purge_already_published_entry_is_refused(tmp_path):
    """[P1, finding #4 follow-through] An 'already_published' entry (a prior
    recovery attempt already succeeded but crashed before updating the
    registry — see test_retained_registry.py's idempotency test) is still
    recoverable via --publish (a no-op registry drop). Purge must refuse it
    the same way it refuses 'ok', not silently allow a second path to the
    same outcome that skips the recoverable-status check."""
    entry, dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Lambda")
    quarantined_path = Path(entry.staging_path)
    # Reproduce the "already_published" on-disk state: destination matches,
    # quarantined copy is gone, registry untouched.
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(quarantined_path.read_bytes())
    quarantined_path.unlink()

    result = runner.invoke(app, ["recover", "--purge", entry.id[:8]])
    assert result.exit_code != 0
    assert len(reg.read_entries().entries) == 1  # untouched


def test_recover_purge_corrupt_entry_deletes_only_files_under_quarantine_root(tmp_path):
    """[P2] Auto-delete on purge is limited to resolved paths beneath the
    quarantine root with the expected naming convention."""
    entry, dest = _make_retained(tmp_path, reg.RetainReason.PUBLISH_PENDING, track_title="Kappa")
    quarantined_path = Path(entry.staging_path)
    quarantined_path.write_bytes(b"tampered, now fails hash check")  # -> corrupt

    result = runner.invoke(app, ["recover", "--purge", entry.id[:8]])
    assert result.exit_code == 0
    assert not quarantined_path.exists()  # safe to delete: under quarantine root, matches <id><ext>
    assert reg.read_entries().entries == []


def test_recover_purge_non_quarantined_fallback_path_is_never_auto_deleted(tmp_path, monkeypatch):
    """[P2] A fallback (non-quarantined) temp path must never be auto-deleted
    by purge — only the registry entry is removed; the file is left for
    manual handling."""
    fallback_file = tmp_path / "somewhere-else.bin"
    fallback_file.write_bytes(b"data")
    reg.add_entry(reg.RetainedEntry(
        id="fallbackid", reason=reg.RetainReason.PUBLISH_PENDING,
        staging_path=str(fallback_file), output_path=str(tmp_path / "dest.bin"),
        observed_size=999, observed_hash="doesnotmatch",  # forces "corrupt" on reconcile
        quarantined=False,
    ))
    result = runner.invoke(app, ["recover", "--purge", "fallbackid"])
    assert result.exit_code == 0
    assert fallback_file.exists()  # never auto-deleted
    assert reg.read_entries().entries == []  # registry entry still removed


def test_recover_shows_orphaned_quarantine_files():
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "orphan.bin").write_bytes(b"x")
    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert "no matching registry entry" in result.output


def test_recover_warns_on_corrupt_registry_but_does_not_crash(tmp_path):
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text("{not json")
    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert "corrupt" in result.output.lower()


def test_recover_warns_on_unreadable_registry_but_does_not_crash(tmp_path, monkeypatch):
    """[P1, third audit finding #1] A registry that can't even be READ
    (distinct from 'corrupt' — see RegistryReadError) must be reported,
    not crash the listing."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text('{"version": 1, "entries": []}')

    real_read_bytes = Path.read_bytes

    def _boom_read_bytes(self, *a, **kw):
        if self == reg.registry_path():
            raise OSError("simulated permission/sharing-violation error")
        return real_read_bytes(self, *a, **kw)

    # [P1, fourth audit finding #1] Patching `read_bytes`, not `read_text` —
    # `read_entries()` now reads raw bytes first, decoding as a separate
    # step (see retained_registry.py), so `read_bytes` is the call that
    # must fail to simulate an actual unreadable-file I/O error here.
    monkeypatch.setattr(Path, "read_bytes", _boom_read_bytes)

    result = runner.invoke(app, ["recover"])
    assert result.exit_code == 0
    assert "could not be read" in result.output.lower()


def test_recover_purge_refuses_on_unreadable_registry_without_crashing(tmp_path, monkeypatch):
    """[P1, third audit finding #1] A mutating command against a registry
    that becomes unreadable partway through (a TOCTOU race: readable when
    `reconcile()` first looked, unreadable by the time the mutation itself
    tries to read-lock-mutate-write it — e.g. another process/permissions
    change in between) must refuse cleanly via `RegistryReadError` caught
    at the CLI layer, not crash with an unhandled traceback, and not
    silently write a fresh registry over whatever's actually on disk.

    The read succeeds for the app's root-callback startup notice AND for
    `reconcile()`'s own read (both needed to reach a purge attempt at all),
    then fails starting on the THIRD read — the one inside `remove_entry`'s
    `_transaction()` — which is exactly the read that must abort instead of
    proceeding to write a fresh registry."""
    reg.add_entry(reg.RetainedEntry(
        id="ghost-purge-test", reason=reg.RetainReason.PUBLISH_PENDING,
        staging_path=str(tmp_path / "nope.bin"), output_path=str(tmp_path / "dest.bin"),
        observed_size=1, observed_hash="a",
    ))
    original = reg.registry_path().read_bytes()

    real_read_bytes = Path.read_bytes
    calls = {"n": 0}

    def _flaky_read_bytes(self, *a, **kw):
        if self == reg.registry_path():
            calls["n"] += 1
            if calls["n"] > 2:
                raise OSError("simulated permission/sharing-violation error")
        return real_read_bytes(self, *a, **kw)

    # [P1, fourth audit finding #1] Patching `read_bytes`, not `read_text` —
    # `read_entries()` now reads raw bytes first (see retained_registry.py),
    # so that's the call that must fail on the 3rd invocation to simulate
    # the registry becoming unreadable partway through this sequence.
    monkeypatch.setattr(Path, "read_bytes", _flaky_read_bytes)

    result = runner.invoke(app, ["recover", "--purge", "ghost-purge-test"])
    assert result.exit_code != 0
    assert "could not be read" in result.output.lower()

    # Read via the builtin open(), not Path.read_bytes() — the latter is
    # still patched above (only the registry_path() call count matters,
    # not this verification read), and this avoids needing an early
    # monkeypatch.undo(), which would also undo this test's autouse
    # APP_PATH-isolation patch (same fixture instance).
    with open(reg.registry_path(), "rb") as f:
        assert f.read() == original  # untouched
