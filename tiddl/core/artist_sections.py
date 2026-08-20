"""Resolve an artist's compilation / live / "appears on" releases.

TIDAL's flat ``get_artist_albums`` endpoint returns compilations and live albums
typed as plain ``ALBUM`` (verified against several artists), so they cannot be
told apart there. The artist *page* endpoint (``pages/artist``) — the one the web
UI renders — instead groups releases into titled sections ("Featured Albums",
"EP & Singles", "Compilations", "Live albums", "Appears On"). This module reads
those sections so an artist download can optionally exclude a release type by
album id.

The only field that distinguishes a section is its (English) ``title``; the
module ``id`` / ``dataApiPath`` are opaque per-artist UUIDs. The page returns
English titles even for non-English accounts, and we additionally request
``locale=en_US`` to bias toward them, then match case-insensitively.
"""

from typing import Any

# Case-insensitive title fragments identifying each excludable section.
_SECTION_FRAGMENTS = {
    "compilations": ("compilation",),
    "live": ("live album",),
    "appears_on": ("appears on",),
}


def excluded_album_ids_from_page(
    page: Any,
    *,
    compilations: bool,
    live: bool,
    appears_on: bool,
) -> set:
    """Pure: given the ``pages/artist`` JSON (a dict), return the set of album
    ids in the requested sections. Unknown/misshaped input yields an empty set
    so this never blocks a download."""
    wanted = set()
    if compilations:
        wanted.add("compilations")
    if live:
        wanted.add("live")
    if appears_on:
        wanted.add("appears_on")
    if not wanted or not isinstance(page, dict):
        return set()

    excluded: set = set()
    for row in page.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        for module in row.get("modules", []) or []:
            if not isinstance(module, dict):
                continue
            title = str(module.get("title", "")).strip().lower()
            section = next(
                (
                    key
                    for key in wanted
                    if any(frag in title for frag in _SECTION_FRAGMENTS[key])
                ),
                None,
            )
            if section is None:
                continue
            paged = module.get("pagedList") or {}
            items = paged.get("items", []) if isinstance(paged, dict) else []
            for item in items or []:
                if isinstance(item, dict) and item.get("id") is not None:
                    excluded.add(item["id"])
    return excluded


def get_excluded_artist_album_ids(
    api: Any,
    artist_id: Any,
    *,
    compilations: bool,
    live: bool,
    appears_on: bool,
) -> set:
    """Fetch ``pages/artist`` and return the album ids to exclude for the
    requested release types. Any failure (network, parsing, missing endpoint)
    returns an empty set — a page hiccup must never block or crash a download."""
    if not (compilations or live or appears_on):
        return set()
    try:
        from pydantic import BaseModel

        class _RawPage(BaseModel):
            class Config:
                extra = "allow"

        page = api.client.fetch(
            _RawPage,
            "pages/artist",
            {
                "artistId": artist_id,
                "countryCode": getattr(api, "country_code", None),
                "deviceType": "BROWSER",
                "locale": "en_US",
            },
            expire_after=3600,
        )
        data = page.dict() if hasattr(page, "dict") else page
        return excluded_album_ids_from_page(
            data, compilations=compilations, live=live, appears_on=appears_on
        )
    except Exception:
        return set()
