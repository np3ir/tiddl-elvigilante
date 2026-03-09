"""Tests for the configurable artist_separator feature."""
import pytest
from tiddl.cli.config import Config
from tiddl.core.utils.format import generate_template_data, format_template, DEFAULT_ARTIST_SEPARATOR
from tiddl.core.metadata.track import add_track_metadata
from tiddl.core.metadata.video import add_video_metadata
import inspect


class TestArtistSeparatorConfig:
    def test_default_separator_is_slash(self):
        cfg = Config()
        assert cfg.templates.artist_separator == DEFAULT_ARTIST_SEPARATOR

    def test_custom_separator_comma(self):
        cfg = Config.parse_obj({"templates": {"artist_separator": ", "}})
        assert cfg.templates.artist_separator == ", "

    def test_custom_separator_ampersand(self):
        cfg = Config.parse_obj({"templates": {"artist_separator": " & "}})
        assert cfg.templates.artist_separator == " & "


class TestArtistSeparatorTemplates:
    ITEM = {
        "id": 1,
        "title": "Song",
        "trackNumber": 1,
        "volumeNumber": 1,
        "version": "",
        "copyright": "",
        "bpm": None,
        "isrc": "TEST",
        "explicit": None,
        "releaseDate": None,
        "streamStartDate": None,
        "artist": {"name": "Artist A", "type": "MAIN"},
        "artists": [
            {"name": "Artist A", "type": "MAIN"},
            {"name": "Artist B", "type": "FEATURED"},
        ],
        "album": {"title": "Album", "genre": None},
        "mediaMetadata": None,
    }

    def test_artists_with_features_slash(self):
        data = generate_template_data(item=self.ITEM, artist_separator=" / ")
        assert data["item"].artists_with_features == "Artist A / Artist B"

    def test_artists_with_features_comma(self):
        data = generate_template_data(item=self.ITEM, artist_separator=", ")
        assert data["item"].artists_with_features == "Artist A, Artist B"

    def test_artists_with_features_ampersand(self):
        data = generate_template_data(item=self.ITEM, artist_separator=" & ")
        assert data["item"].artists_with_features == "Artist A & Artist B"

    def test_item_artists_uses_sep(self):
        data = generate_template_data(item=self.ITEM, artist_separator=" / ")
        # MAIN artists only
        assert data["item"].artists == "Artist A"

    def test_item_features_uses_sep(self):
        data = generate_template_data(item=self.ITEM, artist_separator=" / ")
        assert data["item"].features == "Artist B"

    def test_format_template_passes_separator(self):
        # format_template should accept artist_separator and use it
        sig = inspect.signature(format_template)
        assert "artist_separator" in sig.parameters
        assert sig.parameters["artist_separator"].default == DEFAULT_ARTIST_SEPARATOR


class TestArtistSeparatorMetadata:
    def test_add_track_metadata_has_separator_param(self):
        sig = inspect.signature(add_track_metadata)
        assert "artist_separator" in sig.parameters
        assert sig.parameters["artist_separator"].default == DEFAULT_ARTIST_SEPARATOR

    def test_add_video_metadata_has_separator_param(self):
        sig = inspect.signature(add_video_metadata)
        assert "artist_separator" in sig.parameters
        assert sig.parameters["artist_separator"].default == DEFAULT_ARTIST_SEPARATOR
