"""Shared, Downloader-independent filesystem primitives.

Extracted from ``tiddl/cli/commands/download/downloader.py`` (PR #12, safe
cross-filesystem publish) so they can be reused by code that must not depend
on constructing a full ``Downloader`` (TIDAL auth, SQLite DB, HTTP session) —
notably the retained-staging registry and the offline `tiddl recover`
command. Behavior is unchanged from the original: this is a pure extraction,
not a rewrite. `downloader.py` imports these names instead of defining them.
"""
from __future__ import annotations

import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Optional

log = getLogger(__name__)


def _safe_unlink(path: Optional[Path]) -> bool:
    """Delete a file if it exists, swallowing OS errors (best-effort cleanup).

    Returns True if `path` is gone once this returns (deleted here, or it never
    existed) and False if an existing file could NOT be removed (e.g. locked by
    an antivirus/indexer, or a remote filesystem that rejects the unlink).
    Callers that must not silently claim "no orphan left behind" — i.e. after a
    successful publish, when the leftover would otherwise go unreported — should
    check this return value instead of treating cleanup as unconditional."""
    if path is None:
        return True
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _safe_unlink_warn(path: Path, context: str) -> bool:
    """`_safe_unlink` plus an honest log warning when an existing file could
    not be removed. Cleanup here is always best-effort: a failure logged by
    this helper never turns an otherwise-successful publish into a failure —
    it only makes an otherwise-silent leftover observable."""
    ok = _safe_unlink(path)
    if not ok:
        log.warning(
            f"Could not remove leftover destination-side temp file at {path} "
            f"({context}); left in place (best-effort cleanup)."
        )
    return ok


def _same_volume(a: Path, b: Path) -> bool:
    """True if paths `a` and `b` live on the same filesystem (st_dev match).

    Used by the safe-publish step to pick the atomic-rename fast path. Kept as a
    module-level function so tests can force the cross-filesystem path."""
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _fsync_path(path: Path) -> None:
    """Best-effort flush of a file's data to storage before it is verified.

    shutil.copy2 only closes the file; on a network share the bytes may still sit
    in a write cache, so an immediate verify could read cache rather than what
    actually landed. Filesystems that don't support fsync just no-op."""
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory (POSIX only) so a rename into it is
    durable across a power loss. A no-op on Windows / unsupported filesystems."""
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    chmod_posix: Optional[int] = None,
    fsync_dir: bool = False,
) -> None:
    """Write `data` to `path` so a crash or full disk mid-write can never leave
    a truncated/partial file: a temp file in the SAME directory is written,
    flushed, fsynced, then published with `os.replace` (atomic on every
    platform this project supports). The temp file is removed on any failure.

    `chmod_posix`, when given, is applied to the temp file's descriptor
    *before* it is written and published — matching the original
    `save_auth_data` behavior exactly (mode is set on the still-private temp
    file, not on the final path after replace, so the data is never briefly
    world-readable). Ignored on non-POSIX platforms (no `os.fchmod`).

    `fsync_dir`, when True, best-effort fsyncs `path.parent` after the
    replace (POSIX only, no-op elsewhere) for directory-entry durability
    across a power loss. Default False to keep this a pure extraction of the
    existing `save_auth_data` behavior, which does not fsync its directory.

    This is a plain extraction of `save_auth_data`'s temp+fsync+replace
    dance (see `tiddl/cli/utils/auth/core.py`) into a shared helper — same
    contract, so it can be reused by the retained-staging registry without
    a second copy of this logic."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    # `fd` is a raw OS-level file descriptor from mkstemp. Once `os.fdopen(fd,
    # ...)` returns successfully, the resulting file object OWNS `fd` — its
    # `close()`/context-manager exit will close the descriptor, and closing
    # `fd` a second time via `os.close` would be an error (or, worse, could
    # silently close some *other* unrelated fd the OS has since reused the
    # same number for). But if `os.fdopen` itself raises (or anything
    # between `mkstemp` and a successful `fdopen` raises) BEFORE ownership
    # transfers, nothing else will ever close `fd` — and on Windows,
    # `os.unlink`/`os.replace` on a still-open file fails outright (unlike
    # POSIX, which allows unlinking an open file), so the leftover temp file
    # would silently survive the `except OSError: pass` below. Track
    # ownership explicitly so the except-block always closes whichever of
    # (raw fd) or (file object) is still open, in the right order.
    fd_owned_by_file_object = False
    f = None
    try:
        if chmod_posix is not None and os.name == "posix":
            os.fchmod(fd, chmod_posix)
        f = os.fdopen(fd, "wb")
        fd_owned_by_file_object = True
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
        f.close()
        os.replace(tmp_name, path)
    except BaseException:
        if fd_owned_by_file_object:
            try:
                f.close()
            except OSError:
                pass
        else:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    if fsync_dir:
        _fsync_dir(path.parent)
