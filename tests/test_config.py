"""Tests for Config loading and validator behaviour."""
import pytest
from pathlib import Path
from pydantic import ValidationError

from tiddl.cli.config import Config, DEFAULT_DOWNLOAD_PATH


class TestTemplatesConfig:
    def test_specific_templates_inherit_default(self):
        cfg = Config.parse_obj({"templates": {"default": "custom/{item.title}"}})
        assert cfg.templates.track == "custom/{item.title}"
        assert cfg.templates.video == "custom/{item.title}"
        assert cfg.templates.album == "custom/{item.title}"
        assert cfg.templates.playlist == "custom/{item.title}"
        assert cfg.templates.mix == "custom/{item.title}"

    def test_specific_template_overrides_default(self):
        cfg = Config.parse_obj({
            "templates": {
                "default": "custom/{item.title}",
                "track": "tracks/{item.title}",
            }
        })
        assert cfg.templates.track == "tracks/{item.title}"
        assert cfg.templates.video == "custom/{item.title}"

    def test_empty_default_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Config.parse_obj({"templates": {"default": ""}})
        assert "Default template cannot be empty." in str(exc_info.value)

    def test_default_template_unchanged_when_not_set(self):
        cfg = Config()
        assert cfg.templates.default == "{album.artist}/{album.title}/{item.title}"


class TestDownloadConfig:
    def test_scan_path_syncs_to_download_path(self):
        custom_path = str(Path.home() / "custom_music")
        cfg = Config.parse_obj({"download": {"download_path": custom_path}})
        assert cfg.download.scan_path == Path(custom_path).expanduser().resolve()

    def test_scan_path_not_synced_when_download_path_is_default(self):
        """Explicitly passing DEFAULT_DOWNLOAD_PATH should not trigger resync."""
        baseline = Config().download.scan_path
        cfg = Config.parse_obj({"download": {"download_path": str(DEFAULT_DOWNLOAD_PATH)}})
        assert cfg.download.scan_path == baseline

    def test_scan_path_independent_override(self):
        custom_dl = str(Path.home() / "music")
        custom_scan = str(Path.home() / "old_music")
        cfg = Config.parse_obj({
            "download": {
                "download_path": custom_dl,
                "scan_path": custom_scan,
            }
        })
        assert cfg.download.download_path == Path(custom_dl).expanduser().resolve()
        assert cfg.download.scan_path == Path(custom_scan).expanduser().resolve()

    def test_download_path_default(self):
        cfg = Config()
        assert cfg.download.download_path == DEFAULT_DOWNLOAD_PATH
