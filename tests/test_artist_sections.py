"""Unit coverage for the artist-page section parser that powers the
compilation / live / appears-on exclusion filter."""

from tiddl.core.artist_sections import excluded_album_ids_from_page

# Shaped like a real pages/artist response (English module titles).
PAGE = {
    "rows": [
        {
            "modules": [
                {"title": "Featured Albums", "type": "ALBUM_LIST",
                 "pagedList": {"items": [{"id": 1}, {"id": 2}]}},
                {"title": "EP & Singles", "type": "ALBUM_LIST",
                 "pagedList": {"items": [{"id": 3}]}},
            ]
        },
        {
            "modules": [
                {"title": "Compilations", "type": "ALBUM_LIST",
                 "pagedList": {"items": [{"id": 10}, {"id": 11}]}},
                {"title": "Live albums", "type": "ALBUM_LIST",
                 "pagedList": {"items": [{"id": 20}]}},
                {"title": "Videos", "type": "VIDEO_LIST",
                 "pagedList": {"items": [{"id": 999, "type": "Music Video"}]}},
                {"title": "Appears On", "type": "ALBUM_LIST",
                 "pagedList": {"items": [{"id": 30}, {"id": 31}]}},
            ]
        },
    ]
}


def test_no_flags_excludes_nothing():
    assert excluded_album_ids_from_page(
        PAGE, compilations=False, live=False, appears_on=False
    ) == set()


def test_compilations_only():
    assert excluded_album_ids_from_page(
        PAGE, compilations=True, live=False, appears_on=False
    ) == {10, 11}


def test_live_only():
    assert excluded_album_ids_from_page(
        PAGE, compilations=False, live=True, appears_on=False
    ) == {20}


def test_appears_on_only():
    assert excluded_album_ids_from_page(
        PAGE, compilations=False, live=False, appears_on=True
    ) == {30, 31}


def test_all_three_union():
    assert excluded_album_ids_from_page(
        PAGE, compilations=True, live=True, appears_on=True
    ) == {10, 11, 20, 30, 31}


def test_featured_and_singles_never_excluded():
    got = excluded_album_ids_from_page(
        PAGE, compilations=True, live=True, appears_on=True
    )
    assert 1 not in got and 2 not in got and 3 not in got  # albums/EPs kept
    assert 999 not in got  # videos never counted


def test_title_matching_is_case_insensitive():
    page = {"rows": [{"modules": [
        {"title": "COMPILATIONS", "pagedList": {"items": [{"id": 7}]}},
        {"title": "live albums", "pagedList": {"items": [{"id": 8}]}},
    ]}]}
    assert excluded_album_ids_from_page(
        page, compilations=True, live=True, appears_on=False
    ) == {7, 8}


def test_misshaped_input_is_safe():
    for bad in (None, {}, {"rows": None}, {"rows": [None]}, "nope", 42):
        assert excluded_album_ids_from_page(
            bad, compilations=True, live=True, appears_on=True
        ) == set()
