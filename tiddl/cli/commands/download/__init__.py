from __future__ import annotations
import os
import re
import sys
import random
import typer
import click
import asyncio
import unicodedata

from pathlib import Path
from logging import getLogger
from rich.live import Live

from requests import HTTPError
from typing_extensions import Annotated
from typing import Union, Optional, List

from tiddl.core.cancel import is_cancelled
from tiddl.core.metadata import add_track_metadata, add_video_metadata, Cover
from tiddl.core.api import ApiError
from tiddl.core.api.models import Album, Track, Video, AlbumItemsCredits
from tiddl.core.utils.format import format_template
from tiddl.core.utils.m3u import save_tracks_to_m3u
from tiddl.core.utils import destination_anchor as anchor
from tiddl.core.edition_resolver import find_stereo_editions
from tiddl.core.artist_sections import get_excluded_artist_album_ids
from tiddl.core.download_policy import SessionTrackLimit
from tiddl.cli.config import (
    CONFIG,
    TRACK_QUALITY_LITERAL,
    VIDEO_QUALITY_LITERAL,
    ARTIST_SINGLES_FILTER_LITERAL,
    VALID_M3U_RESOURCE_LITERAL,
    VIDEOS_FILTER_LITERAL,
)
from tiddl.cli.utils.resource import TidalResource
from tiddl.cli.ctx import Context
from tiddl.cli.commands.auth import refresh
from tiddl.cli.commands.subcommands import register_subcommands


from .downloader import Downloader
from .output import RichOutput


def _fold_accents(s: str) -> str:
    """Strip diacritics for loose comparison (Tidal spells the same person's
    name inconsistently across endpoints, e.g. 'Raúl' vs 'Raül')."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def enrich_track_artists(item: Track, api) -> None:
    """Agrega Featured Artists faltantes del endpoint /contributors.

    Tidal a veces elimina featured artists del array artists[] principal
    pero los mantiene en /contributors. Mutamos la lista in-place para que
    tanto format_template (filename) como add_track_metadata (tags) los incluyan.
    """
    if not isinstance(item, Track):
        return
    try:
        existing_names = [a.name for a in item.artists if a.name]
        existing = {_fold_accents(n.lower()) for n in existing_names}
        featured = api.get_featured_from_contributors(item.id)
        for name in featured:
            n_folded = _fold_accents(name.lower())
            if n_folded in existing:
                continue
            # Some tracks have a single MAIN artist whose *name* is already a
            # compound "Artist feat. X, Y & Z" string (Tidal data quirk, e.g.
            # "Macaco feat. Niño De Elche, Bego Salazar & Raúl Refree" as ONE
            # artists[] entry). In that case X/Y/Z are already represented —
            # adding them again as separate FEATURED entries duplicates the
            # credit in both the filename and the tags. Skip any contributor
            # name that's already embedded (word-boundary match, accent-
            # insensitive since Tidal spells names inconsistently across its
            # own endpoints) inside an existing artist's name.
            pattern = re.compile(r"\b" + re.escape(n_folded) + r"\b")
            if any(pattern.search(_fold_accents(existing_name.lower())) for existing_name in existing_names):
                continue
            item.artists.append(Track.Artist(id=0, name=name, type="FEATURED"))
            existing.add(n_folded)
            existing_names.append(name)
    except Exception:
        pass


async def enrich_tracks_concurrently(items, api, limit: int = 8) -> None:
    """Enriquece featured artists de varios tracks en paralelo sin bloquear el event loop.

    Cada llamada a /contributors es HTTP síncrono (~300ms); ejecutarlas en
    threads con concurrencia acotada evita congelar las descargas activas.
    """
    tracks = [it for it in items if isinstance(it, Track)]
    if not tracks:
        return
    sem = asyncio.Semaphore(limit)

    async def _one(track):
        async with sem:
            await asyncio.to_thread(enrich_track_artists, track, api)

    await asyncio.gather(*[_one(t) for t in tracks])


download_command = typer.Typer(name="download")
register_subcommands(download_command)

log = getLogger(__name__)


# ---------------------------------------------------------------------------
# Guarded write helpers for operations 5/6/8 (destination-volume identity,
# v2.2 §1). Implementation-audit finding, 2026-08-18, P1 #3: these three
# writes used to check `assert_write_allowed` once on the event loop and
# THEN dispatch the actual mutation to `asyncio.to_thread`, possibly after a
# retry sleep (track metadata) or a multi-second network fetch with backoff
# (covers) — the protected mount could disappear in that gap between "we
# checked" and "we wrote," exactly the wrong-volume fallback this feature
# exists to prevent.
#
# Each helper below moves `assert_write_allowed` to run INSIDE the same
# synchronous unit of work as the mutation itself — the whole helper (check
# + write) is what gets handed to `asyncio.to_thread`, not just the write —
# so there is no await point, no sleep, and no network I/O between the
# check and the write it guards. `DestinationNotTrusted` propagates back
# through `await asyncio.to_thread(...)` and is caught by the caller on the
# event loop; none of these helpers touch `identity_tracker` themselves
# (v2.4 mandatory safeguard #2: no `asyncio.Event` mutation from a
# `to_thread` worker). Standalone module-level functions (not closures) so
# they're directly unit-testable without going through the full
# `handle_item` call graph — see tests/test_guarded_writes.py.
# ---------------------------------------------------------------------------

def _write_track_metadata_guarded(
    item_root: Path,
    download_path: Path,
    mode: str,
    *,
    track,
    lyrics,
    album_artist,
    cover_data,
    date,
    credits,
    comment,
    genre,
    artist_separator,
) -> None:
    """Operation 5. Callers dispatch this whole function via
    `asyncio.to_thread`, once per retry attempt, so a destination that
    disappeared between attempts (e.g. while waiting out a locked-file
    retry sleep) is caught on the very next attempt instead of writing
    metadata to a mount that is no longer verified."""
    anchor.assert_write_allowed(item_root, download_path, mode)
    add_track_metadata(
        path=download_path,
        track=track,
        lyrics=lyrics,
        album_artist=album_artist,
        cover_data=cover_data,
        date=date,
        credits=credits,
        comment=comment,
        genre=genre,
        artist_separator=artist_separator,
    )


def _write_video_metadata_guarded(
    item_root: Path,
    download_path: Path,
    mode: str,
    *,
    video,
    artist_separator,
) -> None:
    """Operation 6 — see `_write_track_metadata_guarded`'s docstring."""
    anchor.assert_write_allowed(item_root, download_path, mode)
    add_video_metadata(path=download_path, video=video, artist_separator=artist_separator)


async def _guarded_save_cover(
    cover: Cover,
    root: Path,
    path: Path,
    mode: str,
    tracker: "anchor.IdentityFailureTracker",
    label: str,
) -> None:
    """Operation 8. Fetches cover bytes (network I/O, its own retry backoff
    inside `Cover._get_data`) BEFORE the identity check runs — closing the
    gap `Cover.save_to_directory()` used to leave open by fetching AFTER a
    passing pre-dispatch check. The check and the actual file write then run
    together, synchronously, inside one `asyncio.to_thread` dispatch, via
    `Cover.write_prefetched` (no network I/O in that call — it raises
    `CoverDataNotPrefetched` rather than fetching if `data` weren't already
    prefetched, so a second network fetch can never happen from inside the
    guarded worker). Catches `DestinationNotTrusted` here, on the event
    loop, and marks `tracker` — the same safeguard-#2 discipline as the
    metadata helpers above.

    Second implementation-audit finding (2026-08-18), P1 #2: the fetch
    result is assigned to a local explicitly and checked BEFORE dispatching
    the guarded write — `cover.data` alone is not trustworthy here (a
    failed fetch leaves it `None`/falsy, and the old code's implicit
    reliance on `write_prefetched`'s own now-removed fallback silently
    re-fetched over the network on every such failure, after the identity
    check had already run once)."""
    file = path.with_suffix(".jpg")
    if file.exists():
        log.debug(f"cover exists ({file})")
        return

    data = await asyncio.to_thread(cover._get_data)
    if not data:
        log.warning(
            f"[destination-identity] no {label} cover data fetched, skipping write for {path}"
        )
        return
    cover.data = data

    def _guarded_write() -> None:
        anchor.assert_write_allowed(root, path, mode)
        cover.write_prefetched(path)

    try:
        await asyncio.to_thread(_guarded_write)
    except anchor.DestinationNotTrusted as e:
        tracker.mark_refused(e.check)
        log.warning(
            f"[destination-identity] refused {label} cover write "
            f"for {path}: {e.check.reason}"
        )


def _write_lrc_guarded(item_root: Path, lrc_path: Path, mode: str, text: str) -> None:
    """Operation 4. Runs on the event loop, not a worker thread (the write
    itself is a small synchronous text write, never dispatched to
    asyncio.to_thread) — check and write are already adjacent statements
    with no gap to close, unlike operations 5/6/8. Standalone module-level
    function purely for direct unit-test coverage (implementation-audit P2
    finding — this operation class had no dedicated test)."""
    anchor.assert_write_allowed(item_root, lrc_path, mode)
    lrc_path.write_text(text, encoding="utf-8")


def _touch_guarded(item_root: Path, download_path: Path, mode: str) -> None:
    """Operation 9 (v2.3 §1). Same non-threaded reasoning as
    `_write_lrc_guarded` above — extracted only for direct unit-test
    coverage. Unlike operations 4/5/6, a refusal here is COSMETIC: the
    caller must never treat this as withholding the already-completed
    `_db_insert` (Class B's documented exception, v2.3 §3) — that
    distinction is the caller's responsibility, not this function's."""
    anchor.assert_write_allowed(item_root, download_path, mode)
    os.utime(download_path, None)


def _should_insert_db_record(was_downloaded: bool, identity_refused: bool) -> bool:
    """Class B (v2.3 §3): a per-item `_db_insert` is withheld exactly when
    THIS item's own destination-identity refusal happened — operations 4
    (.lrc), 5 (track metadata) or 6 (video metadata), the only three that
    set `identity_refused = True`. Operation 9 (utime) deliberately never
    sets it (a stale mtime is cosmetic, never suppresses an insert that
    already ran — see `_touch_guarded`'s docstring), and operations 7/8
    (M3U/cover, Class C) run AFTER this decision and can never un-insert an
    already-truthful record.

    Standalone pure function so this exact decision has direct unit
    coverage (implementation-audit P2 finding, second round: outcome-level
    Class B/C DB semantics lacked a direct test) without needing to invoke
    the surrounding `handle_item` call graph."""
    return bool(was_downloaded and not identity_refused)


def _finalize_db_record(downloader, item, download_path, was_downloaded, identity_refused) -> None:
    """Class B (v2.3 §3): the COMPLETE per-item DB-insert effect —
    `handle_item` calls this, not `_should_insert_db_record` +
    `downloader._db_insert` inline. Implementation-audit finding, third
    round: a test that only exercises `_should_insert_db_record()` in
    isolation would keep passing even if `handle_item` stopped calling it,
    inverted its result, or inserted via a different path — because the
    helper and the call site were two different pieces of code. Making
    THIS function the single call site means a test that calls it
    directly, against a real `Downloader`'s real SQLite-backed
    `_db_insert`/`_db_lookup`, is exercising the exact same code
    `handle_item` runs — not a parallel copy of it."""
    if not download_path or not _should_insert_db_record(was_downloaded, identity_refused):
        return
    if isinstance(item, Track):
        downloader._db_insert(item.id, download_path, str(item.audioQuality))
    elif isinstance(item, Video):
        downloader._db_insert(item.id, download_path, "VIDEO")


def _download_exit_code(
    any_identity_refused: bool, cooperative_stop: bool = False
) -> Optional[int]:
    """v2.4 §2: the final `tiddl download` exit-code decision, evaluated
    once after every per-item and per-resource task in the run has
    completed (`identity_tracker.any_refused`, which is monotonic across
    however many concurrent tasks refused — see
    `IdentityFailureTracker.mark_refused`). Returns 1 (non-zero) if any
    destination-identity check refused a write during the run — a mixed
    run where some items succeeded and others refused still counts as
    "one or more refused," per the tracker's own monotonic semantics — or
    `None` to fall through to Typer's normal 0. Standalone pure function
    for direct unit coverage of this decision, same audit finding as
    `_should_insert_db_record` above."""
    return 1 if any_identity_refused or cooperative_stop else None


def _resource_resume_done(
    ok: bool, resume_enabled: bool, cancelled: bool, session_limit_reached: bool
) -> bool:
    """Whether a resource may be marked done in the ``--resume`` checkpoint.

    A resource is checkpointed ONLY when it completed cleanly AND the run was not
    stopped underneath it: not cancelled, and — crucially — the session-track
    limit was not reached during it. Reaching the cap cuts a resource short (its
    remaining tracks are never admitted), so marking it done would make a later
    ``--resume`` skip those tracks and silently lose them. Conservative on
    purpose: a resource that actually finished just before the cap is re-checked
    next run, where ``skip_existing`` makes it cheap. Pure function for direct
    unit coverage, same pattern as ``_download_exit_code``."""
    return ok and resume_enabled and not cancelled and not session_limit_reached


def _resolve_prefer_hires(track_quality: str, hires_client: str) -> bool:
    """Which client backs the WHOLE run, from the requested ``-q`` + config
    ``hires_client`` — the STABLE matrix (restored from ``d1613b0``):

    | quality  | hires_client | primary |
    |----------|--------------|---------|
    | high     | auto         | TV      |
    | max      | auto         | HiRes   |
    | any      | never        | TV      |
    | any      | always       | HiRes   |

    Only ``max`` (auto) or ``always`` put the strict HiRes client on the whole
    run; ``high`` (auto) and ``never`` stay on the lenient TV client. A ``high``
    run's occasional 24-bit-only (Atmos) track is escalated PER-TRACK to a
    secondary HiRes client instead of promoting the whole run (which is what
    ``05b1eca`` did, causing real 429s). Pure function for direct unit coverage."""
    if hires_client == "always":
        return True
    if hires_client == "never":
        return False
    return track_quality == "max"  # "auto"


def _finish_download_run(
    console, any_identity_refused: bool, cooperative_stop: bool = False
) -> "int | None":
    """Print the final-outcome warning for `tiddl download` (if any) and
    RETURN the exit code — `1` on identity-refusal or a cooperative safety
    stop (Cancel / rate-limit / account-flagged), else `None`.

    It must NOT call `sys.exit()` nor raise: under the Flet-embedded
    interpreter a `sys.exit()` from the download group's `call_on_close`
    teardown hard-kills the whole host process (the GUI closed on
    Cancel/401/429). The caller — `run()` — turns a non-zero return into
    `click.exceptions.Exit(code)`; `main()` maps that to a non-zero
    `SystemExit` for the CLI, and the in-process host catches it around
    `tiddl_app(standalone_mode=False)`. Kept as the single place that both
    prints AND decides, so a direct unit test asserting the RETURNED code
    exercises the real call site, not a parallel copy of its logic."""
    exit_code = _download_exit_code(any_identity_refused, cooperative_stop)
    if exit_code is not None:
        if any_identity_refused:
            console.print(
                "[red]One or more destination-identity checks refused a write "
                "this run — see the warnings above. Nothing was lost (retryable "
                "copies were retained where applicable); exiting non-zero.[/]"
            )
        else:
            from tiddl.core.cancel import stop_reason
            reason = stop_reason()
            if reason == "tidal_rate_limit":
                console.print(
                    "[red]Stopped: TIDAL rate-limited this run repeatedly. "
                    "Pushing further risks a hard account block. Wait a while, "
                    "then re-run — already-downloaded tracks are skipped, so it "
                    "resumes where it left off (tip: set max_tracks_per_session "
                    "to download big lists in chunks). Exiting non-zero.[/]"
                )
            elif reason == "tidal_account_flagged":
                console.print(
                    "[red]Stopped: TIDAL flagged the account and refused a token "
                    "refresh. Run 'tiddl auth login' to sign in again, then "
                    "re-run (already-downloaded tracks are skipped). "
                    "Exiting non-zero.[/]"
                )
            else:
                console.print(
                    "[red]The download engine stopped the run for safety; "
                    "exiting non-zero.[/]"
                )
    return exit_code


async def _bounded_dispatch(items, handler, concurrency: int, should_stop=None) -> None:
    """Run ``handler(item, index)`` over ``items`` with a FIXED pool of
    ``concurrency`` worker tasks, so at most ``concurrency`` tasks exist at once
    no matter how many items there are.

    This bounds memory on huge expanded runs: a playlist expanded into hundreds
    of thousands of artist resources would otherwise create one asyncio Task per
    resource up front (each parked on a semaphore), which is what exhausted RAM
    and hard-killed the process. asyncio is single-threaded, so pulling the next
    item from the shared iterator between awaits needs no lock. ``index`` is
    1-based, matching the previous ``enumerate(..., start=1)`` heartbeat.

    ``should_stop`` is an optional zero-arg predicate checked before each pull:
    once it returns True the workers stop taking NEW items and drain. This is how
    reaching ``max_tracks_per_session`` halts a run — no further resource is even
    dequeued (so none is enumerated or produces API traffic), while items already
    handed to a worker finish cleanly.

    Cancellation propagates: a worker raising ``CancelledError`` /
    ``KeyboardInterrupt`` (or the awaiting caller being cancelled) tears the
    whole pool down. A per-item error never kills a worker or orphans the rest —
    the existing ``wrapper`` already swallows every non-cancel exception, and
    this is the defensive backstop for anything it doesn't."""
    it = enumerate(items, start=1)

    async def _worker() -> None:
        while True:
            if should_stop is not None and should_stop():
                return
            try:
                index, item = next(it)
            except StopIteration:
                return
            try:
                await handler(item, index)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception:
                log.exception("resource dispatch failed; continuing")

    workers = [asyncio.create_task(_worker()) for _ in range(max(1, concurrency))]
    try:
        await asyncio.gather(*workers)
    except (asyncio.CancelledError, KeyboardInterrupt):
        for w in workers:
            if not w.done():
                w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise


def plan_stereo_resolution(result, keep_original: bool) -> tuple:
    """Pure pre-confirmation decision for the stereo resolution of one album.

    Returns ``(action, album_id, needs_confirmation)`` where ``action`` is one
    of ``"keep-source"``, ``"replace"`` or ``"skip"``. ``keep_original`` is the
    only behavioural difference between the two call sites: a direct album URL
    (``keep_original=False``) is skipped when no stereo edition qualifies,
    while an album reached by expanding an artist (``keep_original=True``)
    keeps its original id instead — so a whole-artist stereo run never silently
    drops an album. Kept a standalone pure function for direct unit coverage,
    same as ``_download_exit_code`` above."""
    source = result.source
    if result.source_satisfies_request:
        return ("keep-source", source.id, False)
    candidate = result.best
    if candidate is None:
        return ("keep-source" if keep_original else "skip", source.id, False)
    return ("replace", candidate.album.id, candidate.requires_confirmation)


class CatalogReadCache:
    """Per-run memoiser for the read-only catalog endpoints the stereo
    resolver hits repeatedly. Resolving a whole artist calls
    ``find_stereo_editions`` once per album, and each of those re-fetches the
    same ``get_artist_albums`` page (and re-reads album items), which is slow
    on large discographies. Wrapping the api in this proxy for one artist run
    fetches each ``get_album`` / ``get_artist_albums`` / ``get_album_items``
    result at most once; every other attribute passes straight through so
    behaviour is identical. Catalog data is stable within a single run, so
    caching these reads is safe."""

    _CACHED = ("get_album", "get_artist_albums", "get_album_items")

    def __init__(self, api):
        self._api = api
        self._cache: dict = {}

    def __getattr__(self, name):
        attr = getattr(self._api, name)
        if name not in self._CACHED or not callable(attr):
            return attr

        def cached(*args, **kwargs):
            key = (name, args, tuple(sorted(kwargs.items())))
            try:
                hash(key)
            except TypeError:
                # Unhashable argument (the catalog reads only take scalars, so
                # this is defensive): skip the cache and call straight through.
                return attr(*args, **kwargs)
            if key not in self._cache:
                self._cache[key] = attr(*args, **kwargs)
            return self._cache[key]

        return cached


@download_command.callback(no_args_is_help=True)
def download_callback(
    ctx: Context,
    TRACK_QUALITY: Annotated[
        TRACK_QUALITY_LITERAL,
        typer.Option(
            "--track-quality",
            "-q",
            help=(
                "Starting rung of the fidelity cascade "
                "max > high > atmos > normal > low. Each track is taken at the "
                "first rung from here DOWN that it offers: start at high/max to "
                "prefer FLAC (Atmos only when no FLAC exists), or at atmos to "
                "take Dolby Atmos first."
            ),
        ),
    ] = CONFIG.download.track_quality,
    AUDIO_MODE: Annotated[
        str,
        typer.Option(
            "--audio-mode",
            help=(
                "Audio edition policy: auto keeps supplied IDs; stereo resolves "
                "album URLs to stereo editions, and expands artist URLs into "
                "their albums resolved to stereo (keeping an album's original "
                "when it has no stereo edition)."
            ),
        ),
    ] = "auto",
    EDITION_MATCH: Annotated[
        str,
        typer.Option(
            "--edition-match",
            help=(
                "Stereo replacement policy: ask before changed track lists, "
                "or best to accept the best match."
            ),
        ),
    ] = "ask",
    QUALITY_POLICY: Annotated[
        str,
        typer.Option(
            "--quality-policy",
            help=(
                "Quality delivery policy: flexible permits normal fallback; "
                "strict requires the exact requested quality."
            ),
        ),
    ] = "flexible",
    DRY_RUN: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Resolve stereo editions and show the plan without downloading or changing files.",
        ),
    ] = False,
    VIDEO_QUALITY: Annotated[
        VIDEO_QUALITY_LITERAL,
        typer.Option(
            "--video-quality",
            "-vq",
        ),
    ] = CONFIG.download.video_quality,
    SKIP_EXISTING: Annotated[
        bool,
        typer.Option(
            "--no-skip",
            "-ns",
            help="Don't skip downloading existing files.",
        ),
    ] = not CONFIG.download.skip_existing,
    REWRITE_METADATA: Annotated[
        bool,
        typer.Option(
            "--rewrite-metadata",
            "-r",
            help="Rewrite metadata for already downloaded tracks.",
        ),
    ] = CONFIG.download.rewrite_metadata,
    THREADS_COUNT: Annotated[
        int,
        typer.Option(
            "--threads-count",
            "-t",
            help="Number of concurrent download threads.",
            min=1,
        ),
    ] = CONFIG.download.threads_count,
    DOWNLOAD_PATH: Annotated[
        Path,
        typer.Option(
            "--path",
            "-p",
            help="Base directory path for all downloads.",
        ),
    ] = CONFIG.download.download_path,
    SCAN_PATH: Annotated[
        Path,
        typer.Option(
            "--scan-path",
            "--sp",
            help="Directory to search for your existing downloads.",
        ),
    ] = CONFIG.download.scan_path,
    VIDEO_DOWNLOAD_PATH: Annotated[
        Optional[Path],
        typer.Option(
            "--video-path",
            "-vp",
            help="Base directory path for video downloads. Overrides --path for videos.",
        ),
    ] = CONFIG.download.video_download_path,
    TEMPLATE: Annotated[
        str,
        typer.Option(
            "--template",
            "--output",
            "-o",
            help="Global fallback template.",
        ),
    ] = "",
    ALBUM_TEMPLATE: Annotated[
        str,
        typer.Option(
            "--album-template",
            "--atf",
            help="Template for album folders.",
        ),
    ] = "",
    TRACK_TEMPLATE: Annotated[
        str,
        typer.Option(
            "--track-template",
            "--ttf",
            help="Template for track filenames.",
        ),
    ] = "",
    VIDEO_TEMPLATE: Annotated[
        str,
        typer.Option(
            "--video-template",
            "--vtf",
            help="Template for video filenames.",
        ),
    ] = "",
    PLAYLIST_TEMPLATE: Annotated[
        str,
        typer.Option(
            "--playlist-template",
            "--ptf",
            help="Template for playlist folders.",
        ),
    ] = "",
    SINGLES_FILTER: Annotated[
        ARTIST_SINGLES_FILTER_LITERAL,
        typer.Option(
            "--singles",
            "-s",
            help="Filter for including artists' singles, used while downloading artist.",
        ),
    ] = CONFIG.download.singles_filter,
    VIDEOS_FILTER: Annotated[
        VIDEOS_FILTER_LITERAL,
        typer.Option(
            "--videos",
            "-vid",
            help="Videos handling: 'none' to exclude, 'allow' to include, 'only' to download videos only.",
        ),
    ] = CONFIG.download.videos_filter,
    ARTIST_CONCURRENCY: Annotated[
        int,
        typer.Option(
            "--concurrency",
            "-c",
            help="Max albums downloading in parallel for artist downloads. 0 = unlimited.",
            min=0,
        ),
    ] = CONFIG.download.artist_concurrency,
    ARTIST_DELAY: Annotated[
        float,
        typer.Option(
            "--delay",
            "-d",
            help="Max random delay in seconds before each album starts (artist downloads only). Staggers API requests.",
            min=0.0,
        ),
    ] = CONFIG.download.artist_delay,
    TRACK_DELAY: Annotated[
        float,
        typer.Option(
            "--track-delay",
            "-td",
            help="Max random delay in seconds before each track download. Makes behavior less bot-like.",
            min=0.0,
        ),
    ] = CONFIG.download.track_delay,
    EXPAND_ALBUMS: Annotated[
        bool,
        typer.Option(
            "--albums",
            help="Expand playlists into their tracks' full albums instead of downloading the playlist tracks.",
        ),
    ] = False,
    EXPAND_ARTISTS: Annotated[
        bool,
        typer.Option(
            "--artists",
            help="Expand playlists into their tracks' credited artists (downloads full discographies).",
        ),
    ] = False,
    EXPAND_TRACKS: Annotated[
        bool,
        typer.Option(
            "--tracks",
            help="Expand playlists into standalone tracks (track template/folders, not the playlist layout).",
        ),
    ] = False,
    EMBED_LYRICS: Annotated[
        Optional[bool],
        typer.Option(
            "--embed-lyrics/--no-embed-lyrics",
            help="Embed lyrics in the file tags (overrides config).",
        ),
    ] = None,
    SAVE_LYRICS: Annotated[
        Optional[bool],
        typer.Option(
            "--save-lyrics/--no-save-lyrics",
            help="Save an .lrc lyrics file next to each track (overrides config).",
        ),
    ] = None,
    COVER: Annotated[
        Optional[bool],
        typer.Option(
            "--cover/--no-cover",
            help="Embed cover art in the file tags (overrides config).",
        ),
    ] = None,
    ALBUM_REVIEW: Annotated[
        Optional[bool],
        typer.Option(
            "--album-review/--no-album-review",
            help="Embed the album review into the comment tag (overrides config).",
        ),
    ] = None,
    SAVE_COVER: Annotated[
        Optional[bool],
        typer.Option(
            "--save-cover/--no-save-cover",
            help="Save a standalone cover.jpg next to downloads (overrides config).",
        ),
    ] = None,
    COVER_SIZE: Annotated[
        Optional[int],
        typer.Option(
            "--cover-size",
            help="Cover art size in pixels (max 1280).",
            min=1,
        ),
    ] = None,
    COVER_FOR: Annotated[
        Optional[List[str]],
        typer.Option(
            "--cover-for",
            help="Resource types to save cover.jpg for: track/album/playlist (repeatable).",
        ),
    ] = None,
    HIRES_CLIENT: Annotated[
        Optional[str],
        typer.Option(
            "--hires-client",
            help="Which client_id backs requests: auto/always/never (overrides config).",
        ),
    ] = None,
    REQUESTS_PER_MINUTE: Annotated[
        Optional[int],
        typer.Option(
            "--rpm",
            "--requests-per-minute",
            help="Max API requests per minute (overrides config).",
            min=0,
        ),
    ] = None,
    UPDATE_MTIME: Annotated[
        Optional[bool],
        typer.Option(
            "--update-mtime/--no-update-mtime",
            help="Set file modified-time to the release date (overrides config).",
        ),
    ] = None,
    EXCLUDE_COMPILATIONS: Annotated[
        Optional[bool],
        typer.Option(
            "--exclude-compilations/--no-exclude-compilations",
            help="On artist downloads, skip the artist's compilations (overrides config).",
        ),
    ] = None,
    EXCLUDE_LIVE_ALBUMS: Annotated[
        Optional[bool],
        typer.Option(
            "--exclude-live-albums/--no-exclude-live-albums",
            help="On artist downloads, skip the artist's live albums (overrides config).",
        ),
    ] = None,
    MAX_TRACKS: Annotated[
        Optional[int],
        typer.Option(
            "--max-tracks",
            help="Stop after N tracks this run. 0 = unlimited (overrides config).",
            min=0,
        ),
    ] = None,
    RESUME: Annotated[
        bool,
        typer.Option(
            "--resume/--no-resume",
            help=(
                "Skip resources already fully processed in a prior run of this "
                "SAME job (same links + options), before any API call — so a run "
                "interrupted by a rate-limit stop or Ctrl-C continues cheaply "
                "instead of re-enumerating everything. Trusts its checkpoint over "
                "the filesystem; run without --resume for a full re-verify."
            ),
        ),
    ] = False,
    SAVE_M3U: Annotated[
        Optional[bool],
        typer.Option(
            "--m3u/--no-m3u",
            help="Generate .m3u playlist files (overrides config).",
        ),
    ] = None,
    M3U_FOR: Annotated[
        Optional[List[str]],
        typer.Option(
            "--m3u-for",
            help="Resource types to generate .m3u for: album/playlist/mix (repeatable).",
        ),
    ] = None,
    MIX_TEMPLATE: Annotated[
        str,
        typer.Option(
            "--mix-template",
            "--mtf",
            help="Template for mix folders.",
        ),
    ] = "",
    ARTIST_SEPARATOR: Annotated[
        Optional[str],
        typer.Option(
            "--artist-separator",
            help="Separator joining multiple artists in names/tags (overrides config).",
        ),
    ] = None,
):
    AUDIO_MODE = AUDIO_MODE.casefold()
    EDITION_MATCH = EDITION_MATCH.casefold()
    QUALITY_POLICY = QUALITY_POLICY.casefold()
    if AUDIO_MODE not in ("auto", "stereo"):
        raise typer.BadParameter("audio mode must be auto or stereo", param_hint="--audio-mode")
    if EDITION_MATCH not in ("ask", "best"):
        raise typer.BadParameter("edition match must be ask or best", param_hint="--edition-match")
    if QUALITY_POLICY not in ("flexible", "strict"):
        raise typer.BadParameter(
            "quality policy must be flexible or strict", param_hint="--quality-policy"
        )
    if DRY_RUN and AUDIO_MODE != "stereo":
        raise typer.BadParameter(
            "dry-run currently requires --audio-mode stereo", param_hint="--dry-run"
        )
    """
    Download Tidal resources.
    """

    if sum([EXPAND_ALBUMS, EXPAND_ARTISTS, EXPAND_TRACKS]) > 1:
        raise typer.BadParameter("Use only one of --albums, --artists or --tracks.")

    # --- CLI flags override config per run (GUI parity) --------------------
    # None/"" means "leave the config value untouched". These are read from
    # CONFIG at runtime by the download flow (not bound as typer defaults), so
    # setting them here BEFORE the hires read + refresh below is what makes the
    # override take effect this run — mirrors the lyrics flags.
    if COVER is not None:
        CONFIG.metadata.cover = COVER
    if ALBUM_REVIEW is not None:
        CONFIG.metadata.album_review = ALBUM_REVIEW
    if SAVE_COVER is not None:
        CONFIG.cover.save = SAVE_COVER
    if COVER_SIZE is not None:
        CONFIG.cover.size = COVER_SIZE
    if COVER_FOR is not None:
        _bad = [v for v in COVER_FOR if v not in ("track", "album", "playlist")]
        if _bad:
            raise typer.BadParameter(
                f"--cover-for: invalid {_bad}; allowed: track, album, playlist."
            )
        CONFIG.cover.allowed = COVER_FOR
    if HIRES_CLIENT is not None:
        if HIRES_CLIENT not in ("auto", "always", "never"):
            raise typer.BadParameter(
                "--hires-client must be auto, always or never."
            )
        CONFIG.download.hires_client = HIRES_CLIENT
    if REQUESTS_PER_MINUTE is not None:
        CONFIG.download.requests_per_minute = REQUESTS_PER_MINUTE
    # Build the ONE shared request budget from the EFFECTIVE rpm (config +
    # optional --rpm override just applied) BEFORE any client is constructed, so
    # both the TV and HiRes clients space their COMBINED traffic at the effective
    # rate. Done unconditionally: with no --rpm this uses the config value.
    ctx.obj.configure_request_budget(CONFIG.download.requests_per_minute)
    if UPDATE_MTIME is not None:
        CONFIG.download.update_mtime = UPDATE_MTIME
    if EXCLUDE_COMPILATIONS is not None:
        CONFIG.download.exclude_compilations = EXCLUDE_COMPILATIONS
    if EXCLUDE_LIVE_ALBUMS is not None:
        CONFIG.download.exclude_live_albums = EXCLUDE_LIVE_ALBUMS
    if MAX_TRACKS is not None:
        CONFIG.download.max_tracks_per_session = MAX_TRACKS
    if SAVE_M3U is not None:
        CONFIG.m3u.save = SAVE_M3U
    if M3U_FOR is not None:
        _bad = [v for v in M3U_FOR if v not in ("album", "playlist", "mix")]
        if _bad:
            raise typer.BadParameter(
                f"--m3u-for: invalid {_bad}; allowed: album, playlist, mix."
            )
        CONFIG.m3u.allowed = M3U_FOR
    if ARTIST_SEPARATOR is not None:
        CONFIG.templates.artist_separator = ARTIST_SEPARATOR
    # -----------------------------------------------------------------------

    # Select which client_id backs ALL requests this run, from config
    # `hires_client` + the requested -q. The HiRes client has a strict TIDAL
    # rate limit (429 on big lists); the TV client is lenient but tops at
    # LOSSLESS. Set BEFORE any ctx.obj.api access (the refresh below builds it).
    # Which client_id backs ALL requests this run — the stable matrix
    # (`high`/`never` -> TV lenient LOSSLESS, `max`/`always` -> HiRes strict). A
    # `high` run's occasional 24-bit-only (Atmos) track is escalated PER-TRACK to
    # a secondary HiRes client (see the downloader), NOT run-wide, so a big `high`
    # run cannot storm the HiRes rate limit. (Reverts 05b1eca.)
    ctx.obj.prefer_hires = _resolve_prefer_hires(TRACK_QUALITY, CONFIG.download.hires_client)

    # Lyrics come from [metadata] in config.toml; these flags override per run
    # (the download flow reads CONFIG.metadata at runtime).
    if EMBED_LYRICS is not None:
        CONFIG.metadata.lyrics = EMBED_LYRICS
    if SAVE_LYRICS is not None:
        CONFIG.metadata.save_lyrics = SAVE_LYRICS

    ctx.invoke(refresh, EARLY_EXPIRE_TIME=600)

    log.debug(f"{ctx.params=}")

    # One IdentityFailureTracker per `tiddl download` invocation (v2.4
    # mandatory safeguard #2) — download_callback() runs once per command
    # invocation, so this is the natural home for it: created here, closed
    # over by every guarded call site below (save_m3u, the cover.save_to_
    # directory sites, and — via download_resources()/handle_item — the
    # Downloader itself), never a module global.
    identity_tracker = anchor.IdentityFailureTracker()

    def resolve_template(specific_cli: str, config_template: str) -> str:
        return specific_cli or TEMPLATE or config_template

    def save_m3u(
        resource_type: VALID_M3U_RESOURCE_LITERAL,
        filename: str,
        tracks_with_path: list[tuple[Union[Path, None], Union[Track, Video]]],
    ):
        if not CONFIG.m3u.save:
            return

        if resource_type not in CONFIG.m3u.allowed:
            return

        tracks_with_existing_paths = [
            (path, track)
            for (path, track) in tracks_with_path
            if path and isinstance(track, Track)
        ]

        log.debug(f"{resource_type=}, {filename=}, {len(tracks_with_existing_paths)=}")

        # Operation 7 (destination-volume identity, v2.2 §1): save_m3u() runs
        # synchronously on the event loop (never inside asyncio.to_thread), so
        # it's safe for save_tracks_to_m3u() to touch identity_tracker
        # directly — no thread-boundary concern here (contrast with the cover
        # sites below, which dispatch to a thread).
        save_tracks_to_m3u(
            tracks_with_path=tracks_with_existing_paths, path=DOWNLOAD_PATH / filename,
            root=DOWNLOAD_PATH, mode=CONFIG.download.destination_identity,
            tracker=identity_tracker,
        )

    def get_item_quality(item: Union[Track, Video]):
        def predict_item_quality() -> Union[TRACK_QUALITY_LITERAL, VIDEO_QUALITY_LITERAL]:
            if isinstance(item, Track):
                if TRACK_QUALITY in ["low", "normal"]:
                    return TRACK_QUALITY

                metadata = getattr(item, "mediaMetadata", None)
                tags = getattr(metadata, "tags", []) or []
                if (
                    TRACK_QUALITY == "max"
                    and "HIRES_LOSSLESS" not in tags
                ):
                    return "high"

                return TRACK_QUALITY

            elif isinstance(item, Video):
                # TODO add missing Video.quality literals so this function can work properly
                return VIDEO_QUALITY

            raise TypeError("Unsupported item type")

        return predict_item_quality().upper()

    async def download_resources():
        import datetime as _dt
        from tiddl.cli.commands.web_login import auto_refresh_if_needed
        await auto_refresh_if_needed(threshold_minutes=30)

        # Resume checkpoint (opt-in --resume). Capture the job signature from the
        # ORIGINAL requested resources + the options that change what "done"
        # means, BEFORE the stereo pre-pass / expansion mutate ctx.obj.resources.
        resume_log = None
        if RESUME:
            from tiddl.core.resume import ResumeLog, job_signature, resource_key
            # Every option that changes what a resource produces on disk goes into
            # the signature (selection, content, metadata, standalone files, paths,
            # names) so changing any one starts a fresh checkpoint instead of
            # skipping resources completed under the old settings.
            _sig = job_signature(
                resources=[resource_key(r) for r in ctx.obj.resources],
                download_path=DOWNLOAD_PATH,
                video_download_path=VIDEO_DOWNLOAD_PATH,
                quality=TRACK_QUALITY,
                video_quality=VIDEO_QUALITY,
                audio_mode=AUDIO_MODE,
                edition_match=EDITION_MATCH,
                quality_policy=QUALITY_POLICY,
                hires_client=CONFIG.download.hires_client,
                expand=(
                    "albums" if EXPAND_ALBUMS
                    else "tracks" if EXPAND_TRACKS
                    else "artists" if EXPAND_ARTISTS
                    else "none"
                ),
                exclude_compilations=CONFIG.download.exclude_compilations,
                exclude_live_albums=CONFIG.download.exclude_live_albums,
                singles=SINGLES_FILTER,
                videos_filter=VIDEOS_FILTER,
                templates={
                    "default": CONFIG.templates.default,
                    "track": CONFIG.templates.track,
                    "album": CONFIG.templates.album,
                    "playlist": CONFIG.templates.playlist,
                    "video": CONFIG.templates.video,
                    "mix": CONFIG.templates.mix,
                    "artist_separator": CONFIG.templates.artist_separator,
                },
                metadata={
                    "enable": bool(CONFIG.metadata.enable),
                    "cover": bool(CONFIG.metadata.cover),
                    "lyrics": bool(CONFIG.metadata.lyrics),
                    "save_lyrics": bool(CONFIG.metadata.save_lyrics),
                    "album_review": bool(CONFIG.metadata.album_review),
                    "update_mtime": bool(CONFIG.download.update_mtime),
                    "rewrite": bool(REWRITE_METADATA),
                },
                cover_file={
                    "save": bool(CONFIG.cover.save),
                    "size": int(CONFIG.cover.size),
                    "allowed": sorted(CONFIG.cover.allowed or []),
                    "tpl_track": CONFIG.cover.templates.track,
                    "tpl_album": CONFIG.cover.templates.album,
                    "tpl_playlist": CONFIG.cover.templates.playlist,
                },
                m3u={
                    "save": bool(CONFIG.m3u.save),
                    "allowed": sorted(CONFIG.m3u.allowed or []),
                    "tpl_album": CONFIG.m3u.templates.album,
                    "tpl_playlist": CONFIG.m3u.templates.playlist,
                    "tpl_mix": CONFIG.m3u.templates.mix,
                },
            )
            resume_log = ResumeLog(_sig).load()
            if resume_log.count:
                ctx.obj.console.print(
                    f"[dim][resume] {resume_log.count} resource(s) already done in a "
                    f"prior run of this job will be skipped.[/]"
                )

        if AUDIO_MODE == "stereo":

            async def _resolve_stereo_album(album_id, keep_original: bool, api=None):
                """Resolve one album id to the album id that should actually be
                downloaded. Returns ``(album_id, download_it)``. When
                ``keep_original`` is True (artist expansion) an unresolved or
                declined album keeps its original id; when False (direct album
                URL) it is skipped, preserving the original single-album
                behaviour. ``api`` lets the artist path pass a
                ``CatalogReadCache`` so the shared artist catalog is fetched
                once per run instead of once per album."""
                result = await asyncio.to_thread(
                    find_stereo_editions,
                    api if api is not None else ctx.obj.api,
                    int(album_id),
                    TRACK_QUALITY,
                    0.75,
                    QUALITY_POLICY,
                )
                resolved_quality = result.requested_quality
                source = result.source
                action, target_id, needs_confirmation = plan_stereo_resolution(
                    result, keep_original
                )

                if action == "keep-source" and result.source_satisfies_request:
                    ctx.obj.console.print(
                        f"[green]Stereo {resolved_quality.upper()} already available:[/] "
                        f"{source.title} (album/{source.id})"
                    )
                    return source.id, True
                if action == "skip":
                    quality_requirement = (
                        f"at or below {TRACK_QUALITY.upper()}"
                        if QUALITY_POLICY == "flexible"
                        else f"at exactly {TRACK_QUALITY.upper()}"
                    )
                    ctx.obj.console.print(
                        f"[red]No matching stereo edition {quality_requirement} found for "
                        f"{source.title} (album/{source.id}); skipped because the requested "
                        "stereo/quality policy cannot be satisfied.[/]"
                    )
                    return source.id, False
                if action == "keep-source":
                    # keep_original and no qualifying stereo edition was found.
                    ctx.obj.console.print(
                        f"[yellow]No stereo edition found for {source.title} "
                        f"(album/{source.id}); keeping the original.[/]"
                    )
                    return source.id, True

                candidate = result.best
                alternate = candidate.album
                ctx.obj.console.print(
                    f"[bold cyan]Stereo replacement:[/] album/{source.id} → "
                    f"album/{alternate.id} ({candidate.score:.1%}, "
                    f"{candidate.track_overlap:.1%} track overlap, "
                    f"catalog tier {resolved_quality.upper()})"
                )
                if candidate.missing_tracks:
                    ctx.obj.console.print(
                        "[yellow]Missing from replacement:[/] "
                        + ", ".join(candidate.missing_tracks)
                    )
                if candidate.extra_tracks:
                    ctx.obj.console.print(
                        "[yellow]Additional in replacement:[/] "
                        + ", ".join(candidate.extra_tracks)
                    )

                accept = True
                if needs_confirmation and EDITION_MATCH == "ask":
                    if DRY_RUN:
                        ctx.obj.console.print(
                            "[yellow]A real run would request confirmation before substitution.[/]"
                        )
                    else:
                        accept = await asyncio.to_thread(
                            typer.confirm,
                            f"Use stereo album {alternate.id} instead of {source.id}?",
                            default=False,
                        )
                if accept:
                    return alternate.id, True
                if keep_original:
                    ctx.obj.console.print(
                        f"[yellow]Replacement declined; keeping original album/{source.id}.[/]"
                    )
                    return source.id, True
                ctx.obj.console.print(
                    f"[yellow]Replacement declined; album/{source.id} was skipped.[/]"
                )
                return source.id, False

            async def _collect_artist_album_ids(artist_id):
                """Enumerate an artist's releases as album ids, honouring the
                same ``--singles`` filter as a normal artist download. Album
                ids are de-duplicated across pages and the ALBUMS/EPSANDSINGLES
                passes (order preserved) so no album is resolved twice."""
                ids: list = []
                seen: set = set()

                async def _page(singles: bool):
                    offset = 0
                    filter_type = "EPSANDSINGLES" if singles else "ALBUMS"
                    while True:
                        if is_cancelled():
                            break
                        page = await asyncio.to_thread(
                            ctx.obj.api.get_artist_albums,
                            artist_id=artist_id,
                            offset=offset,
                            filter=filter_type,
                        )
                        if not page or not getattr(page, "items", None):
                            break
                        for album in page.items:
                            if album.id not in seen:
                                seen.add(album.id)
                                ids.append(album.id)
                        offset += page.limit
                        if offset >= page.totalNumberOfItems:
                            break

                if SINGLES_FILTER == "include":
                    await _page(False)
                    await _page(True)
                else:
                    await _page(SINGLES_FILTER == "only")
                excluded = await asyncio.to_thread(
                    get_excluded_artist_album_ids,
                    ctx.obj.api,
                    artist_id,
                    compilations=CONFIG.download.exclude_compilations,
                    live=CONFIG.download.exclude_live_albums,
                    appears_on=False,  # third-party albums are never in an artist download
                )
                if excluded:
                    ids = [i for i in ids if i not in excluded]
                return ids

            resolved_resources: list[TidalResource] = []
            for resource in ctx.obj.resources:
                if is_cancelled():
                    break
                if resource.type == "album":
                    album_id, download_it = await _resolve_stereo_album(
                        resource.id, keep_original=False
                    )
                    if download_it:
                        resolved_resources.append(
                            TidalResource(type="album", id=str(album_id))
                        )
                elif resource.type == "artist":
                    ctx.obj.console.print(
                        f"[bold cyan]Stereo mode:[/] resolving stereo editions across "
                        f"artist/{resource.id} (videos are not included in stereo mode)."
                    )
                    seen_stereo_ids: set = set()
                    # One shared cache for the whole artist run so the artist
                    # catalog (and repeated album reads) are fetched once, not
                    # once per album.
                    artist_api = CatalogReadCache(ctx.obj.api)
                    for aid in await _collect_artist_album_ids(resource.id):
                        if is_cancelled():
                            break
                        album_id, download_it = await _resolve_stereo_album(
                            aid, keep_original=True, api=artist_api
                        )
                        if download_it and album_id not in seen_stereo_ids:
                            seen_stereo_ids.add(album_id)
                            resolved_resources.append(
                                TidalResource(type="album", id=str(album_id))
                            )
                else:
                    ctx.obj.console.print(
                        f"[yellow]Stereo edition resolution applies only to album and artist "
                        f"URLs; keeping {resource.type}/{resource.id} unchanged.[/]"
                    )
                    resolved_resources.append(resource)

            if DRY_RUN:
                ctx.obj.console.print(
                    "[dim]Dry run complete: no files were downloaded and no settings "
                    "were changed.[/]"
                )
                return False
            ctx.obj.resources = resolved_resources
            if not ctx.obj.resources:
                ctx.obj.console.print("[yellow]No resources remain to download.[/]")
                return False

        rich_output = RichOutput(ctx.obj.console)
        _session_limit = CONFIG.download.max_tracks_per_session
        _session_track_limit = SessionTrackLimit(_session_limit)

        # identity_tracker: created once in download_callback() above (not
        # here) — this closure just reuses it, same object save_m3u() and
        # the cover call sites below already close over.

        downloader = Downloader(
            tidal_api=ctx.obj.api,
            threads_count=THREADS_COUNT,
            rich_output=rich_output,
            track_quality=TRACK_QUALITY,
            video_quality=VIDEO_QUALITY,
            videos_filter=VIDEOS_FILTER,
            skip_existing=not SKIP_EXISTING,
            download_path=DOWNLOAD_PATH,
            scan_path=SCAN_PATH,
            video_download_path=VIDEO_DOWNLOAD_PATH,
            fallback_api=ctx.obj.fallback_api,
            # Secondary HiRes client for the PER-TRACK `max` ascent — only in
            # `auto` while TV is the primary (i.e. `high + auto`). In `max`/`always`
            # HiRes is already the primary (`api`), and `never` must never build or
            # call a HiRes client, so both pass None here.
            hires_api=(
                ctx.obj.hires_api
                if (CONFIG.download.hires_client == "auto" and not ctx.obj.prefer_hires)
                else None
            ),
            primary_client_kind=("hires" if ctx.obj.prefer_hires else "tv"),
            destination_identity=CONFIG.download.destination_identity,
            identity_tracker=identity_tracker,
            audio_mode=AUDIO_MODE,
            quality_policy=QUALITY_POLICY,
        )

        # Fast-skip shortcuts (whole-album fast exit, up-front present detection,
        # per-item pre-checks in playlist/mix/artist-video flows) are only sound
        # when nothing forces reprocessing of existing files. When the user asks
        # to rewrite metadata or bump mtimes, every existing item must still flow
        # through handle_item, so all shortcuts turn off and behaviour is
        # identical to before.
        can_skip = (
            downloader.skip_existing
            and not REWRITE_METADATA
            and not CONFIG.download.update_mtime
        )

        class Metadata:
            def __init__(
                self,
                date: str = "",
                artist: str = "",
                credits: Optional[list[AlbumItemsCredits.ItemWithCredits.CreditsEntry]] = None,
                cover_data: Optional[bytes] = None,
                album_review: str = "",
                genre: str = "",
            ) -> None:
                self.date = date
                self.artist = artist
                self.credits = credits if credits is not None else []
                self.cover_data = cover_data
                self.album_review = album_review
                self.genre = genre

        # Cache de covers por UID: en playlists/mixes varios tracks comparten
        # álbum; sin esto cada track re-descarga el mismo JPG.
        _cover_cache: dict[str, bytes] = {}

        async def get_cover_data_cached(cover_uid: str) -> bytes:
            data = _cover_cache.get(cover_uid)
            if data is None:
                data = await asyncio.to_thread(Cover(cover_uid)._get_data)
                if len(_cover_cache) >= 64:
                    _cover_cache.pop(next(iter(_cover_cache)))
                _cover_cache[cover_uid] = data
            return data

        async def handle_resource(resource: TidalResource):
            async def handle_item(
                item: Union[Track, Video],
                file_path: str,
                track_metadata: Union[Metadata, None] = None,
                source_type: str = "ALBUM",
                source_id: Optional[str] = None,
            ) -> tuple[Union[Path, None], Union[Track, Video]]:
                # Cooperative cancel (in-process GUI): every download task funnels
                # through here. Bailing at the top makes the whole queue of
                # already-scheduled tasks drain instantly instead of downloading.
                from tiddl.core.cancel import is_cancelled
                if is_cancelled():
                    return Path(""), item
                log.debug(f"{item.id=}, {file_path=}")
                rich_output.total_increment()

                # Límite de tracks por sesión
                admitted, announce_limit = _session_track_limit.admit()
                if not admitted:
                    if announce_limit:
                        ctx.obj.console.print(
                            f"[yellow]Límite de sesión alcanzado ({_session_limit} tracks). "
                            f"Reinicia para continuar.[/]"
                        )
                    return Path(""), item

                if not track_metadata:
                    track_metadata = Metadata()

                # The human-pacing delay (TRACK_DELAY) is awaited by the caller,
                # *before* this task is even created — see `_dispatch_delay()`.
                # That keeps every track's delay strictly sequential (so a track
                # that rolls a long "distracted" pause can never let a later,
                # shorter-delayed track jump ahead of it — the disc/track order
                # always matches dispatch order), while still letting a track's
                # delay run concurrently with the *previous* track's in-flight
                # download instead of stacking dead time after it.
                download_path, was_downloaded = await downloader.download(
                    item=item, file_path=Path(file_path),
                    source_type=source_type, source_id=source_id,
                )

                log.debug(f"{download_path=}, {was_downloaded=}")

                # Count only tracks this run actually fetched toward the session
                # cap; an already-present file (skip_existing) must not consume it.
                # Reaching the cap latches the run-wide `reached` signal that
                # stops dispatch/enumeration of the remaining resources.
                _session_track_limit.record(bool(was_downloaded))

                # Destination-volume identity (operations 4/5/6/9, v2.2 §1 /
                # v2.3 §1): the same root operations 1/2/3 already checked for
                # this item, in downloader.py. Tracks and videos can have
                # different configured roots (--video-path overrides --path),
                # so this is item-type-dependent, computed once and reused.
                item_root = (
                    DOWNLOAD_PATH if isinstance(item, Track)
                    else (VIDEO_DOWNLOAD_PATH or DOWNLOAD_PATH)
                )
                # Class B (v2.3 §3): a refusal at the .lrc/metadata level skips
                # this item's _db_insert below, so a later run's directory-scan
                # fallback retries it. utime (operation 9) is exempted per its
                # own outcome rule — never suppresses an insert that already
                # happened.
                identity_refused = False

                if (
                    CONFIG.metadata.enable
                    and download_path
                    # rewrite metadata when track was skipped due to already existing
                    and (REWRITE_METADATA or was_downloaded)
                ):
                    if isinstance(item, Track):
                        lyrics_subtitles = ""

                        if CONFIG.metadata.lyrics or CONFIG.metadata.save_lyrics:
                            lrc_path = download_path.with_suffix(".lrc")
                            lrc_exists = lrc_path.exists()
                            
                            # Only fetch if we are downloading, rewriting, OR (saving lyrics AND lyrics don't exist)
                            # Never fetch lyrics for skipped (existing) tracks unless explicitly rewriting
                            should_fetch_lyrics = (
                                was_downloaded
                                or REWRITE_METADATA
                                or (CONFIG.metadata.save_lyrics and not lrc_exists and was_downloaded)
                            )

                            if should_fetch_lyrics:
                                fetched_lyrics = None
                                for attempt in range(3):
                                    try:
                                        fetched_lyrics_response = await asyncio.to_thread(
                                            ctx.obj.api.get_track_lyrics, item.id
                                        )
                                        if fetched_lyrics_response:
                                            fetched_lyrics = fetched_lyrics_response.subtitles
                                        log.debug(f"Lyrics found for {item.title}")
                                        break  # Success
                                    except ApiError as e:
                                        if e.status in [500, 502, 503, 504] and attempt < 2:
                                            wait_time = (attempt + 1) * 2
                                            log.warning(f"Lyrics unavailable for {item.title} ({e.status}). Retrying in {wait_time}s...")
                                            await asyncio.sleep(wait_time)
                                        elif e.status == 404:
                                            log.debug(f"Lyrics not found for {item.title} (404)")
                                            break # No point in retrying a 404
                                        else:
                                            log.error(f"Failed to fetch lyrics for {item.title} after multiple attempts: {e}")
                                            break # Unhandled error, break
                                    except Exception as e:
                                        log.error(f"An unexpected error occurred while fetching lyrics for {item.title}: {e}")
                                        break

                                if fetched_lyrics:
                                    if CONFIG.metadata.save_lyrics and (not lrc_exists or REWRITE_METADATA):
                                        try:
                                            _write_lrc_guarded(
                                                item_root, lrc_path,
                                                CONFIG.download.destination_identity,
                                                fetched_lyrics,
                                            )
                                        except anchor.DestinationNotTrusted as e:
                                            identity_tracker.mark_refused(e.check)
                                            identity_refused = True
                                            log.warning(
                                                f"[destination-identity] refused .lrc write "
                                                f"for {lrc_path}: {e.check.reason}"
                                            )
                                        except Exception as e:
                                            log.error(f"Could not save .lrc file: {e}")
                                    
                                    if CONFIG.metadata.lyrics:
                                        lyrics_subtitles = fetched_lyrics

                        if (
                            (REWRITE_METADATA or was_downloaded)
                            and not track_metadata.cover_data
                            and item.album.cover
                            and CONFIG.metadata.cover
                        ):
                            try:
                                track_metadata.cover_data = await get_cover_data_cached(
                                    item.album.cover
                                )
                            except Exception as e:
                                log.warning(f"Could not download track cover: {e}")
                                track_metadata.cover_data = b""

                        if REWRITE_METADATA or was_downloaded:
                            # Operation 5, moved into a guarded worker helper
                            # (P1 #3 audit fix) — see _write_track_metadata_
                            # guarded's docstring. The identity check now runs
                            # fresh on EVERY attempt, inside the same
                            # to_thread dispatch as the write itself, instead
                            # of once before the retry loop even starts.
                            for _attempt in range(3):
                                try:
                                    await asyncio.to_thread(
                                        _write_track_metadata_guarded,
                                        item_root, download_path,
                                        CONFIG.download.destination_identity,
                                        track=item,
                                        lyrics=lyrics_subtitles,
                                        album_artist=track_metadata.artist,
                                        cover_data=track_metadata.cover_data,
                                        date=track_metadata.date,
                                        credits=track_metadata.credits,
                                        comment=track_metadata.album_review,
                                        genre=track_metadata.genre,
                                        artist_separator=CONFIG.templates.artist_separator,
                                    )
                                    break
                                except anchor.DestinationNotTrusted as e:
                                    identity_tracker.mark_refused(e.check)
                                    identity_refused = True
                                    log.warning(
                                        f"[destination-identity] refused track metadata "
                                        f"write for {download_path}: {e.check.reason}"
                                    )
                                    break  # not a lock — retrying won't change a refusal
                                except Exception as e:
                                    # mutagen envuelve el PermissionError del SO (lock de slskd/AV en NAS/SMB)
                                    # en su propia excepcion, asi que detectamos el lock por tipo O por mensaje.
                                    _locked = isinstance(e, (PermissionError, OSError)) or "Permission denied" in str(e) or "Errno 13" in str(e) or "WinError 5" in str(e)
                                    if _locked and _attempt < 2:
                                        log.warning(f"Metadata write blocked (attempt {_attempt + 1}/3), retrying in 2s: {download_path}")
                                        await asyncio.sleep(2)
                                    elif _locked:
                                        log.warning(f"Could not write metadata after 3 attempts (file locked by another process), skipping: {download_path} — {e}")
                                        break
                                    else:
                                        log.warning(f"Metadata write failed for {download_path}, skipping: {e}")
                                        break

                    elif isinstance(item, Video):
                        if REWRITE_METADATA or was_downloaded:
                            # Operation 6, moved into a guarded worker helper
                            # (P1 #3 audit fix) — see _write_video_metadata_
                            # guarded's docstring.
                            try:
                                await asyncio.to_thread(
                                    _write_video_metadata_guarded,
                                    item_root, download_path,
                                    CONFIG.download.destination_identity,
                                    video=item,
                                    artist_separator=CONFIG.templates.artist_separator,
                                )
                            except anchor.DestinationNotTrusted as e:
                                identity_tracker.mark_refused(e.check)
                                identity_refused = True
                                log.warning(
                                    f"[destination-identity] refused video metadata "
                                    f"write for {download_path}: {e.check.reason}"
                                )

                # Mark complete in the skip-existing DB only *after* metadata has
                # been attempted (see downloader.download()'s docstring). If the
                # process dies before this line, the DB stays clean and a re-run
                # will find the file via the directory-scan fallback and retry
                # writing its metadata, instead of silently leaving it untagged
                # forever. Class B (v2.3 §3): the same withholding now also
                # covers a destination-identity refusal at .lrc/metadata above
                # — identity_refused stays False (a no-op) whenever
                # CONFIG.download.destination_identity == "off", so this adds
                # no behavior change for anyone not using the feature.
                _finalize_db_record(
                    downloader, item, download_path, was_downloaded, identity_refused
                )

                if download_path and CONFIG.download.update_mtime:
                    try:
                        _touch_guarded(
                            item_root, download_path,
                            CONFIG.download.destination_identity,
                        )
                    except anchor.DestinationNotTrusted as e:
                        # Operation 9 (v2.3 §1): unlike 4/5/6 above, this never
                        # sets identity_refused — a stale mtime is cosmetic,
                        # never suppresses the _db_insert that already ran.
                        identity_tracker.mark_refused(e.check)
                        log.warning(
                            f"[destination-identity] refused mtime update for "
                            f"{download_path}: {e.check.reason}"
                        )
                    except Exception:
                        log.warning(f"could not update mtime for {download_path}")

                return download_path, item

            async def _dispatch_delay():
                """Human-pacing delay awaited by the *dispatch loop* before creating
                each track's download task — not inside the task itself. Doing it
                here keeps every track's delay strictly sequential (so dispatch
                order == download order), while still letting it run concurrently
                with the previous track's in-flight download instead of adding
                dead time after it finishes.
                """
                # Cooperative cancel: skip the human-pacing sleep entirely once
                # cancelled, so the dispatch loop races to the end (draining the
                # queue of no-op tasks) instead of sleeping TRACK_DELAY per item.
                from tiddl.core.cancel import is_cancelled
                if is_cancelled():
                    return
                if TRACK_DELAY <= 0:
                    return
                # 85% del tiempo: pausa corta (comportamiento normal)
                # 15% del tiempo: pausa larga (simula distracción/scroll)
                if random.random() < 0.15:
                    await asyncio.sleep(random.uniform(TRACK_DELAY * 2, TRACK_DELAY * 6))
                else:
                    await asyncio.sleep(random.uniform(0.5, max(0.5, TRACK_DELAY)))

            async def _simulate_browse(album: Album):
                """Simulate natural browsing before downloading an album."""
                try:
                    # Fetch artist info (like clicking on an artist page)
                    if album.artist:
                        await asyncio.to_thread(ctx.obj.api.get_artist, artist_id=album.artist.id)
                        await asyncio.sleep(random.uniform(1.5, 4.0))
                    # Occasionally fetch top tracks (40% chance)
                    if album.artist and random.random() < 0.4:
                        await asyncio.to_thread(ctx.obj.api.get_artist_toptracks, album.artist.id)
                        await asyncio.sleep(random.uniform(1.0, 3.0))
                except Exception:
                    pass

            async def download_album(album: Album, pre_delay: float = 0.0):
                offset = 0
                futures = []
                all_album_items = []  # collect all pages first for batch prefetch

                # --- Page collection FIRST (all pages, no tasks yet) ---
                # We need the track IDs *before* spending any time on browsing,
                # cover/review fetch or /contributors enrichment, so an album that
                # is already fully downloaded can bail out before paying for any
                # of that overhead.
                while True:
                    if is_cancelled():
                        break
                    album_items = None
                    for attempt in range(3):
                        try:
                            album_items = await asyncio.to_thread(
                                ctx.obj.api.get_album_items_credits,
                                album_id=album.id, offset=offset,
                            )
                            break
                        except Exception as e:
                            if attempt < 2:
                                wait = (attempt + 1) * 2
                                log.warning(f"Error fetching album items (offset {offset}): {e}. Retrying in {wait}s...")
                                await asyncio.sleep(wait)
                            else:
                                log.error(f"Failed to fetch album items after 3 attempts: {e}")
                                raise

                    if not album_items:
                        break

                    all_album_items.extend(album_items.items)

                    offset += album_items.limit
                    if offset >= album_items.totalNumberOfItems:
                        break
                    # No extra sleep here: client.fetch() already enforces
                    # requests_per_minute globally (tiddl/core/api/client.py), so
                    # an additional pause between pages was pure redundant dead
                    # time on top of that — same class of bug as ad25ba1.

                # --- Detect already-complete items up front (read-only) ---
                # `present` maps item_id -> on-disk path for tracks AND videos the
                # skip DB confirms are complete (media + tags) and sitting in the
                # correct folder. Those need neither download, metadata rewrite
                # nor /contributors enrichment, so we filter them out below.
                # (`can_skip` is defined once in download_resources; shortcuts
                # turn off under --rewrite-metadata / update_mtime.)

                def _will_process(it) -> bool:
                    # Mirrors download()'s videos_filter gate: items the filter
                    # discards are no-ops, need no present-check and must not
                    # block the whole-album fast exit below.
                    if isinstance(it, Track):
                        return VIDEOS_FILTER != "only"
                    if isinstance(it, Video):
                        return VIDEOS_FILTER != "none"
                    return False

                present: dict = {}  # {item_id: Path} — confirmed-complete items
                if can_skip:
                    check_items = [
                        ai.item for ai in all_album_items if _will_process(ai.item)
                    ]
                    present_results = await asyncio.gather(
                        *[
                            downloader.is_item_present(
                                it,
                                Path(format_template(
                                    template=resolve_template(ALBUM_TEMPLATE, CONFIG.templates.album),
                                    item=it,
                                    album=album,
                                    quality=get_item_quality(it),
                                    artist_separator=CONFIG.templates.artist_separator,
                                )),
                            )
                            for it in check_items
                        ],
                        return_exceptions=True,
                    )
                    for it, res in zip(check_items, present_results):
                        if not isinstance(res, Exception) and res is not None:
                            present[it.id] = res

                # --- Fast exit: whole album already on disk ---
                # Every item we would actually process (track or video, per
                # videos_filter) is already complete, so nothing will be
                # downloaded. Skip the human-simulation browse, the cover fetch,
                # the review fetch, the per-track /contributors enrichment AND the
                # artist stagger delay — all pure overhead when no media moves.
                # Items the videos_filter discards are no-ops and don't block.
                # (The album cover was saved on the run that downloaded it, so it
                # is intentionally not re-saved here.)
                if (
                    can_skip
                    and all_album_items
                    and all(
                        not _will_process(ai.item) or ai.item.id in present
                        for ai in all_album_items
                    )
                ):
                    skipped_with_path: list[tuple] = []
                    for album_item in all_album_items:
                        item = album_item.item
                        if item.id not in present:
                            continue  # filtered-out no-op (videos_filter)
                        downloader.rich_output.show_item_result(
                            result_message="[yellow]Exists",
                            item_description=f"[bold]{item.title}",
                            item_path=present[item.id],
                        )
                        skipped_with_path.append((present[item.id], item))
                    save_m3u(
                        resource_type="album",
                        filename=format_template(
                            CONFIG.m3u.templates.album,
                            album=album,
                            type="album",
                            artist_separator=CONFIG.templates.artist_separator,
                        ),
                        tracks_with_path=skipped_with_path,
                    )
                    return

                # --- Album needs at least one download: pay the artist stagger now ---
                # (Moved here from download_album_throttled so a fully-downloaded
                # album — handled by the fast exit above — never waits on it.)
                if pre_delay > 0:
                    await asyncio.sleep(random.uniform(0, pre_delay))

                # Simulate browsing before downloading
                await _simulate_browse(album)

                cover: Union[Cover, None] = None
                save_cover = ("album" in CONFIG.cover.allowed) and CONFIG.cover.save

                if album.cover and (CONFIG.metadata.cover or save_cover):
                    try:
                        cover = Cover(album.cover, size=CONFIG.cover.size)
                        await asyncio.to_thread(cover._get_data)
                    except Exception as e:
                        log.warning(f"Could not download album cover: {e}")
                        cover = None

                album_review = ""

                if CONFIG.metadata.album_review:
                    try:
                        review = await asyncio.to_thread(
                            ctx.obj.api.get_album_review, album.id
                        )
                        album_review = review.normalized_text()
                    except Exception as e:
                        log.error(e)

                # --- Enrich featured artists ONLY for tracks we will process ---
                # A /contributors HTTP call for an already-complete track is pure
                # waste (enrichment only affects the filename/tags of tracks we are
                # about to (re)write), so the confirmed-complete ones are filtered
                # out. Tracks only found on disk (not in the DB) are NOT in
                # `present`, so they stay in — they still get retagged with the
                # correct featured artists exactly as before.
                await enrich_tracks_concurrently(
                    [
                        ai.item for ai in all_album_items
                        if not (isinstance(ai.item, Track) and ai.item.id in present)
                    ],
                    ctx.obj.api,
                )

                # Ensure tracks are processed in disc/track order (the API is
                # usually ordered, but paginated credits endpoints can arrive
                # shuffled). With threads_count=1 this means they also complete
                # in order; with more threads it only fixes the start order.
                all_album_items.sort(key=lambda ai: (
                    getattr(ai.item, "volumeNumber", 0) or 0,
                    getattr(ai.item, "trackNumber", 0) or 0,
                ))

                # --- Build tasks — already-complete items skipped, rest download ---
                # `present` (computed above) holds tracks/videos the DB confirms
                # are complete AND in the correct folder, so they skip with no
                # metadata rewrite. Items only found on disk (not in the DB) are
                # NOT in `present`, so they still flow through handle_item and get
                # their tags (re)written exactly as before. skipped tuples keep
                # m3u complete.
                skipped_with_path: list[tuple] = []
                for album_item in all_album_items:
                    if is_cancelled():
                        break
                    item = album_item.item
                    if item.id in present:
                        existing_path = present[item.id]
                        downloader.rich_output.show_item_result(
                            result_message="[yellow]Exists",
                            item_description=f"[bold]{item.title}",
                            item_path=existing_path,
                        )
                        skipped_with_path.append((existing_path, item))
                        continue

                    await _dispatch_delay()
                    futures.append(
                        asyncio.create_task(handle_item(
                            item=item,
                            file_path=format_template(
                                template=resolve_template(ALBUM_TEMPLATE, CONFIG.templates.album),
                                item=item,
                                album=album,
                                quality=get_item_quality(item),
                                artist_separator=CONFIG.templates.artist_separator,
                            ),
                            track_metadata=Metadata(
                                cover_data=cover.data if cover else b"",
                                date=str(album.releaseDate) if album.releaseDate else "",
                                artist=album.artist.name if album.artist else "",
                                credits=album_item.credits,
                                album_review=album_review,
                                genre=album.genre or "",
                            ),
                            source_type="ALBUM",
                            source_id=str(album.id),
                        ))
                    )

                try:
                    downloaded_with_path = await asyncio.gather(*futures)
                    tracks_with_path = skipped_with_path + list(downloaded_with_path)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    # Wait for all tasks to be cancelled
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise

                save_m3u(
                    resource_type="album",
                    filename=format_template(
                        CONFIG.m3u.templates.album,
                        album=album,
                        type="album",
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                    tracks_with_path=tracks_with_path,
                )

                if save_cover and cover:
                    _album_cover_path = DOWNLOAD_PATH / format_template(
                        template=CONFIG.cover.templates.album, album=album,
                        artist_separator=CONFIG.templates.artist_separator,
                    )
                    # Operation 8 — via the guarded helper (P1 #3 audit fix);
                    # see _guarded_save_cover's docstring.
                    await _guarded_save_cover(
                        cover, DOWNLOAD_PATH, _album_cover_path,
                        CONFIG.download.destination_identity,
                        identity_tracker, "album",
                    )

            # resources should be collected from a distinct function
            # that would yield the resources.
            # then we would be able to reuse the logic in the export command
            resource_type = resource.type

            if resource_type == "track":
                track = await asyncio.to_thread(ctx.obj.api.get_track, resource.id)
                album = await asyncio.to_thread(ctx.obj.api.get_album, track.album.id)
                await asyncio.to_thread(enrich_track_artists, track, ctx.obj.api)

                ctx.obj.console.print(f"\n[bold green]Downloading Track:[/] {track.title}")
                ctx.obj.console.print(f"[dim]Track ID: {resource.id}[/]\n")

                await _dispatch_delay()
                await handle_item(
                    item=track,
                    file_path=format_template(
                        template=resolve_template(TRACK_TEMPLATE, CONFIG.templates.track),
                        item=track,
                        album=album,
                        quality=get_item_quality(track),
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                    track_metadata=Metadata(
                        date=str(album.releaseDate) if album.releaseDate else "",
                        artist=album.artist.name if album.artist else "",
                        genre=album.genre or "",
                    ),
                    source_type="ALBUM",
                    source_id=str(album.id),
                )

                if (
                    CONFIG.cover.save
                    and ("track" in CONFIG.cover.allowed)
                    and track.album.cover
                ):
                    _track_cover = Cover(track.album.cover, size=CONFIG.cover.size)
                    _track_cover_path = DOWNLOAD_PATH / format_template(
                        CONFIG.cover.templates.track, item=track, album=album,
                        artist_separator=CONFIG.templates.artist_separator,
                    )
                    # Operation 8 — via the guarded helper (P1 #3 audit fix);
                    # see _guarded_save_cover's docstring.
                    await _guarded_save_cover(
                        _track_cover, DOWNLOAD_PATH, _track_cover_path,
                        CONFIG.download.destination_identity,
                        identity_tracker, "track",
                    )

            elif resource_type == "video":
                video = await asyncio.to_thread(ctx.obj.api.get_video, resource.id)

                ctx.obj.console.print(f"\n[bold blue]Downloading Video:[/] {video.title}")
                ctx.obj.console.print(f"[dim]Video ID: {resource.id}[/]\n")
                
                # Fetch album info if available to populate {album.date} and other placeholders
                album = None
                if video.album and video.album.id:
                    try:
                        album = await asyncio.to_thread(ctx.obj.api.get_album, video.album.id)
                    except Exception as e:
                        log.warning(f"Could not fetch album {video.album.id} for video {video.id}: {e}")

                await _dispatch_delay()
                await handle_item(
                    item=video,
                    file_path=format_template(
                        template=resolve_template(VIDEO_TEMPLATE, CONFIG.templates.video),
                        item=video,
                        album=album,
                        quality=get_item_quality(video),
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                    source_type="VIDEO",
                    source_id=str(video.id),
                )

            elif resource_type == "mix":
                offset = 0
                futures = []
                skipped_with_path: list[tuple] = []
                mix_id = resource.id
                ctx.obj.console.print(f"\n[bold yellow]🎧 Downloading Mix:[/] {mix_id}")
                ctx.obj.console.print(f"[dim]Fetching tracks...[/]\n")

                while True:
                    if is_cancelled():
                        break
                    try:
                        mix_items = await asyncio.to_thread(
                            ctx.obj.api.get_mix_items, mix_id, offset=offset
                        )
                    except Exception as e:
                        log.error(f"Could not fetch mix items for {mix_id}: {e}")
                        break

                    await enrich_tracks_concurrently(
                        [mi.item for mi in mix_items.items], ctx.obj.api
                    )
                    for mix_item in mix_items.items:
                        if is_cancelled():
                            break
                        item_file_path = format_template(
                            template=resolve_template(MIX_TEMPLATE, CONFIG.templates.mix),
                            item=mix_item.item,
                            mix_id=mix_id,
                            quality=get_item_quality(mix_item.item),
                            artist_separator=CONFIG.templates.artist_separator,
                        )

                        # Already-complete items (DB-confirmed, correct folder)
                        # skip the dispatch delay and the whole handle_item task.
                        if can_skip:
                            _existing = await downloader.is_item_present(
                                mix_item.item, Path(item_file_path)
                            )
                            if _existing is not None:
                                downloader.rich_output.show_item_result(
                                    result_message="[yellow]Exists",
                                    item_description=f"[bold]{mix_item.item.title}",
                                    item_path=_existing,
                                )
                                skipped_with_path.append((_existing, mix_item.item))
                                continue

                        await _dispatch_delay()
                        futures.append(
                            asyncio.create_task(handle_item(
                                item=mix_item.item,
                                file_path=item_file_path,
                                source_type="MIX",
                                source_id=mix_id,
                            ))
                        )

                    offset += mix_items.limit
                    if offset >= mix_items.totalNumberOfItems:
                        break
                    # client.fetch() already paces every request via requests_per_minute.

                total_items = len(futures) + len(skipped_with_path)
                ctx.obj.console.print(f"\nFound:")
                ctx.obj.console.print(f"  • {total_items} items in the mix.")
                if skipped_with_path:
                    ctx.obj.console.print(f"  • [yellow]{len(skipped_with_path)} already downloaded (skipped)[/]")
                ctx.obj.console.print(f"  • [bold]{len(futures)} total items to download[/]\n")

                try:
                    results = await asyncio.gather(*futures, return_exceptions=True)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise

                tracks_with_path = list(skipped_with_path)
                failed_count = 0
                for res in results:
                    if isinstance(res, Exception):
                        log.error(f"Mix track download failed: {res}")
                        failed_count += 1
                    else:
                        tracks_with_path.append(res)

                save_m3u(
                    resource_type="mix",
                    filename=format_template(
                        CONFIG.m3u.templates.mix,
                        mix_id=mix_id,
                        type="mix",
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                    tracks_with_path=tracks_with_path,
                )

                ctx.obj.console.print(f"\n[bold green]✅ Mix download completed:[/] {mix_id}")
                ctx.obj.console.print(f"   • Downloaded: {len(tracks_with_path)} items")
                if failed_count > 0:
                    ctx.obj.console.print(f"   • [red]Failed: {failed_count} items[/]")

            elif resource_type == "album":
                album = await asyncio.to_thread(ctx.obj.api.get_album, album_id=resource.id)
                await download_album(album)

            elif resource_type == "artist":
                # ============================================================
                # IMPROVED ARTIST DOWNLOAD with SMART deduplication
                # Respects: different qualities, explicit/clean, special editions
                # ============================================================

                _sem = asyncio.Semaphore(ARTIST_CONCURRENCY) if ARTIST_CONCURRENCY > 0 else None

                async def download_album_throttled(album):
                    from tiddl.cli.commands.web_login import auto_refresh_if_needed
                    try:
                        await auto_refresh_if_needed(threshold_minutes=30)
                    except Exception as _re:
                        log.debug(f"auto_refresh_if_needed failed (non-fatal): {_re}")
                    # ARTIST_DELAY is now applied *inside* download_album, after it
                    # has confirmed the album actually needs downloading — a fully
                    # already-downloaded album skips the stagger entirely.
                    if _sem:
                        async with _sem:
                            await download_album(album, pre_delay=ARTIST_DELAY)
                    else:
                        await download_album(album, pre_delay=ARTIST_DELAY)

                futures = []
                seen_album_ids = set()  # Use album.id instead of title for proper deduplication
                artist_stats = {
                    'total_albums': 0,
                    'total_videos': 0,
                    'skipped_duplicates': 0,
                }
                
                # Get artist info for better feedback
                try:
                    artist = await asyncio.to_thread(ctx.obj.api.get_artist, resource.id)
                    artist_name = artist.name
                    ctx.obj.console.print(f"\n[bold cyan]Downloading Artist:[/] {artist_name}")
                    ctx.obj.console.print(f"[dim]Artist ID: {resource.id}[/]\n")
                except Exception as e:
                    artist_name = f"Artist {resource.id}"
                    log.warning(f"Could not get artist info: {e}")

                collected_albums = []
                video_tasks: list = []   # asyncio.Task objects for videos

                async def collect_albums(singles: bool):
                    offset = 0
                    filter_type = "EPSANDSINGLES" if singles else "ALBUMS"
                    display_type = "EPs & Singles" if singles else "Albums"

                    ctx.obj.console.print(f"[dim]Fetching {display_type}...[/]")

                    while True:
                        if is_cancelled():
                            break
                        artist_albums = None
                        for attempt in range(3):
                            try:
                                artist_albums = await asyncio.to_thread(
                                    ctx.obj.api.get_artist_albums,
                                    artist_id=resource.id,
                                    offset=offset,
                                    filter=filter_type,
                                )
                                break
                            except Exception as e:
                                if attempt < 2:
                                    wait = (attempt + 1) * 2
                                    log.warning(f"Error fetching albums (offset {offset}): {e}. Retrying in {wait}s...")
                                    await asyncio.sleep(wait)
                                else:
                                    log.error(f"Failed to fetch albums at offset {offset}: {e}")

                        if not artist_albums:
                            break

                        for album in artist_albums.items:
                            artist_stats['total_albums'] += 1
                            collected_albums.append(album)

                        offset += artist_albums.limit
                        if offset >= artist_albums.totalNumberOfItems:
                            break
                        # client.fetch() already paces every request via requests_per_minute.

                async def get_all_videos():
                    offset = 0

                    ctx.obj.console.print(f"[dim]Fetching videos...[/]")

                    while True:
                        if is_cancelled():
                            break
                        try:
                            artist_videos = await asyncio.to_thread(
                                ctx.obj.api.get_artist_videos,
                                resource.id, offset=offset,
                            )

                            for video in artist_videos.items:
                                if is_cancelled():
                                    break
                                artist_stats['total_videos'] += 1
                                video_file_path = format_template(
                                    template=resolve_template(VIDEO_TEMPLATE, CONFIG.templates.video),
                                    item=video,
                                    quality=get_item_quality(video),
                                    artist_separator=CONFIG.templates.artist_separator,
                                )
                                # Already-complete videos (DB-confirmed, correct
                                # folder) skip the dispatch delay and the whole
                                # handle_item task — no download, no metadata
                                # rewrite, no network.
                                if can_skip:
                                    _existing = await downloader.is_item_present(
                                        video, Path(video_file_path)
                                    )
                                    if _existing is not None:
                                        downloader.rich_output.show_item_result(
                                            result_message="[yellow]Exists",
                                            item_description=f"[bold]{video.title}",
                                            item_path=_existing,
                                        )
                                        continue
                                await _dispatch_delay()
                                video_tasks.append(
                                    asyncio.create_task(handle_item(
                                        item=video,
                                        file_path=video_file_path,
                                        source_type="VIDEO",
                                        source_id=str(resource.id),
                                    ))
                                )

                            if offset > artist_videos.totalNumberOfItems:
                                break

                            offset += artist_videos.limit
                            # client.fetch() already paces every request via requests_per_minute.

                        except Exception as e:
                            log.error(f"Error fetching videos at offset {offset}: {e}")
                            break

                # Gather albums and videos based on filters
                if VIDEOS_FILTER != "none":
                    await get_all_videos()

                if VIDEOS_FILTER != "only":
                    if SINGLES_FILTER == "include":
                        await collect_albums(False)
                        await collect_albums(True)
                    else:
                        await collect_albums(SINGLES_FILTER == "only")

                # Optionally drop compilations / live albums / "appears on"
                # releases, resolved from the artist page (get_artist_albums
                # cannot tell them apart). Config-driven; default keeps all.
                _excluded_ids = await asyncio.to_thread(
                    get_excluded_artist_album_ids,
                    ctx.obj.api,
                    resource.id,
                    compilations=CONFIG.download.exclude_compilations,
                    live=CONFIG.download.exclude_live_albums,
                    appears_on=False,  # third-party albums are never in an artist download
                )
                if _excluded_ids:
                    _before = len(collected_albums)
                    collected_albums = [
                        a for a in collected_albums if a.id not in _excluded_ids
                    ]
                    _dropped = _before - len(collected_albums)
                    if _dropped:
                        ctx.obj.console.print(
                            f"[dim]Excluded {_dropped} compilation/live/appears-on "
                            f"release(s) from the artist download.[/]"
                        )

                # SMART DEDUPLICATION & QUALITY SELECTION
                # Group albums by Title + Type + Version to find duplicates (e.g. same album in HiRes vs Lossless)
                # Keep the highest quality version.
                
                def get_album_score(alb):
                    score = 0
                    # Check explicit audio quality string
                    aq = str(alb.audioQuality).upper() if alb.audioQuality else ""
                    if "HI_RES" in aq or "HIRES" in aq: score = 3
                    elif "LOSSLESS" in aq: score = 2
                    elif "HIGH" in aq: score = 1
                    
                    # Check tags
                    if alb.mediaMetadata and alb.mediaMetadata.tags:
                        tags = [t.upper() for t in alb.mediaMetadata.tags]
                        if "HIRES_LOSSLESS" in tags: score = max(score, 3)
                        elif "LOSSLESS" in tags: score = max(score, 2)
                        
                    # Explicit preference (tie-breaker)
                    # REMOVED: User wants to keep both versions
                    # if alb.explicit: score += 0.5
                        
                    return score

                unique_map = {}
                
                for album in collected_albums:
                    # Key: Title + Type + Version (normalized) + Explicit
                    # This treats "Album" (HiRes) and "Album" (Lossless) as the same entity
                    # But "Album" (Explicit) and "Album" (Clean) as different.
                    key = (
                        album.title.strip().lower(),
                        album.type,
                        (album.version or "").strip().lower(),
                        album.explicit
                    )
                    
                    if key not in unique_map:
                        unique_map[key] = album
                    else:
                        # Compare quality
                        current = unique_map[key]
                        new_score = get_album_score(album)
                        curr_score = get_album_score(current)
                        
                        if new_score > curr_score:
                            # Found better quality version
                            artist_stats['skipped_duplicates'] += 1
                            unique_map[key] = album
                        else:
                            # Current is better or equal
                            artist_stats['skipped_duplicates'] += 1
                
                # Queue the selected best versions oldest-first (by release date),
                # so an artist download proceeds from the earliest album to the
                # newest. Albums without a date sort last; title is a tie-breaker.
                albums_to_download = list(unique_map.values())
                albums_to_download.sort(
                    key=lambda a: (
                        str(a.releaseDate) if a.releaseDate else "9999-99-99",
                        (a.title or "").lower(),
                    )
                )
                for album in albums_to_download:
                    if is_cancelled():
                        break
                    if album.id not in seen_album_ids:
                        seen_album_ids.add(album.id)
                        futures.append(album)  # store album, not task

                # Show what we're about to download
                unique_albums = len(seen_album_ids)
                total_items = unique_albums + artist_stats['total_videos']

                ctx.obj.console.print(f"\nFound:")
                ctx.obj.console.print(f"  • {unique_albums} albums (including all versions)")
                if artist_stats['skipped_duplicates'] > 0:
                    ctx.obj.console.print(f"  • [yellow]{artist_stats['skipped_duplicates']} true duplicates skipped[/]")
                if artist_stats['total_videos'] > 0:
                    ctx.obj.console.print(f"  • {artist_stats['total_videos']} videos")
                ctx.obj.console.print(f"  • [bold]{total_items} total items to download[/]\n")

                # Download everything
                # futures = Album objects only; video_tasks = asyncio.Task objects for videos
                try:
                    if ARTIST_CONCURRENCY == 1:
                        for album in futures:
                            if is_cancelled():
                                break
                            # Per-album resilience: one album's failure (a
                            # geo-block, a transient API error, a bad manifest)
                            # must not abort the rest of the artist's discography.
                            # A run-wide safety stop still propagates via
                            # is_cancelled() checked at the top of the loop.
                            try:
                                await download_album_throttled(album)
                            except asyncio.CancelledError:
                                raise
                            except Exception as _ae:
                                ctx.obj.console.print(
                                    f"[red]Skipped album/{getattr(album, 'id', '?')} "
                                    f"({getattr(album, 'title', '?')}): {_ae}[/]"
                                )
                    else:
                        tasks = [asyncio.create_task(download_album_throttled(a)) for a in futures]
                        # return_exceptions=True so one album failing doesn't cancel
                        # the sibling album tasks; surface each failure instead.
                        _results = await asyncio.gather(*tasks, return_exceptions=True)
                        for _a, _r in zip(futures, _results):
                            if isinstance(_r, asyncio.CancelledError):
                                raise _r
                            if isinstance(_r, Exception):
                                ctx.obj.console.print(
                                    f"[red]Skipped album/{getattr(_a, 'id', '?')} "
                                    f"({getattr(_a, 'title', '?')}): {_r}[/]"
                                )

                    # Videos run concurrently after albums (already created as tasks)
                    if video_tasks:
                        await asyncio.gather(*video_tasks, return_exceptions=True)
                    
                    # Fallback: If artist info failed initially, try to get name from downloaded albums
                    if "Artist " in artist_name and collected_albums:
                        for alb in collected_albums:
                            if alb.artist and alb.artist.name:
                                artist_name = alb.artist.name
                                break
                    
                    # Final stats
                    ctx.obj.console.print(f"\n[bold green]✅ Artist download completed:[/] {artist_name}")
                    ctx.obj.console.print(f"   • Downloaded: {total_items} items")
                    if artist_stats['skipped_duplicates'] > 0:
                        ctx.obj.console.print(f"   • Skipped: {artist_stats['skipped_duplicates']} true duplicates")
                    
                except (asyncio.CancelledError, KeyboardInterrupt):
                    if ARTIST_CONCURRENCY != 1:
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    for t in video_tasks:
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(*video_tasks, return_exceptions=True)
                    raise
                except Exception as e:
                    ctx.obj.console.print(f"\n[red]❌ Error during artist download:[/] {e}")
                    log.exception(f"Error downloading artist {resource.id}")

            elif resource_type == "playlist":
                offset = 0
                futures = []
                playlist_index = 0
                skipped_with_path: list[tuple] = []
                playlist = await asyncio.to_thread(
                    ctx.obj.api.get_playlist, playlist_uuid=resource.id
                )

                ctx.obj.console.print(f"\n[bold magenta]Downloading Playlist:[/] {playlist.title}")
                ctx.obj.console.print(f"[dim]Playlist ID: {resource.id}[/]\n")
                ctx.obj.console.print(f"[dim]Fetching tracks...[/]")

                while True:
                    if is_cancelled():
                        break
                    playlist_items = await asyncio.to_thread(
                        ctx.obj.api.get_playlist_items,
                        playlist_uuid=resource.id, offset=offset,
                    )

                    await enrich_tracks_concurrently(
                        [pi.item for pi in playlist_items.items], ctx.obj.api
                    )
                    for playlist_item in playlist_items.items:
                        if is_cancelled():
                            break
                        playlist_index += 1
                        template = resolve_template(PLAYLIST_TEMPLATE, CONFIG.templates.playlist)

                        if "{album" in template:
                            album = await asyncio.to_thread(
                                ctx.obj.api.get_album, playlist_item.item.album.id
                            )
                        else:
                            album = None

                        item_file_path = format_template(
                            template=template,
                            item=playlist_item.item,
                            album=album,
                            playlist=playlist,
                            playlist_index=playlist_index,
                            quality=get_item_quality(playlist_item.item),
                            artist_separator=CONFIG.templates.artist_separator,
                        )

                        # Already-complete items (DB-confirmed, correct folder)
                        # skip the dispatch delay and the whole handle_item task.
                        if can_skip:
                            _existing = await downloader.is_item_present(
                                playlist_item.item, Path(item_file_path)
                            )
                            if _existing is not None:
                                downloader.rich_output.show_item_result(
                                    result_message="[yellow]Exists",
                                    item_description=f"[bold]{playlist_item.item.title}",
                                    item_path=_existing,
                                )
                                skipped_with_path.append((_existing, playlist_item.item))
                                continue

                        await _dispatch_delay()
                        futures.append(
                            asyncio.create_task(handle_item(
                                item=playlist_item.item,
                                file_path=item_file_path,
                                track_metadata=Metadata(),
                                source_type="PLAYLIST",
                                source_id=resource.id,
                            ))
                        )

                    offset += playlist_items.limit
                    if offset >= playlist_items.totalNumberOfItems:
                        break
                    # client.fetch() already paces every request via requests_per_minute.

                total_items = len(futures) + len(skipped_with_path)
                ctx.obj.console.print(f"\nFound:")
                ctx.obj.console.print(f"  • {total_items} items in the playlist.")
                if skipped_with_path:
                    ctx.obj.console.print(f"  • [yellow]{len(skipped_with_path)} already downloaded (skipped)[/]")
                ctx.obj.console.print(f"  • [bold]{len(futures)} total items to download[/]\n")

                try:
                    results = await asyncio.gather(*futures, return_exceptions=True)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise

                # Filter out exceptions from results; skipped items seed the list
                tracks_with_path = list(skipped_with_path)
                failed_count = 0
                for res in results:
                    if isinstance(res, Exception):
                        log.error(f"Playlist track download failed: {res}")
                        failed_count += 1
                    else:
                        tracks_with_path.append(res)

                save_m3u(
                    resource_type="playlist",
                    filename=format_template(
                        CONFIG.m3u.templates.playlist,
                        playlist=playlist,
                        type="playlist",
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                    tracks_with_path=tracks_with_path,
                )

                if (
                    CONFIG.cover.save
                    and ("playlist" in CONFIG.cover.allowed)
                    and playlist.squareImage
                ):
                    _pl_cover = Cover(playlist.squareImage, size=max(CONFIG.cover.size, 1080))
                    _pl_cover_path = DOWNLOAD_PATH / format_template(
                        template=CONFIG.cover.templates.playlist,
                        playlist=playlist,
                        artist_separator=CONFIG.templates.artist_separator,
                    )
                    # Operation 8 — via the guarded helper (P1 #3 audit fix);
                    # see _guarded_save_cover's docstring.
                    await _guarded_save_cover(
                        _pl_cover, DOWNLOAD_PATH, _pl_cover_path,
                        CONFIG.download.destination_identity,
                        identity_tracker, "playlist",
                    )

                ctx.obj.console.print(f"\n[bold green]✅ Playlist download completed:[/] {playlist.title}")
                ctx.obj.console.print(f"   • Downloaded: {len(tracks_with_path)} items")
                if failed_count > 0:
                    ctx.obj.console.print(f"   • [red]Failed: {failed_count} items[/]")

        with Live(
            rich_output.group,
            refresh_per_second=10,
            console=ctx.obj.console,
            transient=True,
        ):

            async def wrapper(r: TidalResource):
                # Cooperative cancel OR session-limit reached: skip every remaining
                # resource the moment the run is stopped, instead of enumerating it
                # (credits, covers, edition resolution) and issuing API calls. This
                # is the single choke point that stops ALL per-resource work for
                # not-yet-started resources once the cap is hit.
                from tiddl.core.cancel import is_cancelled
                if is_cancelled() or _session_track_limit.is_reached():
                    return
                _rkey = f"{r.type}/{r.id}"
                # Resume: skip a resource already completed in a prior run of this
                # job BEFORE any API call — the whole point is to avoid re-enumerating.
                if resume_log is not None and resume_log.is_done(_rkey):
                    ctx.obj.console.print(f"[dim][resume] skip {_rkey} (done earlier)[/]")
                    return
                ok = False
                try:
                    await handle_resource(r)
                    ok = True
                except HTTPError as e:
                    if e.response is not None and e.response.status_code in [404, 406]:
                         ctx.obj.console.print(f"[yellow]Skipped (Geo-block/Not Found):[/] {r}")
                    else:
                         ctx.obj.console.print(f"[red]HTTP Error:[/] {e} at {r}")
                except ApiError as e:
                    ctx.obj.console.print(f"[red]API Error:[/] {e} at {r}")
                except KeyboardInterrupt:
                    # Silence keyboard interrupt in worker tasks to prevent traceback
                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    ctx.obj.console.print(f"[red]Error:[/] {e} at {r}")
                # Mark done only on a clean completion that was NOT stopped
                # underneath it — not cancelled, and not cut short by the session
                # cap (whose remaining tracks were never admitted). See
                # _resource_resume_done: marking a cap-truncated resource done
                # would make a later --resume skip its missing tracks.
                if _resource_resume_done(
                    ok, resume_log is not None, is_cancelled(),
                    _session_track_limit.is_reached(),
                ):
                    resume_log.mark_done(_rkey)

            async def expand_playlist(resource: TidalResource) -> list[TidalResource]:
                """--albums/--artists: turn a playlist into its unique albums or
                credited artists (same dedupe semantics as tidmon playlist)."""
                playlist = await asyncio.to_thread(
                    ctx.obj.api.get_playlist, playlist_uuid=resource.id
                )
                seen: set = set()
                expanded: list[TidalResource] = []
                skipped_videos = 0
                offset = 0
                while True:
                    page = await asyncio.to_thread(
                        ctx.obj.api.get_playlist_items,
                        playlist_uuid=resource.id, offset=offset,
                    )
                    for playlist_item in page.items:
                        item = playlist_item.item
                        if not isinstance(item, Track):
                            skipped_videos += 1
                            continue
                        if EXPAND_ALBUMS:
                            if item.album and item.album.id not in seen:
                                seen.add(item.album.id)
                                expanded.append(TidalResource(type="album", id=str(item.album.id)))
                        elif EXPAND_TRACKS:
                            if item.id not in seen:
                                seen.add(item.id)
                                expanded.append(TidalResource(type="track", id=str(item.id)))
                        else:
                            artists = item.artists or ([item.artist] if item.artist else [])
                            for artist in artists:
                                if artist and artist.id and artist.id not in seen:
                                    seen.add(artist.id)
                                    expanded.append(TidalResource(type="artist", id=str(artist.id)))
                    offset += page.limit
                    if offset >= page.totalNumberOfItems:
                        break
                kind = "albums" if EXPAND_ALBUMS else ("tracks" if EXPAND_TRACKS else "artists")
                msg = (
                    f"\n[bold magenta]Playlist expanded:[/] {playlist.title} "
                    f"-> [bold]{len(expanded)} unique {kind}[/]"
                )
                if skipped_videos:
                    msg += f" [dim]({skipped_videos} video item(s) skipped)[/]"
                ctx.obj.console.print(msg)
                return expanded

            expanded_run = False
            if EXPAND_ALBUMS or EXPAND_ARTISTS or EXPAND_TRACKS:
                expanded_run = True
                new_resources: list[TidalResource] = []
                seen_global: set = set()
                for r in ctx.obj.resources:
                    if r.type == "playlist":
                        for er in await expand_playlist(r):
                            key = (er.type, er.id)
                            if key not in seen_global:
                                seen_global.add(key)
                                new_resources.append(er)
                    else:
                        new_resources.append(r)
                ctx.obj.resources = new_resources

            if expanded_run or len(ctx.obj.resources) > 1:
                # Multi-resource runs (expansions or many pasted URLs) can be
                # hundreds of THOUSANDS of resources (a playlist expanded into
                # every credited artist). A bounded worker pool keeps at most
                # ARTIST_CONCURRENCY tasks alive at once, so peak memory does not
                # scale with the resource count — creating one asyncio Task per
                # resource up front (each parked on a semaphore) is exactly what
                # exhausted RAM on a giant stereo+artists run. It also caps
                # concurrency so resource #1 starts producing output immediately
                # instead of every task queueing behind the shared rate-limit lock.
                expand_total = len(ctx.obj.resources)

                async def dispatch_one(r: TidalResource, idx: int):
                    # Cooperative cancel OR session-limit reached: bail BEFORE the
                    # heartbeat print and before wrapper(), so a stopped run
                    # doesn't flood the log with a burst of "[idx/total] type/id"
                    # lines for every remaining resource (on a big expanded batch
                    # that's thousands of lines, which reads as "still working"
                    # even though nothing downloads) and issues no API traffic for
                    # resources it will not process.
                    if is_cancelled() or _session_track_limit.is_reached():
                        return
                    # Steady per-resource heartbeat: complete albums are skipped
                    # silently, so without this the output can go quiet for
                    # minutes on largely-downloaded expansions.
                    ctx.obj.console.print(
                        f"[{idx}/{expand_total}] {r.type}/{r.id}", markup=False
                    )
                    await wrapper(r)

                try:
                    await _bounded_dispatch(
                        ctx.obj.resources, dispatch_one, max(1, ARTIST_CONCURRENCY),
                        should_stop=_session_track_limit.is_reached,
                    )
                finally:
                    # Flush report_playback pendientes y cierra la sesión HTTP compartida
                    await downloader.close()
            else:
                tasks = [asyncio.create_task(wrapper(r)) for r in ctx.obj.resources]
                try:
                    await asyncio.gather(*tasks)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                finally:
                    # Flush report_playback pendientes y cierra la sesión HTTP compartida
                    await downloader.close()

        rich_output.show_stats()

        # v2.4 §2: checked once, after every per-item and per-resource task
        # has completed — not by scanning output or counting log lines.
        return identity_tracker.any_refused

    def run():
        # Sin recursos no hay nada que descargar: evita pintar los paneles
        # vacíos de progreso (que entierran el mensaje de error de Click
        # cuando el subcomando falló al parsear sus argumentos).
        if not ctx.obj.resources:
            return
        # Fresh 429 strike budget per invocation: the run-wide circuit breaker
        # counts 429s across the whole run, so it must start at zero here (the
        # GUI reuses this process for run after run). Cancel state is managed by
        # the caller (the GUI clears it before a batch; a safety stop should
        # halt the rest of the batch, so it is intentionally NOT cleared here).
        from tiddl.core.ratelimit import guard as _rl_guard
        _rl_guard().reset()
        import warnings
        # Suppress ResourceWarning noise from asyncio pipe cleanup on Windows Ctrl+C
        if sys.platform == "win32":
            warnings.filterwarnings("ignore", category=ResourceWarning)
        try:
            any_identity_refused = asyncio.run(download_resources())
        except KeyboardInterrupt:
            ctx.obj.console.print("\n[yellow]Download interrupted by user.[/]")
        except Exception as e:
            ctx.obj.console.print(f"\n[red]Unexpected error during download: {e}[/]")
            import traceback
            log.error(traceback.format_exc())
        else:
            code = _finish_download_run(
                ctx.obj.console,
                any_identity_refused,
                cooperative_stop=is_cancelled(),
            )
            # A non-zero outcome (identity-refusal or a cooperative safety
            # stop: Cancel / rate-limit / account-flagged) is signalled with
            # click.exceptions.Exit — NOT sys.exit — so it stays host-safe:
            # main() maps it to a non-zero SystemExit for the CLI, and the
            # in-process host catches it around tiddl_app(standalone_mode=False)
            # instead of the interpreter being hard-killed.
            if code:
                raise click.exceptions.Exit(code)

    ctx.call_on_close(run)
