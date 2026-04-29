"""
Playback event reporter — simulates web player activity.

Sends playback_session events to TIDAL's event API after each track download,
matching the pattern a real browser session would produce.
"""
from __future__ import annotations
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger(__name__)

EVENTS_URL = "https://api.tidal.com/v1/events"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0000"


async def report_playback(
    headers: dict,
    track_id: int,
    duration: int,     # seconds
    audio_quality: str,
    country_code: str,
    source_type: str = "ALBUM",
    source_id: Optional[str] = None,
) -> None:
    """
    Fire-and-forget POST to TIDAL's events endpoint.
    Simulates a completed web player stream session.
    Does NOT block the download flow — errors are silently ignored.
    """
    import aiohttp
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=duration)
        session_id = str(uuid.uuid4())

        payload = {
            "events": [
                {
                    "group": "playback",
                    "name": "playback_session",
                    "version": 1,
                    "ts": _iso(now),
                    "payload": {
                        "playbackSessionId": session_id,
                        "requestedStreamingSessionId": session_id,
                        "actualStreamingSessionId": session_id,
                        "startAssetPosition": 0.0,
                        "endAssetPosition": float(duration),
                        "actualProductId": str(track_id),
                        "requestedProductId": str(track_id),
                        "actualAudioQuality": audio_quality,
                        "requestedAudioQuality": audio_quality,
                        "sourceType": source_type,
                        "sourceId": str(source_id) if source_id else str(track_id),
                        "sessionType": "PLAYBACK",
                        "outputDeviceType": "WEB_PLAYER",
                        "outputDevice": "BROWSER",
                        "playbackStart": _iso(start),
                        "playbackEnd": _iso(now),
                    },
                }
            ]
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                EVENTS_URL,
                json=payload,
                params={"countryCode": country_code},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                log.debug(f"Playback event for track {track_id}: HTTP {resp.status}")

    except Exception as e:
        log.debug(f"Playback event silently failed for track {track_id}: {e}")
