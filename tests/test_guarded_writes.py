"""Coverage for the operation 5/6/8 guarded-write helpers in
`tiddl.cli.commands.download` — `_write_track_metadata_guarded`,
`_write_video_metadata_guarded`, `_guarded_save_cover`.

These were extracted from inline closures inside the (untestable-in-
isolation) `handle_item`/`download_callback` call graph specifically so the
implementation-audit finding (2026-08-18, P1 #3 — "guards placed before
asyncio.to_thread are not at the final mutation boundary") has direct,
targeted regression coverage: the identity check must run INSIDE the same
unit of work as the mutation, with no await point, sleep, or network I/O
between "checked" and "written."

Also covers a slice of the P2 finding ("seven guarded operation classes
lack direct integration evidence") for operations 5, 6 and 8 specifically —
the other five (1, 2, 4, 7, 9) remain covered only indirectly via
test_downloader.py/test_destination_anchor.py, which is a real, disclosed
gap (see the audit response)."""
from __future__ import annotations

import asyncio

import pytest

import tiddl.cli.commands.download as dlinit
import tiddl.core.utils.destination_anchor as da
from tiddl.cli.commands.download import (
    _guarded_save_cover,
    _write_track_metadata_guarded,
    _write_video_metadata_guarded,
)
from tiddl.core.metadata import Cover


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
