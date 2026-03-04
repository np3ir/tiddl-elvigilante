from logging import getLogger
from pathlib import Path
from pydantic import BaseModel, validator, root_validator, Field
from typing import Literal

# Python 3.11+ has tomllib built-in, but 3.10 needs tomli package
try:
    from tomllib import loads as parse_toml
except ImportError:
    from tomli import loads as parse_toml

from tiddl.cli.const import APP_PATH
from tiddl.core.utils.const import TRACK_QUALITY_LITERAL, VIDEO_QUALITY_LITERAL

CONFIG_FILENAME = "config.toml"
DEFAULT_DOWNLOAD_PATH = Path.home() / "Music" / "tiddl"

ARTIST_SINGLES_FILTER_LITERAL = Literal["none", "only", "include"]
VALID_M3U_RESOURCE_LITERAL = Literal["album", "playlist", "mix"]
VALID_RESOURCE_COVER_SAVE_LITERAL = Literal["track", "album", "playlist"]
VIDEOS_FILTER_LITERAL = Literal["none", "only", "allow"]

log = getLogger(__name__)


class Config(BaseModel):
    enable_cache: bool = True
    debug: bool = False

    class MetadataConfig(BaseModel):
        enable: bool = True
        lyrics: bool = Field(default=False, alias="embed_lyrics")
        save_lyrics: bool = False
        cover: bool = False
        album_review: bool = False

    metadata: MetadataConfig = MetadataConfig()

    class CoverConfig(BaseModel):
        save: bool = False
        size: int = 1280
        allowed: list[VALID_RESOURCE_COVER_SAVE_LITERAL] = []

        class CoverTemplatesConfig(BaseModel):
            track: str = ""
            album: str = ""
            playlist: str = ""

        templates: CoverTemplatesConfig = CoverTemplatesConfig()

    cover: CoverConfig = CoverConfig()

    class DownloadConfig(BaseModel):
        track_quality: TRACK_QUALITY_LITERAL = "high"
        video_quality: VIDEO_QUALITY_LITERAL = "fhd"
        skip_existing: bool = True
        threads_count: int = 2
        download_path: Path = DEFAULT_DOWNLOAD_PATH
        scan_path: Path = DEFAULT_DOWNLOAD_PATH
        singles_filter: ARTIST_SINGLES_FILTER_LITERAL = "none"
        videos_filter: VIDEOS_FILTER_LITERAL = "none"
        update_mtime: bool = False
        rewrite_metadata: bool = False

        @root_validator
        def sync_scan_to_download(cls, values):
            scan_path = values.get("scan_path")
            download_path = values.get("download_path")
            if (scan_path == DEFAULT_DOWNLOAD_PATH
                    and download_path is not None
                    and download_path != DEFAULT_DOWNLOAD_PATH):
                values["scan_path"] = download_path
            return values

        @validator("download_path", "scan_path", pre=True, always=True)
        def str_to_path(cls, v):
            # convert to absolute, expand ~, normalize
            return Path(v).expanduser().resolve() if isinstance(v, str) else v

    download: DownloadConfig = DownloadConfig()

    class M3UConfig(BaseModel):
        # m3u playlists
        save: bool = False
        allowed: list[VALID_M3U_RESOURCE_LITERAL] = []

        class M3UTemplatesConfig(BaseModel):
            album: str = ""
            playlist: str = ""
            mix: str = ""

        templates: M3UTemplatesConfig = M3UTemplatesConfig()

    m3u: M3UConfig = M3UConfig()

    class TemplatesConfig(BaseModel):
        default: str = "{album.artist}/{album.title}/{item.title}"
        track: str = ""
        video: str = ""
        album: str = ""
        playlist: str = ""
        mix: str = ""

        @root_validator
        def fill_empty_templates(cls, values):
            default = values.get("default", "")
            assert default != "", "Default template cannot be empty."
            for field in ["track", "video", "album", "playlist", "mix"]:
                if not values.get(field):
                    values[field] = default
            return values

    templates: TemplatesConfig = TemplatesConfig()


def load_config_file(config_file: Path) -> Config:
    log.debug(f"loading '{config_file}'")

    if not config_file.exists():
        log.debug("config file not found, loading default config")
        return Config()

    toml_dict = parse_toml(config_file.read_text())
    config = Config.parse_obj(toml_dict)

    log.debug("loaded config from file")

    return config


CONFIG = load_config_file(APP_PATH / CONFIG_FILENAME)
log.debug(f"{CONFIG=}")
