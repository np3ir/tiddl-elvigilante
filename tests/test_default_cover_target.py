"""An empty [cover.templates] entry must save the cover next to the audio.

`config.example.toml` documents "empty = next to the audio, default name", but an
empty template fed to `format_template` renders to nothing, so the standalone
cover used to land at the download root as `.*.jpg`. `_default_cover_target`
restores the contract: the cover goes in the common folder of the just-downloaded
tracks, named `cover` (the guarded writer appends `.jpg`).

These tests are cross-platform — paths are built under pytest's tmp_path.
"""
from pathlib import Path

from tiddl.cli.commands.download import _default_cover_target


def test_single_disc_album_lands_in_album_folder(tmp_path):
    root = tmp_path
    album = root / "SGVO" / "Afro Archives (2026)"
    tracks = [
        (album / "01 - Thando Awpheli.flac", object()),
        (album / "02 - Oko Oko.flac", object()),
    ]
    assert _default_cover_target(tracks, root) == album / "cover"


def test_multi_disc_album_lands_in_album_root(tmp_path):
    root = tmp_path
    album = root / "Artist" / "Big Album"
    tracks = [
        (album / "Disc 1" / "01 - A.flac", object()),
        (album / "Disc 1" / "02 - B.flac", object()),
        (album / "Disc 2" / "01 - C.flac", object()),
    ]
    # The common parent of the disc folders is the album root — the cover belongs
    # there, not inside one disc folder.
    assert _default_cover_target(tracks, root) == album / "cover"


def test_flat_template_at_root_is_skipped(tmp_path):
    # A template that drops every track straight into the root has no per-album
    # folder to hold one cover -> skip rather than litter the root.
    root = tmp_path
    tracks = [(root / "01 - A.flac", object()), (root / "02 - B.flac", object())]
    assert _default_cover_target(tracks, root) is None


def test_empty_input_returns_none(tmp_path):
    assert _default_cover_target([], tmp_path) is None


def test_cancelled_sentinels_are_ignored(tmp_path):
    # handle_item returns Path("") (str -> ".") for cancelled / cap-rejected
    # items; those must not pollute the resolution.
    root = tmp_path
    album = root / "Artist" / "Album"
    tracks = [
        (Path(""), object()),
        (album / "01 - A.flac", object()),
        ("", object()),
    ]
    assert _default_cover_target(tracks, root) == album / "cover"


def test_all_sentinels_returns_none(tmp_path):
    tracks = [(Path(""), object()), ("", object()), (None, object())]
    assert _default_cover_target(tracks, tmp_path) is None
