from types import SimpleNamespace

from tiddl.core.edition_resolver import (
    find_stereo_editions,
    normalize_catalog_text,
    quality_fallback_order,
    score_stereo_candidate,
    supports_requested_quality,
)


def ns(**values):
    return SimpleNamespace(**values)


def album(album_id, mode, *, tracks=13, duration=2363, title="NO ME ARREPIENTO DE SENTIR TANTO"):
    return ns(
        id=album_id,
        title=title,
        artist=ns(id=5237820, name="KAROL G"),
        releaseDate="2026-08-07",
        explicit=True,
        duration=duration,
        numberOfTracks=tracks,
        audioModes=[mode],
        audioQuality="LOSSLESS" if mode == "STEREO" else "LOW",
        mediaMetadata=ns(
            tags=["HIRES_LOSSLESS", "LOSSLESS"] if mode == "STEREO" else ["DOLBY_ATMOS"]
        ),
    )


def track(title, version=None):
    return ns(title=title, version=version)


def wrapped_tracks(titles):
    return ns(items=[ns(type="track", item=track(title)) for title in titles])


ATMOS_TITLES = [
    "Te llevas To", "Maybe", "Bebiendo Lágrimas", "Ahí", "Final feliz",
    "Alguien que te amaba", "MATADORA", "For u My lova", "Si lo ven", "BbY WOW",
    "Con quién andará?", "Eclipse", "Después de ti",
]
STEREO_TITLES = ATMOS_TITLES[:5] + ["Still"] + ATMOS_TITLES[5:]


def test_normalization_handles_case_accents_and_punctuation():
    assert normalize_catalog_text("  Ahí — (Remix)! ") == "ahi remix"


def test_atmos_rung_maps_to_high_instead_of_raising():
    # The `atmos` download rung is fetched at the LOSSLESS tier, which the edition
    # resolver only knows as `high`; `-q atmos --audio-mode stereo` must resolve,
    # not raise ValueError (regression).
    assert quality_fallback_order("atmos") == quality_fallback_order("high")
    assert quality_fallback_order("atmos", "strict") == quality_fallback_order("high", "strict")


def test_flexible_quality_is_a_user_ceiling_with_downward_fallback():
    assert quality_fallback_order("max") == ("max", "high", "normal", "low")
    assert quality_fallback_order("high") == ("high", "normal", "low")
    assert quality_fallback_order("normal") == ("normal", "low")
    assert quality_fallback_order("low") == ("low",)


def test_strict_quality_never_falls_back():
    assert quality_fallback_order("max", "strict") == ("max",)
    assert quality_fallback_order("high", "strict") == ("high",)


def test_known_stereo_edition_scores_high_and_requires_confirmation():
    source = album(549984784, "DOLBY_ATMOS")
    candidate = album(549980023, "STEREO", tracks=14, duration=2583)

    scored = score_stereo_candidate(
        source,
        candidate,
        [track(title) for title in ATMOS_TITLES],
        [track(title) for title in STEREO_TITLES],
    )

    assert scored is not None
    assert scored.score > 0.90
    assert scored.track_overlap == 13 / 14
    assert scored.missing_tracks == ()
    assert scored.extra_tracks == ("still",)
    assert scored.requires_confirmation


def test_rejects_atmos_and_unrelated_candidates():
    source = album(1, "DOLBY_ATMOS")
    tracks = [track(title) for title in ATMOS_TITLES]
    assert score_stereo_candidate(source, album(2, "DOLBY_ATMOS"), tracks, tracks) is None
    assert score_stereo_candidate(
        source, album(3, "STEREO", title="Completely Different"), tracks, tracks
    ) is None


def test_quality_filter_uses_tidal_catalog_tags():
    stereo_max = album(10, "STEREO")
    stereo_high = album(11, "STEREO")
    stereo_high.mediaMetadata.tags = ["LOSSLESS"]
    atmos = album(12, "DOLBY_ATMOS")

    assert supports_requested_quality(stereo_max, "max")
    assert supports_requested_quality(stereo_max, "high")
    assert not supports_requested_quality(stereo_high, "max")
    assert supports_requested_quality(stereo_high, "high")
    assert not supports_requested_quality(atmos, "max")
    assert supports_requested_quality(stereo_high, "normal")
    assert supports_requested_quality(stereo_high, "low")
    assert not supports_requested_quality(atmos, "normal")


def test_find_stereo_editions_is_read_only_and_returns_best_match():
    source = album(549984784, "DOLBY_ATMOS")
    stereo = album(549980023, "STEREO", tracks=14, duration=2583)
    unrelated = album(9, "STEREO", title="Other Album")

    class FakeApi:
        def __init__(self):
            self.calls = []

        def get_album(self, album_id):
            self.calls.append(("get_album", album_id))
            return source

        def get_artist_albums(self, artist_id, limit, offset):
            self.calls.append(("get_artist_albums", artist_id, limit, offset))
            return ns(items=[source, unrelated, stereo])

        def get_album_items(self, album_id):
            self.calls.append(("get_album_items", album_id))
            titles = STEREO_TITLES if album_id == stereo.id else ATMOS_TITLES
            return wrapped_tracks(titles)

    api = FakeApi()
    result = find_stereo_editions(api, source.id)

    assert result.best is not None
    assert result.best.album.id == 549980023
    assert result.requested_quality == "max"
    assert all(call[0].startswith("get_") for call in api.calls)
    assert ("get_album_items", unrelated.id) not in api.calls


def test_max_excludes_lossless_only_but_high_accepts_it():
    source = album(20, "DOLBY_ATMOS")
    lossless = album(21, "STEREO")
    lossless.mediaMetadata.tags = ["LOSSLESS"]

    class FakeApi:
        def get_album(self, album_id):
            return source

        def get_artist_albums(self, artist_id, limit, offset):
            return ns(items=[lossless])

        def get_album_items(self, album_id):
            return wrapped_tracks(ATMOS_TITLES)

    api = FakeApi()
    assert find_stereo_editions(api, source.id, requested_quality="max").best is None
    assert find_stereo_editions(api, source.id, requested_quality="high").best is not None


def test_flexible_max_chooses_lossless_candidate_with_one_catalog_scan():
    source = album(40, "DOLBY_ATMOS")
    lossless = album(41, "STEREO")
    lossless.mediaMetadata.tags = ["LOSSLESS"]

    class FakeApi:
        def __init__(self):
            self.catalog_calls = 0

        def get_album(self, album_id):
            return source

        def get_artist_albums(self, artist_id, limit, offset):
            self.catalog_calls += 1
            return ns(items=[lossless])

        def get_album_items(self, album_id):
            return wrapped_tracks(ATMOS_TITLES)

    api = FakeApi()
    result = find_stereo_editions(
        api, source.id, requested_quality="max", quality_policy="flexible"
    )

    assert result.best is not None
    assert result.best.album.id == lossless.id
    assert result.requested_quality == "high"
    assert api.catalog_calls == 1


def test_compatible_source_is_kept_without_catalog_search():
    source = album(30, "STEREO")

    class FakeApi:
        def __init__(self):
            self.catalog_searched = False

        def get_album(self, album_id):
            return source

        def get_artist_albums(self, **kwargs):
            self.catalog_searched = True
            raise AssertionError("compatible source should not trigger an edition search")

    api = FakeApi()
    result = find_stereo_editions(api, source.id, requested_quality="max")

    assert result.source_satisfies_request
    assert result.best is None
    assert not api.catalog_searched
