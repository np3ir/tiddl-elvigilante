from __future__ import annotations
import os
import random
import typer
import asyncio
import time

from pathlib import Path
from logging import getLogger
from rich.live import Live

from requests import HTTPError
from typing_extensions import Annotated
from typing import Union, Optional

from tiddl.core.metadata import add_track_metadata, add_video_metadata, Cover
from tiddl.core.api import ApiError
from tiddl.core.api.models import Album, Track, Video, AlbumItemsCredits
from tiddl.core.utils.format import format_template
from tiddl.core.utils.m3u import save_tracks_to_m3u
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


def enrich_track_artists(item: Track, api) -> None:
    """Agrega Featured Artists faltantes del endpoint /contributors.

    Tidal a veces elimina featured artists del array artists[] principal
    pero los mantiene en /contributors. Mutamos la lista in-place para que
    tanto format_template (filename) como add_track_metadata (tags) los incluyan.
    """
    if not isinstance(item, Track):
        return
    try:
        existing = {a.name.lower() for a in item.artists}
        featured = api.get_featured_from_contributors(item.id)
        for name in featured:
            if name.lower() not in existing:
                item.artists.append(Track.Artist(id=0, name=name, type="FEATURED"))
                existing.add(name.lower())
    except Exception:
        pass

download_command = typer.Typer(name="download")
register_subcommands(download_command)

log = getLogger(__name__)


@download_command.callback(no_args_is_help=True)
def download_callback(
    ctx: Context,
    TRACK_QUALITY: Annotated[
        TRACK_QUALITY_LITERAL,
        typer.Option(
            "--track-quality",
            "-q",
        ),
    ] = CONFIG.download.track_quality,
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
):
    """
    Download Tidal resources.
    """

    ctx.invoke(refresh, EARLY_EXPIRE_TIME=600)

    log.debug(f"{ctx.params=}")

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

        save_tracks_to_m3u(
            tracks_with_path=tracks_with_existing_paths, path=DOWNLOAD_PATH / filename
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
        rich_output = RichOutput(ctx.obj.console)

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
        )

        class Metadata:
            def __init__(
                self,
                date: str = "",
                artist: str = "",
                credits: list[AlbumItemsCredits.ItemWithCredits.CreditsEntry] = [],
                cover_data: bytes = None,
                album_review: str = "",
                genre: str = "",
            ) -> None:
                self.date = date
                self.artist = artist
                self.credits = credits
                self.cover_data = cover_data
                self.album_review = album_review
                self.genre = genre

        async def handle_resource(resource: TidalResource):
            async def handle_item(
                item: Union[Track, Video],
                file_path: str,
                track_metadata: Union[Metadata, None] = None,
            ) -> tuple[Union[Path, None], Union[Track, Video]]:
                log.debug(f"{item.id=}, {file_path=}")
                rich_output.total_increment()

                if not track_metadata:
                    track_metadata = Metadata()

                download_path, was_downloaded = await downloader.download(
                    item=item, file_path=Path(file_path)
                )

                log.debug(f"{download_path=}, {was_downloaded=}")

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
                                        fetched_lyrics_response = ctx.obj.api.get_track_lyrics(item.id)
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
                                            lrc_path.write_text(fetched_lyrics, encoding="utf-8")
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
                                track_metadata.cover_data = Cover(
                                    item.album.cover
                                )._get_data()
                            except Exception as e:
                                log.warning(f"Could not download track cover: {e}")
                                track_metadata.cover_data = b""

                        if REWRITE_METADATA or was_downloaded:
                            for _attempt in range(3):
                                try:
                                    add_track_metadata(
                                        path=download_path,
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
                                except (PermissionError, OSError) as e:
                                    if _attempt < 2:
                                        log.warning(f"Metadata write blocked (attempt {_attempt + 1}/3), retrying in 2s: {download_path}")
                                        await asyncio.sleep(2)
                                    else:
                                        log.warning(f"Could not write metadata after 3 attempts, skipping: {download_path} — {e}")

                    elif isinstance(item, Video):
                        if REWRITE_METADATA or was_downloaded:
                            add_video_metadata(path=download_path, video=item, artist_separator=CONFIG.templates.artist_separator)

                if download_path and CONFIG.download.update_mtime:
                    try:
                        os.utime(download_path, None)
                    except Exception:
                        log.warning(f"could not update mtime for {download_path}")

                return download_path, item

            async def download_album(album: Album):
                offset = 0
                futures = []
                all_album_items = []  # collect all pages first for batch prefetch

                cover: Union[Cover, None] = None
                save_cover = ("album" in CONFIG.cover.allowed) and CONFIG.cover.save

                if album.cover and (CONFIG.metadata.cover or save_cover):
                    try:
                        cover = Cover(album.cover, size=CONFIG.cover.size)
                        cover._get_data()
                    except Exception as e:
                        log.warning(f"Could not download album cover: {e}")
                        cover = None

                album_review = ""

                if CONFIG.metadata.album_review:
                    try:
                        album_review = ctx.obj.api.get_album_review(
                            album_id=album.id
                        ).normalized_text()
                    except Exception as e:
                        log.error(e)

                # --- Page collection (all pages, no tasks yet) ---
                while True:
                    album_items = None
                    for attempt in range(3):
                        try:
                            album_items = ctx.obj.api.get_album_items_credits(
                                album_id=album.id, offset=offset
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

                # --- Batch DB prefetch: one SQL query for all tracks in this album ---
                # Instead of one SELECT per track inside each task, we do a single
                # SELECT ... IN (...) for all track IDs, then check file existence
                # concurrently. Tracks confirmed on disk are skipped without creating
                # a coroutine. Stale DB entries (file deleted) are cleaned up here too.
                confirmed: dict = {}  # {track_id: Path} — tracks verified on disk
                if downloader.skip_existing:
                    track_ids = [
                        ai.item.id
                        for ai in all_album_items
                        if isinstance(ai.item, Track)
                    ]
                    db_hits = downloader._db_batch_lookup(track_ids)

                    if db_hits:
                        # Check all found paths concurrently (one asyncio round instead of N)
                        hit_items = list(db_hits.items())  # [(track_id, path), ...]
                        exists_results = await asyncio.gather(
                            *[asyncio.to_thread(p.exists) for _, p in hit_items],
                            return_exceptions=True,
                        )
                        for (track_id, path), exists in zip(hit_items, exists_results):
                            if isinstance(exists, Exception) or not exists:
                                downloader._db_remove(track_id)
                                log.debug(f"Track {track_id} was in DB but file missing, will re-download")
                            else:
                                confirmed[track_id] = path

                # --- Build tasks — confirmed tracks are skipped, rest download normally ---
                # confirmed-skipped tuples are pre-populated so save_m3u stays complete
                skipped_with_path: list[tuple] = []
                for album_item in all_album_items:
                    item = album_item.item
                    enrich_track_artists(item, ctx.obj.api)
                    if isinstance(item, Track) and item.id in confirmed:
                        confirmed_path = confirmed[item.id]
                        downloader.rich_output.show_item_result(
                            result_message="[yellow]Exists",
                            item_description=f"[bold]{item.title}",
                            item_path=confirmed_path,
                        )
                        skipped_with_path.append((confirmed_path, item))
                        continue

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
                    cover.save_to_directory(
                        path=DOWNLOAD_PATH
                        / format_template(
                            template=CONFIG.cover.templates.album, album=album,
                            artist_separator=CONFIG.templates.artist_separator,
                        )
                    )

            # resources should be collected from a distinct function
            # that would yield the resources.
            # then we would be able to reuse the logic in the export command
            resource_type = resource.type

            if resource_type == "track":
                track = ctx.obj.api.get_track(resource.id)
                album = ctx.obj.api.get_album(track.album.id)
                enrich_track_artists(track, ctx.obj.api)

                ctx.obj.console.print(f"\n[bold green]Downloading Track:[/] {track.title}")
                ctx.obj.console.print(f"[dim]Track ID: {resource.id}[/]\n")

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
                )

                if (
                    CONFIG.cover.save
                    and ("track" in CONFIG.cover.allowed)
                    and track.album.cover
                ):
                    Cover(
                        track.album.cover, size=CONFIG.cover.size
                    ).save_to_directory(
                        path=DOWNLOAD_PATH
                        / format_template(
                            CONFIG.cover.templates.track, item=track, album=album,
                            artist_separator=CONFIG.templates.artist_separator,
                        )
                    )

            elif resource_type == "video":
                video = ctx.obj.api.get_video(resource.id)

                ctx.obj.console.print(f"\n[bold blue]Downloading Video:[/] {video.title}")
                ctx.obj.console.print(f"[dim]Video ID: {resource.id}[/]\n")
                
                # Fetch album info if available to populate {album.date} and other placeholders
                album = None
                if video.album and video.album.id:
                    try:
                        album = ctx.obj.api.get_album(video.album.id)
                    except Exception as e:
                        log.warning(f"Could not fetch album {video.album.id} for video {video.id}: {e}")

                await handle_item(
                    item=video,
                    file_path=format_template(
                        template=resolve_template(VIDEO_TEMPLATE, CONFIG.templates.video),
                        item=video,
                        album=album,
                        quality=get_item_quality(video),
                        artist_separator=CONFIG.templates.artist_separator,
                    ),
                )

            elif resource_type == "mix":
                offset = 0
                futures = []
                mix_id = resource.id
                ctx.obj.console.print(f"\n[bold yellow]🎧 Downloading Mix:[/] {mix_id}")
                ctx.obj.console.print(f"[dim]Fetching tracks...[/]\n")

                while True:
                    try:
                        mix_items = ctx.obj.api.get_mix_items(mix_id, offset=offset)
                    except Exception as e:
                        log.error(f"Could not fetch mix items for {mix_id}: {e}")
                        break

                    for mix_item in mix_items.items:
                        enrich_track_artists(mix_item.item, ctx.obj.api)
                        futures.append(
                            asyncio.create_task(handle_item(
                                item=mix_item.item,
                                file_path=format_template(
                                    template=resolve_template("", CONFIG.templates.mix),
                                    item=mix_item.item,
                                    mix_id=mix_id,
                                    quality=get_item_quality(mix_item.item),
                                    artist_separator=CONFIG.templates.artist_separator,
                                ),
                            ))
                        )

                    offset += mix_items.limit
                    if offset >= mix_items.totalNumberOfItems:
                        break

                total_items = len(futures)
                ctx.obj.console.print(f"\nFound:")
                ctx.obj.console.print(f"  • {total_items} items in the mix.")
                ctx.obj.console.print(f"  • [bold]{total_items} total items to download[/]\n")

                try:
                    results = await asyncio.gather(*futures, return_exceptions=True)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise

                tracks_with_path = []
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
                album = ctx.obj.api.get_album(album_id=resource.id)
                await download_album(album)

            elif resource_type == "artist":
                # ============================================================
                # IMPROVED ARTIST DOWNLOAD with SMART deduplication
                # Respects: different qualities, explicit/clean, special editions
                # ============================================================
                
                futures = []
                seen_album_ids = set()  # Use album.id instead of title for proper deduplication
                artist_stats = {
                    'total_albums': 0,
                    'total_videos': 0,
                    'skipped_duplicates': 0,
                }
                
                # Get artist info for better feedback
                try:
                    artist = ctx.obj.api.get_artist(resource.id)
                    artist_name = artist.name
                    ctx.obj.console.print(f"\n[bold cyan]Downloading Artist:[/] {artist_name}")
                    ctx.obj.console.print(f"[dim]Artist ID: {resource.id}[/]\n")
                except Exception as e:
                    artist_name = f"Artist {resource.id}"
                    log.warning(f"Could not get artist info: {e}")

                collected_albums = []

                def collect_albums(singles: bool):
                    offset = 0
                    filter_type = "EPSANDSINGLES" if singles else "ALBUMS"
                    display_type = "EPs & Singles" if singles else "Albums"
                    
                    ctx.obj.console.print(f"[dim]Fetching {display_type}...[/]")

                    while True:
                        artist_albums = None
                        for attempt in range(3):
                            try:
                                artist_albums = ctx.obj.api.get_artist_albums(
                                    artist_id=resource.id,
                                    offset=offset,
                                    filter=filter_type,
                                )
                                break
                            except Exception as e:
                                if attempt < 2:
                                    wait = (attempt + 1) * 2
                                    log.warning(f"Error fetching albums (offset {offset}): {e}. Retrying in {wait}s...")
                                    time.sleep(wait)
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

                def get_all_videos():
                    offset = 0
                    
                    ctx.obj.console.print(f"[dim]Fetching videos...[/]")

                    while True:
                        try:
                            artist_videos = ctx.obj.api.get_artist_videos(
                                resource.id, offset=offset
                            )

                            for video in artist_videos.items:
                                artist_stats['total_videos'] += 1
                                futures.append(
                                    asyncio.create_task(handle_item(
                                        item=video,
                                        file_path=format_template(
                                            template=resolve_template(VIDEO_TEMPLATE, CONFIG.templates.video),
                                            item=video,
                                            quality=get_item_quality(video),
                                            artist_separator=CONFIG.templates.artist_separator,
                                        ),
                                    ))
                                )

                            if offset > artist_videos.totalNumberOfItems:
                                break

                            offset += artist_videos.limit
                            
                        except Exception as e:
                            log.error(f"Error fetching videos at offset {offset}: {e}")
                            break

                # Gather albums and videos based on filters
                if VIDEOS_FILTER != "none":
                    get_all_videos()

                if VIDEOS_FILTER != "only":
                    if SINGLES_FILTER == "include":
                        collect_albums(False)
                        collect_albums(True)
                    else:
                        collect_albums(SINGLES_FILTER == "only")
                
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
                
                # Queue the selected best versions in random order
                albums_to_download = list(unique_map.values())
                random.shuffle(albums_to_download)
                for album in albums_to_download:
                    if album.id not in seen_album_ids:
                        seen_album_ids.add(album.id)
                        futures.append(asyncio.create_task(download_album(album)))
                
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
                try:
                    await asyncio.gather(*futures)
                    
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
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise
                except Exception as e:
                    ctx.obj.console.print(f"\n[red]❌ Error during artist download:[/] {e}")
                    log.exception(f"Error downloading artist {resource.id}")

            elif resource_type == "playlist":
                offset = 0
                futures = []
                playlist_index = 0
                playlist = ctx.obj.api.get_playlist(playlist_uuid=resource.id)

                ctx.obj.console.print(f"\n[bold magenta]Downloading Playlist:[/] {playlist.title}")
                ctx.obj.console.print(f"[dim]Playlist ID: {resource.id}[/]\n")
                ctx.obj.console.print(f"[dim]Fetching tracks...[/]")

                while True:
                    playlist_items = ctx.obj.api.get_playlist_items(
                        playlist_uuid=resource.id, offset=offset
                    )

                    for playlist_item in playlist_items.items:
                        playlist_index += 1
                        enrich_track_artists(playlist_item.item, ctx.obj.api)
                        template = resolve_template(PLAYLIST_TEMPLATE, CONFIG.templates.playlist)

                        if "{album" in template:
                            album = ctx.obj.api.get_album(
                                playlist_item.item.album.id
                            )
                        else:
                            album = None

                        futures.append(
                            asyncio.create_task(handle_item(
                                item=playlist_item.item,
                                file_path=format_template(
                                    template=template,
                                    item=playlist_item.item,
                                    album=album,
                                    playlist=playlist,
                                    playlist_index=playlist_index,
                                    quality=get_item_quality(playlist_item.item),
                                    artist_separator=CONFIG.templates.artist_separator,
                                ),
                                track_metadata=Metadata(),
                            ))
                        )

                    offset += playlist_items.limit
                    if offset >= playlist_items.totalNumberOfItems:
                        break

                total_items = len(futures)
                ctx.obj.console.print(f"\nFound:")
                ctx.obj.console.print(f"  • {total_items} items in the playlist.")
                ctx.obj.console.print(f"  • [bold]{total_items} total items to download[/]\n")

                try:
                    results = await asyncio.gather(*futures, return_exceptions=True)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    await asyncio.gather(*futures, return_exceptions=True)
                    raise

                # Filter out exceptions from results
                tracks_with_path = []
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
                    Cover(
                        playlist.squareImage, size=max(CONFIG.cover.size, 1080)
                    ).save_to_directory(
                        path=DOWNLOAD_PATH
                        / format_template(
                            template=CONFIG.cover.templates.playlist,
                            playlist=playlist,
                            artist_separator=CONFIG.templates.artist_separator,
                        )
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
                try:
                    await handle_resource(r)
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

            tasks = [asyncio.create_task(wrapper(r)) for r in ctx.obj.resources]
            try:
                await asyncio.gather(*tasks)
            except (asyncio.CancelledError, KeyboardInterrupt):
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        rich_output.show_stats()

    def run():
        try:
            asyncio.run(download_resources())
        except KeyboardInterrupt:
            ctx.obj.console.print("\n[yellow]Download interrupted by user.[/]")
        except Exception as e:
            ctx.obj.console.print(f"\n[red]Unexpected error during download: {e}[/]")
            import traceback
            log.error(traceback.format_exc())

    ctx.call_on_close(run)
