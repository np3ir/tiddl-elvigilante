"""Read-only discovery of alternate stereo editions.

TIDAL commonly publishes stereo and Dolby Atmos mixes as separate album and
track IDs.  This module deliberately does not affect downloads: it only finds
and scores possible stereo counterparts so the behaviour can be evaluated
before automatic substitution is introduced.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

SUPPORTED_QUALITIES = ("low", "normal", "high", "max")


def quality_fallback_order(requested_quality: str, policy: str = "flexible") -> tuple[str, ...]:
    """Catalog tiers to try, from the user's ceiling down to LOW."""
    quality = requested_quality.casefold()
    if quality not in SUPPORTED_QUALITIES:
        raise ValueError(f"unsupported quality: {requested_quality}")
    if policy.casefold() == "strict":
        return (quality,)
    if policy.casefold() != "flexible":
        raise ValueError(f"unsupported quality policy: {policy}")
    index = SUPPORTED_QUALITIES.index(quality)
    return tuple(reversed(SUPPORTED_QUALITIES[: index + 1]))


def normalize_catalog_text(value: str | None) -> str:
    """Normalize catalog text for comparison, preserving meaningful words."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def album_modes(album: Any) -> tuple[str, ...]:
    return tuple(str(mode).upper() for mode in (getattr(album, "audioModes", None) or []))


def is_stereo_album(album: Any) -> bool:
    return "STEREO" in album_modes(album)


def is_atmos_album(album: Any) -> bool:
    return "DOLBY_ATMOS" in album_modes(album)


def album_quality_tags(album: Any) -> tuple[str, ...]:
    metadata = getattr(album, "mediaMetadata", None)
    return tuple(str(tag).upper() for tag in (getattr(metadata, "tags", None) or []))


def supports_requested_quality(album: Any, requested_quality: str) -> bool:
    """Whether the TIDAL catalog advertises the requested stereo tier."""
    quality = requested_quality.casefold()
    if quality not in SUPPORTED_QUALITIES:
        raise ValueError(f"unsupported quality: {requested_quality}")
    if not is_stereo_album(album):
        return False
    # Every stereo album can be requested from TIDAL at its lossy LOW/HIGH
    # delivery tiers; catalog lossless tags only matter for High and MAX.
    if quality in ("low", "normal"):
        return True
    tags = set(album_quality_tags(album))
    if quality == "max":
        return "HIRES_LOSSLESS" in tags
    # A HiRes edition can also be requested at LOSSLESS by the playback API.
    return bool(tags.intersection({"LOSSLESS", "HIRES_LOSSLESS"}))


def _title_similarity(source: Any, candidate: Any) -> float:
    source_title = normalize_catalog_text(getattr(source, "title", ""))
    candidate_title = normalize_catalog_text(getattr(candidate, "title", ""))
    return SequenceMatcher(None, source_title, candidate_title).ratio()


def _track_title(track: Any) -> str:
    title = getattr(track, "title", "")
    version = getattr(track, "version", None)
    return f"{title} {version}" if version else str(title)


def _tracks(items: Any) -> list[Any]:
    result = []
    for wrapped in getattr(items, "items", []) or []:
        item = getattr(wrapped, "item", wrapped)
        # Album item endpoints can include videos; edition matching is audio-only.
        if getattr(wrapped, "type", "track") == "track":
            result.append(item)
    return result


def _title_multiset(tracks: Iterable[Any]) -> list[str]:
    return [normalize_catalog_text(_track_title(track)) for track in tracks]


def _match_titles(source: list[str], candidate: list[str]) -> tuple[int, list[str], list[str]]:
    """Return exact normalized matches and unmatched titles, preserving duplicates."""
    remaining = list(candidate)
    missing: list[str] = []
    matches = 0
    for title in source:
        try:
            remaining.remove(title)
            matches += 1
        except ValueError:
            missing.append(title)
    return matches, missing, remaining


@dataclass(frozen=True)
class EditionCandidate:
    album: Any
    score: float
    title_similarity: float
    track_overlap: float
    missing_tracks: tuple[str, ...]
    extra_tracks: tuple[str, ...]

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.missing_tracks or self.extra_tracks)


@dataclass(frozen=True)
class EditionSearchResult:
    source: Any
    requested_quality: str
    candidates: tuple[EditionCandidate, ...]

    @property
    def best(self) -> EditionCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def source_satisfies_request(self) -> bool:
        return supports_requested_quality(self.source, self.requested_quality)


def score_stereo_candidate(
    source: Any,
    candidate: Any,
    source_tracks: Iterable[Any],
    candidate_tracks: Iterable[Any],
) -> EditionCandidate | None:
    """Score a stereo candidate; unrelated titles are rejected early."""
    if getattr(source, "id", None) == getattr(candidate, "id", None):
        return None
    if not is_stereo_album(candidate):
        return None

    title_similarity = _title_similarity(source, candidate)
    if title_similarity < 0.85:
        return None

    source_names = _title_multiset(source_tracks)
    candidate_names = _title_multiset(candidate_tracks)
    matches, missing, extra = _match_titles(source_names, candidate_names)
    denominator = max(len(source_names), len(candidate_names), 1)
    track_overlap = matches / denominator

    source_artist = getattr(getattr(source, "artist", None), "id", None)
    candidate_artist = getattr(getattr(candidate, "artist", None), "id", None)
    artist_match = bool(source_artist and source_artist == candidate_artist)
    date_match = bool(
        getattr(source, "releaseDate", None)
        and getattr(source, "releaseDate", None) == getattr(candidate, "releaseDate", None)
    )
    explicit_match = getattr(source, "explicit", None) == getattr(candidate, "explicit", None)
    source_duration = max(int(getattr(source, "duration", 0) or 0), 1)
    candidate_duration = max(int(getattr(candidate, "duration", 0) or 0), 1)
    duration_similarity = min(source_duration, candidate_duration) / max(
        source_duration, candidate_duration
    )

    score = (
        0.35 * title_similarity
        + 0.15 * float(artist_match)
        + 0.10 * float(date_match)
        + 0.30 * track_overlap
        + 0.05 * duration_similarity
        + 0.05 * float(explicit_match)
    )
    return EditionCandidate(
        album=candidate,
        score=score,
        title_similarity=title_similarity,
        track_overlap=track_overlap,
        missing_tracks=tuple(missing),
        extra_tracks=tuple(extra),
    )


def find_stereo_editions(
    api: Any,
    album_id: int,
    requested_quality: str = "max",
    minimum_score: float = 0.75,
    quality_policy: str = "strict",
) -> EditionSearchResult:
    """Find likely stereo counterparts using only read-only catalog endpoints."""
    requested_quality = requested_quality.casefold()
    if requested_quality not in SUPPORTED_QUALITIES:
        raise ValueError(f"unsupported quality: {requested_quality}")
    tiers = quality_fallback_order(requested_quality, quality_policy)
    source = api.get_album(album_id=album_id)
    for tier in tiers:
        if supports_requested_quality(source, tier):
            return EditionSearchResult(source=source, requested_quality=tier, candidates=())
    artist = getattr(source, "artist", None)
    artist_id = getattr(artist, "id", None)
    if not artist_id:
        return EditionSearchResult(
            source=source, requested_quality=requested_quality, candidates=()
        )

    source_tracks = _tracks(api.get_album_items(album_id=album_id))
    albums_page = api.get_artist_albums(artist_id=artist_id, limit=100, offset=0)
    candidates_by_tier: dict[str, list[EditionCandidate]] = {tier: [] for tier in tiers}
    for album in getattr(albums_page, "items", []) or []:
        if getattr(album, "id", None) == album_id:
            continue
        candidate_tier = next(
            (tier for tier in tiers if supports_requested_quality(album, tier)), None
        )
        if candidate_tier is None:
            continue
        # Avoid one network request per album in a large discography. Track
        # lists are only fetched after the cheap catalog-title filter passes.
        if _title_similarity(source, album) < 0.85:
            continue
        candidate_tracks = _tracks(api.get_album_items(album_id=album.id))
        scored = score_stereo_candidate(source, album, source_tracks, candidate_tracks)
        if scored is not None and scored.score >= minimum_score:
            candidates_by_tier[candidate_tier].append(scored)

    for tier in tiers:
        candidates = candidates_by_tier[tier]
        if not candidates:
            continue
        candidates.sort(key=lambda value: (value.score, value.track_overlap), reverse=True)
        return EditionSearchResult(
            source=source,
            requested_quality=tier,
            candidates=tuple(candidates),
        )

    return EditionSearchResult(
        source=source,
        requested_quality=tiers[-1],
        candidates=(),
    )
