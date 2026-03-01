from __future__ import annotations
import subprocess
from pathlib import Path


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

    run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(output_path)])

    source.unlink()

    return output_path


def extract_flac(source: Path) -> Path:
    """
    Extracts flac audio from mp4 container
    """

    tmp = source.with_suffix(".tmp.flac")
    dest = source.with_suffix(".flac")

    run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(tmp)])

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

    run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", "-movflags", "+faststart", str(tmp)])

    # Replace original only if tmp was created
    if tmp.exists():
        tmp.replace(source)

    return source
