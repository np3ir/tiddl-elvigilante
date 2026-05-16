from __future__ import annotations
from pathlib import Path
from logging import getLogger
from mutagen.easymp4 import EasyMP4 as MutagenEasyMP4
from tiddl.core.api.models import Video
from tiddl.core.utils.ffmpeg import is_ffmpeg_installed, convert_to_mp4
from tiddl.core.utils.format import DEFAULT_ARTIST_SEPARATOR

log = getLogger(__name__)


def add_video_metadata(path: Path, video: Video, artist_separator: str = DEFAULT_ARTIST_SEPARATOR):
    """
    Adds metadata to an MP4 video file. 
    If the file is a TS file, it attempts to convert it to MP4 first using FFmpeg.
    """
    suffix = path.suffix.lower()

    # 1. Handle TS Conversion
    if suffix == ".ts":
        if not is_ffmpeg_installed():
            log.warning(f"skip video metadata, ffmpeg not installed for TS: {path}")
            return
        
        try:
            path = convert_to_mp4(path)
        except Exception as e:
            log.error(f"reconvert TS to MP4 failed: {path} -> {e}")
            return

    # 2. Validate Extension (must be .mp4 at this point)
    elif suffix != ".mp4":
        log.warning(f"skip video metadata, not MP4: {path}")
        return

    # 3. Load Mutagen File
    try:
        mutagen = MutagenEasyMP4(path)
    except Exception as e:
        log.error(f"could not open MP4 for metadata: {path} -> {e}")
        return

    # 4. Prepare Metadata
    _raw   = video.artists or []
    _main  = sorted([a.name for a in _raw if getattr(a, 'type', None) == "MAIN"     and a.name])
    _feat  = sorted([a.name for a in _raw if getattr(a, 'type', None) == "FEATURED" and a.name])
    artists_list = (_main + _feat) or [a.name for a in _raw if a.name] or ["Unknown Artist"]

    meta_update = {
        "title":  video.title,
        "artist": artists_list,
    }

    # Optional metadata: Only add if value exists
    if video.artist:
        meta_update["albumartist"] = video.artist.name

    if video.album and video.album.title:
        meta_update["album"] = video.album.title

    # Year-only date — matches music track behavior
    _date = video.releaseDate or getattr(video, 'streamStartDate', None)
    if _date:
        meta_update["date"] = str(_date.year) if hasattr(_date, 'year') else str(_date)[:4]

    if video.trackNumber:
        meta_update["tracknumber"] = str(video.trackNumber)

    if video.volumeNumber:
        meta_update["discnumber"] = str(video.volumeNumber)

    # 5. Apply and Save
    try:
        # Filter out None values just in case
        clean_update = {k: v for k, v in meta_update.items() if v is not None}
        mutagen.update(clean_update)
        mutagen.save(path)
    except Exception as e:
        log.error(f"could not save MP4 metadata: {path} -> {e}")