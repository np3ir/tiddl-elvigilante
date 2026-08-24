from dataclasses import dataclass
from typing import Any


QUALITY_RANK = {
    "LOW": 0,
    "HIGH": 1,
    "LOSSLESS": 2,
    "HI_RES_LOSSLESS": 3,
}

REQUESTED_QUALITY = {
    "low": "LOW",
    "normal": "HIGH",
    "atmos": "LOSSLESS",  # the Atmos rung is fetched at the LOSSLESS tier
    "high": "LOSSLESS",
    "max": "HI_RES_LOSSLESS",
}


@dataclass(frozen=True)
class StreamInspection:
    audio_mode: str
    audio_quality: str
    bit_depth: int | None
    sample_rate: int | None
    is_stereo: bool
    meets_requested_quality: bool
    accepted: bool
    reason: str = ""


def inspect_track_stream(
    stream: Any,
    *,
    audio_mode: str = "auto",
    requested_quality: str = "high",
    quality_policy: str = "flexible",
) -> StreamInspection:
    """Inspect playback metadata before any media URL is downloaded."""
    mode = str(getattr(stream, "audioMode", "") or "UNKNOWN").upper()
    quality = str(getattr(stream, "audioQuality", "") or "UNKNOWN").upper()
    wanted = REQUESTED_QUALITY.get(requested_quality.casefold(), requested_quality.upper())
    is_stereo = mode == "STEREO"
    meets_quality = QUALITY_RANK.get(quality, -1) >= QUALITY_RANK.get(wanted, 99)

    if audio_mode.casefold() == "stereo" and not is_stereo:
        return StreamInspection(
            mode,
            quality,
            getattr(stream, "bitDepth", None),
            getattr(stream, "sampleRate", None),
            is_stereo,
            meets_quality,
            False,
            f"requested stereo but TIDAL returned {mode}",
        )

    # The Atmos rung has no single clean tier (its stream reports HIGH/LOSSLESS
    # depending on the master), so an exact-tier strict check can never pass for
    # it — skip the gate for `-q atmos` rather than always stopping the download.
    if (
        quality_policy.casefold() == "strict"
        and requested_quality.casefold() != "atmos"
        and quality != wanted
    ):
        return StreamInspection(
            mode,
            quality,
            getattr(stream, "bitDepth", None),
            getattr(stream, "sampleRate", None),
            is_stereo,
            meets_quality,
            False,
            f"requested exact quality {wanted} but TIDAL returned {quality}",
        )

    return StreamInspection(
        mode,
        quality,
        getattr(stream, "bitDepth", None),
        getattr(stream, "sampleRate", None),
        is_stereo,
        meets_quality,
        True,
    )
