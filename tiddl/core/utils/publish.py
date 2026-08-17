"""Cross-filesystem safe publish of an already-verified local file.

Extracted from `Downloader._publish_staged` (PR #12, safe cross-filesystem
publish; see `AUDIT_cross_volume.md`) into a free function with no
dependency on `Downloader` — no TIDAL auth, no SQLite DB, no HTTP session —
so both the live download path and the offline `tiddl recover` command share
the exact same publish contract instead of two implementations drifting
apart. Behavior for the download path is unchanged: `Downloader._publish_staged`
now verifies/repairs locally, then delegates the move/copy/replace mechanics
here.

Contract (unchanged from PR #12): `source` MUST already be verified once by
the caller before calling this — this function only re-verifies the
DESTINATION-side copy after each cross-filesystem attempt, via `reverify`.
Returns `(published, retained)`:
  * `(True, None)`     — published; `source` deleted.
  * `(True, source')`  — published, but `source` (or the original path it
                          was passed as) could not be deleted afterward
                          (best-effort cleanup failure). Safe to delete
                          manually once noticed.
  * `(False, source')` — the destination could not be published; `source` is
                          retained untouched — caller must not delete it or
                          re-derive it, and the prior `destination` (if any)
                          is never touched by a failed publish.

This function never returns `(False, None)` — unlike `_publish_staged`'s
full four-outcome contract, there is no "local file is invalid" outcome here
because verifying `source` is the caller's job, not this function's.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from logging import getLogger
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .fsio import _fsync_dir, _fsync_path, _safe_unlink, _safe_unlink_warn, _same_volume

log = getLogger(__name__)

# (ok, error_message_if_any)
ReverifyFn = Callable[[Path], Awaitable[tuple[bool, Optional[str]]]]
WarnFn = Callable[[str], None]


async def publish_verified_file(
    source: Path,
    destination: Path,
    *,
    reverify: ReverifyFn,
    on_warning: Optional[WarnFn] = None,
) -> tuple[bool, Optional[Path]]:
    warn: WarnFn = on_warning or (lambda _msg: None)

    # [P1, third audit finding #2] This function does NOT create the
    # destination directory, at any depth, ever. An earlier version tried a
    # single-level (non-recursive) `mkdir` as a middle ground, reasoning
    # that a missing single leaf directory (parent exists) was a safe,
    # common case while a missing *chain* (what an unmounted network share
    # looks like on POSIX) was not. The third audit review correctly
    # rejected that as still heuristic: directory DEPTH says nothing about
    # whether the expected filesystem is actually mounted. If the mount
    # point itself is present as an ordinary local directory (common right
    # after an unmount) and one level of the old library tree still exists
    # below it, single-level creation can still land a "successful" publish
    # entirely on local disk with no data ever reaching the real
    # destination.
    #
    # The safe, fail-closed behavior instead: NEVER create the destination
    # directory here. If `destination.parent` doesn't already exist, refuse
    # immediately and let the caller decide what to do about it (nothing
    # about this decision is filesystem-specific or recoverable by retrying
    # the copy). This does mean a live download whose destination folder
    # hasn't been created yet must create it BEFORE calling this function —
    # which `cli/commands/download` already does unconditionally for the
    # live download path — and it means `tiddl recover`, running long after
    # the original attempt, will refuse to recreate a reorganized/missing
    # destination folder rather than silently guessing it's safe to do so.
    # A future explicit `--create-destination` recovery flag, requiring the
    # user to confirm the destination is actually mounted first, is the
    # right place to relax this — not an automatic heuristic here.
    #
    # [P2, fourth audit finding #4 — residual limitation, not fixed here]
    # This "existing parent" check is a fail-closed improvement over
    # recursive auto-creation, but it does NOT prove the expected
    # filesystem (e.g. a NAS share) is actually mounted — only that SOME
    # directory with the expected path already exists. A directory tree can
    # remain present as an ordinary local directory after the real mount
    # disappears (common right after an unmount on POSIX), and the live
    # download path currently creates its destination parents unconditionally
    # before ever calling this function — so a publish can still land
    # entirely on local disk in that specific scenario. Closing this
    # properly needs an explicit destination-root identity check (a
    # configured expected mount/volume identity, not a directory-depth or
    # existence heuristic), applied consistently to both the live download
    # path and offline recovery — tracked as follow-up work, deliberately
    # out of scope for this fail-closed-on-a-missing-parent fix.
    if not destination.parent.exists():
        msg = (
            f"destination directory {destination.parent} does not exist "
            "(refusing to create it — this could silently land the file on "
            "the wrong filesystem if a network share/mount is actually just "
            "unmounted; create the directory yourself once you've confirmed "
            "the real destination is available, then retry)"
        )
        warn(msg)
        log.warning(f"Publish refused: {msg}")
        return False, source

    # Same filesystem: a single atomic rename (no bytes copied). Retry only
    # transient locks; if it never happens the source still exists.
    if _same_volume(source, destination.parent):
        for move_attempt in range(5):
            try:
                os.replace(source, destination)
                await asyncio.to_thread(_fsync_dir, destination.parent)
                return True, None
            except OSError as e:
                msg = f"publish rename failed: {e}"
                warn(msg)
                if move_attempt == 4:
                    log.warning(f"Failed to publish (rename) after 5 attempts: {e}")
                    return False, source
                log.warning(f"Publish rename locked (attempt {move_attempt+1}), retrying: {e}")
                await asyncio.sleep(1.0 + move_attempt)
        return False, source

    # Cross filesystem: copy -> fsync -> verify a dest-side temp, then
    # atomically publish it with os.replace().
    dest_tmp = destination.with_name(destination.name + f".part.{uuid.uuid4().hex[:8]}")
    for publish_attempt in range(5):
        _safe_unlink_warn(dest_tmp, "stale temp from a previous attempt")
        try:
            await asyncio.to_thread(shutil.copy2, str(source), str(dest_tmp))
            await asyncio.to_thread(_fsync_path, dest_tmp)  # commit before verifying
        except OSError as e:
            msg = f"copy to destination failed: {e}"
            warn(msg)
            log.warning(f"{msg} (attempt {publish_attempt+1})")
            _safe_unlink_warn(dest_tmp, "cleanup after a failed copy")
            if publish_attempt == 4:
                break
            await asyncio.sleep(1.0 + publish_attempt)
            continue

        # [P1, third audit finding #4] `reverify` does real file I/O
        # (typically hashing `dest_tmp`) and can raise `OSError` — e.g. the
        # temp vanishes mid-verify due to an unrelated concurrent process,
        # an antivirus/indexer lock, a flaky network share. An earlier
        # version let that propagate straight out of this function,
        # skipping every bit of cleanup below and leaking `dest_tmp` on
        # disk forever (catching the exception at the CLI layer, as
        # `tiddl recover` now does, stops the traceback but does NOT
        # recover the publisher's own cleanup contract). Treat a reverify
        # exception the same as a failed verification: it flows into the
        # exact same "corrupt destination copy" cleanup/retry path below.
        try:
            ok, err = await reverify(dest_tmp)
        except OSError as e:
            ok, err = False, f"reverify raised an unexpected error: {e}"
        if ok:
            # Atomic publish, with its own retry. A failure here must NEVER
            # delete the prior final file — only a successful os.replace
            # overwrites it, atomically.
            for replace_attempt in range(5):
                try:
                    os.replace(dest_tmp, destination)
                    await asyncio.to_thread(_fsync_dir, destination.parent)
                    # Only now is the source copy safe to drop. Best-effort:
                    # report it, don't lie about it.
                    if await asyncio.to_thread(_safe_unlink, source):
                        return True, None
                    warn(
                        f"Published, but could not delete the local copy at "
                        f"{source}; left in place (best-effort cleanup)."
                    )
                    return True, source
                except OSError as e:
                    msg = f"atomic publish failed: {e}"
                    warn(msg)
                    log.warning(f"{msg} (attempt {replace_attempt+1})")
                    if replace_attempt == 4:
                        _safe_unlink_warn(dest_tmp, "replace exhausted its retries")
                        return False, source  # keep source; prior final untouched
                    await asyncio.sleep(1.0 + replace_attempt)

        # Destination copy is corrupt (e.g. a NAS that corrupts on flush).
        # Drop it and re-copy from the surviving source.
        warn(err or "destination validation failed")
        log.warning(f"Destination validation failed (attempt {publish_attempt+1}): {err}")
        _safe_unlink_warn(dest_tmp, "cleanup after a corrupt destination copy")
        if publish_attempt < 4:
            await asyncio.sleep(1.0 + publish_attempt)

    # Publish exhausted: best-effort clean the dest temp, KEEP the source.
    _safe_unlink_warn(dest_tmp, "cleanup after publish exhausted its retries")
    return False, source
