from __future__ import annotations
import asyncio
import shutil
import hashlib
import uuid
import sqlite3
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Optional, Literal, Union
from dataclasses import dataclass
from enum import Enum

import os
import aiofiles
import aiohttp
from requests import HTTPError

from tiddl.cli.config import VIDEOS_FILTER_LITERAL
from tiddl.cli.utils.download import get_existing_track_filename
from tiddl.core.api import ApiError, TidalAPI
import sys
from tiddl.core.api.models import StreamVideoQuality, Track, TrackQuality, Video
from tiddl.core.utils import parse_track_stream, parse_video_stream
from tiddl.core.utils.format import _prepare_long_path
from tiddl.core.utils.const import (
    TRACK_QUALITY_LITERAL,
    VIDEO_QUALITY_LITERAL,
    track_qualities,
    video_qualities,
)
from tiddl.core.utils.ffmpeg import convert_to_mp4, extract_flac, fix_mp4_faststart, is_mp4_container
from tiddl.core.api.playback import report_playback

from .output import RichOutput

log = getLogger(__name__)

CHUNK_SIZE = 1024**2
MAX_RETRIES = 3  # Maximum number of retries for corrupt files


def _normalize_dir(path: Path) -> str:
    """Canonical form of a directory path for equality checks.

    Strips the Windows long-path prefix (``\\\\?\\`` / ``\\\\?\\UNC\\``) so a
    DB-stored, prefixed path compares equal to a freshly built one, then applies
    ``normcase`` + ``normpath``. Pure string work — no filesystem access."""
    s = str(path)
    if s.startswith("\\\\?\\UNC\\"):
        s = "\\\\" + s[len("\\\\?\\UNC\\"):]
    elif s.startswith("\\\\?\\"):
        s = s[len("\\\\?\\"):]
    return os.path.normcase(os.path.normpath(s))


def _safe_unlink(path: Optional[Path]) -> bool:
    """Delete a file if it exists, swallowing OS errors (best-effort cleanup).

    Returns True if `path` is gone once this returns (deleted here, or it never
    existed) and False if an existing file could NOT be removed (e.g. locked by
    an antivirus/indexer, or a remote filesystem that rejects the unlink).
    Callers that must not silently claim "no orphan left behind" — i.e. after a
    successful publish, when the leftover would otherwise go unreported — should
    check this return value instead of treating cleanup as unconditional."""
    if path is None:
        return True
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _same_volume(a: Path, b: Path) -> bool:
    """True if paths `a` and `b` live on the same filesystem (st_dev match).

    Used by the safe-publish step to pick the atomic-rename fast path. Kept as a
    module-level function so tests can force the cross-filesystem path."""
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _fsync_path(path: Path) -> None:
    """Best-effort flush of a file's data to storage before it is verified.

    shutil.copy2 only closes the file; on a network share the bytes may still sit
    in a write cache, so an immediate verify could read cache rather than what
    actually landed. Filesystems that don't support fsync just no-op."""
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory (POSIX only) so a rename into it is
    durable across a power loss. A no-op on Windows / unsupported filesystems."""
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)

# ====================================================================
# IMPROVEMENT 1: Enums for download states
# ====================================================================

class DownloadStatus(Enum):
    """Possible statuses of a download"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CORRUPTED = "corrupted"


class DownloadPriority(Enum):
    """Download priorities"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ====================================================================
# IMPROVEMENT 2: Dataclass for download tracking
# ====================================================================

@dataclass
class DownloadTask:
    """Download task with complete metadata"""
    url: str
    output_path: Path
    track_id: Optional[int] = None
    track_title: Optional[str] = None
    expected_size: Optional[int] = None  # Expected bytes
    expected_hash: Optional[str] = None  # Expected MD5/SHA256 hash
    status: DownloadStatus = DownloadStatus.PENDING
    priority: DownloadPriority = DownloadPriority.NORMAL
    attempts: int = 0
    max_attempts: int = 3
    bytes_downloaded: int = 0
    error_message: Optional[str] = None
    # Set when the download succeeded but the destination could not be published:
    # the verified local file is kept here for recovery/re-publish (never deleted).
    retained_staging: Optional[Path] = None

    @property
    def progress_percentage(self) -> float:
        """Progress percentage (0-100)"""
        if not self.expected_size or self.expected_size == 0:
            return 0.0
        return (self.bytes_downloaded / self.expected_size) * 100

    @property
    def can_retry(self) -> bool:
        """Checks if a retry is possible"""
        return self.attempts < self.max_attempts

    def increment_attempt(self) -> None:
        """Increments the attempt counter"""
        self.attempts += 1


track_qualities_color: dict[TrackQuality, str] = {
    "LOW": "[gray]96 kbps",
    "HIGH": "[gray]320 kbps",
    "LOSSLESS": "[cyan]",
    "HI_RES_LOSSLESS": "[yellow]",
}

video_qualities_color: dict[StreamVideoQuality, str] = {
    "LOW": "[gray]360p",
    "MEDIUM": "[cyan]720p",
    "HIGH": "[yellow]1080p",
}


# ====================================================================
# File integrity checker
# ====================================================================

class FileIntegrityChecker:
    """Checks the integrity of downloaded files"""

    @staticmethod
    async def verify_file_async(
        file_path: Path,
        expected_size: Optional[int] = None,
        expected_hash: Optional[str] = None,
        hash_algorithm: Literal["md5", "sha256"] = "md5"
    ) -> tuple[bool, Optional[str]]:
        """
        Verifies the integrity of a file asynchronously.

        Returns:
            tuple[is_valid, error_message]
        """
        if not file_path.exists():
            return False, "File does not exist"

        # Check size
        actual_size = file_path.stat().st_size

        # Very small files are suspicious
        if actual_size < 2048:  # Less than 2KB
            return False, f"File too small ({actual_size} bytes)"

        # Check expected size
        if expected_size and abs(actual_size - expected_size) > 1024:  # 1KB tolerance
            return False, f"Size mismatch: expected {expected_size}, got {actual_size}"

        # Check magic bytes based on extension
        try:
            async with aiofiles.open(file_path, "rb") as f:
                header = await f.read(12)

                if not FileIntegrityChecker._check_magic_bytes(file_path, header):
                    return False, "Invalid file format (magic bytes check failed)"

                # For MP4/M4A files, check atoms
                if file_path.suffix.lower() in ['.m4a', '.mp4', '.m4v']:
                    await f.seek(0)
                    first_256kb = await f.read(262144)

                    if b'moov' not in first_256kb:
                        return False, "Invalid MP4/M4A: missing 'moov' atom"

                # Verify hash if provided
                if expected_hash:
                    actual_hash = await FileIntegrityChecker._calculate_hash_async(
                        file_path,
                        hash_algorithm
                    )

                    if actual_hash != expected_hash.lower():
                        return False, f"Hash mismatch: expected {expected_hash}, got {actual_hash}"

        except Exception as e:
            return False, f"Verification error: {str(e)}"

        return True, None

    @staticmethod
    def _check_magic_bytes(file_path: Path, header: bytes) -> bool:
        """Checks magic bytes based on file type"""
        ext = file_path.suffix.lower()

        # FLAC
        if ext == '.flac':
            # TIDAL delivers HI_RES_LOSSLESS as an M4A container; extract_flac()
            # converts it after this check, so accept both signatures.
            return header.startswith(b'fLaC') or (len(header) >= 8 and header[4:8] == b'ftyp')

        # MP4/M4A
        elif ext in ['.m4a', '.mp4', '.m4v']:
            return len(header) >= 8 and header[4:8] == b'ftyp'

        # MP3
        elif ext == '.mp3':
            # ID3v2 tag or frame sync
            return header.startswith(b'ID3') or (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)

        # AAC
        elif ext == '.aac':
            return header.startswith(b'\xFF\xF1') or header.startswith(b'\xFF\xF9')

        # If we don't know the format, assume it's valid
        return True

    @staticmethod
    async def _calculate_hash_async(
        file_path: Path,
        algorithm: Literal["md5", "sha256"] = "md5"
    ) -> str:
        """Calculates the hash of a file asynchronously"""
        hash_obj = hashlib.md5() if algorithm == "md5" else hashlib.sha256()

        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                hash_obj.update(chunk)

        return hash_obj.hexdigest()


class Downloader:
    api: TidalAPI
    rich_output: RichOutput
    semaphore: asyncio.Semaphore
    track_quality: TrackQuality
    video_quality: StreamVideoQuality
    videos_filter: VIDEOS_FILTER_LITERAL
    skip_existing: bool
    download_path: Path
    scan_path: Path
    video_download_path: Optional[Path]

    def __init__(
        self,
        tidal_api: TidalAPI,
        threads_count: int,
        rich_output: RichOutput,
        track_quality: TRACK_QUALITY_LITERAL,
        video_quality: VIDEO_QUALITY_LITERAL,
        videos_filter: VIDEOS_FILTER_LITERAL,
        skip_existing: bool,
        download_path: Path,
        scan_path: Path,
        video_download_path: Optional[Path] = None,
        fallback_api: Optional[TidalAPI] = None,
    ) -> None:
        self.api = tidal_api
        # Modo hibrido: cliente TV (lossless) para cuando el primario (HiRes)
        # degrada un track no-HiRes a 320. None = sin fallback.
        self.fallback_api = fallback_api
        self.rich_output = rich_output
        self.semaphore = asyncio.Semaphore(threads_count)
        self.track_quality = track_qualities[track_quality]
        self.video_quality = video_qualities[video_quality]
        self.videos_filter = videos_filter
        self.skip_existing = skip_existing
        self.download_path = download_path
        self.scan_path = scan_path
        self.video_download_path = video_download_path
        self.dir_cache: dict[Path, set[str]] = {}
        # Flat index: stem → set of extensions, para lookup de alternativas sin re-escanear
        self._stem_index: dict[str, set[str]] = {}
        # Per-directory locks: allows scanning different dirs in parallel while
        # preventing duplicate scans of the same directory.
        self._dir_locks: dict[Path, asyncio.Lock] = {}
        self._dir_locks_meta: asyncio.Lock = asyncio.Lock()  # guards _dir_locks dict
        # SQLite DB for O(1) skip-existing lookup without any filesystem I/O.
        # Track IDs are stored after a successful download; on subsequent runs
        # we do a DB lookup first (instant), then a single stat() to confirm
        # the file still exists on disk. No false positives.
        self._db: sqlite3.Connection = self._init_db()
        # Shared HTTP session: one connection pool for all downloads instead of
        # a new TCP+TLS handshake per track. Created lazily inside the loop.
        self._http_session: Optional[aiohttp.ClientSession] = None
        # Strong refs to fire-and-forget tasks (report_playback) so the GC
        # can't cancel them mid-flight; awaited in close().
        self._bg_tasks: set[asyncio.Task] = set()

    def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            connector = None
            if sys.platform == "win32":
                # aiohttp defaults to the aiodns/c-ares AsyncResolver whenever
                # aiodns is installed. On Windows c-ares queries the configured DNS
                # servers directly over UDP, bypassing the Windows DNS Client (its
                # cache, per-adapter failover and retry). On flaky links or
                # multi-WAN setups a dropped UDP packet then yields "Timeout while
                # contacting DNS servers" — which aiohttp surfaces on the first
                # attempt as the cryptic "[Errno 22] Invalid argument", failing an
                # otherwise-fine track. ThreadedResolver uses the OS getaddrinfo()
                # (the full Windows resolution path), which is far more robust here.
                connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=120),
                connector=connector,
            )
        return self._http_session

    def _spawn_bg(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def close(self) -> None:
        """Flush pending background tasks and release the HTTP session/DB."""
        if self._bg_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._bg_tasks, return_exceptions=True),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                for t in self._bg_tasks:
                    t.cancel()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # SQLite track-DB: O(1) skip-existing without filesystem I/O
    # ------------------------------------------------------------------

    def _init_db(self) -> sqlite3.Connection:
        """Open (or create) the SQLite DB that tracks downloaded track IDs."""
        from tiddl.cli.const import APP_PATH
        db_path = APP_PATH / "downloaded_tracks.db"
        try:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")  # safe for concurrent writes
            conn.execute('''
                CREATE TABLE IF NOT EXISTS downloaded_tracks (
                    track_id  INTEGER PRIMARY KEY,
                    path      TEXT    NOT NULL,
                    quality   TEXT,
                    ts        TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            ''')
            conn.commit()
            log.debug(f"Track DB opened at {db_path}")
        except Exception as e:
            log.warning(f"Could not open track DB ({e}), DB cache disabled")
            conn = None  # type: ignore
        return conn

    def _db_lookup(self, track_id: int) -> Optional[Path]:
        """Return the stored path for a track_id, or None if not in DB."""
        if not self._db:
            return None
        try:
            row = self._db.execute(
                "SELECT path FROM downloaded_tracks WHERE track_id = ?",
                (track_id,)
            ).fetchone()
            return Path(row[0]) if row else None
        except Exception:
            return None

    def _db_insert(self, track_id: int, path: Path, quality: str) -> None:
        """Record a successfully downloaded track in the DB."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO downloaded_tracks (track_id, path, quality) VALUES (?, ?, ?)",
                (track_id, str(path), quality)
            )
            self._db.commit()
        except Exception as e:
            log.debug(f"DB insert failed for track {track_id}: {e}")

    def _db_batch_lookup(self, track_ids: list) -> dict:
        """Batch lookup multiple track IDs in one SQL query.

        Replaces N individual _db_lookup() calls with a single
        SELECT ... WHERE track_id IN (...) — one round-trip to SQLite
        regardless of album size.

        Returns {track_id: Path} for every track found in the DB.
        Tracks not in the DB are simply absent from the result.
        """
        if not self._db or not track_ids:
            return {}
        try:
            placeholders = ",".join("?" * len(track_ids))
            rows = self._db.execute(
                f"SELECT track_id, path FROM downloaded_tracks WHERE track_id IN ({placeholders})",
                track_ids,
            ).fetchall()
            return {row[0]: Path(row[1]) for row in rows}
        except Exception:
            return {}

    def _db_remove(self, track_id: int) -> None:
        """Remove a track from the DB (e.g. file was deleted from disk)."""
        if not self._db:
            return
        try:
            self._db.execute(
                "DELETE FROM downloaded_tracks WHERE track_id = ?",
                (track_id,)
            )
            self._db.commit()
        except Exception:
            pass

    async def _scan_directory(self, dir_path: Path) -> None:
        """Scans a directory and caches its contents.

        Uses per-directory locks so that:
        - Different directories can be scanned concurrently (parallel SMB round-trips)
        - The same directory is only scanned once (double-check locking pattern)
        - The iterdir() is offloaded to a thread so the event loop stays free
        """
        if dir_path in self.dir_cache:
            return
        # Get (or create) the lock for this specific directory
        async with self._dir_locks_meta:
            if dir_path not in self._dir_locks:
                self._dir_locks[dir_path] = asyncio.Lock()
            dir_lock = self._dir_locks[dir_path]
        async with dir_lock:
            # Double-check: another coroutine may have scanned while we waited
            if dir_path in self.dir_cache:
                return
            try:
                # os.listdir() returns names only — no per-entry stat() calls.
                # iterdir() + is_file() would add one SMB round-trip per file,
                # which is catastrophic on network shares.
                names = await asyncio.to_thread(os.listdir, dir_path)
                files = set(names)
                self.dir_cache[dir_path] = files
                for name in files:
                    stem = Path(name).stem
                    if stem not in self._stem_index:
                        self._stem_index[stem] = set()
                    self._stem_index[stem].add(Path(name).suffix)
            except (FileNotFoundError, OSError):
                self.dir_cache[dir_path] = set()

    async def _is_file_in_cache(self, file_path: Path) -> bool:
        """Checks if a file exists, using async dir scan + in-memory cache.

        Strategy: always scan the parent directory on first access (one iterdir
        per directory instead of one stat per file).  For playlists/albums where
        N tracks share the same directory, this is N× faster than N individual
        stat calls, because SMB round-trips are amortised into a single request.
        Subsequent lookups for the same directory are pure in-memory O(1).
        """
        dir_path = file_path.parent
        if dir_path not in self.dir_cache:
            await self._scan_directory(dir_path)
        return file_path.name in self.dir_cache.get(dir_path, set())

    async def is_item_present(
        self, item: Union[Track, Video], file_path: Path
    ) -> Optional[Path]:
        """Read-only check used by the album/playlist/mix/artist flows to detect
        *confirmed-complete* items (tracks AND videos) up front, so fully
        downloaded content can skip the browse simulation, cover/review fetch,
        per-track /contributors enrichment and dispatch delays — and each such
        item can also skip the per-run metadata rewrite.

        Returns the on-disk path only when the item is BOTH:
          * recorded in the skip DB — a record is inserted by the caller only
            *after* metadata was successfully applied, so this proves the media
            AND tags are complete (unlike a file found by a bare directory scan,
            which may have been left untagged and must still be reprocessed); and
          * that DB file still exists and sits in the folder THIS download targets
            (compared absolute-vs-absolute, long-path prefix normalized).

        Returns None otherwise (missing, only-on-disk/untagged, or wrong folder),
        so the item falls through to download()'s normal path exactly as before.
        A false negative merely costs the overhead we hoped to save — never a
        wrong skip. The network is never touched.
        """
        if not self.skip_existing or not isinstance(item, (Track, Video)):
            return None

        db_path = self._db_lookup(item.id)
        if db_path is None:
            return None

        try:
            still_on_disk = await self._is_file_in_cache(db_path)
        except OSError:
            return None
        if not still_on_disk:
            self._db_remove(item.id)
            return None

        # Mirror download()'s destination logic per item type: videos land in
        # video_download_path (when configured) with a fixed .mp4 suffix.
        if isinstance(item, Video):
            filename = file_path.with_suffix(".mp4")
            base_path = self.video_download_path or self.scan_path
        else:
            filename = get_existing_track_filename(
                item.audioQuality, self.track_quality, file_path
            )
            base_path = self.scan_path
        intended_dir = (base_path / filename).parent
        if _normalize_dir(db_path.parent) == _normalize_dir(intended_dir):
            return db_path
        return None

    async def _verify_or_repair(self, candidate: Path, task: DownloadTask):
        """Verify a candidate file (size/hash). On an MP4/M4A container failure,
        attempt one faststart repair in place and re-verify. Returns (ok, error)."""
        ok, err = await FileIntegrityChecker.verify_file_async(
            candidate, expected_size=task.expected_size, expected_hash=task.expected_hash
        )
        if ok:
            return True, None
        if candidate.suffix.lower() in [".m4a", ".mp4", ".m4v"]:
            try:
                repaired = Path(await asyncio.to_thread(fix_mp4_faststart, candidate))
                ok2, err2 = await FileIntegrityChecker.verify_file_async(repaired)
                if ok2:
                    if repaired != candidate:
                        os.replace(repaired, candidate)
                    self.rich_output.console.print(
                        f"[green]✓ Repaired container (moov atom) [/]{task.track_title}"
                    )
                    return True, None
                return False, err2
            except Exception as repair_exc:
                log.error(f"Repair failed for '{task.track_title}': {repair_exc}")
        return False, err

    async def _publish_staged(self, task: DownloadTask, staging: Path):
        """Publish a downloaded staging file to ``task.output_path``.

        Contract: the final path is only ever replaced atomically by a
        fully-verified candidate, and the known-good local staging is deleted
        (best-effort — see the ``(True, staging)`` case below) ONLY after a
        successful publish. A prior valid final file is never removed by a failed
        publish.

        Returns ``(published, retained_staging)``:
          * ``(True, None)``    published; local staging deleted; output_path is
                                 verified; ``task.error_message`` is cleared.
          * ``(True, staging)``  published — output_path is verified and correct —
                                 but the local staging copy could not be deleted
                                 afterwards (best-effort cleanup failure, e.g. an
                                 AV/indexer lock or a remote filesystem). Logged as
                                 a warning; the leftover file is safe to delete
                                 manually once noticed.
          * ``(False, staging)``  the DESTINATION could not be published; the local
                                  staging is retained (caller must NOT re-download);
                                  the prior final file and every temp created here
                                  are left clean.
          * ``(False, None)``   the local staging itself is invalid; re-download.

        This is a general cross-filesystem safe publish — it protects any
        destination that can fail or write partially mid-publish (NAS/SMB/NFS,
        USB/external drives, cloud-synced folders, full/quota disks, AV/indexer
        locks, a crash mid-copy, silent same-size corruption). The NAS is only the
        most visible consumer. Same-filesystem publishes use an atomic rename.
        """
        task.status = DownloadStatus.VERIFYING

        # 1. Verify (and repair) the LOCAL staging ONCE, before touching the
        #    destination: a corrupt local download must be re-downloaded, not
        #    copied to the destination five times.
        ok, err = await self._verify_or_repair(staging, task)
        if not ok:
            task.error_message = f"local file invalid: {err}"
            _safe_unlink(staging)
            return False, None

        # 2. Same filesystem: a single atomic rename (no bytes copied). Retry only
        #    transient locks; if it never happens the staging still exists.
        if _same_volume(staging, task.output_path.parent):
            for move_attempt in range(5):
                try:
                    os.replace(staging, task.output_path)
                    await asyncio.to_thread(_fsync_dir, task.output_path.parent)
                    task.error_message = None
                    return True, None
                except OSError as e:
                    task.error_message = f"publish rename failed: {e}"
                    if move_attempt == 4:
                        log.warning(f"Failed to publish (rename) after 5 attempts: {e}")
                        return False, staging
                    log.warning(f"Publish rename locked (attempt {move_attempt+1}), retrying: {e}")
                    await asyncio.sleep(1.0 + move_attempt)
            return False, staging

        # 3. Cross filesystem: copy -> fsync -> verify a dest-side temp, then
        #    atomically publish it with os.replace().
        dest_tmp = task.output_path.with_name(
            task.output_path.name + f".part.{uuid.uuid4().hex[:8]}"
        )
        for publish_attempt in range(5):
            _safe_unlink(dest_tmp)
            try:
                await asyncio.to_thread(shutil.copy2, str(staging), str(dest_tmp))
                await asyncio.to_thread(_fsync_path, dest_tmp)  # commit before verifying
            except OSError as e:
                task.error_message = f"copy to destination failed: {e}"
                log.warning(f"{task.error_message} (attempt {publish_attempt+1})")
                _safe_unlink(dest_tmp)
                if publish_attempt == 4:
                    break
                await asyncio.sleep(1.0 + publish_attempt)
                continue

            ok, err = await self._verify_or_repair(dest_tmp, task)
            if ok:
                # Atomic publish, with its own retry. A failure here must NEVER
                # delete the prior final file — only a successful os.replace
                # overwrites it, atomically.
                for replace_attempt in range(5):
                    try:
                        os.replace(dest_tmp, task.output_path)
                        await asyncio.to_thread(_fsync_dir, task.output_path.parent)
                        task.error_message = None
                        # Only now is the local copy safe to drop. This is a
                        # best-effort delete: report it, don't lie about it — if
                        # it fails (AV/indexer lock, remote fs), the publish is
                        # still a success, but the leftover must not go unnoticed.
                        if await asyncio.to_thread(_safe_unlink, staging):
                            return True, None
                        log.warning(
                            f"Published '{task.track_title}' but could not delete "
                            f"the local staging copy at {staging}; left in place "
                            "(best-effort cleanup)."
                        )
                        self.rich_output.console.print(
                            f"[yellow]⚠️  Published, but couldn't remove local "
                            f"staging copy at {staging}[/] {task.track_title}"
                        )
                        return True, staging
                    except OSError as e:
                        task.error_message = f"atomic publish failed: {e}"
                        log.warning(f"{task.error_message} (attempt {replace_attempt+1})")
                        if replace_attempt == 4:
                            _safe_unlink(dest_tmp)
                            return False, staging  # keep staging; prior final untouched
                        await asyncio.sleep(1.0 + replace_attempt)

            # Destination copy is corrupt (e.g. a NAS that corrupts on flush).
            # Drop it and re-copy from the surviving staging.
            task.error_message = err
            log.warning(f"Destination validation failed (attempt {publish_attempt+1}): {err}")
            _safe_unlink(dest_tmp)
            if publish_attempt < 4:
                await asyncio.sleep(1.0 + publish_attempt)

        # Publish exhausted: clean the dest temp, KEEP the local staging.
        _safe_unlink(dest_tmp)
        return False, staging

    async def _download_with_retry(
        self,
        task: DownloadTask,
        urls: list[str],
        task_id: int,
        headers: Optional[dict] = None,
    ) -> bool:
        """
        Downloads a file with automatic retry in case of corruption.
        Validates the file after each download.

        Returns:
            True if download was successful and validated, False if failed after all retries
        """
        from tiddl.core.cancel import is_cancelled

        tmp_path = None
        task.status = DownloadStatus.DOWNLOADING

        while task.can_retry:
            # Cooperative cancel (in-process GUI): stop retrying at once so a
            # cancelled track doesn't burn its whole retry budget with sleeps.
            if is_cancelled():
                return False
            task.increment_attempt()
            attempt = task.attempts

            # Per-attempt reset: bytes_downloaded accumulates inside the chunk
            # loop, so without this a retry keeps the previous attempt's bytes and
            # reports >100% (e.g. 3000+5000 over a 5000-byte file = 160%). Also
            # clear the transient error so a task that succeeds after a retry
            # doesn't keep a stale error_message once it is COMPLETED. The visual
            # bar only needs resetting on a retry (the first attempt starts clean).
            task.bytes_downloaded = 0
            task.error_message = None
            # A stale retained_staging from an earlier call (e.g. this same
            # DownloadTask being retried later by an outer caller) must not
            # survive into a fresh attempt — it's only meaningful as the direct
            # outcome of THIS attempt's publish.
            task.retained_staging = None
            if attempt > 1:
                self.rich_output.download_reset(task_id)

            try:
                # Stage the download on LOCAL disk, then move it to the final
                # destination once complete. Writing directly to a network share
                # (SMB/NAS) across a slow download means hundreds of interleaved
                # ~1 MB writes; when the NAS is IO-saturated (e.g. a concurrent
                # rsync/rescan) those intermittently fail with "[Errno 22] Invalid
                # argument" mid-stream. Staging locally turns it into ONE sequential
                # copy to the share at the end — covered by the move-retry loop
                # below — which a busy NAS tolerates. Fall back to a same-directory
                # temp if the local temp dir can't be used.
                unique_suffix = f".part.{uuid.uuid4().hex[:8]}"
                try:
                    tmp_path = Path(tempfile.gettempdir()) / (
                        f"tiddl-{uuid.uuid4().hex}{task.output_path.suffix}{unique_suffix}"
                    )
                except Exception:
                    tmp_path = task.output_path.with_suffix(
                        task.output_path.suffix + unique_suffix
                    )

                # Download — shared session, per-request headers
                session = self._get_http_session()
                cancelled = False
                async with aiofiles.open(tmp_path, "wb") as f:
                    for url in urls:
                        async with session.get(url, headers=headers) as resp:

                            # 1. Intercept HTTP Status Errors with specific messages
                            if resp.status == 451:
                                raise Exception(f"HTTP 451 Unavailable For Legal Reasons (Geo-block) for {url}")
                            if resp.status == 403:
                                raise Exception(f"HTTP 403 Forbidden (Token expired or Blocked) for {url}")
                            if resp.status != 200:
                                raise Exception(f"HTTP {resp.status} for {url}")

                            # 2. Intercept Invalid Content-Type
                            content_type = resp.headers.get("Content-Type", "").lower()
                            if "application/json" in content_type or "text/" in content_type or "xml" in content_type:
                                # Try to read the error message
                                try:
                                    error_content = await resp.text()
                                    # Truncate if too long
                                    if len(error_content) > 200: error_content = error_content[:200] + "..."
                                    raise Exception(f"Invalid Content-Type '{content_type}' with content: {error_content}")
                                except Exception as read_err:
                                    if "Invalid Content-Type" in str(read_err): raise read_err
                                    raise Exception(f"Invalid Content-Type '{content_type}'")

                            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                                if is_cancelled():
                                    cancelled = True
                                    break
                                await f.write(chunk)
                                task.bytes_downloaded += len(chunk)
                                self.rich_output.download_advance(
                                    task_id, size=len(chunk)
                                )
                        if cancelled:
                            break

                # Cancelled mid-download (in-process GUI use): drop the partial
                # file and bail WITHOUT retrying so the CURRENT track stops now.
                if cancelled:
                    task.status = DownloadStatus.FAILED
                    if tmp_path and tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass
                    return False

                # Publish the downloaded staging to its destination. See
                # _publish_staged for the copy -> fsync -> verify -> atomic-replace
                # contract and its cross-filesystem rationale.
                published, retained = await self._publish_staged(task, tmp_path)

                if published:
                    tmp_path = None  # staging consumed/deleted by the publisher
                    task.status = DownloadStatus.COMPLETED
                    # None unless _publish_staged could not delete the local
                    # staging copy after a successful publish (see its docstring).
                    task.retained_staging = retained
                    if attempt > 1:
                        log.info(f"Successfully downloaded '{task.track_title}' on attempt {attempt}")
                        self.rich_output.console.print(
                            f"[green]✓ Retry successful![/] {task.track_title}"
                        )
                    return True

                if retained is not None:
                    # The download is intact but the DESTINATION could not be
                    # published. Do NOT re-download: keep the local file so it can be
                    # recovered / re-published later, and stop.
                    tmp_path = None  # ownership handed to the retained staging
                    task.status = DownloadStatus.FAILED
                    task.retained_staging = retained
                    log.error(
                        f"Could not publish '{task.track_title}' to destination; kept "
                        f"local copy at {retained} ({task.error_message})"
                    )
                    self.rich_output.console.print(
                        f"[red]❌ Could not publish to destination; kept local copy at "
                        f"{retained}[/] {task.track_title}"
                    )
                    return False

                # The local staging itself was invalid -> re-download.
                tmp_path = None  # already removed by the publisher
                task.status = DownloadStatus.CORRUPTED
                if task.can_retry:
                    self.rich_output.console.print(
                        f"[yellow]⚠️  Corrupt download ({task.error_message}), retrying... "
                        f"({attempt}/{task.max_attempts})[/] {task.track_title}"
                    )
                    await asyncio.sleep(2)
                    task.status = DownloadStatus.DOWNLOADING
                    continue
                else:
                    self.rich_output.console.print(
                        f"[red]❌ Download corrupt after {task.max_attempts} attempts: "
                        f"{task.error_message}[/] {task.track_title}"
                    )
                    task.status = DownloadStatus.FAILED
                    return False

            except Exception as e:
                task.error_message = str(e)
                log.error(f"Download error for '{task.track_title}' (attempt {attempt}): {e}")

                # Clean up the partial local staging from this failed attempt.
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                # NB: never delete task.output_path here. Download errors happen
                # before publishing, so a prior valid final file must survive a
                # failed attempt — only a successful atomic publish replaces it.

                if task.can_retry:
                    self.rich_output.console.print(
                        f"[yellow]⚠️  Download failed, retrying... "
                        f"({attempt}/{task.max_attempts})[/] {task.track_title}"
                    )
                    await asyncio.sleep(2)
                    task.status = DownloadStatus.DOWNLOADING
                    continue
                else:
                    # All attempts failed
                    task.status = DownloadStatus.FAILED
                    self.rich_output.console.print(
                        f"[red]❌ Download failed after {task.max_attempts} attempts[/] {task.track_title}"
                    )
                    return False
        
        return False

    async def download(
        self, item: Union[Track, Video], file_path: Path,
        source_type: str = "ALBUM", source_id: Optional[str] = None,
    ) -> tuple[Union[Path, None], bool]:
        """
        returns
        - Path `item_path` path of existing/downloaded item
        - bool `needs_metadata` — True if the caller should (re)write metadata:
          either the audio was just downloaded, or it was found on disk without
          a confirmed-complete DB record. False only when the DB confirms both
          audio and tags were already fully written on a previous run.
        """
        # Cooperative cancellation for in-process (GUI) use: bail immediately so
        # queued items drain fast. The CLI download command never sets this flag.
        from tiddl.core.cancel import is_cancelled
        if is_cancelled():
            return None, False

        artist_name = item.artist.name if getattr(item, 'artist', None) else "Unknown"
        display_title = f"{artist_name} - {item.title}"

        if not item.allowStreaming:
            self.rich_output.console.print(
                f"[red]Streaming not allowed for[/] {display_title} ({item.id})"
            )
            return None, False

        if isinstance(item, Track) and not getattr(item, "streamReady", True):
            self.rich_output.console.print(
                f"[yellow]Track not yet available for streaming (streamReady=False):[/] {display_title}"
            )
            return None, False

        # Apply video/track filter before any skip_existing logic
        if (isinstance(item, Video) and self.videos_filter == "none") or (
            isinstance(item, Track) and self.videos_filter == "only"
        ):
            log.debug(f"skipping {item.id} due to {self.videos_filter=}")
            return None, False

        if isinstance(item, Track):
            filename = get_existing_track_filename(
                item.audioQuality, self.track_quality, file_path
            )
            vibrant_color = item.album.vibrantColor

        elif isinstance(item, Video):
            filename = file_path.with_suffix(".mp4")
            vibrant_color = item.vibrantColor

        vibrant_color = vibrant_color or "gray"

        # For videos, use video_download_path as scan base when configured
        if isinstance(item, Video) and self.video_download_path:
            existing_file_path = self.video_download_path / filename
        else:
            existing_file_path = self.scan_path / filename

        log.debug(f"{file_path=}, {filename=}, {existing_file_path=}")

        result_message = "[green]Downloaded"

        # --- Fast path: SQLite DB lookup (O(1), no network I/O) ---
        # A DB record is only inserted by the caller *after* metadata is
        # successfully written (see handle_item), so a hit here means media
        # + tags are both confirmed complete — safe to fully skip.
        # Applies to tracks AND videos (handle_item records both types).
        if self.skip_existing:
            db_path = self._db_lookup(item.id)
            if db_path is not None:
                # DB says we downloaded this item.  Do a single stat() to
                # confirm the file still exists (guards against manual deletes).
                try:
                    file_still_exists = await self._is_file_in_cache(db_path)
                except OSError:
                    file_still_exists = False
                if file_still_exists:
                    # Only skip if the file is already in the intended destination
                    # folder. If it was downloaded elsewhere (e.g. a playlist),
                    # still download it to the correct location. Compared against
                    # existing_file_path (absolute; scan/video base) — the old
                    # comparison against the template-relative file_path.parent
                    # never matched, which silently forced a metadata rewrite of
                    # every existing file on each rescan via the dir-scan path.
                    if _normalize_dir(db_path.parent) == _normalize_dir(existing_file_path.parent):
                        self.rich_output.show_item_result(
                            result_message="[yellow]Exists",
                            item_description=f"[{vibrant_color}]{display_title}",
                            item_path=db_path,
                        )
                        return db_path, False
                else:
                    # File is gone — remove stale DB entry and continue to download
                    self._db_remove(item.id)
                    log.debug(f"Item {item.id} was in DB but file missing, re-downloading")

        # --- Fallback: directory scan cache ---
        # Unlike the DB fast-path above, a file found only by scanning disk is
        # NOT a confirmed-complete record — the DB is only inserted (by the
        # caller) after metadata is written, so a file that exists without a
        # DB entry may have been left mid-way (process killed between the
        # download finishing and tags being written). Return True here (not
        # False) so the caller still attempts to (re)write metadata, even
        # though the audio itself doesn't need re-downloading.
        if await self._is_file_in_cache(existing_file_path):
            result_message = "[cyan]Overwritten"

            if self.skip_existing:
                self.rich_output.show_item_result(
                    result_message="[yellow]Exists",
                    item_description=f"[{vibrant_color}]{display_title}",
                    item_path=existing_file_path,
                )
                return existing_file_path, True

        # Check for alternative extensions (e.g. have FLAC, requesting M4A)
        elif self.skip_existing:
            qual_map = {".flac": 2, ".m4a": 1, ".mp4": 1}
            target_score = qual_map.get(filename.suffix, 0)
            stem = existing_file_path.stem

            # Usar stem_index para evitar re-escanear el mismo directorio 3 veces
            existing_exts = self._stem_index.get(stem)
            if existing_exts is None:
                # stem no indexado aún — garantizar que el dir esté escaneado (async)
                await self._scan_directory(existing_file_path.parent)
                existing_exts = self._stem_index.get(stem, set())

            for ext in [".flac", ".m4a", ".mp4"]:
                if ext == filename.suffix or ext not in existing_exts:
                    continue

                found_score = qual_map.get(ext, 0)
                if found_score >= target_score:
                    alt_path = existing_file_path.with_suffix(ext)
                    self.rich_output.show_item_result(
                        result_message="[yellow]Exists (Alt)",
                        item_description=f"[{vibrant_color}]{display_title}",
                        item_path=alt_path,
                    )
                    return alt_path, True

        should_extract_flac = False

        async with self.semaphore:
            # Re-check cancel AFTER acquiring the semaphore. The check at the top of
            # download() runs when the coroutine is first scheduled — with a gather()
            # over many tracks that happens up-front, before the user can click
            # Cancel, so it never fires for queued items. This second check runs the
            # instant each track is about to download, so a mid-run cancel drains the
            # remaining queue fast instead of downloading everything anyway.
            if is_cancelled():
                return None, False
            if isinstance(item, Track):
                # Cap attempts at the quality the USER requested (self.track_quality),
                # then fall back downward only on real stream failures. Do NOT cap by
                # item.audioQuality: TIDAL's track LISTING under-reports it (frequently
                # reports LOSSLESS when HI_RES_LOSSLESS is actually available), which
                # silently prevented downloads in maximum quality.
                quality_score = {"HI_RES_LOSSLESS": 3, "LOSSLESS": 2, "HIGH": 1, "LOW": 0}
                max_score = quality_score.get(self.track_quality, 3)

                # Check for Dolby Atmos
                is_atmos = False
                if item.mediaMetadata:
                    tags = []
                    if isinstance(item.mediaMetadata, dict):
                        tags = item.mediaMetadata.get("tags", [])
                    elif hasattr(item.mediaMetadata, "tags"):
                        tags = item.mediaMetadata.tags
                    if "DOLBY_ATMOS" in tags:
                        is_atmos = True

                if not is_atmos and item.audioModes and "DOLBY_ATMOS" in item.audioModes:
                    is_atmos = True

                attempt_qualities: list[TrackQuality] = ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"]
                # Filter out qualities higher than what the track supports
                attempt_qualities = [q for q in attempt_qualities if quality_score.get(q, 0) <= max_score]

                for _qi, q in enumerate(attempt_qualities):
                    # Cooperative cancel: don't try the next quality tier if the
                    # user cancelled while the previous tier was being fetched.
                    if is_cancelled():
                        return None, False
                    try:
                        # Use asyncio.to_thread to prevent blocking the event loop during retries (sleep)
                        stream = await asyncio.to_thread(self.api.get_track_stream, track_id=item.id, quality=q)
                    except Exception as e:
                        # Check for Asset Not Ready (4005) first to avoid noisy logs
                        try:
                            if hasattr(e, 'response') and e.response is not None:
                                err_json = e.response.json()
                                if err_json.get("subStatus") == 4005:
                                    self.rich_output.console.print(f"[yellow]Skipped '{display_title}' (Asset not ready)[/]")
                                    return None, False
                        except:
                            pass

                        # Catch all exceptions (ApiError, HTTPError, etc.) to allow fallback or skip
                        log.warning(f"Quality '{q}' failed for {item.id}: {e}")
                        self.rich_output.console.print(f"[yellow]⚠ Quality {q} failed: {e}[/]")

                        # FIX: Fail fast on Rate Limit to avoid "Error Could not download..." spam
                        if "429" in str(e) or "Limit" in str(e):
                            self.rich_output.console.print(f"[yellow]Skipped '{display_title}' (Rate Limit)[/]")
                            return None, False

                        continue

                    # Hibrido de 2 tokens: si el primario (HiRes) degrado por debajo
                    # de LOSSLESS (ej. HI_RES_LOSSLESS -> HIGH 320 en un track solo
                    # lossless), pide LOSSLESS al cliente fallback (TV), que SI entrega
                    # el FLAC 16-bit. Headless, sin ventanas. Sustituye el stream.
                    if (self.fallback_api is not None
                            and quality_score.get(stream.audioQuality, 0) < quality_score.get("LOSSLESS", 2)):
                        try:
                            _fb = await asyncio.to_thread(
                                self.fallback_api.get_track_stream, track_id=item.id, quality="LOSSLESS"
                            )
                            if quality_score.get(_fb.audioQuality, 0) > quality_score.get(stream.audioQuality, 0):
                                # Demoted to debug: this per-track line was noise in
                                # normal output. Still visible with `--debug`.
                                log.debug(
                                    f"Fallback LOSSLESS para '{display_title}': "
                                    f"{stream.audioQuality} -> {_fb.audioQuality}"
                                )
                                stream, q = _fb, _fb.audioQuality
                        except Exception as _fe:
                            log.debug(f"fallback lossless fallo {item.id}: {_fe}")

                    # Si TIDAL degrado la entrega POR DEBAJO del siguiente nivel que
                    # ibamos a intentar, no aceptes el downgrade lossy: reintenta
                    # explicitamente en ese nivel. Ej.: HI_RES_LOSSLESS puede volver
                    # como HIGH (320 kbps) en un track solo-lossless; pedir LOSSLESS
                    # entonces entrega el FLAC 16-bit en vez de AAC.
                    if stream.audioQuality != q and _qi + 1 < len(attempt_qualities):
                        _next_q = attempt_qualities[_qi + 1]
                        if quality_score.get(stream.audioQuality, 0) < quality_score.get(_next_q, 0):
                            log.debug(f"{item.id}: {q}->{stream.audioQuality} degradado, reintento en {_next_q}")
                            continue
                    urls, _ = parse_track_stream(stream)
                    # Use stream.audioQuality (actual delivery) not q (requested quality).
                    # TIDAL can downgrade silently; using q would save M4A content as .flac.
                    if stream.audioQuality != q:
                        self.rich_output.console.print(
                            f"[yellow]⚠ TIDAL degraded quality for '{display_title}': "
                            f"requested {q} → got {stream.audioQuality}[/]"
                        )
                    chosen_filename = get_existing_track_filename(item.audioQuality, stream.audioQuality, file_path)

                    # Prepare path for Windows Long Path / UNC
                    download_path = self.download_path / chosen_filename
                    if sys.platform == "win32":
                        download_path = Path(_prepare_long_path(str(download_path.absolute())))

                    quality = track_qualities_color[stream.audioQuality]
                    if is_atmos:
                        quality = "[purple]Dolby Atmos"
                    elif stream.audioQuality in ["HI_RES_LOSSLESS", "LOSSLESS"]:
                        quality = f"{quality} {stream.bitDepth}-bit, {(stream.sampleRate or 0) / 1000:.1f} kHz"
                    should_extract_flac = stream.audioQuality == "HI_RES_LOSSLESS"

                    task_id = self.rich_output.download_start(f"[{vibrant_color}]{display_title} {quality}")

                    download_path.parent.mkdir(exist_ok=True, parents=True)

                    task = DownloadTask(
                        url=urls[0] if urls else "",
                        output_path=download_path,
                        track_id=item.id,
                        track_title=display_title,
                        max_attempts=MAX_RETRIES
                    )

                    download_success = await self._download_with_retry(
                        task=task,
                        urls=urls,
                        task_id=task_id,
                    )
                    if not download_success:
                        task = self.rich_output.download_finish(task_id=task_id)
                        self.rich_output.show_item_result(
                            result_message="[yellow]Failed (Retrying lower quality)",
                            item_description=task.description,
                            item_path=None,
                        )
                        continue
                    try:
                        # audioQuality alone can't be trusted to predict the actual
                        # container anymore — TIDAL now sometimes wraps plain
                        # LOSSLESS in MP4 too, not just HI_RES_LOSSLESS. Sniff the
                        # real bytes on disk for any .flac-named file so it still
                        # gets unwrapped even when audioQuality said otherwise.
                        if not should_extract_flac and download_path.suffix.lower() == ".flac":
                            if await asyncio.to_thread(is_mp4_container, download_path):
                                should_extract_flac = True
                        if should_extract_flac:
                            download_path = await asyncio.to_thread(extract_flac, download_path)
                    except Exception as exc:
                        log.error(f"{should_extract_flac=}, {exc=}")
                        self.rich_output.console.print(
                            f"[red]Error converting format:[/] {display_title} - {exc}"
                        )
                    task = self.rich_output.download_finish(task_id=task_id)
                    self.rich_output.show_item_result(
                        result_message=result_message,
                        item_description=task.description,
                        item_path=download_path,
                    )
                    # DB insert happens in the caller, after metadata is written —
                    # not here. Recording "done" this early meant a process killed
                    # between the download finishing and tags being written left a
                    # file permanently marked complete with no metadata (skip_existing
                    # would never revisit it). See handle_item() in __init__.py.

                    # Report playback event — makes activity look like web player streaming
                    self._spawn_bg(report_playback(
                        headers=dict(self.api.client.session.headers),
                        track_id=item.id,
                        duration=getattr(item, "duration", 240),
                        audio_quality=stream.audioQuality,
                        country_code=self.api.country_code,
                        source_type=source_type,
                        source_id=source_id or (str(item.album.id) if getattr(item, "album", None) else None),
                    ))

                    return download_path, True

                self.rich_output.console.print(
                    f"[red]Error[/] Could not download '{display_title}' in any quality"
                )
                return None, False

            elif isinstance(item, Video):
                attempt_v_qualities: list[StreamVideoQuality] = ["HIGH", "MEDIUM", "LOW"]
                for q in attempt_v_qualities:
                    try:
                        # Run blocking API call in a thread to avoid freezing the event loop
                        stream = await asyncio.to_thread(self.api.get_video_stream, video_id=item.id, quality=q)
                    except (ApiError, HTTPError) as e:
                        log.warning(f"video quality '{q}' failed for {item.id}: {e}")
                        if "429" in str(e) or "Rate" in str(e):
                            self.rich_output.console.print(f"[yellow]Skipped '{display_title}' (Rate Limit)[/]")
                            return None, False
                        continue
                    except Exception as e:
                        log.error(f"Unexpected error for video {item.id} q={q}: {e}")
                        continue

                    quality = video_qualities_color[stream.videoQuality]

                    # Prepare .ts path for Windows Long Path / UNC
                    video_base = self.video_download_path or self.download_path
                    download_path = (video_base / filename).with_suffix(".ts")
                    if sys.platform == "win32":
                        download_path = Path(_prepare_long_path(str(download_path.absolute())))

                    download_path.parent.mkdir(exist_ok=True, parents=True)

                    # Parse M3U8 to get segment URLs (blocking I/O → thread)
                    try:
                        urls = await asyncio.to_thread(parse_video_stream, stream)
                    except Exception as e:
                        log.warning(f"parse_video_stream failed for {item.id} q={q}: {e}")
                        continue

                    task_id = self.rich_output.download_start(f"[{vibrant_color}]{display_title} {quality}")

                    video_task = DownloadTask(
                        url=urls[0] if urls else "",
                        output_path=download_path,
                        track_id=item.id,
                        track_title=display_title,
                        max_attempts=MAX_RETRIES
                    )

                    download_success = await self._download_with_retry(
                        task=video_task,
                        urls=urls,
                        task_id=task_id,
                    )

                    if not download_success:
                        self.rich_output.download_finish(task_id=task_id)
                        if download_path.exists():
                            download_path.unlink()
                        continue

                    # Convert .ts segments → .mp4
                    ts_path = download_path
                    try:
                        download_path = await asyncio.to_thread(convert_to_mp4, download_path)
                    except Exception as e:
                        log.error(f"convert_to_mp4 failed for {item.id}: {e}")
                        self.rich_output.download_finish(task_id=task_id)
                        self.rich_output.show_item_result(
                            result_message="[red]Failed (mp4 conversion)",
                            item_description=display_title,
                            item_path=None,
                        )
                        if ts_path.exists():
                            ts_path.unlink(missing_ok=True)
                        continue

                    finished_task = self.rich_output.download_finish(task_id=task_id)
                    self.rich_output.show_item_result(
                        result_message=result_message,
                        item_description=finished_task.description,
                        item_path=download_path,
                    )
                    # DB insert happens in the caller, after metadata is written —
                    # see handle_item() in __init__.py.

                    self._spawn_bg(report_playback(
                        headers=dict(self.api.client.session.headers),
                        track_id=item.id,
                        duration=getattr(item, "duration", 180),
                        audio_quality=stream.videoQuality,
                        country_code=self.api.country_code,
                        source_type=source_type,
                        source_id=source_id or str(item.id),
                    ))

                    return download_path, True

                self.rich_output.console.print(
                    f"[red]Error[/] Could not download video '{display_title}' in any quality"
                )
                return None, False
