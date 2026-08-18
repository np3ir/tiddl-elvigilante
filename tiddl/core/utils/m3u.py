from __future__ import annotations
from logging import getLogger
from pathlib import Path
from typing import Literal, Optional

from tiddl.core.api.models import Track
from tiddl.core.utils import destination_anchor as anchor

log = getLogger(__name__)


def save_tracks_to_m3u(
    tracks_with_path: list[tuple[Path, Track]],
    path: Path,
    root: Optional[Path] = None,
    mode: Literal["off", "strict"] = "off",
    tracker: Optional["anchor.IdentityFailureTracker"] = None,
):
    """
    tracks_with_path: [track_path, Track]
    path: m3u file location
    filename: name of the m3u file
    root/mode/tracker: destination-volume identity guard (operation 7, see
        tiddl.core.utils.destination_anchor). Called synchronously — this
        function is always invoked directly on the event loop, never inside
        asyncio.to_thread, so touching `tracker` here is safe (v2.4 mandatory
        safeguard #2 is a non-issue for this call site by construction, not
        by a caught-after-to_thread pattern). `root` may be omitted (mode
        stays "off") for callers that predate this feature, e.g. direct
        unit tests of this function.
    """

    file = path.with_suffix(".m3u")
    log.debug(f"{path=}, {file=}")

    if not tracks_with_path:
        log.warning(f"can't save '{file}', no tracks")
        return

    if root is not None:
        try:
            anchor.assert_write_allowed(root, file, mode)
        except anchor.DestinationNotTrusted as e:
            # Class C (v2.3 §3): every track in this M3U already has its own
            # truthful _db_insert record by the time this runs (the M3U is
            # written after all per-track processing completes) — nothing to
            # withhold here, just a distinguishable warning + tracker trip.
            if tracker is not None:
                tracker.mark_refused(e.check)
            log.warning(
                f"[destination-identity] refused m3u write for {file}: {e.check.reason}"
            )
            return

    try:
        file.parent.mkdir(parents=True, exist_ok=True)

        with file.open("w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for track_path, track in tracks_with_path:
                f.write(
                    f"#EXTINF:{track.duration},{track.artist.name if track.artist else ''} - {track.title}\n{track_path}\n"
                )

            log.debug(f"saved m3u file as '{file}' with {len(tracks_with_path)} tracks")

    except Exception as e:
        log.error(f"can't save m3u file: {e}")
