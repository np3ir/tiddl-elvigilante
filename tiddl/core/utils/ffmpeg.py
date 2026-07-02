from __future__ import annotations
import subprocess
from pathlib import Path


def _ffmpeg_path(p: Path) -> str:
    """
    Convert a path to a string safe for ffmpeg on Windows.
    ffmpeg does not support the long-path prefix.
    Path() on Windows normalizes the long-path prefix to a single leading backslash.
    This function strips it so ffmpeg receives a standard UNC or drive path.
    """
    s = str(p)
    # \?\UNC\server\share  ->  \\server\share  (7 chars prefix)
    if s.startswith("\\?\\UNC\\"):
        return "\\\\" + s[7:]
    # \?\C:\...  ->  C:\...  (3 chars prefix)
    if s.startswith("\\?\\"):
        return s[3:]
    return s


def run(cmd: list[str]):
    """Run process without printing to terminal"""
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_ffmpeg_installed() -> bool:
    """Checks if `ffmpeg` is installed."""

    try:
        run(["ffmpeg", "-version"])
        return True
    except FileNotFoundError:
        return False


def convert_to_mp4(source: Path) -> Path:
    output_path = source.with_suffix(".mp4")

    run(["ffmpeg", "-y", "-i", _ffmpeg_path(source), "-c", "copy", _ffmpeg_path(output_path)])

    source.unlink()

    return output_path


def is_mp4_container(path: Path) -> bool:
    """
    Checks the actual bytes on disk for an MP4/M4A 'ftyp' box, regardless of
    the file's extension. TIDAL doesn't only wrap HI_RES_LOSSLESS in MP4 —
    it has also started delivering plain LOSSLESS this way, so a '.flac'
    file's real container can't be trusted from the requested/reported
    quality alone.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(12)
    except OSError:
        return False
    return header[4:8] == b"ftyp"


def extract_flac(source: Path) -> Path:
    """
    Extracts flac audio from mp4 container
    """

    tmp = source.with_suffix(".tmp.flac")
    dest = source.with_suffix(".flac")

    run(["ffmpeg", "-y", "-i", _ffmpeg_path(source), "-c", "copy", _ffmpeg_path(tmp)])

    if not tmp.exists():
        raise RuntimeError(f"ffmpeg did not produce output for {source}")

    tmp.replace(dest)

    # Delete source (e.g. .m4a) only if it's different from the destination (.flac)
    if source != dest:
        try:
            source.unlink()
        except OSError:
            pass

    return dest


def fix_mp4_faststart(source: Path) -> Path:
    """
    Remux MP4/M4A to move 'moov' atom to the beginning and fix fragmented containers.
    Keeps the same extension and replaces the source on success.
    """
    tmp = source.with_name(source.stem + ".fixed" + source.suffix)

    run(["ffmpeg", "-y", "-i", _ffmpeg_path(source), "-c", "copy", "-movflags", "+faststart", _ffmpeg_path(tmp)])

    # Replace original only if tmp was created
    if tmp.exists():
        tmp.replace(source)

    return source
