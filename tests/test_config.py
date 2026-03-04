from __future__ import annotations
import pytest
from pathlib import Path
from pydantic import ValidationError

from tiddl.cli.config import Config, DEFAULT_DOWNLOAD_PATH


class TestConfig:
    def test_default_config(self):
        """Default Config should instantiate without errors."""
        config = Config()
        assert config.enable_cache is True
        assert config.debug is False

    def test_default_download_path(self):
        """Default download path should point to ~/Music/tiddl."""
        config = Config()
        assert config.download.download_path == DEFAULT_DOWNLOAD_PATH

    def test_scan_path_syncs_to_download_path(self):
        """When download_path is set, scan_path should follow."""
        custom_path = str(Path.home() / "custom_music")
        config = Config.parse_obj({"download": {"download_path": custom_path}})
        assert config.download.scan_path == Path(custom_path).expanduser().resolve()

    def test_scan_path_independent_override(self):
        """Explicit scan_path should NOT be overridden by download_path sync."""
        custom_dl = str(Path.home() / "custom_dl")
        custom_scan = str(Path.home() / "custom_scan")
        config = Config.parse_obj({
            "download": {
                "download_path": custom_dl,
                "scan_path": custom_scan,
            }
        })
        assert config.download.scan_path == Path(custom_scan).expanduser().resolve()

    def test_default_template_nonempty(self):
        """Default template must not be empty."""
        config = Config()
        assert config.templates.default != ""

    def test_templates_fill_from_default(self):
        """Empty per-type templates should inherit the default."""
        config = Config()
        assert config.templates.track == config.templates.default
        assert config.templates.album == config.templates.default
        assert config.templates.playlist == config.templates.default

    def test_templates_custom_override(self):
        """Per-type templates set explicitly should not be overridden."""
        custom = "{item.title}"
        config = Config.parse_obj({"templates": {"track": custom}})
        assert config.templates.track == custom
        # Other types still inherit the default
        assert config.templates.album == config.templates.default

    def test_empty_default_template_raises(self):
        """Empty default template should raise a validation error."""
        with pytest.raises((ValidationError, AssertionError)):
            Config.parse_obj({"templates": {"default": ""}})

    def test_tilde_expansion_in_path(self):
        """Paths with ~ should be expanded to the home directory."""
        config = Config.parse_obj({"download": {"download_path": "~/Music/test"}})
        assert not str(config.download.download_path).startswith("~")
        assert config.download.download_path.is_absolute()

    def test_metadata_defaults(self):
        """Metadata config should default to safe values."""
        config = Config()
        assert config.metadata.enable is True
        assert config.metadata.lyrics is False
        assert config.metadata.save_lyrics is False
        assert config.metadata.cover is False

    def test_download_thread_count_default(self):
        """Default thread count should be 2."""
        config = Config()
        assert config.download.threads_count == 2

    def test_quality_defaults(self):
        """Default audio quality should be high."""
        config = Config()
        assert config.download.track_quality == "high"

    def test_parse_from_toml_dict(self):
        """Config should parse from a TOML-like dict."""
        data = {
            "enable_cache": False,
            "download": {
                "track_quality": "max",
                "threads_count": 4,
            },
        }
        config = Config.parse_obj(data)
        assert config.enable_cache is False
        assert config.download.track_quality == "max"
        assert config.download.threads_count == 4
