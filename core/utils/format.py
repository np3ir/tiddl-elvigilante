
from __future__ import annotations
import re
import logging
import unicodedata
import sys
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional, Union, Dict
from pathlib import Path

from tiddl.core.api.models import Track, Video, Album, Playlist, Explicit
from tiddl.core.utils.strings import (
    sanitize_filename, remove_zalgo, get_alpha_bucket, 
    truncate_str_bytes, _truncate,
    _DRIVE_RE, _WIN_FORBIDDEN_RE, _RESERVED_NAMES,
    MAX_COMPONENT_LEN, RESERVED_BYTE_COUNT
)

logger = logging.getLogger(__name__)

# ============================================================
# LENGTH LIMITS
# ============================================================
MAX_ARTISTS_LEN = 100
MAX_TITLE_LEN = 150
MAX_FILENAME_BYTES = 250
MAX_COMPONENT_LEN = 250

# ============================================================
# Security options
# ============================================================
ASCII_ONLY = False
# _WIN_FORBIDDEN_RE, _DRIVE_RE, _RESERVED_NAMES imported from strings

_KEYWORDS_PATTERN = (
    # English / Universal
    r"f(?:ea)?t(?:\.|uring)?|with|w/|starring|guest(?: vocals:?)?|vocals?(?::| by)|"
    r"prod(?:\.|uced by)|(?:remix|edit|mix) by|"
    r"vs\.?|x|×|pres(?:en)?t(?:s|a|e)?|"
    r"collab(?:oration)?|"
    
    # Spanish
    r"con|junto a|y|col(?:\.|aboraci[oó]n)?|invitado|voz(?: de)?|producido por|remix de|"
    
    # German / French
    r"mit|avec|et"
)

_RE_ANTI_FEAT = re.compile(
    # Option 1: Parentheses/Brackets - REQUIRES closing bracket
    r"(?:\s*(?:[\(\[\{])\s*"
    r"(?:" + _KEYWORDS_PATTERN + r")"
    r"\s+([^)\}\]]+?)\s*(?:[\)\]\}]))"
    
    r"|"  # OR
    
    # Option 2: Dash Separator - consumes rest of string or until next delimiter
    r"(?:\s+[-\u2013]\s+\s*"
    r"(?:" + _KEYWORDS_PATTERN + r")"
    r"\s+(.*))",
    
    flags=re.IGNORECASE
)

# ============================================================
# Helper Functions
# ============================================================

def safe_getattr(obj: Any, attr: str, default: Any = None) -> Any:
    """Safely retrieves an attribute from an object or key from a dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

def clean_track_title(track_title: str, artist_name: str) -> str:
    # 1. Parse metadata artists
    # Normalize but keep spaces for word boundary checks
    meta_artists = [a.strip().lower() for a in artist_name.split(",")]
    meta_artists = [a for a in meta_artists if a]
    
    # Helper to check if a name is in metadata
    def is_known(name):
        n = name.strip().lower()
        if not n: return True # Ignore empty parts
        
        # Check exact match
        if n in meta_artists: return True
        
        # Check word-boundary match inside any meta artist
        # e.g. meta="Lil Wayne". feat="Lil". Match.
        # meta="Lily Allen". feat="Lil". No Match.
        pattern = rf"\b{re.escape(n)}\b"
        for ma in meta_artists:
             if re.search(pattern, ma): return True
        return False

    def replacement(match):
        full_match = match.group(0)
        # Check which group matched (1 for parens, 2 for dash)
        content = match.group(1) or match.group(2)
        
        if not content: return full_match
        
        # Split content
        # Separators: , & + and y et und con with
        parts = re.split(r"\s*(?:,|&|\+| and | y | et | und | con | with )\s*", content, flags=re.IGNORECASE)
        
        # Filter parts
        unknown_parts = []
        for p in parts:
            if not is_known(p):
                unknown_parts.append(p.strip())
        
        if not unknown_parts:
            # All parts known -> Remove entirely
            return ""
            
        if len(unknown_parts) == len(parts):
            # None known -> Keep entirely
            return full_match
            
        # Partial match -> Reconstruct
        # This is best-effort. We use ", " as separator for remaining parts.
        new_content = ", ".join(unknown_parts)
        
        # Reconstruct the string preserving the wrapper (parens, brackets, etc)
        return full_match.replace(content, new_content)
        
    current_title = track_title
    # Use re.sub with the single compiled regex
    current_title = _RE_ANTI_FEAT.sub(replacement, current_title)
        
    return current_title.strip()


# Alias for backward compatibility and clarity
def _normalize_for_filesystem(s: str, item_id: Optional[int] = None, max_len: int = 250, reserve_bytes: int = 0) -> str:
    return sanitize_filename(s, item_id, max_len, reserve_bytes=reserve_bytes)


def _sanitize_segment(segment: str, index: int, item_id: Optional[int] = None, max_len: int = 250, reserve_bytes: int = 0) -> str:
    s = (segment or "").strip()

    leading_dot = ""
    if s.startswith("."):
        leading_dot = "."
        s = s[1:]

    if index == 0 and _DRIVE_RE.match(s):
        return s.upper()
    
    # Adjust max_len if a leading dot was present, to not exceed component limits
    effective_max_len = max_len - len(leading_dot)
    
    sanitized = _normalize_for_filesystem(s, item_id, effective_max_len, reserve_bytes=reserve_bytes)
    return leading_dot + sanitized


# ============================================================
# Templates
# ============================================================


class UserFormat:
    def __init__(self, val):
        self.val = val

    def __format__(self, fmt):
        return fmt if self.val else ""


@dataclass
class AlbumTemplate:
    id: int
    title: str
    safe_title: str
    artist: str
    safe_artist: str
    artists: str
    safe_artists: str
    date: datetime
    explicit: Explicit
    master: UserFormat
    release: str


@dataclass
class ItemTemplate:
    id: int
    title: str
    safe_title: str
    title_version: str
    number: int
    volume: int
    version: str
    copyright: str
    bpm: int
    isrc: str
    quality: str
    artist: str
    safe_artist: str
    artists: str
    safe_artists: str
    features: str
    artists_with_features: str
    explicit: Explicit
    genre: str
    dolby: UserFormat
    releaseDate: datetime
    streamStartDate: datetime


@dataclass
class PlaylistTemplate:
    uuid: str
    title: str
    index: int
    created: datetime
    updated: datetime


# ============================================================
# Main Logic
# ============================================================

def parse_date_safe(date_str: Any) -> datetime:
    if not date_str:
        return datetime.min
    if isinstance(date_str, datetime):
        return date_str
    try:
        # Handle simple date strings like "2023-01-01"
        if len(str(date_str)) == 10 and '-' in str(date_str):
             return datetime.strptime(str(date_str), "%Y-%m-%d")
        return datetime.fromisoformat(str(date_str))
    except ValueError:
        return datetime.min


def generate_template_data(item=None, album=None, playlist=None, playlist_index=0, quality="", artist_separator=", ") -> dict:
    # Helper to calc safe limits (defined at scope level to be available for all blocks)
    # sanitize_filename now accepts reserve_bytes, so we pass explicit limits here.
    safe_file_len = MAX_COMPONENT_LEN
    safe_folder_len = 150

    item_tmpl = None
    
    if item:
        # Handle dicts where artists might be a list of dicts or objects
        artists_raw = safe_getattr(item, "artists") or []
        m_arts = []
        f_arts = []
        
        # Helper to get name from artist object/dict
        def get_name(a): return safe_getattr(a, "name") if not isinstance(a, dict) else a.get("name")
        def get_type(a): return safe_getattr(a, "type") if not isinstance(a, dict) else a.get("type")

        for a in artists_raw:
            a_name = get_name(a)
            a_type = get_type(a)
            if a_type == "MAIN": m_arts.append(a_name)
            elif a_type == "FEATURED": f_arts.append(a_name)
            # Fallback if no type (common in some API responses)
            elif not a_type: m_arts.append(a_name)

        m_arts = sorted(m_arts)
        f_arts = sorted(f_arts)
        
        ver = safe_getattr(item, "version", "") or ""
        
        is_dolby = False
        # Here we use Track and it will work even if it's the dummy version if import failed
        if isinstance(item, (Track, dict)):
            metadata = safe_getattr(item, "mediaMetadata", None)
            tags = safe_getattr(metadata, "tags", []) or []
            is_dolby = "DOLBY_ATMOS" in tags

        all_names_list = m_arts + f_arts
        all_names = artist_separator.join(all_names_list) if all_names_list else artist_separator.join(m_arts)
        item_title = safe_getattr(item, "title", "")
        clean_title = clean_track_title(item_title, all_names)

        t_trunc = _truncate(clean_title, MAX_TITLE_LEN)
        ver_str = f" ({ver})" if ver else ""
        tv_trunc = _truncate(f"{t_trunc}{ver_str}", MAX_TITLE_LEN)
        af_trunc = _truncate(artist_separator.join(m_arts + f_arts), MAX_ARTISTS_LEN)
        
        item_artist_obj = safe_getattr(item, "artist", None)
        art_name = get_name(item_artist_obj) if item_artist_obj else (m_arts[0] if m_arts else "")

        item_tmpl = ItemTemplate(
            id=safe_getattr(item, "id", 0),
            title=t_trunc,
            safe_title=sanitize_filename(t_trunc, safe_getattr(item, "id", 0), max_len=safe_file_len),
            title_version=tv_trunc,
            number=safe_getattr(item, "trackNumber", 0),
            volume=safe_getattr(item, "volumeNumber", 0),
            version=ver,
            copyright=safe_getattr(item, "copyright", "") or "",
            bpm=safe_getattr(item, "bpm", 0),
            isrc=safe_getattr(item, "isrc", "") or "",
            quality=quality,
            artist=art_name,
            safe_artist=sanitize_filename(art_name, safe_getattr(item, "id", 0), max_len=safe_folder_len),
            artists=artist_separator.join(m_arts),
            safe_artists=sanitize_filename(artist_separator.join(m_arts), safe_getattr(item, "id", 0), max_len=safe_folder_len),
            features=artist_separator.join(f_arts),
            artists_with_features=af_trunc,
            explicit=Explicit(safe_getattr(item, "explicit", None)),
            genre=safe_getattr(safe_getattr(item, "album"), "genre", "") or "",
            dolby=UserFormat(is_dolby),
            releaseDate=parse_date_safe(safe_getattr(item, "releaseDate", "")),
            streamStartDate=parse_date_safe(safe_getattr(item, "streamStartDate", "")),
        )

    album_tmpl = None
    if album:
        d = parse_date_safe(safe_getattr(album, "releaseDate"))
        metadata = safe_getattr(album, "mediaMetadata", None)
        tags = safe_getattr(metadata, "tags", []) or []
        is_master = "HIRES_LOSSLESS" in tags and quality == "MAX"

        clean_album_title = safe_getattr(album, "title", "") or ""
        clean_album_title = re.sub(r"\s*\(\s*(?:Explicit|E)\s*\)", "", clean_album_title, flags=re.IGNORECASE)

        album_artist_obj = safe_getattr(album, "artist", None)
        # Handle dict vs object for artist
        album_artist_name = (safe_getattr(album_artist_obj, "name") if not isinstance(album_artist_obj, dict) else album_artist_obj.get("name")) if album_artist_obj else ""
        
        alb_artists = safe_getattr(album, "artists", []) or []
        alb_main_artists = []
        for a in alb_artists:
            if isinstance(a, dict):
                if a.get("type") == "MAIN": alb_main_artists.append(a.get("name"))
            elif getattr(a, "type", None) == "MAIN":
                alb_main_artists.append(a.name)

        album_tmpl = AlbumTemplate(
            id=safe_getattr(album, "id", 0),
            title=clean_album_title,
            safe_title=sanitize_filename(clean_album_title, safe_getattr(album, "id", 0), max_len=safe_folder_len),
            artist=album_artist_name,
            safe_artist=sanitize_filename(album_artist_name, safe_getattr(album, "id", 0), max_len=safe_folder_len),
            artists=artist_separator.join(alb_main_artists),
            safe_artists=sanitize_filename(artist_separator.join(alb_main_artists), safe_getattr(album, "id", 0), max_len=safe_folder_len),
            date=d,
            explicit=Explicit(safe_getattr(album, "explicit", None)),
            master=UserFormat(is_master),
            release=safe_getattr(album, "type", "ALBUM")
        )
    elif item:
        # Fallback for items without album (e.g. Music Videos) to avoid template errors
        # when users use {album.artist} etc.
        d = parse_date_safe(safe_getattr(item, "releaseDate", ""))
        item_artist_obj = safe_getattr(item, "artist", None)
        art_name = (safe_getattr(item_artist_obj, "name") if not isinstance(item_artist_obj, dict) else item_artist_obj.get("name")) if item_artist_obj else ""
        
        album_tmpl = AlbumTemplate(
            id=0,
            title=safe_getattr(item, "title", ""),
            safe_title=sanitize_filename(safe_getattr(item, "title", ""), 0, max_len=safe_folder_len),
            artist=art_name,
            safe_artist=sanitize_filename(art_name, 0, max_len=safe_folder_len),
            artists=art_name,
            safe_artists=sanitize_filename(art_name, 0, max_len=safe_folder_len),
            date=d,
            explicit=Explicit(safe_getattr(item, "explicit", None)),
            master=UserFormat(False),
            release="SINGLE"
        )

    playlist_tmpl = None
    if playlist:
        c = parse_date_safe(safe_getattr(playlist, "created"))
        u = parse_date_safe(safe_getattr(playlist, "lastUpdated"))
        playlist_tmpl = PlaylistTemplate(uuid=playlist.uuid, title=playlist.title, index=playlist_index, created=c, updated=u)

    return {"item": item_tmpl, "album": album_tmpl, "playlist": playlist_tmpl}


def _normalize_initial_folder_component(component: str) -> str:
    if not component: return component
    comp = str(component).strip()
    if not comp or comp == "#": return "#"
    if len(comp) == 1: return get_alpha_bucket(comp)
    return component


def clean_filepath(fp: str) -> str:
    s = remove_zalgo(fp)
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(". ")
    is_unc = s.startswith("//") or s.startswith("\\\\")
    
    parts = re.split(r"[\\/]+", s)
    drive = None
    
    if parts:
        first = parts[0]
        if _DRIVE_RE.match(first):
            drive = first.upper()
            parts = parts[1:]
        else:
            # Only normalize first component if it's NOT a drive letter
            if parts[0]:
                 parts[0] = _normalize_initial_folder_component(parts[0])
            
    sanitized = []
    # Filter empty parts first
    parts = [p for p in parts if p]
    for idx, p in enumerate(parts):
        is_last = (idx == len(parts) - 1)
        # Apply reservation ONLY to the last component (filename)
        # Folders get 0 reservation.
        r_bytes = RESERVED_BYTE_COUNT if is_last else 0
        limit = MAX_COMPONENT_LEN if is_last else 150
        sanitized.append(_normalize_for_filesystem(p, max_len=limit, reserve_bytes=r_bytes))
    parts = sanitized

    path = "/".join(parts)

    if drive:
        path = f"{drive}{('/' + path) if path else ''}"
    if is_unc:
        path = "//" + path
    return path


def truncate_filepath_to_max(path: str, max_length: int = 240) -> str:
    if len(path.encode('utf-8')) <= max_length: return path
    m = re.match(r"^(.*[\\/])([^\\/]+)$", path)
    if not m: return truncate_str_bytes(path, max_length)
        
    dir_path, filename = m.group(1), m.group(2)
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
        ext = f".{ext}"
    else:
        base, ext = filename, ""
        
    dir_len = len(dir_path.encode('utf-8'))
    ext_len = len(ext.encode('utf-8'))
    allowed_base_len = max_length - dir_len - ext_len
    
    if allowed_base_len <= 0: return truncate_str_bytes(path, max_length)
        
    truncated_base = truncate_str_bytes(base, allowed_base_len)
    return f"{dir_path}{truncated_base}{ext}"


def _prepare_long_path(path: str) -> str:
    """
    Prepends the Windows Long Path prefix (\\\\?\\) if necessary.
    Handles standard paths and UNC paths.
    Only applies on Windows.
    """
    if sys.platform != "win32":
        return path

    path = path.replace("/", "\\")
    
    if path.startswith("\\\\?\\"):
        return path

    # UNC Paths: \\Server\Share -> \\?\UNC\Server\Share
    if path.startswith("\\\\"):
        # Removing the leading \\ to append to UNC\
        return f"\\\\?\\UNC\\{path.lstrip('\\')}"
    
    # Absolute paths: C:\Foo -> \\?\C:\Foo
    if _DRIVE_RE.match(path[:2]):
        return f"\\\\?\\{path}"

    return path

def format_template(template: str,
                    item: Optional[Union[Track, Video, Dict]] = None,
                    album: Optional[Union[Album, Dict]] = None,
                    playlist: Optional[Union[Playlist, Dict]] = None,
                    playlist_index: int = 0,
                    quality: str = "",
                    with_asterisk_ext: bool = True,
                    artist_separator: str = ", ",
                    **extra) -> str:

    template = template.strip().lstrip('\ufeff').replace("\\", "/")
    base_data = generate_template_data(item, album, playlist, playlist_index, quality, artist_separator)
    
    aliases = {}
    if item and base_data.get("item"):
        aliases["title"] = base_data["item"].title
        aliases["artist"] = base_data["item"].artist
        aliases["artist_initials"] = get_alpha_bucket(base_data["item"].artist)
        
    if album and base_data.get("album"):
        aliases["albumartist"] = base_data["album"].artist
        # Fix: releaseDate might be datetime or string in source, but here it is datetime in Template
        aliases["release_date"] = base_data["album"].date 
        
        # Always prefer Album Artist for initials to keep albums together in directory structure
        aliases["artist_initials"] = get_alpha_bucket(base_data["album"].artist)
            
    data = {**base_data, **extra, **aliases, "now": datetime.now(), "quality": quality}
    
    # Determine ID for fallback sanitization
    current_id = None
    if item:
        current_id = safe_getattr(item, "id")
    if not current_id and album:
        current_id = safe_getattr(album, "id")
    
    parts = template.split("/")
    rendered_parts = []
    
    is_unc = template.startswith("//") or template.startswith("\\\\")
    if is_unc: parts = [p for p in parts if p]
        
    for idx, part in enumerate(parts):
        try:
            rendered = part.format(**data)
        except Exception:
            # Fallback for unformatted parts (maybe missing keys)
            rendered = part.replace(":", "-").replace("{", "(").replace("}", ")")
            
        seg_idx = idx if not is_unc else idx + 99
        
        # Determine max length:
        # If it's the last part, assume it's the filename base -> MAX
        # Otherwise it's a folder -> 150
        # sanitize_filename will subtract RESERVED_BYTE_COUNT (50) from these.
        is_last = (idx == len(parts) - 1)
        limit = MAX_COMPONENT_LEN if is_last else 150
        r_bytes = RESERVED_BYTE_COUNT if is_last else 0
        
        rendered_parts.append(_sanitize_segment(rendered, seg_idx, current_id, max_len=limit, reserve_bytes=r_bytes))
        
    # AUTO-INJECT DISC FOLDER
    # If album has multiple volumes and template doesn't explicitly handle volume
    if item and album and safe_getattr(album, "numberOfVolumes", 0) > 1:
        if "{item.volume}" not in template:
            vol = safe_getattr(item, "volumeNumber", 1)
            disc_part = _sanitize_segment(f"Disc {vol}", 0, current_id, max_len=150, reserve_bytes=0)
            # Insert before the filename (last component)
            if len(rendered_parts) >= 1:
                rendered_parts.insert(-1, disc_part)
            else:
                rendered_parts.insert(0, disc_part)

    path = "/".join(rendered_parts)
    if is_unc: path = "//" + path
        
    path = clean_filepath(path)
    path = truncate_filepath_to_max(path, MAX_FILENAME_BYTES)
    
    if with_asterisk_ext: path += ".*"
    
    # Apply Long Path prefix for Windows if path is absolute
    # This bypasses the 260 character limit
    if sys.platform == "win32":
        # Check if path is absolute (Drive letter or UNC)
        if _DRIVE_RE.match(path[:2]) or path.startswith("//") or path.startswith("\\\\"):
             # For return value, we keep it as is because pathlib might strip it 
             # or other tools might be confused.
             # However, the caller MUST handle long paths.
             # Ideally, we return the prefixed path here.
             path = _prepare_long_path(path)

    return path
