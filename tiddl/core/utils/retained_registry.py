"""Persistent recovery of retained staging files across app restarts.

Background: `Downloader._publish_staged` (PR #12) already keeps a verified
local file instead of deleting it when the destination can't be published,
or when it can be published but the local copy can't be cleaned up
afterward (`task.retained_staging`). That fact used to live only in memory —
lost on any restart, and the file itself sat in the OS temp directory, which
is not a place anything promises to leave alone.

This module closes that gap:

* `quarantine_file` moves a retained file out of the OS temp directory into
  `APP_PATH / "retained"`, a directory this project already treats as
  durable (it's the same tree `auth.json` lives in).
* A small JSON registry (`APP_PATH / "retained_staging.json"`) records enough
  to recover or safely discard each entry later, written atomically
  (`tiddl.core.utils.fsio.atomic_write_bytes`) and mutated only inside a
  `FileLock`-guarded read -> validate -> mutate -> write transaction, so two
  concurrent writers (two downloads failing at once, or two `tiddl`
  processes) can't lose an update.
* `reconcile()` (deep, explicit-only — called by `tiddl recover`, never at
  plain startup) and `startup_status()` (lightweight, no hashing, no
  destination I/O — called from the app's root callback) let a later run
  discover what's pending.

Entries are never silently dropped: a retained file that has disappeared, or
a registry that turned out to be corrupt/from a future version, is reported
and preserved (a backup copy for a corrupt/unsupported registry; a bounded
tombstone entry for a `gone` file) rather than quietly treated as "nothing
to see here". Deep integrity re-verification (`reconcile`) and any
destination-touching recovery only happen when the user explicitly asks for
them via `tiddl recover` — never as a side effect of running an unrelated
command.

This module has NO dependency on `Downloader`, TIDAL auth, or any network
code — `tiddl recover` works fully offline.

Crash-durability contract [P1, third audit finding #3]: every write this
module performs that's meant to survive a restart — the registry file
itself, its corrupt/unsupported-version backups, and a file's move/copy
into the quarantine directory — goes through `atomic_write_bytes(...,
fsync_dir=True)` or an explicit `_fsync_dir()` call after the relevant
`os.replace()`, not just the atomic-replace-of-content that
`atomic_write_bytes` already gives for free. Content-level atomicity alone
(no torn/partial file) is not the same guarantee as directory-entry
durability: without fsyncing the containing directory on POSIX, a power
loss immediately after a successful `os.replace()` can still lose or roll
back the directory entry pointing at the new inode, even though the write
itself completed. This is best-effort on Windows, where directory fsync
isn't supported (`fsio._fsync_dir` is a documented no-op there) — the
content-atomicity guarantee still holds on Windows, just not the
directory-entry one.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from logging import getLogger
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from tiddl.cli.const import APP_PATH

from .fsio import _fsync_dir, _fsync_path, _safe_unlink_warn, _same_volume, atomic_write_bytes

log = getLogger(__name__)

REGISTRY_VERSION = 1
DEFAULT_LOCK_TIMEOUT = 10.0
HASH_ALGORITHM = "sha256"
#: [P2, third audit finding #5] Schema validation previously accepted ANY
#: name in `hashlib.algorithms_available` for `hash_algorithm`, but
#: `_hash_and_size`/`hexdigest()` are called with no extra arguments —
#: variable-length algorithms like `shake_128`/`shake_256` require a
#: `length` argument to `hexdigest()` and raise `TypeError` (not `OSError`,
#: so it wasn't even caught by the per-entry error isolation elsewhere)
#: the moment they're actually hashed. Registry version 1 only ever WRITES
#: `sha256` (see `HASH_ALGORITHM` above) — restricting what it will accept
#: on READ to the same fixed-length allowlist closes that gap without
#: weakening anything production actually needs today. Extend this set
#: (with a corresponding registry version bump if the on-disk format is
#: meant to change) if algorithm agility is genuinely needed later.
SUPPORTED_HASH_ALGORITHMS = frozenset({"sha256"})


def registry_path() -> Path:
    return APP_PATH / "retained_staging.json"


def _lock_path() -> Path:
    return APP_PATH / "retained_staging.json.lock"


def _recovery_lock_path() -> Path:
    """A SEPARATE lock file from `_lock_path()`, deliberately. `filelock`
    locks are not reentrant across distinct `FileLock` instances on the same
    path within one process (confirmed empirically: a second `FileLock` on
    an already-held path just times out) — so a single long-held lock
    guarding a whole recovery sequence cannot share a path with the
    short-lived lock `_transaction()` takes internally for each registry
    mutation, or a recovery operation would time out locking itself out.
    Two independent lock files keep those two locking needs from colliding
    while still being consistent (both live under the same APP_PATH)."""
    return APP_PATH / "retained_staging.recovery.lock"


def quarantine_dir() -> Path:
    return APP_PATH / "retained"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetainReason(str, Enum):
    #: The destination could not be published; `staging_path` is the only
    #: copy of the verified content. Must be re-published, not deleted.
    PUBLISH_PENDING = "publish_pending"
    #: The destination WAS published successfully; `staging_path` is a
    #: redundant local copy that only needs to be cleaned up once the
    #: destination is confirmed to still hold the same content.
    CLEANUP_PENDING = "cleanup_pending"


ReconcileStatus = Literal["ok", "gone", "corrupt", "already_published"]
#: 'corrupt'/'unsupported_version': the file WAS read successfully (raw_bytes
#: is available) but its content is invalid UTF-8/JSON/schema, or from a
#: future registry version — a mutation can safely back this up before
#: overwriting. 'unreadable': the file could NOT be read at all (permission
#: error, a sharing violation, a transient network-share I/O error) — there
#: is no `raw_bytes` to back up, and — critically — no way to know whether
#: the content on disk still matches what was reported as unreadable a
#: moment ago. [P1, third audit finding #1] This must never be treated the
#: same as 'corrupt': a mutation must refuse outright rather than silently
#: replacing a file it was never actually able to read.
RegistryStatus = Literal["missing", "valid", "corrupt", "unsupported_version", "unreadable"]


@dataclass
class RetainedEntry:
    id: str
    reason: RetainReason
    staging_path: str
    output_path: str
    observed_size: int
    observed_hash: str
    hash_algorithm: str = HASH_ALGORITHM
    track_title: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    #: False if the move into `quarantine_dir()` failed and this entry's
    #: `staging_path` is still wherever the caller originally staged it (a
    #: degraded-but-not-lost outcome — see `quarantine_file`).
    quarantined: bool = True

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["reason"] = self.reason.value
        return d

    @staticmethod
    def from_json_dict(d: dict) -> "RetainedEntry":
        """Raises ValueError/TypeError/KeyError on a schema violation.
        Callers (`_parse_registry_text`) treat any such failure as making
        the WHOLE registry corrupt, not just this one entry — a registry
        that can silently drop individual malformed entries while reporting
        itself 'valid' can lose track of a retained file without any
        visible warning, which is worse than refusing to touch it.

        Deliberately NOT strict about `id` being a UUID or `observed_hash`
        matching the exact digest length for its algorithm: this project's
        own test suite constructs entries with short human-readable ids and
        placeholder hashes, and there is no correctness reason a foreign/
        future registry writer couldn't use a different id scheme. The
        checks below focus on things that would otherwise crash downstream
        code (wrong types, negative sizes, unknown hash algorithms, naive
        timestamps) rather than pinning today's production format as the
        only valid one.
        """
        d = dict(d)

        entry_id = d.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"invalid 'id': {entry_id!r}")

        reason = RetainReason(d["reason"])  # raises ValueError on unknown value

        for key in ("staging_path", "output_path"):
            v = d.get(key)
            if not isinstance(v, str) or not v:
                raise ValueError(f"invalid {key!r}: {v!r}")

        size = d.get("observed_size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"invalid 'observed_size': {size!r}")

        algorithm = d.get("hash_algorithm", HASH_ALGORITHM)
        if not isinstance(algorithm, str) or algorithm not in SUPPORTED_HASH_ALGORITHMS:
            raise ValueError(f"unsupported 'hash_algorithm': {algorithm!r}")

        # Deliberately only checking the TYPE here, not hex-charset/length:
        # this project's own test suite uses human-readable placeholder
        # values (e.g. "doesnotmatch") for `observed_hash` specifically to
        # simulate a hash MISMATCH that should be caught by re-hashing at
        # `reconcile()` time — that is a content-integrity check, not a
        # schema violation, and must not be conflated with one here.
        digest = d.get("observed_hash")
        if not isinstance(digest, str) or not digest:
            raise ValueError(f"invalid 'observed_hash': {digest!r}")

        track_title = d.get("track_title")
        if track_title is not None and not isinstance(track_title, str):
            raise ValueError(f"invalid 'track_title': {track_title!r}")

        created_at = d.get("created_at")
        if not isinstance(created_at, str):
            raise ValueError(f"invalid 'created_at': {created_at!r}")
        try:
            parsed_created_at = datetime.fromisoformat(created_at)
        except ValueError as e:
            raise ValueError(f"'created_at' is not a valid ISO timestamp: {created_at!r}") from e
        if parsed_created_at.tzinfo is None:
            raise ValueError(f"'created_at' must be timezone-aware: {created_at!r}")

        quarantined = d.get("quarantined", True)
        if not isinstance(quarantined, bool):
            raise ValueError(f"invalid 'quarantined': {quarantined!r}")

        d["reason"] = reason
        d["hash_algorithm"] = algorithm
        return RetainedEntry(**d)


@dataclass
class ReadResult:
    status: RegistryStatus
    entries: list  # list[RetainedEntry]
    #: [P1, fourth audit finding #1] Bytes, not decoded text — this must
    #: hold the EXACT original bytes read from disk (whether or not they're
    #: valid UTF-8) so a corrupt/unsupported-version backup preserves the
    #: original file byte-for-byte instead of round-tripping it through a
    #: decode+re-encode that only works when the original happened to be
    #: valid UTF-8 in the first place.
    raw_bytes: Optional[bytes] = None


@dataclass
class ReconcileEntry:
    entry: RetainedEntry
    status: ReconcileStatus
    detail: Optional[str] = None


@dataclass
class ReconcileReport:
    status: RegistryStatus
    entries: list  # list[ReconcileEntry]
    orphans: list  # list[Path]


@dataclass
class StartupStatus:
    status: RegistryStatus
    count: int


# ---------------------------------------------------------------------------
# Low-level read/write. Reads never need a lock: atomic_write_bytes always
# publishes a complete file via os.replace, so a concurrent reader sees
# either the old or the new content, never a torn one.
# ---------------------------------------------------------------------------


def _parse_registry_text(text: str, raw_bytes: bytes) -> ReadResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning(f"Retained-staging registry at {registry_path()} is not valid JSON: {e}")
        return ReadResult(status="corrupt", entries=[], raw_bytes=raw_bytes)

    try:
        version = data["version"]
        raw_entries = data["entries"]
        if not isinstance(raw_entries, list):
            raise TypeError("'entries' is not a list")
    except (KeyError, TypeError) as e:
        log.warning(f"Retained-staging registry at {registry_path()} has an unexpected shape: {e}")
        return ReadResult(status="corrupt", entries=[], raw_bytes=raw_bytes)

    if version != REGISTRY_VERSION:
        log.warning(
            f"Retained-staging registry at {registry_path()} is version {version!r}, "
            f"this build understands version {REGISTRY_VERSION}. Leaving it untouched."
        )
        return ReadResult(status="unsupported_version", entries=[], raw_bytes=raw_bytes)

    entries = []
    for raw in raw_entries:
        try:
            entries.append(RetainedEntry.from_json_dict(raw))
        except (KeyError, TypeError, ValueError) as e:
            # A single malformed entry makes the WHOLE registry 'corrupt' for
            # this read, rather than being silently skipped while the
            # registry is reported 'valid' — otherwise a partially-corrupted
            # file could quietly lose track of a retained file with no
            # visible warning, and (worse) a mutation could go on to write
            # back a registry that's missing that entry entirely.
            log.warning(
                f"Retained-staging registry at {registry_path()} has an unreadable "
                f"entry ({e}); treating the whole registry as corrupt so nothing is "
                "silently dropped."
            )
            return ReadResult(status="corrupt", entries=[], raw_bytes=raw_bytes)
    return ReadResult(status="valid", entries=entries, raw_bytes=raw_bytes)


def read_entries() -> ReadResult:
    """Read-only. Never mutates the registry file, never raises on a
    missing/corrupt/future-version/unreadable/non-UTF-8 file — always
    returns a usable result.

    [P1, third audit finding #1] An I/O failure while reading (permissions,
    a sharing violation, a transient network-share error) is reported as
    'unreadable', NOT 'corrupt' — 'corrupt' means the content was
    successfully read and turned out to be invalid, which is safe to back
    up and replace. 'unreadable' means we never got the content at all, so
    there is nothing to back up and no way to know it's safe to replace
    whatever is actually on disk. `_transaction()` refuses to mutate on
    'unreadable' rather than treating it like 'corrupt'.

    [P1, fourth audit finding #1] Reads raw BYTES first, then decodes as a
    separate, explicit step. An earlier version called
    `Path.read_text(encoding="utf-8")` directly, which conflates I/O
    failure (`OSError`) with decode failure (`UnicodeDecodeError` — NOT an
    `OSError` subclass) into a single call. A registry containing invalid
    UTF-8 bytes made `read_text()` raise `UnicodeDecodeError` straight out
    of this function, uncaught — bypassing the controlled 'unreadable'/
    'corrupt' handling entirely and crashing `tiddl recover` and every
    other caller with an unhandled traceback. Splitting the read into
    read-bytes-then-decode makes invalid UTF-8 an ordinary, controlled
    'corrupt' result (the bytes WERE read; they just aren't valid text —
    exactly like invalid JSON is 'corrupt'), with the original bytes
    preserved byte-for-byte in `raw_bytes` for `_preserve_unreadable` to
    back up, no round-trip through a decode that would have failed."""
    path = registry_path()
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        return ReadResult(status="missing", entries=[])
    except OSError as e:
        log.warning(f"Could not read the retained-staging registry at {path}: {e}")
        return ReadResult(status="unreadable", entries=[])

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        log.warning(f"Retained-staging registry at {path} is not valid UTF-8: {e}")
        return ReadResult(status="corrupt", entries=[], raw_bytes=raw_bytes)

    return _parse_registry_text(text, raw_bytes)


def _write_entries(entries: list) -> None:
    payload = {
        "version": REGISTRY_VERSION,
        "entries": [e.to_json_dict() for e in entries],
    }
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    # [P1, third audit finding #3] fsync_dir=True: this file is explicitly
    # described (see this module's docstring) as surviving app restarts —
    # atomic_write_bytes's os.replace() alone prevents a TORN write, but
    # without also fsyncing the containing directory, a power loss right
    # after a successful replace can still lose or roll back the directory
    # entry pointing at the new inode on POSIX. Best-effort/no-op on
    # Windows (see fsio._fsync_dir).
    atomic_write_bytes(registry_path(), data, fsync_dir=True)


class RegistryPreservationError(Exception):
    """Raised when a corrupt/unsupported-version registry could not be
    backed up before a mutation would otherwise have overwritten it. The
    mutation MUST be aborted in this case — proceeding would destroy the
    only copy of whatever the original file contained, silently. The
    original registry file itself is untouched by this failure (nothing has
    been written yet), so the caller can retry later once the underlying
    problem (e.g. a full disk, permissions) is fixed."""


def _preserve_unreadable(read: ReadResult) -> None:
    """Back up a corrupt/unsupported-version registry under a timestamped
    name before a mutation would otherwise overwrite it with a fresh one.
    Quarantined FILES are never touched by this — only the registry JSON.

    Fails CLOSED: if the backup itself cannot be written, this raises
    `RegistryPreservationError` instead of letting the caller proceed to
    overwrite the original — silently destroying an unreadable registry is
    strictly worse than refusing the mutation, since backup failures are
    usually transient (disk full, permissions) and retryable, while an
    overwritten original is not recoverable."""
    if read.raw_bytes is None:
        return
    ts = _utcnow_iso().replace(":", "").replace("-", "")
    backup = registry_path().with_name(f"{registry_path().name}.{read.status}-{ts}.bak")
    # [P1, fourth audit finding #1] Use the original bytes directly — NOT a
    # decode-then-re-encode round trip. That round trip only works when the
    # original bytes happened to be valid UTF-8 in the first place; for a
    # registry that's corrupt precisely BECAUSE it's not valid UTF-8, a
    # decode would already have failed before ever reaching here. Preserving
    # `raw_bytes` verbatim is what makes it possible to back up ANY corrupt
    # content, not just the subset that also happens to decode.
    payload = read.raw_bytes
    try:
        # [P2, third audit finding #9] Use the same atomic-write primitive
        # the registry itself uses (temp file -> fsync -> os.replace ->
        # fsync the directory), not a plain Path.write_text() — a crash or
        # disk-full event mid-write must not leave a partial/torn backup
        # standing in for "the original was safely preserved".
        atomic_write_bytes(backup, payload, fsync_dir=True)
        # And don't just trust that the write "succeeded" — read it back
        # and compare byte-for-byte before treating the original as safely
        # backed up. Belt-and-suspenders: atomic_write_bytes already fsyncs
        # before replace, but this is the one place in the whole module
        # where "the backup exists" is treated as a green light to
        # overwrite the only other copy of this data, so it's worth the
        # extra read.
        if backup.read_bytes() != payload:
            raise OSError(f"backup at {backup} did not read back identical to what was written")
    except OSError as e:
        log.error(
            f"Retained-staging registry was {read.status} AND the backup copy could "
            f"not be written and verified ({e}); refusing to proceed with this "
            f"mutation so the original content at {registry_path()} is not lost. "
            f"Quarantined files under {quarantine_dir()} are untouched. Try again "
            "once the problem preventing the backup write is resolved."
        )
        raise RegistryPreservationError(str(e)) from e
    log.warning(
        f"Retained-staging registry was {read.status}; preserved and verified the original at "
        f"{backup} before writing a fresh one. Any quarantined files under "
        f"{quarantine_dir()} are untouched and can be recovered manually."
    )


class RegistryLockTimeout(Exception):
    """Raised when a registry mutation could not acquire the transaction
    lock in time. The caller's in-memory state (e.g. task.retained_staging
    for the CURRENT run) is unaffected either way — this only means the
    NEXT restart won't know about this particular change."""


class RegistryReadError(Exception):
    """[P1, third audit finding #1] Raised when a registry mutation could
    not even READ the registry file (as opposed to reading it and finding
    invalid content, which is 'corrupt' and handled by
    `RegistryPreservationError`/`_preserve_unreadable`). There is no
    `raw_bytes` to back up in this case, and critically no way to know
    whether the file that couldn't be read a moment ago still has the same
    content now — proceeding to write a fresh empty registry here would
    risk silently discarding whatever is actually on disk. The mutation is
    aborted outright; nothing is written."""


def _transaction(timeout: Optional[float] = None):
    """Context manager yielding a mutable `{"entries": [...]}` box. On clean
    exit (no exception), the box's entries are atomically written back under
    the same lock that guarded the read — the whole read -> mutate -> write
    sequence is one transaction, not two independently-locked calls.

    `timeout` defaults to the module-level `DEFAULT_LOCK_TIMEOUT`, read
    dynamically (not baked in as a def-time default) so tests can override it
    via `monkeypatch.setattr(reg, "DEFAULT_LOCK_TIMEOUT", ...)`."""
    from contextlib import contextmanager

    if timeout is None:
        timeout = DEFAULT_LOCK_TIMEOUT

    @contextmanager
    def _cm():
        lock = FileLock(str(_lock_path()), timeout=timeout)
        try:
            with lock:
                result = read_entries()
                if result.status == "unreadable":
                    log.error(
                        f"Refusing to mutate the retained-staging registry at "
                        f"{registry_path()}: it could not be read (see the "
                        "preceding warning for the underlying I/O error), so there "
                        "is nothing to safely back up and no way to know this "
                        "mutation wouldn't silently discard whatever is actually "
                        "on disk. Nothing was written. Try again once the "
                        "underlying problem (permissions, a sharing lock, a "
                        "network-share hiccup) is resolved."
                    )
                    raise RegistryReadError(
                        f"could not read {registry_path()} before mutating it"
                    )
                if result.status in ("corrupt", "unsupported_version"):
                    _preserve_unreadable(result)
                    entries = []
                else:
                    entries = list(result.entries)
                box = {"entries": entries}
                yield box
                _write_entries(box["entries"])
        except FileLockTimeout as e:
            log.warning(
                f"Could not acquire the retained-staging registry lock within "
                f"{timeout}s ({e}); skipping this registry update (best-effort — "
                "the file itself, if any, is untouched)."
            )
            raise RegistryLockTimeout(str(e)) from e

    return _cm()


def recovery_operation_lock(timeout: Optional[float] = None) -> FileLock:
    """Public: a process-wide lock for callers (namely `tiddl recover`) that
    need to serialize an entire multi-step recovery sequence — verify a
    candidate, publish or clean up the file, THEN mutate the registry — not
    just the registry's own internal read-mutate-write.

    [P2, finding #12] `_transaction()` alone only ever locks the JSON
    read/write itself. Two concurrent `tiddl recover` processes racing on
    the same (or even a different) entry could previously each decide,
    independently, that it was safe to act — real file I/O in between was
    never covered by any lock, so e.g. two processes could both publish the
    same source, or one could publish while another purges the same entry
    out from under it. Holding THIS lock for the full verify -> publish/
    cleanup -> registry-mutation sequence serializes all recovery activity
    across processes.

    Deliberately a DIFFERENT lock file from `_lock_path()` (see
    `_recovery_lock_path`) — nesting a second `FileLock` on the same path
    while the first is held would just time itself out (`filelock` is not
    reentrant across separate instances), and this lock is held for the
    entire recovery sequence specifically so it can safely call
    `add_entry`/`update_entry`/`remove_entry` (each of which briefly takes
    the OTHER lock via `_transaction()`) from within its `with` block."""
    if timeout is None:
        timeout = DEFAULT_LOCK_TIMEOUT
    return FileLock(str(_recovery_lock_path()), timeout=timeout)


def add_entry(entry: RetainedEntry) -> RetainedEntry:
    with _transaction() as box:
        box["entries"].append(entry)
    return entry


def update_entry(entry_id: str, **changes) -> Optional[RetainedEntry]:
    updated = None
    with _transaction() as box:
        for i, e in enumerate(box["entries"]):
            if e.id == entry_id:
                updated = replace(e, **changes)
                box["entries"][i] = updated
                break
    return updated


def remove_entry(entry_id: str) -> bool:
    removed = False
    with _transaction() as box:
        before = len(box["entries"])
        box["entries"] = [e for e in box["entries"] if e.id != entry_id]
        removed = len(box["entries"]) != before
    return removed


# ---------------------------------------------------------------------------
# Quarantine: move a retained file out of the OS temp directory.
# ---------------------------------------------------------------------------


def quarantine_file(staging: Path, *, output_suffix: str, entry_id: str) -> tuple[Path, bool]:
    """Move `staging` into the quarantine dir under a name derived from
    `entry_id` (NOT staging's own `.part.<random>` suffix, which has nothing
    to do with the media type) so the registry entry and the file on disk
    can always be matched back up — see `find_orphaned_quarantine_files`.

    Returns `(final_path, quarantined)`. On any failure this degrades to
    `(staging, False)` — the caller still has a usable path, just not one
    protected from OS temp cleanup.

    Cross-filesystem case: `staging` is the ONLY verified copy of this file
    at this point, so it is never deleted until the quarantine copy has been
    independently verified byte-for-byte (exact size + sha256) against it —
    a copy is not trusted just because `shutil.copy2` didn't raise. This
    mirrors the same discipline `publish_verified_file` already applies to
    the destination copy (see PR #12) — an earlier version of this function
    skipped that step and could silently promote a corrupt copy to
    "quarantined" while deleting the only good bytes."""
    qdir = quarantine_dir()
    try:
        qdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning(
            f"Could not create the retained-staging quarantine dir at {qdir} ({e}); "
            f"leaving the retained file at its original location {staging}."
        )
        return staging, False

    target = qdir / f"{entry_id}{output_suffix}"

    if _same_volume(staging, qdir):
        # Atomic rename: no bytes are copied, so there is nothing to verify —
        # `target` is byte-identical to `staging` by construction.
        try:
            os.replace(staging, target)
            # [P1, third audit finding #3] fsync the quarantine directory
            # itself so the new directory entry survives a power loss —
            # os.replace() alone is atomic against torn content but not
            # against the directory entry itself being lost/rolled back.
            _fsync_dir(qdir)
            return target, True
        except OSError as e:
            log.warning(
                f"Could not move the retained file at {staging} into quarantine ({e}); "
                "leaving it at its original location."
            )
            return staging, False

    # Cross filesystem: copy to a quarantine-side temp, verify it against the
    # SOURCE's own exact size/hash, and only then atomically publish it as
    # `target` — and only THEN consider deleting the source.
    dest_tmp = target.with_name(target.name + f".part.{uuid4().hex[:8]}")
    try:
        source_size, source_hash = _hash_and_size(staging)
        shutil.copy2(str(staging), str(dest_tmp))
        _fsync_path(dest_tmp)
        dest_size, dest_hash = _hash_and_size(dest_tmp)
    except OSError as e:
        log.warning(
            f"Could not copy the retained file at {staging} into quarantine ({e}); "
            "leaving it at its original location."
        )
        _safe_unlink_warn(dest_tmp, "cleanup after a failed quarantine copy")
        return staging, False

    if dest_size != source_size or dest_hash != source_hash:
        log.warning(
            f"Quarantine copy of {staging} did not verify (expected {source_size}b/"
            f"{source_hash}, got {dest_size}b/{dest_hash}); leaving the original in "
            "place — it was NOT deleted."
        )
        _safe_unlink_warn(dest_tmp, "cleanup after a failed quarantine copy verification")
        return staging, False

    try:
        os.replace(dest_tmp, target)
        # [P1, third audit finding #3] Same reasoning as the same-volume
        # branch above: fsync the quarantine directory so this publish's
        # directory entry survives a power loss, not just the file's bytes.
        _fsync_dir(qdir)
    except OSError as e:
        log.warning(
            f"Verified quarantine copy of {staging} could not be published to {target} "
            f"({e}); leaving the original in place — it was NOT deleted."
        )
        _safe_unlink_warn(dest_tmp, "cleanup after a failed quarantine publish")
        return staging, False

    # Only now — `target` is a byte-verified copy of `staging` — is it safe
    # to consider the source redundant. A failure to delete it is harmless
    # (the quarantined copy is authoritative) but must not go unreported.
    cleanup_ctx = "cleanup of original staging after a VERIFIED quarantine copy"
    if not _safe_unlink_warn(staging, cleanup_ctx):
        log.warning(
            f"Quarantined copy of '{staging.name}' is verified and safe to use at "
            f"{target}, but the original at {staging} could not be deleted; a "
            "redundant copy remains there (harmless)."
        )
    return target, True


def find_orphaned_quarantine_files() -> list:
    """Files physically present in the quarantine dir with no matching
    registry entry — e.g. a crash between `quarantine_file` and the registry
    write that was supposed to record it, or between a successful recovery
    delete and its `remove_entry` call. Never auto-deleted; only surfaced."""
    qdir = quarantine_dir()
    if not qdir.is_dir():
        return []
    known = {Path(e.staging_path).name for e in read_entries().entries}
    try:
        return sorted(
            p for p in qdir.iterdir()
            if p.is_file() and p.name not in known and not p.name.endswith(".lock")
        )
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Hashing (observed-at-retention-time facts, independent of any upstream
# `expected_hash`, which may be absent).
# ---------------------------------------------------------------------------


def _hash_and_size(path: Path, algorithm: str = HASH_ALGORITHM) -> tuple[int, str]:
    h = hashlib.new(algorithm)
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


async def hash_and_size_async(path: Path, algorithm: str = HASH_ALGORITHM) -> tuple[int, str]:
    """Public: also used by `tiddl recover` (`cli/commands/recover.py`) to
    re-verify a candidate against an entry's observed size/hash without
    reaching into this module's private helpers. `algorithm` should be the
    SPECIFIC entry's own `hash_algorithm` when re-verifying an existing
    entry — the module default is only correct for brand-new entries being
    retained for the first time under the current build's algorithm."""
    return await asyncio.to_thread(_hash_and_size, path, algorithm)


def delete_quarantined_file(path: Path, context: str) -> bool:
    """Public wrapper around the shared best-effort-delete-and-warn helper,
    so callers outside this module (namely `tiddl recover`) don't need to
    reach into `tiddl.core.utils.fsio` directly."""
    return _safe_unlink_warn(path, context)


# ---------------------------------------------------------------------------
# Registering a newly-retained file (called from Downloader._download_with_retry).
# ---------------------------------------------------------------------------


@dataclass
class RegisterResult:
    #: Where the file ACTUALLY is right now, regardless of whether registry
    #: persistence succeeded — the caller (Downloader) must always point
    #: `task.retained_staging` at this, never at the pre-quarantine path.
    actual_path: Path
    #: The persisted registry entry, or None if bookkeeping failed (the file
    #: itself is still fine at `actual_path` — this only affects whether a
    #: restart will know about it).
    entry: Optional[RetainedEntry]

    @property
    def persisted(self) -> bool:
        return self.entry is not None


async def register_retained_file(
    retained: Path,
    output_path: Path,
    reason: RetainReason,
    track_title: Optional[str] = None,
) -> RegisterResult:
    """Quarantine `retained` and record it in the registry. Best-effort end
    to end: a registry-persistence failure is logged and leaves `entry=None`
    rather than raising — persistence is a breadcrumb for the NEXT restart,
    it must never turn an already-decided publish outcome (success or
    failure) into an exception for the CURRENT run. `actual_path` on the
    returned result is ALWAYS the file's real current location — even when
    persistence fails after the file has already been (possibly)
    quarantined — so the caller's own in-process pointer never goes stale."""
    entry_id = uuid4().hex
    suffix = output_path.suffix or Path(retained).suffix
    retained = Path(retained)

    try:
        final_path, quarantined = await asyncio.to_thread(
            quarantine_file, retained, output_suffix=suffix, entry_id=entry_id
        )
    except OSError as e:
        log.warning(
            f"Unexpected failure quarantining the retained file for "
            f"'{track_title}' ({e}); it remains at its original location {retained}."
        )
        return RegisterResult(actual_path=retained, entry=None)

    try:
        size, digest = await hash_and_size_async(final_path)
        entry = RetainedEntry(
            id=entry_id,
            reason=reason,
            staging_path=str(final_path),
            output_path=str(output_path),
            observed_size=size,
            observed_hash=digest,
            track_title=track_title,
            quarantined=quarantined,
        )
        persisted_entry = await asyncio.to_thread(add_entry, entry)
        return RegisterResult(actual_path=final_path, entry=persisted_entry)
    except (OSError, RegistryLockTimeout, RegistryPreservationError, RegistryReadError) as e:
        log.warning(
            f"Could not persist retained-file recovery bookkeeping for "
            f"'{track_title}' ({e}); the file itself is unaffected and is "
            f"currently at {final_path} — it will not be listed by `tiddl "
            "recover` after a restart unless this succeeds on a later attempt."
        )
        return RegisterResult(actual_path=final_path, entry=None)


# ---------------------------------------------------------------------------
# Reconciliation.
# ---------------------------------------------------------------------------


async def _verify_observed(path: Path, entry: RetainedEntry) -> tuple[bool, Optional[str]]:
    if not path.exists():
        return False, "missing"
    size, digest = await hash_and_size_async(path, entry.hash_algorithm)
    if size != entry.observed_size:
        return False, f"size mismatch: recorded {entry.observed_size}, now {size}"
    if digest != entry.observed_hash:
        return False, f"{entry.hash_algorithm} mismatch: content has changed since it was retained"
    return True, None


async def reconcile() -> ReconcileReport:
    """Deep check: does each entry's file still exist, and does it still
    match what was observed when it was retained? Involves hashing every
    retained file — by design this is ONLY called explicitly (`tiddl
    recover`), never from ordinary application startup.

    A single bad entry (unreadable file, permission error, whatever) must
    never abort the whole reconciliation — it is reported as `corrupt` and
    the rest of the entries still get checked.
    """
    result = read_entries()
    out = []
    for e in result.entries:
        try:
            out.append(await _reconcile_one(e))
        except OSError as exc:
            log.warning(f"Error reconciling retained entry {e.id}: {exc}")
            out.append(ReconcileEntry(e, "corrupt", f"error while reconciling: {exc}"))
    return ReconcileReport(
        status=result.status, entries=out, orphans=find_orphaned_quarantine_files()
    )


async def _reconcile_one(e: RetainedEntry) -> ReconcileEntry:
    p = Path(e.staging_path)
    if p.exists():
        ok, detail = await _verify_observed(p, e)
        return ReconcileEntry(e, "ok" if ok else "corrupt", detail)

    # The retained copy is gone. This is normally a real loss — but it is
    # also exactly what happens when a PRIOR recovery attempt actually
    # succeeded (published the destination and/or deleted the local copy)
    # and then crashed or was killed before it could remove the registry
    # entry. Telling those two situations apart matters: naively reporting
    # "gone" here would make a fully-recovered file look unrecoverable
    # forever (there is no source left to re-publish from). So: if the
    # destination independently matches the size+hash observed at retention
    # time, this is stale bookkeeping from an already-converged recovery,
    # not data loss — surface it distinctly so it can be safely dropped
    # without requiring any (nonexistent) source bytes or further I/O.
    dest = Path(e.output_path)
    if dest.exists():
        try:
            dsize, ddigest = await hash_and_size_async(dest, e.hash_algorithm)
        except OSError as exc:
            log.warning(f"Could not re-verify destination {dest} for entry {e.id}: {exc}")
            dsize, ddigest = None, None
        if dsize == e.observed_size and ddigest == e.observed_hash:
            return ReconcileEntry(
                e, "already_published",
                "the retained copy is gone, but the destination independently "
                "matches the content observed when this entry was retained "
                "(a prior recovery attempt already succeeded before it could "
                "update this registry) — safe to drop this stale entry",
            )
    return ReconcileEntry(e, "gone", "the retained file no longer exists on disk")


def startup_status() -> StartupStatus:
    """Lightweight: registry status + entry count only. No hashing, no
    filesystem access beyond reading the registry JSON itself, no
    destination I/O. Cheap and safe to call from the app's root callback
    for ordinary subcommand invocations (`auth`, `recover`, non-download
    commands).

    [P2, third audit finding #8] NOT called for `--help`/`--version` —
    those are eager Click/Typer options that exit during parameter
    processing, before the root callback's body (where this is invoked
    from, in `cli/app.py`) ever runs. Verified via a `CliRunner` check
    (`tests/test_app_startup_notice.py`), not assumed — an earlier version
    of this docstring claimed the opposite."""
    result = read_entries()
    return StartupStatus(status=result.status, count=len(result.entries))
