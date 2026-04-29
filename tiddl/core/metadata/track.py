from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import re
import logging
import unicodedata
import shutil
import tempfile

from mutagen.flac import FLAC as MutagenFLAC, Picture
from mutagen.mp4 import MP4 as MutagenMP4, MP4Cover

from tiddl.core.api.models import AlbumItemsCredits, Track
from tiddl.core.utils.format import clean_track_title, DEFAULT_ARTIST_SEPARATOR

log = logging.getLogger(__name__)


# ===========================
# Helper to clean track title
# ===========================

def clean_title_for_metadata(raw_title: str) -> str:
    """
    Remove 'feat.' fragments from title for metadata/filenames.
    Does not touch artist list, only the title string.
    """
    title = raw_title

    # Remove (feat. ...), (feat ...), [feat. ...], [feat ...]
    title = re.sub(r"\s*\(feat\.?.*?\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)

    # Remove '- feat. ...' at end
    title = re.sub(r"\s*-\s*feat\.?.*$", "", title, flags=re.IGNORECASE)

    return title.strip()


@dataclass(slots=True)
class Metadata:
    title: str
    track_number: str
    disc_number: str
    copyright: str | None
    album_artist: str
    artists: str
    album_title: str
    date: str
    isrc: str
    artists_list: list[str] = field(default_factory=list)
    bpm: str | None = None
    lyrics: str | None = None
    credits: list[AlbumItemsCredits.ItemWithCredits.CreditsEntry] = field(
        default_factory=list
    )
    cover_data: bytes | None = None
    comment: str = ""
    genre: str | None = None


# =====================
# FLAC metadata writing
# =====================

def add_flac_metadata(track_path: Path, metadata: Metadata) -> None:
    """Write FLAC metadata tags using Mutagen."""
    mutagen = MutagenFLAC(track_path)

    # Embed cover art
    if metadata.cover_data:
        picture = Picture()
        picture.data = metadata.cover_data
        picture.mime = "image/jpeg"
        picture.type = 3  # front cover
        mutagen.add_picture(picture)

    # Parse date if possible
    if metadata.date:
        try:
            date = datetime.fromisoformat(metadata.date)
        except Exception:
            date = None
    else:
        date = None

    # Remove redundant YEAR tag if present (standard is DATE)
    if "YEAR" in mutagen:
        del mutagen["YEAR"]

    mutagen.update(
        {
            "TITLE": metadata.title,
            "TRACKNUMBER": metadata.track_number,
            "DISCNUMBER": metadata.disc_number,
            "ALBUM": metadata.album_title,
            "ALBUMARTIST": metadata.album_artist,
            "ARTIST": metadata.artists_list or [metadata.artists],
            "DATE": str(date.year) if date else "",
            "COPYRIGHT": metadata.copyright or "",
            "ISRC": metadata.isrc,
            "COMMENT": metadata.comment,
            "GENRE": metadata.genre or "",
        }
    )

    if metadata.bpm:
        mutagen["BPM"] = metadata.bpm
    if metadata.lyrics:
        mutagen["LYRICS"] = metadata.lyrics

    # Write credits using their type as a tag key (uppercased)
    for entry in metadata.credits:
        # entry.type is the category, contributors is a list of Contributor models
        try:
            # Vorbis keys must be ASCII and cannot contain '='
            # Normalize to decompose characters (NFD) so 'Ñ' becomes 'N' + '~'
            raw_key = entry.type.upper()
            normalized = unicodedata.normalize('NFKD', raw_key)
            # Encode to ASCII, ignoring non-convertible marks (like the tilde ~ separated from n)
            safe_key = normalized.encode('ascii', 'ignore').decode('ascii')
            # Final cleanup
            safe_key = safe_key.replace('=', '').strip()
            
            if safe_key:
                mutagen[safe_key] = [c.name for c in entry.contributors]
        except Exception as e:
            log.debug(f"Skipping invalid credit tag '{entry.type}': {e}")

    try:
        mutagen.save()
    except (OSError, Exception) as e:
        # On Windows SMB shares, mutagen's resize_bytes() can fail with
        # [Errno 22] Invalid argument because seek()+read() doesn't work
        # reliably over SMB. Fallback: write metadata to a local temp file
        # then replace the original.
        log.debug(f"Direct FLAC save failed ({e}), retrying via temp file...")
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".flac")
        tmp = Path(tmp_path)
        try:
            import os
            os.close(tmp_fd)
            shutil.copy2(track_path, tmp)
            tmp_mutagen = MutagenFLAC(tmp)
            tmp_mutagen.update(mutagen)
            tmp_mutagen.save()
            shutil.move(str(tmp), str(track_path))
            log.debug(f"FLAC metadata saved via temp file for {track_path.name}")
        except Exception as e2:
            log.warning(f"Could not write FLAC metadata for {track_path.name}: {e2}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


# =====================
# M4A / MP4 metadata
# =====================

def add_m4a_metadata(track_path: Path, metadata: Metadata) -> None:
    """
    Write M4A (MP4) metadata tags using Mutagen.

    This function uses raw MP4 atoms (©nam, ©alb, etc.) so that
    Windows Explorer and most players correctly show the updated
    title, album and artist fields.
    """
    mp4 = MutagenMP4(track_path)

    # Clean any previous title atoms to avoid stale values
    for key in ["\xa9nam"]:
        if key in mp4:
            del mp4[key]

    # Cover art
    if metadata.cover_data:
        mp4["covr"] = [
            MP4Cover(metadata.cover_data, imageformat=MP4Cover.FORMAT_JPEG)
        ]

    # Lyrics
    if metadata.lyrics:
        mp4["\xa9lyr"] = [metadata.lyrics]

    # Basic tags
    mp4["\xa9nam"] = metadata.title                    # Title
    mp4["\xa9alb"] = metadata.album_title              # Album
    mp4["aART"] = metadata.album_artist                # Album artist
    mp4["\xa9ART"] = metadata.artists_list or [metadata.artists]  # Track artists (multi-value)
    
    # Date / Year (extract year only)
    if metadata.date:
        try:
            # Try to parse date string to get just the year
            dt = datetime.fromisoformat(metadata.date)
            mp4["\xa9day"] = str(dt.year)
        except Exception:
            # Fallback: grab first 4 chars if they represent a valid year (1-9999)
            if len(metadata.date) >= 4 and metadata.date[:4].isdigit() and 1 <= int(metadata.date[:4]) <= 9999:
                mp4["\xa9day"] = metadata.date[:4]
            else:
                mp4["\xa9day"] = metadata.date
            
    if metadata.copyright:
        mp4["cprt"] = metadata.copyright               # Copyright
    if metadata.comment:
        mp4["\xa9cmt"] = metadata.comment              # Comment
    if metadata.genre:
        mp4["\xa9gen"] = metadata.genre                # Genre

    # Track and disc numbers (current, total)
    try:
        track_no = int(metadata.track_number)
    except ValueError:
        track_no = 0
    try:
        disc_no = int(metadata.disc_number)
    except ValueError:
        disc_no = 0

    mp4["trkn"] = [(track_no, 0)]
    mp4["disk"] = [(disc_no, 0)]

    # BPM
    if metadata.bpm:
        try:
            mp4["tmpo"] = [int(float(metadata.bpm))]
        except ValueError:
            pass

    mp4.save()


# =====================
# Main entry point
# =====================

def add_track_metadata(
    path: Path,
    track: Track,
    date: str = "",
    album_artist: str = "",
    lyrics: str = "",
    cover_data: bytes | None = None,
    credits: list[AlbumItemsCredits.ItemWithCredits.CreditsEntry] | None = None,
    comment: str = "",
    genre: str | None = None,
    artist_separator: str = DEFAULT_ARTIST_SEPARATOR,
) -> None:
    """
    Add FLAC or M4A metadata based on file extension.

    Title is cleaned to remove 'feat.' parts, while the full artist list
    (main + featured) is stored in the ARTIST/©ART field.
    """
    # Build artist list — sorted for consistency
    artists_sorted = sorted(a.name.strip() for a in track.artists)
    # Separator-joined string → used for filenames and folder names
    artists_str = artist_separator.join(artists_sorted)
    # Individual list → written as repeated tags in FLAC/M4A (spec-correct)
    artists_list = artists_sorted

    # Original title + version from Tidal
    raw_title = f"{track.title} ({track.version})" if track.version else track.title
    all_artists_str = ", ".join(artists_sorted) or artists_str
    clean_title = clean_track_title(raw_title, all_artists_str)

    metadata = Metadata(
        title=clean_title,
        track_number=str(track.trackNumber),
        disc_number=str(track.volumeNumber),
        copyright=track.copyright,
        album_artist=album_artist,
        artists=artists_str,
        artists_list=artists_list,
        album_title=track.album.title,
        date=date,
        isrc=track.isrc,
        bpm=str(track.bpm or "") if track.bpm is not None else None,
        lyrics=lyrics or None,
        cover_data=cover_data,
        credits=credits or [],
        comment=comment,
        genre=genre or track.album.genre,
    )

    ext = path.suffix.lower()

    if ext == ".flac":
        try:
            add_flac_metadata(path, metadata)
        except Exception as e:
            from mutagen.flac import FLACNoHeaderError
            if not isinstance(e, FLACNoHeaderError):
                raise
            # File has .flac extension but content is not FLAC.
            # Try M4A directly first, then fix_mp4_faststart as last resort.
            try:
                add_m4a_metadata(path, metadata)
            except Exception:
                from tiddl.core.utils.ffmpeg import fix_mp4_faststart
                try:
                    fixed = fix_mp4_faststart(path)
                    add_m4a_metadata(fixed, metadata)
                except Exception as inner:
                    log.warning(f"Could not write metadata to {path} (FLAC/M4A fallback failed): {inner}")
    elif ext == ".m4a":
        add_m4a_metadata(path, metadata)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")
