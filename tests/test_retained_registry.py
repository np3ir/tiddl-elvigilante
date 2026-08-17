"""Coverage for `tiddl.core.utils.retained_registry` — persistent recovery of
`task.retained_staging` across app restarts.

Each test here is written to pin one specific finding from the audit review
of `PROPOSAL_retained_staging_recovery.md` (kept local/untracked, not part of
this diff) — see the test names and docstrings for the mapping. This module
has no dependency on Downloader/TIDAL, matching the design goal that
`tiddl recover` works fully offline.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from filelock import FileLock

import tiddl.core.utils.retained_registry as reg
from tiddl.core.utils.retained_registry import (
    RegistryLockTimeout,
    RegistryReadError,
    RetainedEntry,
    RetainReason,
)


@pytest.fixture(autouse=True)
def _isolated_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "APP_PATH", tmp_path / "_app")
    return tmp_path / "_app"


def _entry(**overrides) -> RetainedEntry:
    defaults = dict(
        id="abc123",
        reason=RetainReason.PUBLISH_PENDING,
        staging_path="/tmp/x.bin",
        output_path="/mnt/nas/x.bin",
        observed_size=100,
        observed_hash="deadbeef",
    )
    defaults.update(overrides)
    return RetainedEntry(**defaults)


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


def test_missing_registry_reads_as_missing_with_no_entries():
    result = reg.read_entries()
    assert result.status == "missing"
    assert result.entries == []


def test_add_then_read_round_trip():
    e = _entry()
    reg.add_entry(e)
    result = reg.read_entries()
    assert result.status == "valid"
    assert len(result.entries) == 1
    assert result.entries[0] == e


def test_add_multiple_preserves_all():
    reg.add_entry(_entry(id="a"))
    reg.add_entry(_entry(id="b"))
    reg.add_entry(_entry(id="c"))
    ids = {e.id for e in reg.read_entries().entries}
    assert ids == {"a", "b", "c"}


def test_remove_entry_by_id():
    reg.add_entry(_entry(id="a"))
    reg.add_entry(_entry(id="b"))
    removed = reg.remove_entry("a")
    assert removed is True
    ids = {e.id for e in reg.read_entries().entries}
    assert ids == {"b"}


def test_remove_nonexistent_entry_returns_false():
    reg.add_entry(_entry(id="a"))
    assert reg.remove_entry("does-not-exist") is False
    assert len(reg.read_entries().entries) == 1


def test_update_entry_changes_fields_and_persists():
    reg.add_entry(_entry(id="a", reason=RetainReason.PUBLISH_PENDING))
    updated = reg.update_entry("a", reason=RetainReason.CLEANUP_PENDING, staging_path="/new/path")
    assert updated.reason == RetainReason.CLEANUP_PENDING
    reread = reg.read_entries().entries[0]
    assert reread.reason == RetainReason.CLEANUP_PENDING
    assert reread.staging_path == "/new/path"


def test_registry_file_is_valid_json_with_version():
    reg.add_entry(_entry())
    raw = json.loads(reg.registry_path().read_text())
    assert raw["version"] == reg.REGISTRY_VERSION
    assert isinstance(raw["entries"], list)


# ---------------------------------------------------------------------------
# [P2, third audit finding #5] hash_algorithm schema validation: only
# fixed-length algorithms that `_hash_and_size`'s no-argument
# `hexdigest()` actually works with are accepted.
# ---------------------------------------------------------------------------


def test_entry_with_unsupported_hash_algorithm_makes_registry_corrupt():
    """`shake_128`/`shake_256` are real, valid `hashlib` algorithm names —
    `hashlib.algorithms_available` would have accepted them — but they
    require a `length` argument to `hexdigest()`, which `_hash_and_size`
    never supplies, so hashing one raises `TypeError` the moment it's
    actually used. Registry version 1 only ever writes `sha256`; a
    hand-edited or foreign-tool-written entry claiming a variable-length
    algorithm must be rejected at schema-validation time, not discovered
    via a crash the first time something tries to reconcile it."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text(json.dumps({
        "version": 1,
        "entries": [{
            "id": "abc123", "reason": "publish_pending",
            "staging_path": "/tmp/x.bin", "output_path": "/tmp/y.bin",
            "observed_size": 1, "observed_hash": "aa",
            "hash_algorithm": "shake_128",
            "created_at": "2026-01-01T00:00:00+00:00", "quarantined": True,
        }],
    }))
    result = reg.read_entries()
    assert result.status == "corrupt"
    assert result.entries == []


def test_entry_with_supported_hash_algorithm_parses_fine():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text(json.dumps({
        "version": 1,
        "entries": [{
            "id": "abc123", "reason": "publish_pending",
            "staging_path": "/tmp/x.bin", "output_path": "/tmp/y.bin",
            "observed_size": 1, "observed_hash": "aa",
            "hash_algorithm": "sha256",
            "created_at": "2026-01-01T00:00:00+00:00", "quarantined": True,
        }],
    }))
    result = reg.read_entries()
    assert result.status == "valid"
    assert len(result.entries) == 1
    assert result.entries[0].hash_algorithm == "sha256"


# ---------------------------------------------------------------------------
# [P1] Corrupt / unsupported-version registries must be preserved, not
# silently overwritten as if they were empty.
# ---------------------------------------------------------------------------


def test_corrupt_registry_is_read_as_corrupt_not_missing():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text("{not valid json at all")
    result = reg.read_entries()
    assert result.status == "corrupt"
    assert result.entries == []


def test_reading_corrupt_registry_does_not_overwrite_it():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    original = "{not valid json at all"
    reg.registry_path().write_text(original)
    reg.read_entries()  # read-only: must never write
    assert reg.registry_path().read_text() == original


def test_mutation_on_corrupt_registry_preserves_a_backup_before_overwriting():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    original = "{not valid json at all"
    reg.registry_path().write_text(original)

    reg.add_entry(_entry(id="a"))  # mutation must not silently destroy `original`

    backups = list(reg.registry_path().parent.glob("retained_staging.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    # And the mutation itself succeeded on a fresh registry.
    assert [e.id for e in reg.read_entries().entries] == ["a"]


def test_mutation_on_corrupt_registry_aborts_if_backup_write_lies_about_success(monkeypatch):
    """[P2, third audit finding #9] The backup write is not trusted just
    because it didn't raise — it's read back and compared byte-for-byte
    against what should have been written. A write that silently corrupts
    (e.g. a flaky filesystem that reports success but truncates/garbles the
    content) must still abort the mutation rather than proceed to overwrite
    the original corrupt registry believing a good backup now exists."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    original = "{not valid json at all"
    reg.registry_path().write_text(original)

    def _lying_atomic_write_bytes(path, data, **kwargs):
        # Writes something OTHER than what was asked for, but doesn't
        # raise — simulating a filesystem that reports success while
        # silently corrupting the write.
        path.write_bytes(b"corrupted-on-write")

    monkeypatch.setattr(reg, "atomic_write_bytes", _lying_atomic_write_bytes)

    with pytest.raises(reg.RegistryPreservationError):
        reg.add_entry(_entry(id="should-not-be-added"))

    # The ORIGINAL corrupt registry must still be exactly as it was — the
    # mutation must never have reached _write_entries().
    assert reg.registry_path().read_text() == original


def test_unsupported_future_version_is_read_as_unsupported_not_missing():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text(json.dumps({"version": 999, "entries": []}))
    result = reg.read_entries()
    assert result.status == "unsupported_version"
    assert result.entries == []


def test_mutation_on_unsupported_version_preserves_a_backup_before_overwriting():
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    future_payload = json.dumps({"version": 999, "entries": [{"future": "schema"}]})
    reg.registry_path().write_text(future_payload)

    reg.add_entry(_entry(id="a"))

    backups = list(
        reg.registry_path().parent.glob("retained_staging.json.unsupported_version-*.bak")
    )
    assert len(backups) == 1
    assert backups[0].read_text() == future_payload


def test_registry_unreadable_due_to_io_error_is_reported_distinctly_from_corrupt(monkeypatch):
    """[P1, third audit finding #1] A read that fails with an OSError
    (permissions, a sharing violation, a transient network-share hiccup)
    must be distinguished from 'corrupt' (content that WAS read but is
    invalid) — there's no raw_bytes to back up and no way to know the file
    still holds what it held a moment ago."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    reg.registry_path().write_text('{"version": 1, "entries": []}')

    real_read_bytes = Path.read_bytes

    def _boom_read_bytes(self, *a, **kw):
        if self == reg.registry_path():
            raise OSError("simulated permission/sharing-violation error")
        return real_read_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", _boom_read_bytes)
    result = reg.read_entries()
    assert result.status == "unreadable"
    assert result.entries == []
    assert result.raw_bytes is None


def test_registry_with_invalid_utf8_is_reported_as_corrupt_not_crashed(monkeypatch):
    """[P1, fourth audit finding #1] A registry file containing bytes that
    are not valid UTF-8 must be reported as 'corrupt' (the bytes WERE read
    successfully; they just aren't valid text — the same category as
    invalid JSON), not raise an uncaught `UnicodeDecodeError` straight out
    of `read_entries()`. An earlier version called
    `Path.read_text(encoding="utf-8")` directly, which let the decode
    failure propagate past every one of the controlled status checks this
    module promises to make (missing/corrupt/unsupported_version/
    unreadable) and crash every caller, including `tiddl recover`, with a
    raw traceback."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    invalid_utf8 = b"\xff\xfe not valid utf-8 at all"
    reg.registry_path().write_bytes(invalid_utf8)

    result = reg.read_entries()

    assert result.status == "corrupt"
    assert result.entries == []
    assert result.raw_bytes == invalid_utf8


def test_mutation_on_invalid_utf8_registry_preserves_exact_original_bytes():
    """[P1, fourth audit finding #1] A mutation against an invalid-UTF-8
    registry must back it up byte-for-byte before writing a fresh one —
    proving the fix doesn't just avoid crashing, but actually preserves the
    original unreadable-as-text content losslessly (no decode/re-encode
    round trip, which would be impossible for bytes that aren't valid UTF-8
    in the first place)."""
    reg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    invalid_utf8 = b"\xff\xfe garbage \x00\x01"
    reg.registry_path().write_bytes(invalid_utf8)

    reg.add_entry(_entry(id="a"))  # mutation must not silently destroy the original

    backups = list(reg.registry_path().parent.glob("retained_staging.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == invalid_utf8
    # And the mutation itself succeeded on a fresh registry.
    assert [e.id for e in reg.read_entries().entries] == ["a"]


def test_mutation_refuses_when_registry_cannot_be_read_not_just_when_corrupt(monkeypatch):
    """[P1, third audit finding #1] The prior fail-closed fix
    (`RegistryPreservationError`) only covered corrupt/unsupported-version
    registries whose content WAS successfully read. A registry that could
    not be read at all must ALSO refuse to mutate — not fall through to
    `_preserve_unreadable` (which no-ops when `raw_bytes is None`) and then
    silently write a fresh, effectively empty registry over whatever is
    actually on disk. This proves the original bytes on disk are completely
    untouched by a mutation attempt, using a targeted patch of `Path.read_bytes`
    that leaves `os.replace` (and every other path) working normally — so if
    the mutation DID silently succeed by writing a fresh registry, this test
    would catch it via the byte-for-byte comparison below, not just via the
    exception type."""
    reg.add_entry(_entry(id="pre-existing"))
    original_bytes = reg.registry_path().read_bytes()

    real_read_bytes = Path.read_bytes

    def _boom_read_bytes(self, *a, **kw):
        if self == reg.registry_path():
            raise OSError("simulated permission/sharing-violation error")
        return real_read_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", _boom_read_bytes)

    with pytest.raises(RegistryReadError):
        reg.add_entry(_entry(id="should-not-be-added"))

    # NOTE: patching `Path.read_bytes` (not `read_text`) since `read_entries()`
    # now reads bytes first and decodes as a separate step (see the fourth
    # audit finding #1 fix) — this is the call that must actually fail to
    # exercise the mutation-refuses path. The read-back below deliberately
    # uses the builtin `open()`, not `Path.read_bytes()` — the patch above
    # is still active at this point in the test, so going through
    # `Path.read_bytes()` here would hit the same simulated failure. This
    # avoids needing an early `monkeypatch.undo()`, which would also undo
    # this test's autouse APP_PATH-isolation patch since both share the
    # same `monkeypatch` fixture instance.
    with open(reg.registry_path(), "rb") as f:
        assert f.read() == original_bytes


# ---------------------------------------------------------------------------
# [P1] Lock the complete registry transaction, not individual load/save
# calls — two concurrent writers must both survive, not lose an update.
# ---------------------------------------------------------------------------


def test_two_concurrent_add_operations_both_survive():
    """Two threads each running the full add_entry() transaction concurrently
    must both end up in the registry — proves the lock guards the WHOLE
    read -> mutate -> write sequence, not just the final write (which would
    let both threads read the same empty snapshot and clobber each other)."""
    barrier = threading.Barrier(2)

    def worker(entry_id):
        barrier.wait()
        reg.add_entry(_entry(id=entry_id))

    t1 = threading.Thread(target=worker, args=("first",))
    t2 = threading.Thread(target=worker, args=("second",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    ids = {e.id for e in reg.read_entries().entries}
    assert ids == {"first", "second"}


def test_lock_timeout_raises_and_leaves_registry_untouched(monkeypatch):
    """[P2] A synchronous FileLock wait must have a finite timeout; on
    timeout the registry file itself is left exactly as it was (best-effort:
    the caller's current-run in-memory state is unaffected either way)."""
    monkeypatch.setattr(reg, "DEFAULT_LOCK_TIMEOUT", 0.3)
    reg.add_entry(_entry(id="pre-existing"))
    before = reg.registry_path().read_text()

    held = threading.Event()
    release = threading.Event()

    def hold_lock():
        lock = FileLock(str(reg._lock_path()))
        with lock:
            held.set()
            # Held well past the 0.3s transaction timeout below, so the
            # timeout below is deterministic rather than a race.
            release.wait(timeout=10)

    t = threading.Thread(target=hold_lock)
    t.start()
    assert held.wait(timeout=5)

    try:
        with pytest.raises(RegistryLockTimeout):
            reg.add_entry(_entry(id="should-not-be-added"))
    finally:
        release.set()
        t.join(timeout=10)

    assert reg.registry_path().read_text() == before
    assert [e.id for e in reg.read_entries().entries] == ["pre-existing"]


def test_lock_timeout_is_configurable_and_does_not_hang_forever(monkeypatch):
    held = threading.Event()
    release = threading.Event()

    def hold_lock():
        lock = FileLock(str(reg._lock_path()))
        with lock:
            held.set()
            release.wait(timeout=10)

    t = threading.Thread(target=hold_lock)
    t.start()
    assert held.wait(timeout=5)

    start = time.monotonic()
    try:
        with pytest.raises(RegistryLockTimeout):
            with reg._transaction(timeout=0.3):
                pass  # pragma: no cover - should never enter, lock is held
        elapsed = time.monotonic() - start
        assert elapsed < 5  # bounded, not an indefinite hang
    finally:
        release.set()
        t.join(timeout=10)


# ---------------------------------------------------------------------------
# Quarantine relocation + orphan detection.
# ---------------------------------------------------------------------------


def test_quarantine_file_preserves_output_extension_not_part_suffix(tmp_path):
    """[P2] The quarantine filename must derive its extension from the
    intended output (e.g. `.flac`), not from staging's own `.part.<random>`
    suffix — otherwise downstream magic/container checks that branch on
    filename extension would silently stop working on a recovered file."""
    staging = tmp_path / "tiddl-abc123.flac.part.9f8e7d6c"
    staging.write_bytes(b"fake flac bytes")

    final_path, quarantined = reg.quarantine_file(
        staging, output_suffix=".flac", entry_id="myid"
    )
    assert quarantined is True
    assert final_path.name == "myid.flac"
    assert final_path.suffix == ".flac"
    assert final_path.read_bytes() == b"fake flac bytes"
    assert not staging.exists()  # moved, not copied-and-left


@pytest.mark.parametrize("suffix", [".flac", ".m4a", ".mp4", ".mp3"])
def test_quarantine_file_preserves_various_output_extensions(tmp_path, suffix):
    staging = tmp_path / f"tiddl-xyz{suffix}.part.aaaaaaaa"
    staging.write_bytes(b"data")
    final_path, quarantined = reg.quarantine_file(
        staging, output_suffix=suffix, entry_id="eid"
    )
    assert quarantined is True
    assert final_path.suffix == suffix


def test_quarantine_file_degrades_gracefully_on_relocation_failure(tmp_path, monkeypatch):
    staging = tmp_path / "tiddl-abc.bin.part.1"
    staging.write_bytes(b"data")

    def boom_mkdir(*a, **k):
        raise OSError("simulated permission error")

    monkeypatch.setattr(type(reg.quarantine_dir()), "mkdir", boom_mkdir)
    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".bin", entry_id="eid")
    assert quarantined is False
    assert final_path == staging
    assert staging.exists()  # left in place, not lost


# ---------------------------------------------------------------------------
# [P2, third audit finding #6] Cross-filesystem quarantine (`_same_volume`
# forced False) — the copy/verify/publish/delete-source sequence, not just
# the same-volume atomic-rename fast path every other quarantine test above
# exercises. `staging` is the ONLY verified copy at this point, so getting
# this sequencing wrong risks destroying the only good bytes.
# ---------------------------------------------------------------------------


def test_cross_volume_quarantine_copies_verifies_then_deletes_source(tmp_path, monkeypatch):
    """The success path: source is copied to a quarantine-side temp,
    verified byte-for-byte, published as the final quarantined path, and
    ONLY THEN is the source deleted."""
    monkeypatch.setattr(reg, "_same_volume", lambda a, b: False)
    staging = tmp_path / "tiddl-abc.flac.part.1"
    content = b"cross-volume payload" * 100
    staging.write_bytes(content)

    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".flac", entry_id="xv1")

    assert quarantined is True
    assert final_path.name == "xv1.flac"
    assert final_path.read_bytes() == content
    assert not staging.exists()  # only deleted AFTER the verified copy landed
    # No leftover .part.* temp in the quarantine dir either.
    leftovers = [p for p in reg.quarantine_dir().iterdir() if ".part." in p.name]
    assert leftovers == []


def test_cross_volume_quarantine_silent_copy_corruption_leaves_source_untouched(
    tmp_path, monkeypatch
):
    """[P1] If the copy silently corrupts (shutil.copy2 doesn't raise, but
    the bytes that land don't match the source), the mismatch must be
    caught by the byte-for-byte re-hash BEFORE the source is ever deleted —
    a copy is not trusted just because the copy call didn't raise."""
    monkeypatch.setattr(reg, "_same_volume", lambda a, b: False)
    staging = tmp_path / "tiddl-abc.bin.part.1"
    staging.write_bytes(b"the real content")

    def _corrupting_copy2(src, dst):
        Path(dst).write_bytes(b"SILENTLY CORRUPTED, WRONG BYTES ENTIRELY")

    monkeypatch.setattr(reg.shutil, "copy2", _corrupting_copy2)

    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".bin", entry_id="xv2")

    assert quarantined is False
    assert final_path == staging
    assert staging.exists()
    assert staging.read_bytes() == b"the real content"  # untouched
    # The corrupted quarantine-side temp must not be left behind either.
    leftovers = list(reg.quarantine_dir().glob("xv2*")) if reg.quarantine_dir().is_dir() else []
    assert leftovers == []


def test_cross_volume_quarantine_copy_failure_keeps_source_and_cleans_temp(tmp_path, monkeypatch):
    """A copy that raises outright (disk full, permission error) must leave
    the source exactly as it was and not leak a partial temp file."""
    monkeypatch.setattr(reg, "_same_volume", lambda a, b: False)
    staging = tmp_path / "tiddl-abc.bin.part.1"
    staging.write_bytes(b"data")

    def _boom_copy2(src, dst):
        raise OSError("simulated disk-full mid-copy")

    monkeypatch.setattr(reg.shutil, "copy2", _boom_copy2)

    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".bin", entry_id="xv3")

    assert quarantined is False
    assert final_path == staging
    assert staging.exists()
    leftovers = list(reg.quarantine_dir().glob("xv3*")) if reg.quarantine_dir().is_dir() else []
    assert leftovers == []


def test_cross_volume_quarantine_publish_replace_failure_keeps_source_and_cleans_temp(
    tmp_path, monkeypatch
):
    """The copy succeeds and verifies, but the final `os.replace()` of the
    verified temp into place fails — the source must still be preserved
    (it's the only known-good copy at that point) and the temp cleaned up."""
    monkeypatch.setattr(reg, "_same_volume", lambda a, b: False)
    staging = tmp_path / "tiddl-abc.bin.part.1"
    staging.write_bytes(b"data")

    real_replace = reg.os.replace

    def _boom_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(reg.os, "replace", _boom_replace)

    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".bin", entry_id="xv4")

    assert quarantined is False
    assert final_path == staging
    assert staging.exists()
    assert staging.read_bytes() == b"data"
    # Nothing quarantine-side named after this entry should survive (the
    # verified temp is cleaned up on a failed publish).
    monkeypatch.setattr(reg.os, "replace", real_replace)  # restore before globbing
    leftovers = list(reg.quarantine_dir().glob("xv4*")) if reg.quarantine_dir().is_dir() else []
    assert leftovers == []


def test_cross_volume_quarantine_source_delete_failure_still_returns_verified_target(
    tmp_path, monkeypatch
):
    """[P1] Once the quarantine copy is verified and published, it is
    authoritative — a best-effort failure to delete the now-redundant
    source must NOT be treated as an overall failure: the function still
    returns the verified target with `quarantined=True`, just with a
    logged warning about the harmless leftover duplicate."""
    monkeypatch.setattr(reg, "_same_volume", lambda a, b: False)
    staging = tmp_path / "tiddl-abc.bin.part.1"
    staging.write_bytes(b"data")

    monkeypatch.setattr(reg, "_safe_unlink_warn", lambda path, ctx: False)

    final_path, quarantined = reg.quarantine_file(staging, output_suffix=".bin", entry_id="xv5")

    assert quarantined is True
    assert final_path.name == "xv5.bin"
    assert final_path.read_bytes() == b"data"
    assert staging.exists()  # best-effort delete failed; redundant copy remains (harmless)


def test_orphaned_quarantine_file_is_detected_not_silently_ignored():
    """[P1] A crash between relocating a file into quarantine and publishing
    the registry entry for it must leave a DETECTABLE orphan, never an
    invisible leftover."""
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    orphan = qdir / "no-matching-entry.bin"
    orphan.write_bytes(b"data")

    orphans = reg.find_orphaned_quarantine_files()
    assert orphans == [orphan]


def test_known_quarantine_file_is_not_reported_as_orphan():
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    known = qdir / "known.bin"
    known.write_bytes(b"data")
    reg.add_entry(_entry(id="known", staging_path=str(known)))

    assert reg.find_orphaned_quarantine_files() == []


def test_no_quarantine_dir_yields_no_orphans():
    assert reg.find_orphaned_quarantine_files() == []


# ---------------------------------------------------------------------------
# register_retained_file: the end-to-end "just retained a file" call.
# ---------------------------------------------------------------------------


async def test_register_retained_file_quarantines_and_records_observed_hash(tmp_path):
    staging = tmp_path / "tiddl-abc.flac.part.1"
    content = b"\x00" * 5000
    staging.write_bytes(content)

    result = await reg.register_retained_file(
        staging, tmp_path / "dest" / "track.flac", RetainReason.PUBLISH_PENDING,
        track_title="My Track",
    )

    assert result.persisted
    entry = result.entry
    assert result.actual_path == Path(entry.staging_path)
    assert entry.reason == RetainReason.PUBLISH_PENDING
    assert entry.track_title == "My Track"
    assert entry.quarantined is True
    quarantined_path = Path(entry.staging_path)
    assert quarantined_path.exists()
    assert quarantined_path.suffix == ".flac"
    assert not staging.exists()

    assert entry.observed_size == len(content)
    assert entry.observed_hash == hashlib.sha256(content).hexdigest()
    assert entry.hash_algorithm == "sha256"

    # And it round-trips through the registry.
    reread = reg.read_entries().entries[0]
    assert reread.id == entry.id


async def test_register_retained_file_degrades_to_unpersisted_result_on_lock_timeout(monkeypatch):
    """[Failure handling] A registry persistence failure must never raise out
    of the download path — it degrades to a RegisterResult with entry=None
    (result.persisted is False), logged, but `result.actual_path` still
    reflects where the file physically ended up (quarantine still happened),
    so the caller (downloader.py) can keep task.retained_staging accurate
    even though this attempt won't be listed by `tiddl recover` until a
    later successful registry write."""
    staging_dir = reg.APP_PATH.parent / "stage"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging = staging_dir / "tiddl-x.bin.part.1"
    staging.write_bytes(b"data")

    def boom_add_entry(entry):
        raise RegistryLockTimeout("simulated")

    monkeypatch.setattr(reg, "add_entry", boom_add_entry)
    result = await reg.register_retained_file(
        staging, staging_dir / "dest.bin", RetainReason.PUBLISH_PENDING
    )
    assert result.entry is None  # never raises
    assert not result.persisted
    # The file was still quarantined (that step succeeded); actual_path must
    # point at its real, current location — not the stale original staging
    # path, which no longer exists.
    assert result.actual_path.exists()
    assert not staging.exists()


# ---------------------------------------------------------------------------
# reconcile(): ok / gone / corrupt, and never auto-deletes.
# ---------------------------------------------------------------------------


async def test_reconcile_reports_ok_for_untouched_entry(tmp_path):
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    f = qdir / "e1.bin"
    content = b"hello world"
    f.write_bytes(content)
    import hashlib
    reg.add_entry(_entry(
        id="e1", staging_path=str(f),
        observed_size=len(content), observed_hash=hashlib.sha256(content).hexdigest(),
    ))

    report = await reg.reconcile()
    assert report.status == "valid"
    assert len(report.entries) == 1
    assert report.entries[0].status == "ok"


async def test_reconcile_reports_gone_for_missing_file_and_does_not_remove_entry():
    """[P2] The stale-entry policy: a `gone` file is reported, not silently
    dropped from the registry — retain a bounded tombstone so the user can
    see what was lost, per the audit's recommendation."""
    reg.add_entry(_entry(id="e1", staging_path="/does/not/exist.bin"))

    report = await reg.reconcile()
    assert len(report.entries) == 1
    assert report.entries[0].status == "gone"

    # Tombstone retained: still present on a second reconcile, not dropped.
    still_there = reg.read_entries().entries
    assert len(still_there) == 1
    assert still_there[0].id == "e1"


async def test_reconcile_reports_corrupt_when_content_changed_but_keeps_entry(tmp_path):
    """[P1] Recovery must compare exact observed size/hash, not just
    existence — a file that changed on disk since it was retained must be
    flagged, never treated as still valid."""
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    f = qdir / "e1.bin"
    f.write_bytes(b"original content")
    import hashlib
    reg.add_entry(_entry(
        id="e1", staging_path=str(f),
        observed_size=len(b"original content"),
        observed_hash=hashlib.sha256(b"original content").hexdigest(),
    ))

    f.write_bytes(b"tampered content!!")  # changed after retention

    report = await reg.reconcile()
    assert report.entries[0].status == "corrupt"
    # Never auto-deleted:
    assert f.exists()
    assert len(reg.read_entries().entries) == 1


async def test_reconcile_never_writes_when_registry_is_valid(tmp_path):
    reg.add_entry(_entry(id="e1", staging_path=str(tmp_path / "gone.bin")))
    before_mtime = reg.registry_path().stat().st_mtime_ns
    await reg.reconcile()
    after_mtime = reg.registry_path().stat().st_mtime_ns
    assert before_mtime == after_mtime  # reconcile() is read-only


async def test_reconcile_surfaces_orphans_alongside_entries():
    qdir = reg.quarantine_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    orphan = qdir / "orphan.bin"
    orphan.write_bytes(b"x")

    report = await reg.reconcile()
    assert report.orphans == [orphan]
    assert report.entries == []


# ---------------------------------------------------------------------------
# startup_status(): lightweight, no hashing, no destination I/O.
# ---------------------------------------------------------------------------


def test_startup_status_empty_registry():
    status = reg.startup_status()
    assert status.status == "missing"
    assert status.count == 0


def test_startup_status_counts_entries_without_hashing(tmp_path, monkeypatch):
    reg.add_entry(_entry(id="a", staging_path=str(tmp_path / "does-not-exist.bin")))
    reg.add_entry(_entry(id="b", staging_path=str(tmp_path / "also-missing.bin")))

    def boom_hash(*a, **k):
        raise AssertionError("startup_status must never hash a file")

    monkeypatch.setattr(reg, "_hash_and_size", boom_hash)  # sync helper used by hash_and_size_async
    status = reg.startup_status()
    assert status.status == "valid"
    assert status.count == 2  # counted despite files not existing - no existence check either


def test_startup_status_never_touches_fs_beyond_the_registry_itself(tmp_path, monkeypatch):
    """[P1] Startup reconciliation must be lightweight: registry status/count
    only, no destination access. Simulate `Path.exists` blowing up for
    anything under a fake "destination" to prove it's never called."""
    reg.add_entry(_entry(id="a", output_path="/mnt/nas/should-not-be-touched.bin"))

    from pathlib import Path
    real_exists = Path.exists

    def guarded_exists(self):
        if "should-not-be-touched" in str(self):
            raise AssertionError("startup_status must not touch destination paths")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    status = reg.startup_status()
    assert status.count == 1


# ---------------------------------------------------------------------------
# TIDDL_PATH / APP_PATH resolution honored (factual correction from the audit).
# ---------------------------------------------------------------------------


def test_registry_path_follows_app_path(tmp_path, monkeypatch):
    custom = tmp_path / "custom-app-dir"
    monkeypatch.setattr(reg, "APP_PATH", custom)
    assert reg.registry_path() == custom / "retained_staging.json"
    assert reg.quarantine_dir() == custom / "retained"


def test_env_tiddl_path_is_honored_end_to_end(tmp_path, monkeypatch):
    """[Factual correction from the audit] APP_PATH is not always ~/.tiddl —
    `TIDDL_PATH` always wins (see tiddl/cli/const.py:get_app_path). Exercise
    the REAL resolution function (not just the registry's own APP_PATH
    attribute) to prove the registry ends up wherever TIDDL_PATH points."""
    from tiddl.cli.const import get_app_path

    custom = tmp_path / "custom-via-env"
    monkeypatch.setenv("TIDDL_PATH", str(custom))
    assert get_app_path() == custom

    # retained_registry imports APP_PATH once at module load time (like every
    # other consumer, e.g. auth/core.py's AUTH_DATA_FILE) — simulate a process
    # that started with this env var set by pointing the module at the same
    # freshly-resolved path, and confirm the registry/quarantine paths follow.
    monkeypatch.setattr(reg, "APP_PATH", get_app_path())
    assert reg.registry_path() == custom / "retained_staging.json"
    assert reg.quarantine_dir() == custom / "retained"


# ---------------------------------------------------------------------------
# [P2] Synchronous FileLock waits must not block the asyncio event loop.
# ---------------------------------------------------------------------------


async def test_registry_transaction_does_not_block_the_event_loop_when_used_via_to_thread():
    """The synchronous FileLock-guarded transaction (`_transaction`, used by
    `add_entry`/`update_entry`/`remove_entry`) must be run via
    `asyncio.to_thread` from async call sites — exactly what
    `register_retained_file` does. Prove a concurrent asyncio task keeps
    making progress (ticking a counter) while a slow, lock-held mutation is
    in flight in a thread, rather than the whole event loop stalling."""
    ticks = []

    async def ticker():
        for _ in range(20):
            ticks.append(1)
            await asyncio.sleep(0.01)

    def slow_mutation():
        # Simulate a slow disk / contended lock inside the transaction body
        # by holding the lock for a while via a direct, blocking call.
        with reg._transaction() as box:
            time.sleep(0.3)
            box["entries"].append(_entry(id="slow"))

    ticker_task = asyncio.create_task(ticker())
    await asyncio.to_thread(slow_mutation)
    await ticker_task

    # If the event loop had been blocked for the ~0.3s the mutation took, far
    # fewer than 20 ticks (0.01s apart) would have landed by the time we get
    # here — the ticker would have been starved instead of interleaved.
    assert len(ticks) == 20
    assert [e.id for e in reg.read_entries().entries] == ["slow"]


# ---------------------------------------------------------------------------
# [Minimum additional test, per audit] Idempotent recovery: a crash between a
# successful destination publish and the registry's remove_entry() call must
# not corrupt anything, and a re-run must still converge cleanly.
# ---------------------------------------------------------------------------


def test_recovery_converges_via_reconcile_and_cli_if_interrupted_after_publish(
    tmp_path,
):
    """[Minimum additional test, per audit] Idempotent recovery: a crash
    between a successful destination publish and the registry's
    `remove_entry()` call must not corrupt anything, and a re-run must
    still converge cleanly.

    The second audit review specifically flagged an earlier version of this
    test for FAKING convergence (calling `remove_entry()` manually) instead
    of exercising the real recovery path. This version instead reproduces
    the exact ON-DISK STATE such a crash leaves behind — using real
    `publish_verified_file` semantics (destination holds the verified
    bytes, the quarantined source is gone, the registry is untouched and
    still says `publish_pending`) — and then drives the actual production
    code (`reconcile()`, then the real `tiddl recover --publish` CLI
    command) to confirm IT detects and converges this on its own, with no
    manual registry surgery standing in for what the code is supposed to
    do."""
    content = b"\x33" * 4000
    source = tmp_path / "src.bin"
    source.write_bytes(content)
    dest = tmp_path / "dest.bin"

    # This test invokes the CliRunner below, which internally does its own
    # `asyncio.run()` — so, unlike the rest of this file, it must NOT itself
    # be an `async def` test (that would already have a loop running, and
    # nested `asyncio.run()` calls raise). Drive the async registry calls
    # explicitly instead.
    result = asyncio.run(reg.register_retained_file(
        source, dest, RetainReason.PUBLISH_PENDING, track_title="Idempotent"
    ))
    assert result.persisted
    entry = result.entry
    quarantined = Path(entry.staging_path)
    assert quarantined.exists()

    # Reproduce the on-disk state a crash AFTER a successful publish but
    # BEFORE the registry's remove_entry() call would leave behind: the
    # destination holds the verified bytes and the quarantined copy is
    # gone (that's what a real publish_verified_file success does — see
    # tiddl.core.utils.publish), but the registry was never updated.
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    quarantined.unlink()
    assert reg.read_entries().entries[0].id == entry.id  # registry still stale

    # reconcile() (the real deep-check used by `tiddl recover`) must
    # recognize this WITHOUT hashing/touching either file a second time in
    # a way that could disturb it: the retained copy is gone, but the
    # destination independently matches what was observed at retention
    # time, so this is stale bookkeeping from an already-converged recovery
    # -- not data loss.
    report = asyncio.run(reg.reconcile())
    assert len(report.entries) == 1
    assert report.entries[0].status == "already_published"
    assert report.entries[0].entry.id == entry.id

    # And the real CLI path must be able to drop the stale entry — no
    # manual remove_entry() call standing in for it.
    from typer.testing import CliRunner

    from tiddl.cli.app import app

    runner = CliRunner()
    cli_result = runner.invoke(app, ["recover", "--publish", entry.id[:8]])
    assert cli_result.exit_code == 0, cli_result.output
    assert "already converged" in cli_result.output
    assert dest.read_bytes() == content  # untouched by the convergence
    assert reg.read_entries().entries == []
