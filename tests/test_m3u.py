"""Coverage for tiddl.core.utils.m3u.save_tracks_to_m3u's destination-volume
identity guard (operation 7, see tiddl.core.utils.destination_anchor and
PROPOSAL_destination_volume_identity_v2_1..v2_4.md, kept local/untracked).

Pre-existing behavior (no root/mode/tracker passed) is exercised too, since
those parameters are optional precisely so callers that predate this feature
(direct unit tests of this function, before this PR) keep working unchanged.
"""
from __future__ import annotations

import types

import pytest

import tiddl.core.utils.destination_anchor as da
from tiddl.core.utils.m3u import save_tracks_to_m3u


@pytest.fixture(autouse=True)
def _isolated_anchor_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "APP_PATH", tmp_path / "_app")


def _fake_track(title="T", duration=180, artist_name="A"):
    artist = types.SimpleNamespace(name=artist_name) if artist_name else None
    return types.SimpleNamespace(title=title, duration=duration, artist=artist)


def test_no_root_given_skips_the_guard_entirely(tmp_path):
    # Backward compatible: a caller that doesn't pass root/mode (mode stays
    # the "off" default) never touches destination_anchor's I/O at all.
    path = tmp_path / "playlist"
    save_tracks_to_m3u([(tmp_path / "t.flac", _fake_track())], path)
    assert (tmp_path / "playlist.m3u").exists()


def test_off_mode_writes_even_with_no_trust_record(tmp_path):
    root = tmp_path / "dest"
    root.mkdir()
    path = root / "playlist"
    save_tracks_to_m3u(
        [(root / "t.flac", _fake_track())], path, root=root, mode="off",
    )
    assert (root / "playlist.m3u").exists()


def test_strict_mode_trusted_root_writes_normally(tmp_path):
    root = tmp_path / "dest"
    root.mkdir()
    da.establish_anchor(root)
    path = root / "playlist"
    tracker = da.IdentityFailureTracker()
    save_tracks_to_m3u(
        [(root / "t.flac", _fake_track())], path,
        root=root, mode="strict", tracker=tracker,
    )
    assert (root / "playlist.m3u").exists()
    assert tracker.any_refused is False


def test_strict_mode_untrusted_root_refuses_and_trips_the_tracker(tmp_path):
    root = tmp_path / "dest"
    root.mkdir()
    path = root / "playlist"
    tracker = da.IdentityFailureTracker()
    save_tracks_to_m3u(
        [(root / "t.flac", _fake_track())], path,
        root=root, mode="strict", tracker=tracker,
    )
    # Class C (v2.3 §3): no exception escapes this function — matches its
    # existing "log and return" contract for every other failure mode here
    # (see the except Exception clause below the guard).
    assert not (root / "playlist.m3u").exists()
    assert tracker.any_refused is True


def test_class_c_refusal_never_touches_db_or_registry(tmp_path, monkeypatch):
    # Second implementation-audit finding (2026-08-18), P2: Class C (v2.3
    # §3) — every track in this M3U already has its own truthful
    # `_db_insert` record by the time this runs, and a refusal here must
    # never touch it. Spies on retained_registry to prove no registry
    # function is called during an M3U refusal — matches
    # test_guarded_writes.py's analogous cover test.
    import tiddl.core.utils.retained_registry as registrymod

    def _must_not_be_called(*a, **k):
        pytest.fail("an m3u refusal must never touch the retained registry")

    monkeypatch.setattr(registrymod, "register_retained_file", _must_not_be_called)
    monkeypatch.setattr(registrymod, "update_entry", _must_not_be_called)
    monkeypatch.setattr(registrymod, "remove_entry", _must_not_be_called)

    root = tmp_path / "dest"
    root.mkdir()
    path = root / "playlist"
    tracker = da.IdentityFailureTracker()
    save_tracks_to_m3u(
        [(root / "t.flac", _fake_track())], path,
        root=root, mode="strict", tracker=tracker,
    )
    assert not (root / "playlist.m3u").exists()
    assert tracker.any_refused is True


def test_strict_mode_refusal_without_a_tracker_does_not_raise(tmp_path):
    # tracker is optional too — a caller not threading one through still
    # gets a safe refusal, not an AttributeError on None.
    root = tmp_path / "dest"
    root.mkdir()
    path = root / "playlist"
    save_tracks_to_m3u(
        [(root / "t.flac", _fake_track())], path, root=root, mode="strict",
    )
    assert not (root / "playlist.m3u").exists()


def test_empty_tracklist_still_short_circuits_before_the_guard(tmp_path, monkeypatch):
    # Pre-existing behavior: no tracks -> warn and return, never even reaching
    # the identity guard (asserted by making the guard explode if reached).
    root = tmp_path / "dest"
    root.mkdir()
    path = root / "playlist"

    def _boom(*a, **k):
        raise AssertionError("guard must not run when there are no tracks")

    monkeypatch.setattr(da, "assert_write_allowed", _boom)
    save_tracks_to_m3u([], path, root=root, mode="strict")
    assert not (root / "playlist.m3u").exists()
