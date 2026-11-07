"""TIDAL "View all" artist URLs put a section name in the path and the real id
in ``?artistId=``; the parser must resolve them to the artist (issue #6)."""
import pytest

from tiddl.cli.utils.resource import TidalResource


def test_view_all_albums_url_uses_artist_id_query():
    r = TidalResource.from_string(
        "https://tidal.com/artist/ARTIST_ALBUMS/view-all?artistId=8405"
    )
    assert (r.type, r.id) == ("artist", "8405")


def test_view_all_query_key_is_case_insensitive():
    r = TidalResource.from_string(
        "https://tidal.com/artist/ARTIST_ALBUMS/view-all?artistid=8405"
    )
    assert r.id == "8405"


@pytest.mark.parametrize(
    "url",
    [
        "https://tidal.com/artist/8405",
        "https://listen.tidal.com/artist/8405",
        "artist/8405",
    ],
)
def test_canonical_artist_urls_unchanged(url):
    r = TidalResource.from_string(url)
    assert (r.type, r.id) == ("artist", "8405")


def test_numeric_path_id_wins_over_query():
    r = TidalResource.from_string("https://tidal.com/artist/111?artistId=222")
    assert r.id == "111"


@pytest.mark.parametrize(
    "url",
    [
        "https://tidal.com/artist/ARTIST_ALBUMS/view-all",
        "https://tidal.com/artist/ARTIST_ALBUMS/view-all?artistId=abc",
        "https://tidal.com/album/ARTIST_ALBUMS?artistId=8405",
    ],
)
def test_still_rejects_without_a_valid_id(url):
    with pytest.raises(ValueError):
        TidalResource.from_string(url)
