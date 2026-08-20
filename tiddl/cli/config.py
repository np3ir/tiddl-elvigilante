import os
from logging import getLogger
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, validator

# Python 3.11+ has tomllib built-in, but 3.10 needs tomli package
try:
    from tomllib import loads as parse_toml
except ImportError:
    from tomli import loads as parse_toml

from tiddl.cli.const import APP_PATH
from tiddl.core.utils.const import TRACK_QUALITY_LITERAL, VIDEO_QUALITY_LITERAL
from tiddl.core.utils.format import DEFAULT_ARTIST_SEPARATOR

CONFIG_FILENAME = "config.toml"
DEFAULT_DOWNLOAD_PATH = Path.home() / "Music" / "tiddl"
DEFAULT_TEMPLATE = "{album.artist}/{album.title}/{item.title}"

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
        # Which client_id backs the requests, by quality. The HiRes client
        # (fX2Jxdmnt) gives 24-bit but has a STRICT TIDAL rate limit (429s on
        # big lists); the TV client (4N3n6Q1x95LL5K7p) tops out at LOSSLESS
        # 16-bit but is lenient. "auto" = HiRes only for -q max, TV otherwise
        # (avoids 429 on LOSSLESS runs). "always" = HiRes always. "never" = TV
        # always. Needs both tokens (`tiddl auth login`).
        hires_client: Literal["auto", "always", "never"] = "auto"
        video_quality: VIDEO_QUALITY_LITERAL = "fhd"
        skip_existing: bool = True
        threads_count: int = 1
        requests_per_minute: int = 20
        download_path: Path = DEFAULT_DOWNLOAD_PATH
        scan_path: Path = DEFAULT_DOWNLOAD_PATH
        video_download_path: Optional[Path] = None
        singles_filter: ARTIST_SINGLES_FILTER_LITERAL = "none"
        videos_filter: VIDEOS_FILTER_LITERAL = "none"
        # Artist-download release-type filters. TIDAL's get_artist_albums returns
        # compilations and live albums typed as plain ALBUM, so these are resolved
        # from the artist *page* endpoint (the "Compilations" / "Live albums"
        # sections the web UI shows) and excluded by album id. Both default off
        # (unchanged behavior). ("Appears On" releases are third-party albums the
        # artist endpoint never returns, so no toggle is needed for them.)
        # See core.artist_sections.
        exclude_compilations: bool = False
        exclude_live_albums: bool = False
        update_mtime: bool = False
        rewrite_metadata: bool = False
        # Destination-volume identity (see tiddl.core.utils.destination_anchor).
        # "off" (default): unchanged pre-existing behavior, no anchor I/O at all.
        # "strict": every guarded write site must resolve to a currently-trusted
        # anchor for its configured root, or the write is refused. There is no
        # "warn" mode — see PROPOSAL_destination_volume_identity_v2_1.md §1 for
        # why (an unresolved identity-pair ambiguity for roots never actually
        # trusted). An unrecognized value is a config validation error at load
        # time, same as any other invalid field here — pydantic enforces this
        # via the Literal type below, no extra validator needed.
        destination_identity: Literal["off", "strict"] = "off"
        artist_concurrency: int = 1
        artist_delay: float = 8.0
        track_delay: float = 3.0
        max_tracks_per_session: int = 0      # 0 = sin límite

        @validator("download_path", "scan_path", "video_download_path", pre=True, always=True)
        def str_to_path(cls, v):
            # Convert to an absolute, ~-expanded, normalized path WITHOUT touching
            # the filesystem. .resolve() calls os.path.realpath(), which does a
            # network round-trip for mapped drives (e.g. Z:\ on a NAS); when the
            # share is temporarily offline that raised WinError 64 here and took
            # down config loading — and thus all of tiddl — at import time.
            # os.path.abspath normalizes (expands ~ first) with no I/O.
            if v is None:
                return None
            return Path(os.path.abspath(os.path.expanduser(v))) if isinstance(v, str) else v

        @validator("scan_path", always=True)
        def sync_scan_path(cls, v, values):
            download_path = values.get("download_path", DEFAULT_DOWNLOAD_PATH)
            if v == DEFAULT_DOWNLOAD_PATH and download_path != DEFAULT_DOWNLOAD_PATH:
                return download_path
            return v

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
        default: str = DEFAULT_TEMPLATE
        track: str = ""
        video: str = ""
        album: str = ""
        playlist: str = ""
        mix: str = ""
        artist_separator: str = DEFAULT_ARTIST_SEPARATOR

        @validator("default", always=True)
        def default_not_empty(cls, v):
            # An empty default (e.g. written by a GUI that saved a blank field)
            # would otherwise crash tiddl at import for every command. For an
            # end-user CLI the right contract is: never break startup over one
            # bad field — warn and fall back to the built-in default instead.
            if not v:
                log.warning(
                    "Empty 'default' template in config; falling back to the "
                    "built-in default (%s).",
                    DEFAULT_TEMPLATE,
                )
                return DEFAULT_TEMPLATE
            return v

        @validator("track", "video", "album", "playlist", "mix", always=True)
        def inherit_default(cls, v, values):
            return v or values.get("default", "")

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
