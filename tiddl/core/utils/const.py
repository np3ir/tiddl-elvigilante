from __future__ import annotations
from typing import Literal

from tiddl.core.api.models import StreamVideoQuality, TrackQuality

# Quality "rungs" the user can pick as the START of the download cascade. Ordered
# by FIDELITY, highest to lowest: max/high are lossless FLAC, atmos is the
# (lossy, immersive) Dolby Atmos version, normal/low are AAC. `atmos` is a rung,
# NOT a distinct TIDAL audioquality — it is served by requesting the LOSSLESS
# tier on an Atmos-flagged track (see tiddl.core.quality_cascade).
TRACK_QUALITY_LITERAL = Literal["low", "normal", "atmos", "high", "max"]
VIDEO_QUALITY_LITERAL = Literal["sd", "hd", "fhd"]

track_qualities: dict[TRACK_QUALITY_LITERAL, TrackQuality] = {
    "low": "LOW",
    "normal": "HIGH",
    "atmos": "LOSSLESS",  # Atmos stream comes back from the LOSSLESS request
    "high": "LOSSLESS",
    "max": "HI_RES_LOSSLESS",
}

video_qualities: dict[VIDEO_QUALITY_LITERAL, StreamVideoQuality] = {
    "sd": "LOW",
    "hd": "MEDIUM",
    "fhd": "HIGH",
}
