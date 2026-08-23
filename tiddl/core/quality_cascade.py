"""User-chosen quality cascade with Dolby Atmos as a rung.

TIDAL does not expose a single linear quality order that includes Atmos: Atmos
is a separate track *version* (``audioMode`` ``DOLBY_ATMOS``), delivered lossy
(~768 kbps immersive EAC3), while the real tiers are HI_RES_LOSSLESS / LOSSLESS
(both FLAC) and HIGH / LOW (AAC). We arrange them into ONE ladder ordered by
**fidelity** (lossless before lossy):

    max  →  high  →  atmos  →  normal  →  low

The user picks the STARTING rung with ``-q`` (e.g. ``-q max`` starts at the top,
``-q atmos`` starts at Atmos for those who want it first); the downloader then
walks DOWN the ladder from that rung and takes the first rung the track actually
offers. So "prefer FLAC over Atmos" is just "start at high or max": a dual-format
track resolves to its FLAC, and only a track with no FLAC falls through to Atmos.

Per-track availability comes from ``mediaMetadata.tags``:

* ``max``   — a ``HIRES_LOSSLESS`` tag (24-bit FLAC).
* ``high``  — a ``LOSSLESS`` tag AND the track is NOT Atmos. On an Atmos track the
  LOSSLESS tier returns the Atmos stream, not a 16-bit FLAC (verified against
  TIDAL), so the only FLAC for an Atmos track is ``max``; ``high`` is therefore
  not offered for it and the cascade falls straight to the ``atmos`` rung.
* ``atmos`` — a ``DOLBY_ATMOS`` tag.
* ``normal`` / ``low`` — always (AAC is universal).
"""
from __future__ import annotations

from typing import Dict, Iterable, List

# Fidelity order, highest to lowest.
QUALITY_LADDER: List[str] = ["max", "high", "atmos", "normal", "low"]

# Which TIDAL audioquality each rung is fetched at.
RUNG_TO_API: Dict[str, str] = {
    "max": "HI_RES_LOSSLESS",
    "high": "LOSSLESS",
    "atmos": "LOSSLESS",  # LOSSLESS request on an Atmos track yields the Atmos stream
    "normal": "HIGH",
    "low": "LOW",
}


def _tagset(tags: Iterable[str]) -> set:
    return {str(t).upper() for t in (tags or [])}


def available_rungs(tags: Iterable[str]) -> Dict[str, bool]:
    """Which ladder rungs this track actually offers, from its media tags."""
    t = _tagset(tags)
    atmos = "DOLBY_ATMOS" in t
    return {
        "max": "HIRES_LOSSLESS" in t,
        # An Atmos track's LOSSLESS tier is the Atmos stream, not a FLAC, so it
        # has no separate `high` (16-bit FLAC) rung — its FLAC lives only at `max`.
        "high": ("LOSSLESS" in t) and not atmos,
        "atmos": atmos,
        "normal": True,
        "low": True,
    }


# The two lossless-FLAC rungs, and everything below them, in fidelity order.
FLAC_RUNGS = ("max", "high")
BELOW_FLAC = ("atmos", "normal", "low")


def resolve_cascade(start: str, tags: Iterable[str]) -> List[str]:
    """Ordered rungs to attempt for a track, given the user's ``start`` rung.

    **FLAC is preferred over Atmos.** When ``start`` is a FLAC rung (``high`` or
    ``max``), BOTH FLAC rungs are tried before Atmos — the chosen one first, then
    the other by fidelity — so e.g. ``-q high`` on an Atmos track (which has no
    16-bit FLAC) climbs to ``max`` for the 24-bit FLAC instead of dropping to
    Atmos. Most users want any FLAC before Atmos; those who actually want Atmos
    start at ``-q atmos``, which cascades plainly down (atmos > normal > low).

    An unknown ``start`` is treated as the top (``max``) so a stray value never
    silently drops the track to AAC."""
    if start not in QUALITY_LADDER:
        start = "max"
    avail = available_rungs(tags)
    if start in FLAC_RUNGS:
        order = [start] + [r for r in FLAC_RUNGS if r != start] + list(BELOW_FLAC)
    else:
        order = QUALITY_LADDER[QUALITY_LADDER.index(start):]
    return [r for r in order if avail.get(r)]


def cascade_api_qualities(start: str, tags: Iterable[str]) -> List[str]:
    """The cascade as TIDAL audioquality strings, de-duplicated in order."""
    out: List[str] = []
    for rung in resolve_cascade(start, tags):
        api = RUNG_TO_API[rung]
        if not out or out[-1] != api:
            out.append(api)
    return out
