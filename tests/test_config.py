"""Tests for Config loading and validator behaviour."""
import logging
from pathlib import Path

from tiddl.cli.config import DEFAULT_DOWNLOAD_PATH, DEFAULT_TEMPLATE, Config


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

    def test_empty_default_falls_back_to_builtin(self, caplog):
        """Contract: an empty default template must NOT crash the CLI. It falls
        back to the built-in default and logs a warning (end-user-friendly)."""
        with caplog.at_level(logging.WARNING):
            cfg = Config.parse_obj({"templates": {"default": ""}})
        assert cfg.templates.default == DEFAULT_TEMPLATE
        # specific templates inherit the resolved default, never the empty string
        assert cfg.templates.track == DEFAULT_TEMPLATE
        # A specific WARNING must name the empty default, say it is falling back,
        # and quote the built-in template it fell back to.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "Empty 'default' template" in r.getMessage()
            and "falling back to the built-in default" in r.getMessage()
            and DEFAULT_TEMPLATE in r.getMessage()
            for r in warnings
        )

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
