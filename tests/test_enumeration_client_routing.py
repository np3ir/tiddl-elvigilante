"""Enumeration must stay on the lenient TV client for `high + auto`.

The user's real 429 reproduction was `--artists`, not `--albums`, on the same
playlist. Root cause (baseline 05b1eca): `high + auto` promoted the WHOLE run to
the strict HiRes client, and `--artists` enumerates every credited artist's FULL
discography (`get_artist_albums` + `get_album_items` per album — see resume.py),
hammering that strict client far harder than `--albums` (only the albums the
playlist lists). `--resume` skips already-done resources BEFORE any API call, so
`--albums --resume` stayed quiet — which is exactly why the amplifier is the
artist FAN-OUT, not `--resume`.

These pin the fixed behaviour at the reachable seams:
* the playlist expansion (`_expand_playlist_resources`) — modes + fan-out, all on
  the passed API;
* the client identity per phase — `ctx.obj.api` (all enumeration) is TV in
  high+auto; the HiRes client is a distinct secondary reachable only via
  `hires_api` for a per-track Max stream;
* `--resume` reduces API calls on the second run (never increases).
"""
from __future__ import annotations

import asyncio

from tiddl.cli.commands.download import _expand_playlist_resources, _resolve_prefer_hires
from tiddl.core.resume import ResumeLog, resource_key


# --------------------------------------------------------------------------
# Fakes for the playlist-expansion phase.
# --------------------------------------------------------------------------
def _track(track_id, album_id, artist_ids):
    from tiddl.core.api.models import Track

    artists = [{"id": a, "name": f"A{a}", "type": "MAIN"} for a in artist_ids]
    return Track(
        id=track_id, title=f"T{track_id}", duration=180, replayGain=0.0, peak=1.0,
        allowStreaming=True, streamReady=True, adSupportedStreamReady=True,
        djReady=True, stemReady=True, premiumStreamingOnly=False,
        trackNumber=1, volumeNumber=1, popularity=1, url="http://t",
        editable=True, explicit=False, audioQuality="LOSSLESS", audioModes=[],
        mediaMetadata={"tags": ["LOSSLESS"]},
        artist=artists[0], artists=artists,
        album={"id": album_id, "title": f"Alb{album_id}", "vibrantColor": "#fff"},
    )


class _FakePlaylistItem:
    def __init__(self, item):
        self.item = item


class _FakePage:
    def __init__(self, items, limit, total):
        self.items = items
        self.limit = limit
        self.totalNumberOfItems = total


class _FakePlaylistAPI:
    """Records every call; serves the playlist items in pages of `page_size`."""

    def __init__(self, tracks, *, page_size=100, title="PL"):
        self._tracks = tracks
        self._page_size = page_size
        self._title = title
        self.calls: list = []

    def get_playlist(self, playlist_uuid):
        self.calls.append(("get_playlist", playlist_uuid))
        return type("P", (), {"title": self._title})()

    def get_playlist_items(self, playlist_uuid, offset=0):
        self.calls.append(("get_playlist_items", playlist_uuid, offset))
        window = self._tracks[offset:offset + self._page_size]
        return _FakePage(
            [_FakePlaylistItem(t) for t in window],
            limit=self._page_size, total=len(self._tracks),
        )


# A playlist whose tracks span 3 albums but 4 distinct credited artists (one
# collaboration), so the mode-specific dedupe is observable.
def _sample_tracks():
    return [
        _track(1, album_id=100, artist_ids=[10, 11]),  # album 100, artists 10 & 11
        _track(2, album_id=100, artist_ids=[10]),      # same album, artist 10
        _track(3, album_id=101, artist_ids=[12]),      # album 101, artist 12
        _track(4, album_id=102, artist_ids=[10, 13]),  # album 102, artists 10 & 13
    ]


def _expand(api, *, albums, tracks):
    return asyncio.run(
        _expand_playlist_resources(api, "PL-UUID", expand_albums=albums, expand_tracks=tracks)
    )


def test_expand_albums_yields_unique_albums():
    api = _FakePlaylistAPI(_sample_tracks())
    resources, skipped, title = _expand(api, albums=True, tracks=False)
    assert {(r.type, r.id) for r in resources} == {
        ("album", "100"), ("album", "101"), ("album", "102")
    }
    assert skipped == 0 and title == "PL"


def test_expand_artists_yields_unique_credited_artists():
    api = _FakePlaylistAPI(_sample_tracks())
    resources, _, _ = _expand(api, albums=False, tracks=False)
    assert {(r.type, r.id) for r in resources} == {
        ("artist", "10"), ("artist", "11"), ("artist", "12"), ("artist", "13")
    }


def test_expand_tracks_yields_unique_tracks():
    api = _FakePlaylistAPI(_sample_tracks())
    resources, _, _ = _expand(api, albums=False, tracks=True)
    assert {(r.type, r.id) for r in resources} == {
        ("track", "1"), ("track", "2"), ("track", "3"), ("track", "4")
    }


def test_artists_fan_out_at_least_as_wide_and_feed_discography_enumeration():
    # --artists resolves to the credited-artist set; each of those artist
    # resources is later enumerated into its WHOLE discography (get_artist_albums
    # + get_album_items per album — resume.py), whereas each --albums resource is
    # a single album enumeration. So even when the RESOURCE counts are close, the
    # downstream API volume of --artists dwarfs --albums — the real 429 amplifier.
    api = _FakePlaylistAPI(_sample_tracks())
    albums, _, _ = _expand(api, albums=True, tracks=False)
    api2 = _FakePlaylistAPI(_sample_tracks())
    artists, _, _ = _expand(api2, albums=False, tracks=False)
    assert len(artists) >= len(albums)
    assert all(r.type == "artist" for r in artists)
    assert all(r.type == "album" for r in albums)


def test_expansion_only_calls_playlist_endpoints_on_the_given_api():
    # The expansion touches ONLY get_playlist / get_playlist_items, and only on
    # the api it was handed — in production ctx.obj.api, the TV client for
    # high+auto. It never reaches for another client.
    api = _FakePlaylistAPI(_sample_tracks())
    _expand(api, albums=False, tracks=False)
    assert {c[0] for c in api.calls} == {"get_playlist", "get_playlist_items"}


def test_expansion_paginates_across_pages():
    api = _FakePlaylistAPI(_sample_tracks(), page_size=2)  # 4 tracks -> 2 pages
    resources, _, _ = _expand(api, albums=True, tracks=False)
    offsets = [c[2] for c in api.calls if c[0] == "get_playlist_items"]
    assert offsets == [0, 2]  # walked both pages
    assert {r.id for r in resources} == {"100", "101", "102"}


# --------------------------------------------------------------------------
# Client identity per phase: all enumeration on TV; HiRes is a distinct secondary.
# --------------------------------------------------------------------------
class _RecProxy:
    """Stand-in TidalAPI that records (kind, method) for every attribute call."""

    def __init__(self, kind, log):
        self._kind = kind
        self._log = log

    def __getattr__(self, name):
        def _call(*a, **k):
            self._log.append((self._kind, name))
            return None
        return _call


def test_high_auto_every_enumeration_phase_uses_tv_hires_is_secondary_only(monkeypatch):
    from rich.console import Console

    from tiddl.cli.ctx import ContextObject
    from tiddl.cli.utils.auth.core import AUTH_FALLBACK_FILE

    log: list = []
    ctx = ContextObject(api_omit_cache=False, debug_path=None, console=Console())
    ctx.prefer_hires = _resolve_prefer_hires("high", "auto")  # False -> TV primary

    def fake_build(auth_file, *a, **k):
        kind = "tv" if auth_file == AUTH_FALLBACK_FILE else "hires"
        return _RecProxy(kind, log)

    monkeypatch.setattr(ctx, "_build_api", fake_build)

    # Every enumeration phase goes through ctx.obj.api (playlist, artist, album,
    # credits, track), which in high+auto is the TV client.
    enum_api = ctx.api
    for method in (
        "get_playlist", "get_playlist_items",         # playlist
        "get_artist", "get_artist_albums", "get_artist_toptracks",  # artist
        "get_album", "get_album_items_credits", "get_album_review",  # album/credits
        "get_track", "get_track_credits", "get_track_lyrics",        # track
    ):
        getattr(enum_api, method)()
    assert log and all(kind == "tv" for kind, _ in log)

    # The HiRes client is a DISTINCT secondary, reachable only via hires_api (the
    # per-track Max ascent); the LOSSLESS fallback is absent in TV-primary mode.
    hires = ctx.hires_api
    assert isinstance(hires, _RecProxy) and hires._kind == "hires"
    assert enum_api is not hires
    assert ctx.fallback_api is None


# --------------------------------------------------------------------------
# --resume reduces API calls on the second run (never increases).
# --------------------------------------------------------------------------
def test_resume_skips_done_resources_with_zero_calls_second_run(tmp_path):
    # Mirrors wrapper(): a resource marked done in a prior run is skipped BEFORE
    # any API call. First run enumerates all; second run (same signature) skips
    # them all -> zero calls, strictly fewer than the first.
    sig = "sig-artists-run"
    resources = [
        type("R", (), {"type": "artist", "id": str(i)})() for i in (10, 11, 12, 13)
    ]

    def run(resume_enabled):
        log = ResumeLog(sig, base_dir=tmp_path).load()
        api_calls = 0
        for r in resources:
            key = resource_key(r)
            if resume_enabled and log.is_done(key):
                continue  # skipped before any API call (the wrapper contract)
            api_calls += 1  # stands for this resource's enumeration API traffic
            log.mark_done(key)
        return api_calls

    first = run(resume_enabled=True)          # cold checkpoint -> enumerates all 4
    second = run(resume_enabled=True)         # warm checkpoint -> skips all 4
    assert first == 4
    assert second == 0
    assert second <= first  # --resume never INCREASES calls on the second run


def test_without_resume_reprocesses_every_resource(tmp_path):
    # Control: without --resume the checkpoint is ignored, so the second run does
    # the same work as the first (this is the API storm --resume exists to avoid).
    sig = "sig-no-resume"
    resources = [type("R", (), {"type": "artist", "id": str(i)})() for i in (1, 2, 3)]

    def run():
        log = ResumeLog(sig, base_dir=tmp_path).load()
        calls = 0
        for r in resources:
            calls += 1
            log.mark_done(resource_key(r))
        return calls

    assert run() == 3
    assert run() == 3  # no --resume -> reprocessed, never fewer than needed
