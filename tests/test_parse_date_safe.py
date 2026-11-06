"""parse_date_safe must resolve PARTIAL TIDAL release dates (year-only,
year-month) to the real year, not datetime.min. datetime.min renders as the
folder "(0001)" in path templates and silently diverges from consumers that DO
normalize partial dates (tidmon-cli), producing duplicate downloads for the same
album in a shared library."""
from datetime import datetime

from tiddl.core.utils.format import parse_date_safe, format_template


def test_year_only_resolves_to_that_year():
    assert parse_date_safe("2019") == datetime(2019, 1, 1)


def test_year_month_resolves_to_first_of_month():
    assert parse_date_safe("2019-05") == datetime(2019, 5, 1)


def test_full_date_unchanged():
    assert parse_date_safe("2019-05-01") == datetime(2019, 5, 1)


def test_datetime_passthrough():
    dt = datetime(2020, 3, 4)
    assert parse_date_safe(dt) is dt


def test_empty_and_invalid_are_min():
    assert parse_date_safe("") == datetime.min
    assert parse_date_safe(None) == datetime.min
    assert parse_date_safe("not a date") == datetime.min


def test_year_only_renders_correct_folder_year():
    album = {
        "id": 1, "title": "X", "releaseDate": "2019", "type": "ALBUM",
        "artist": {"id": 1, "name": "A", "type": "MAIN"},
        "artists": [{"id": 1, "name": "A", "type": "MAIN"}], "numberOfVolumes": 1,
    }
    track = {
        "id": 2, "title": "T", "trackNumber": 1, "volumeNumber": 1, "explicit": False,
        "artist": {"id": 1, "name": "A", "type": "MAIN"},
        "artists": [{"id": 1, "name": "A", "type": "MAIN"}],
    }
    path = format_template(
        "{album.artist}/({album.date:%Y}) {album.title}/{item.title}",
        item=track, album=album, with_asterisk_ext=False,
    )
    assert "(2019)" in path and "(0001)" not in path
