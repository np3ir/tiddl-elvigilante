"""Coverage for `tiddl.core.utils.fsio.atomic_write_bytes`, extracted from
`save_auth_data` (see `tests/test_auth_core.py` for the auth-specific
regression coverage this extraction must not change) so it can be reused by
the retained-staging registry."""
from __future__ import annotations

import os

import pytest

from tiddl.core.utils.fsio import atomic_write_bytes


def test_writes_new_file(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_creates_parent_directories(tmp_path):
    target = tmp_path / "a" / "b" / "c" / "f.txt"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_replaces_existing_content(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"old")
    atomic_write_bytes(target, b"new-content")
    assert target.read_bytes() == b"new-content"


def test_no_temp_file_left_behind_on_success(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"hello")
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_temp_file_cleaned_up_on_write_failure(tmp_path, monkeypatch):
    """The fake below must accurately model real `os.fdopen` behavior: once
    `os.fdopen(fd, ...)` returns successfully, the resulting object OWNS the
    raw fd — its `close()` is what releases it. An earlier version of this
    fake never closed the real underlying fd in `close()`, which hid a real
    production bug (see `test_temp_fd_closed_when_fdopen_itself_raises`
    below and `fsio.atomic_write_bytes`'s fd-ownership tracking): on
    Windows, `os.unlink()`/`os.replace()` cannot touch a file that is still
    open, so a leaked fd would silently make the except-block's temp-file
    cleanup fail every time a write failed mid-flight."""
    target = tmp_path / "f.txt"

    class _BoomFile:
        def __init__(self, fd):
            self._fd = fd

        def write(self, data):
            raise OSError("simulated disk-full mid-write")

        def flush(self):
            pass

        def fileno(self):
            return self._fd

        def close(self):
            os.close(self._fd)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    monkeypatch.setattr(os, "fdopen", lambda fd, *a, **k: _BoomFile(fd))
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"hello")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # temp file removed, not left behind


def test_temp_fd_closed_when_fdopen_itself_raises(tmp_path, monkeypatch):
    """[Windows correctness, P1 finding #9] If `os.fdopen()` itself raises
    before the file object ever takes ownership of the raw fd (`mkstemp`'s
    fd is still just a bare descriptor at that point), `atomic_write_bytes`
    must close that raw fd directly in its except-handler. Otherwise, on
    Windows, the subsequent `os.unlink(tmp_name)` cleanup attempt fails
    outright (Windows refuses to unlink a file that's still open) and is
    swallowed by `except OSError: pass` — silently leaking both the fd and
    the temp file forever."""
    target = tmp_path / "f.txt"
    real_close = os.close
    closed_fds = []

    def _tracking_close(fd):
        closed_fds.append(fd)
        real_close(fd)

    def _boom_fdopen(fd, *a, **k):
        raise OSError("simulated fdopen failure")

    monkeypatch.setattr(os, "fdopen", _boom_fdopen)
    monkeypatch.setattr(os, "close", _tracking_close)

    with pytest.raises(OSError):
        atomic_write_bytes(target, b"hello")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # temp file removed, not left behind
    assert len(closed_fds) == 1  # the raw fd was explicitly closed exactly once


def test_original_file_untouched_on_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"original")

    def boom_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")

    assert target.read_bytes() == b"original"          # untouched
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []                              # temp cleaned up


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod semantics")
def test_chmod_posix_applied_to_temp_before_publish(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"secret", chmod_posix=0o600)
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_chmod_posix_none_leaves_default_mode(tmp_path):
    target = tmp_path / "f.txt"
    # Should not raise even on non-POSIX platforms / when omitted.
    atomic_write_bytes(target, b"hello", chmod_posix=None)
    assert target.read_bytes() == b"hello"


def test_fsync_dir_false_by_default_does_not_raise(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"hello")  # fsync_dir defaults to False
    assert target.read_bytes() == b"hello"


def test_fsync_dir_true_is_best_effort_and_does_not_raise(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_bytes(target, b"hello", fsync_dir=True)
    assert target.read_bytes() == b"hello"
