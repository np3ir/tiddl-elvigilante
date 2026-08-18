"""Coverage for the operation 1/2/4/5/6/8/9 guarded-write helpers in
`tiddl.cli.commands.download` (`__init__.py`) and `.downloader` —
`_guarded_mkdir`, `_write_lrc_guarded`, `_write_track_metadata_guarded`,
`_write_video_metadata_guarded`, `_guarded_save_cover`, `_touch_guarded`.

Operations 5/6/8 were extracted from inline closures inside the
(untestable-in-isolation) `handle_item`/`download_callback` call graph
specifically so the implementation-audit finding (2026-08-18, P1 #3 —
"guards placed before asyncio.to_thread are not at the final mutation
boundary") has direct, targeted regression coverage: the identity check
must run INSIDE the same unit of work as the mutation, with no await
point, sleep, or network I/O between "checked" and "written."

Operations 1, 2, 4 and 9 have no such gap (their check and mutation were
already adjacent statements, never separated by a to_thread dispatch) but
were extracted the same way purely so each guarded operation class has its
own direct unit test — implementation-audit P2 finding ("seven guarded
operation classes lack direct integration evidence"). That leaves only
operation 3 (media publication — covered end-to-end in
test_downloader.py) and operation 7 (M3U — covered in test_m3u.py) without
a dedicated test in *this* file; both already have direct coverage
elsewhere, matching the audit's own note that those two were the ones NOT
missing evidence."""
from __future__ import annotations

import asyncio
import os

import pytest

import tiddl.cli.commands.download as dlinit
import tiddl.core.utils.destination_anchor as da
from tiddl.cli.commands.download import (
    _guarded_save_cover,
    _touch_guarded,
    _write_lrc_guarded,
    _write_track_metadata_guarded,
    _write_video_metadata_guarded,
)
from tiddl.cli.commands.download.downloader import _guarded_mkdir
from tiddl.core.metadata import Cover, CoverDataNotPrefetched


@pytest.fixture(autouse=True)
def _isolated_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "APP_PATH", tmp_path / "_app")


@pytest.fixture
def trusted_root(tmp_path):
    root = tmp_path / "dest_root"
    root.mkdir()
    da.establish_anchor(root)
    return root


@pytest.fixture
def untrusted_root(tmp_path):
    root = tmp_path / "dest_root"
    root.mkdir()
    return root  # never establish_anchor()'d — no trust record, no marker


# ---------------------------------------------------------------------------
# Operation 5: track metadata
# ---------------------------------------------------------------------------

def test_track_metadata_guard_writes_when_trusted(trusted_root, monkeypatch):
    calls = []
    monkeypatch.setattr(dlinit, "add_track_metadata", lambda **kw: calls.append(kw))

    download_path = trusted_root / "track.flac"
    _write_track_metadata_guarded(
        trusted_root, download_path, "strict",
        track="TRACK", lyrics="", album_artist="A", cover_data=None,
        date="", credits=None, comment="", genre=None, artist_separator="; ",
    )

    assert len(calls) == 1
    assert calls[0]["path"] == download_path
    assert calls[0]["track"] == "TRACK"


def test_track_metadata_guard_refuses_and_never_writes_when_untrusted(
    untrusted_root, monkeypatch
):
    calls = []
    monkeypatch.setattr(dlinit, "add_track_metadata", lambda **kw: calls.append(kw))

    download_path = untrusted_root / "track.flac"
    with pytest.raises(da.DestinationNotTrusted) as excinfo:
        _write_track_metadata_guarded(
            untrusted_root, download_path, "strict",
            track="TRACK", lyrics="", album_artist="A", cover_data=None,
            date="", credits=None, comment="", genre=None, artist_separator="; ",
        )

    assert excinfo.value.check.reason == "unknown_root"
    assert calls == []  # the mutation never ran


async def test_track_metadata_guard_propagates_through_to_thread(
    untrusted_root, monkeypatch
):
    # Mirrors the real call site: `await asyncio.to_thread(_write_track_
    # metadata_guarded, ...)`. Proves DestinationNotTrusted survives the
    # thread hop intact so the event-loop caller can catch it and mark the
    # tracker there (v2.4 mandatory safeguard #2) — never inside the worker.
    monkeypatch.setattr(dlinit, "add_track_metadata", lambda **kw: pytest.fail("must not write"))

    download_path = untrusted_root / "track.flac"
    with pytest.raises(da.DestinationNotTrusted):
        await asyncio.to_thread(
            _write_track_metadata_guarded,
            untrusted_root, download_path, "strict",
            track="TRACK", lyrics="", album_artist="A", cover_data=None,
            date="", credits=None, comment="", genre=None, artist_separator="; ",
        )


# ---------------------------------------------------------------------------
# Operation 6: video metadata
# ---------------------------------------------------------------------------

def test_video_metadata_guard_writes_when_trusted(trusted_root, monkeypatch):
    calls = []
    monkeypatch.setattr(dlinit, "add_video_metadata", lambda **kw: calls.append(kw))

    download_path = trusted_root / "video.mp4"
    _write_video_metadata_guarded(
        trusted_root, download_path, "strict",
        video="VIDEO", artist_separator="; ",
    )

    assert len(calls) == 1
    assert calls[0]["path"] == download_path


def test_video_metadata_guard_refuses_and_never_writes_when_untrusted(
    untrusted_root, monkeypatch
):
    calls = []
    monkeypatch.setattr(dlinit, "add_video_metadata", lambda **kw: calls.append(kw))

    download_path = untrusted_root / "video.mp4"
    with pytest.raises(da.DestinationNotTrusted) as excinfo:
        _write_video_metadata_guarded(
            untrusted_root, download_path, "strict",
            video="VIDEO", artist_separator="; ",
        )

    assert excinfo.value.check.reason == "unknown_root"
    assert calls == []


# ---------------------------------------------------------------------------
# Operation 8: cover write
# ---------------------------------------------------------------------------

async def test_cover_guard_writes_when_trusted(trusted_root, monkeypatch):
    cover = Cover("uid-1")
    monkeypatch.setattr(cover, "_get_data", lambda: b"jpegbytes")
    tracker = da.IdentityFailureTracker()
    cover_path = trusted_root / "cover"

    await _guarded_save_cover(cover, trusted_root, cover_path, "strict", tracker, "album")

    assert cover_path.with_suffix(".jpg").read_bytes() == b"jpegbytes"
    assert tracker.any_refused is False


async def test_cover_guard_refuses_and_never_writes_when_untrusted(
    untrusted_root, monkeypatch
):
    cover = Cover("uid-1")
    monkeypatch.setattr(cover, "_get_data", lambda: b"jpegbytes")
    tracker = da.IdentityFailureTracker()
    cover_path = untrusted_root / "cover"

    await _guarded_save_cover(cover, untrusted_root, cover_path, "strict", tracker, "album")

    assert not cover_path.with_suffix(".jpg").exists()
    assert tracker.any_refused is True
    assert tracker.first_refusal.reason == "unknown_root"


async def test_cover_guard_skips_fetch_and_check_when_file_already_exists(
    untrusted_root, monkeypatch
):
    # Matches the pre-existing Cover.save_to_directory contract: an
    # existing file short-circuits before any network I/O or identity
    # check — including on an untrusted root, since nothing is being
    # written. Proves _get_data() is never called (would raise if it were).
    cover_path = untrusted_root / "cover"
    cover_path.with_suffix(".jpg").write_bytes(b"already-here")

    cover = Cover("uid-1")
    monkeypatch.setattr(cover, "_get_data", lambda: pytest.fail("must not fetch"))
    tracker = da.IdentityFailureTracker()

    await _guarded_save_cover(cover, untrusted_root, cover_path, "strict", tracker, "album")

    assert cover_path.with_suffix(".jpg").read_bytes() == b"already-here"
    assert tracker.any_refused is False


async def test_cover_guard_closes_the_fetch_to_write_toctou_gap(trusted_root, monkeypatch):
    # THE regression test for the audit's P1 #3 finding: the destination
    # becomes untrusted DURING the (network) fetch — after the old
    # pre-dispatch check would already have passed, but before the actual
    # write. The old code (check on the event loop, then
    # `to_thread(cover.save_to_directory, ...)` which fetches-then-writes
    # inside the worker) would have published the cover anyway, because its
    # only check happened before the fetch ran. The new code fetches first,
    # then checks immediately before writing — so this must refuse.
    cover = Cover("uid-1")

    def _fetch_then_destination_disappears():
        # Simulates the mount vanishing mid-network-fetch (a slow cover
        # download over several retries is exactly the kind of gap the
        # audit flagged).
        da.marker_path(trusted_root).unlink()
        return b"jpegbytes"

    monkeypatch.setattr(cover, "_get_data", _fetch_then_destination_disappears)
    tracker = da.IdentityFailureTracker()
    cover_path = trusted_root / "cover"

    await _guarded_save_cover(cover, trusted_root, cover_path, "strict", tracker, "album")

    assert not cover_path.with_suffix(".jpg").exists()  # never published
    assert tracker.any_refused is True
    assert tracker.first_refusal.reason == "marker_absent"


async def test_cover_guard_off_mode_never_checks(untrusted_root, monkeypatch):
    cover = Cover("uid-1")
    monkeypatch.setattr(cover, "_get_data", lambda: b"jpegbytes")
    tracker = da.IdentityFailureTracker()
    cover_path = untrusted_root / "cover"

    await _guarded_save_cover(cover, untrusted_root, cover_path, "off", tracker, "album")

    assert cover_path.with_suffix(".jpg").read_bytes() == b"jpegbytes"
    assert tracker.any_refused is False


# ---------------------------------------------------------------------------
# Operations 1/2: audio/video directory creation
# ---------------------------------------------------------------------------

def test_mkdir_guard_creates_the_directory_when_trusted(trusted_root):
    target = trusted_root / "sub" / "dir" / "track.flac"
    _guarded_mkdir(trusted_root, target, "strict")
    assert target.parent.is_dir()


def test_mkdir_guard_refuses_and_never_creates_when_untrusted(untrusted_root):
    target = untrusted_root / "sub" / "dir" / "track.flac"
    with pytest.raises(da.DestinationNotTrusted) as excinfo:
        _guarded_mkdir(untrusted_root, target, "strict")

    assert excinfo.value.check.reason == "unknown_root"
    assert not target.parent.exists()  # the mutation never ran


def test_mkdir_guard_off_mode_never_checks(untrusted_root):
    target = untrusted_root / "sub" / "dir" / "video.ts"
    _guarded_mkdir(untrusted_root, target, "off")
    assert target.parent.is_dir()


# ---------------------------------------------------------------------------
# Operation 4: .lrc write
# ---------------------------------------------------------------------------

def test_lrc_guard_writes_when_trusted(trusted_root):
    lrc_path = trusted_root / "track.lrc"
    _write_lrc_guarded(trusted_root, lrc_path, "strict", "[00:01.00]la la la")
    assert lrc_path.read_text(encoding="utf-8") == "[00:01.00]la la la"


def test_lrc_guard_refuses_and_never_writes_when_untrusted(untrusted_root):
    lrc_path = untrusted_root / "track.lrc"
    with pytest.raises(da.DestinationNotTrusted) as excinfo:
        _write_lrc_guarded(untrusted_root, lrc_path, "strict", "[00:01.00]la la la")

    assert excinfo.value.check.reason == "unknown_root"
    assert not lrc_path.exists()


# ---------------------------------------------------------------------------
# Operation 9: utime
# ---------------------------------------------------------------------------

def test_touch_guard_updates_mtime_when_trusted(trusted_root):
    target = trusted_root / "track.flac"
    target.write_bytes(b"x")
    old_mtime = target.stat().st_mtime
    # Force a detectable mtime change regardless of filesystem timestamp
    # resolution by setting it in the past first.
    os.utime(target, (old_mtime - 1000, old_mtime - 1000))

    _touch_guarded(trusted_root, target, "strict")

    assert target.stat().st_mtime > old_mtime - 1000


def test_touch_guard_refuses_and_never_touches_when_untrusted(untrusted_root):
    target = untrusted_root / "track.flac"
    target.write_bytes(b"x")
    os.utime(target, (0, 0))  # a known, ancient mtime

    with pytest.raises(da.DestinationNotTrusted) as excinfo:
        _touch_guarded(untrusted_root, target, "strict")

    assert excinfo.value.check.reason == "unknown_root"
    assert target.stat().st_mtime == 0  # untouched


# ---------------------------------------------------------------------------
# Second implementation-audit finding (2026-08-18), P1 #2: write_prefetched()
# was not actually network-free — a failed first fetch left cover.data
# falsy, and its own fallback silently fetched AGAIN, after the identity
# check had already run once (for _guarded_save_cover's guarded write).
# These tests pin the fixed contract: _get_data() is called AT MOST ONCE by
# _guarded_save_cover, and write_prefetched() never calls it at all.
# ---------------------------------------------------------------------------

def test_write_prefetched_never_fetches_and_raises_without_data(tmp_path):
    cover = Cover("uid-1")

    def _must_not_be_called():
        pytest.fail("write_prefetched() must never call _get_data()")

    cover._get_data = _must_not_be_called  # type: ignore[method-assign]
    assert cover.data is None

    with pytest.raises(CoverDataNotPrefetched):
        cover.write_prefetched(tmp_path / "cover")

    assert not (tmp_path / "cover.jpg").exists()


def test_write_prefetched_writes_when_data_already_present(tmp_path):
    cover = Cover("uid-1")
    cover.data = b"jpegbytes"

    cover.write_prefetched(tmp_path / "cover")

    assert (tmp_path / "cover.jpg").read_bytes() == b"jpegbytes"


async def test_cover_guard_fetches_exactly_once_when_trusted(trusted_root, monkeypatch):
    cover = Cover("uid-1")
    calls = []

    def _get_data():
        calls.append(1)
        return b"jpegbytes"

    monkeypatch.setattr(cover, "_get_data", _get_data)
    tracker = da.IdentityFailureTracker()
    cover_path = trusted_root / "cover"

    await _guarded_save_cover(cover, trusted_root, cover_path, "strict", tracker, "album")

    assert len(calls) == 1  # never fetched twice
    assert cover_path.with_suffix(".jpg").read_bytes() == b"jpegbytes"


async def test_cover_guard_writes_nothing_on_empty_fetch_data(trusted_root, monkeypatch):
    # A legitimately empty fetch result (network/HTTP failure inside
    # _get_data, which returns b"" without raising) must skip the write
    # entirely — no file, no identity check, no second fetch attempt, and
    # NOT reported as a destination-identity refusal (it's a fetch
    # failure, unrelated to trust).
    cover = Cover("uid-1")
    calls = []

    def _get_data():
        calls.append(1)
        return b""

    monkeypatch.setattr(cover, "_get_data", _get_data)
    tracker = da.IdentityFailureTracker()
    cover_path = trusted_root / "cover"

    await _guarded_save_cover(cover, trusted_root, cover_path, "strict", tracker, "album")

    assert len(calls) == 1  # exactly one fetch attempt, never a silent retry
    assert not cover_path.with_suffix(".jpg").exists()
    assert tracker.any_refused is False


async def test_cover_guard_never_fetches_twice_even_when_untrusted(
    untrusted_root, monkeypatch
):
    cover = Cover("uid-1")
    calls = []

    def _get_data():
        calls.append(1)
        return b"jpegbytes"

    monkeypatch.setattr(cover, "_get_data", _get_data)
    tracker = da.IdentityFailureTracker()
    cover_path = untrusted_root / "cover"

    await _guarded_save_cover(cover, untrusted_root, cover_path, "strict", tracker, "album")

    assert len(calls) == 1
    assert not cover_path.with_suffix(".jpg").exists()
    assert tracker.any_refused is True


# ---------------------------------------------------------------------------
# Second implementation-audit finding (2026-08-18), P1 #1: identity must be
# captured at operations 1/2 (pre-staging), not only at operation 3
# (post-staging) — a refusal at operation 3 must never erase what 1/2
# already captured.
# ---------------------------------------------------------------------------

def test_mkdir_guard_returns_the_trusted_check_for_capture(trusted_root):
    target = trusted_root / "track.flac"
    check = _guarded_mkdir(trusted_root, target, "strict")
    assert check.reason == "trusted"
    assert check.anchor_id is not None
    assert check.anchor_id == da.read_marker(trusted_root)[1]


def test_mkdir_guard_off_mode_returns_disabled_not_trusted(untrusted_root):
    target = untrusted_root / "track.flac"
    check = _guarded_mkdir(untrusted_root, target, "off")
    assert check.reason == "disabled"
    assert check.anchor_id is None
