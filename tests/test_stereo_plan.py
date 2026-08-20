"""Unit coverage for `plan_stereo_resolution`, the pure decision that drives
both the direct-album and the artist-expansion stereo paths in
`tiddl.cli.commands.download`.

The only behavioural difference between the two call sites is `keep_original`:
a direct album URL is skipped when no stereo edition qualifies, while an album
reached by expanding an artist keeps its original id so a whole-artist stereo
run never silently drops an album.
"""

from types import SimpleNamespace

from tiddl.cli.commands.download import CatalogReadCache, plan_stereo_resolution


def ns(**values):
    return SimpleNamespace(**values)


def result(*, source_ok=False, candidate=None, source_id=100):
    return ns(
        source=ns(id=source_id, title="Some Album"),
        source_satisfies_request=source_ok,
        best=candidate,
    )


def candidate(album_id, *, needs_confirmation):
    return ns(album=ns(id=album_id), requires_confirmation=needs_confirmation)


def test_source_already_stereo_keeps_source_for_both_modes():
    r = result(source_ok=True, source_id=7)
    assert plan_stereo_resolution(r, False) == ("keep-source", 7, False)
    assert plan_stereo_resolution(r, True) == ("keep-source", 7, False)


def test_source_satisfies_request_ignores_candidate():
    # The decision short-circuits on source_satisfies_request and must never
    # inspect result.best in that case, even when a candidate exists.
    r = result(source_ok=True, source_id=7, candidate=candidate(9, needs_confirmation=True))
    assert plan_stereo_resolution(r, False) == ("keep-source", 7, False)
    assert plan_stereo_resolution(r, True) == ("keep-source", 7, False)


def test_no_candidate_direct_album_is_skipped():
    r = result(source_ok=False, candidate=None, source_id=11)
    assert plan_stereo_resolution(r, keep_original=False) == ("skip", 11, False)


def test_no_candidate_artist_expansion_keeps_original():
    # The whole point of keep_original: an artist album with no stereo edition
    # is downloaded as-is instead of being dropped.
    r = result(source_ok=False, candidate=None, source_id=11)
    assert plan_stereo_resolution(r, keep_original=True) == ("keep-source", 11, False)


def test_candidate_replace_propagates_confirmation_flag():
    r = result(candidate=candidate(999, needs_confirmation=True))
    assert plan_stereo_resolution(r, False) == ("replace", 999, True)
    assert plan_stereo_resolution(r, True) == ("replace", 999, True)


def test_candidate_replace_without_confirmation():
    r = result(candidate=candidate(1000, needs_confirmation=False))
    assert plan_stereo_resolution(r, keep_original=False) == ("replace", 1000, False)


class _CountingApi:
    """Fake api counting real calls to the cached catalog reads."""

    def __init__(self):
        self.calls = {"get_album": 0, "get_artist_albums": 0, "get_uncached": 0}

    def get_album(self, album_id):
        self.calls["get_album"] += 1
        return ("album", album_id)

    def get_artist_albums(self, artist_id, limit=100, offset=0, filter=None):
        self.calls["get_artist_albums"] += 1
        return ("artist_albums", artist_id, limit, offset, filter)

    def get_uncached(self, x):
        self.calls["get_uncached"] += 1
        return x


def test_cache_memoises_repeated_reads_by_args():
    api = _CountingApi()
    cache = CatalogReadCache(api)
    # same album id repeated -> underlying called once
    assert cache.get_album(album_id=549984784) == ("album", 549984784)
    assert cache.get_album(album_id=549984784) == ("album", 549984784)
    assert api.calls["get_album"] == 1
    # same artist page repeated (the hot path when resolving a whole artist)
    for _ in range(5):
        cache.get_artist_albums(artist_id=5237820, limit=100, offset=0)
    assert api.calls["get_artist_albums"] == 1


def test_cache_distinguishes_different_args():
    api = _CountingApi()
    cache = CatalogReadCache(api)
    cache.get_album(album_id=1)
    cache.get_album(album_id=2)
    assert api.calls["get_album"] == 2
    cache.get_artist_albums(artist_id=9, offset=0, filter="ALBUMS")
    cache.get_artist_albums(artist_id=9, offset=0, filter="EPSANDSINGLES")
    assert api.calls["get_artist_albums"] == 2


def test_cache_passes_through_uncached_methods():
    api = _CountingApi()
    cache = CatalogReadCache(api)
    assert cache.get_uncached(7) == 7
    assert cache.get_uncached(7) == 7
    assert api.calls["get_uncached"] == 2  # not memoised
