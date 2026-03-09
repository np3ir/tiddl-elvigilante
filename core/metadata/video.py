from __future__ import annotations
from pathlib import Path
from logging import getLogger
from mutagen.easymp4 import EasyMP4 as MutagenEasyMP4
from tiddl.core.api.models import Video
from tiddl.core.utils.ffmpeg import is_ffmpeg_installed, convert_to_mp4

log = getLogger(__name__)


def add_video_metadata(path: Path, video: Video, artist_separator: str = " / "):
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
    # Base metadata
    artists_str = artist_separator.join([a.name.strip() for a in video.artists]) if video.artists else ""
    
    meta_update = {
        "title": video.title,
        "artist": artists_str,
    }

    # Optional metadata: Only add if value exists
    if video.artist:
        meta_update["albumartist"] = video.artist.name
    
    if video.album and video.album.title:
        meta_update["album"] = video.album.title

    # Prefer releaseDate (from metadata) over streamStartDate
    if video.releaseDate:
        meta_update["date"] = str(video.releaseDate)
    elif video.streamStartDate:
        meta_update["date"] = str(video.streamStartDate)

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