from __future__ import annotations
import requests
import time

from pathlib import Path
from logging import getLogger
from requests.exceptions import RequestException

log = getLogger(__name__)


class CoverDataNotPrefetched(Exception):
    """Raised by `Cover.write_prefetched()` when called with no data
    already fetched. `write_prefetched()` must never perform network I/O
    itself (implementation-audit finding, 2026-08-18, P1 #2) — a caller
    that needs a guarded, network-free write must fetch first and is
    expected to check the result before calling this."""


class Cover:
    uid: str
    url: str
    data: bytes | None

    def __init__(self, uid: str, size=1280) -> None:
        self.uid = uid

        if size > 1280:
            log.warning(f"can not set cover size higher than 1280 (user set: {size})")
            size = 1280

        formatted_uid = uid.replace("-", "/")

        self.url = (
            f"https://resources.tidal.com/images/{formatted_uid}/{size}x{size}.jpg"
        )

        self.data = None

    def _get_data(self) -> bytes:
        # Already fetched — reuse so album-level prefetch is shared per track
        if self.data is not None:
            return self.data

        retries = 3
        for attempt in range(retries):
            try:
                req = requests.get(self.url, timeout=20)

                if req.status_code != 200:
                    if 500 <= req.status_code < 600:
                         # Force retry on server errors
                         raise RequestException(f"Server error {req.status_code}")

                    log.error(f"could not download cover. ({req.status_code}) {self.url}")
                    return b""

                log.debug(f"got cover {self.url}")
                self.data = req.content
                return self.data

            except RequestException as e:
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 2
                    log.warning(f"Network error downloading cover from {self.url}: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    log.warning(f"Network error downloading cover from {self.url}: {e}")
                    return b""
            except Exception as e:
                log.warning(f"Failed to download cover from {self.url}: {e}")
                return b""
        return b""

    def save_to_directory(self, path: Path):
        file = path.with_suffix(".jpg")

        if file.exists():
            log.debug(f"cover exists ({file})")
            return

        if not self.data:
            self.data = self._get_data()

        if not self.data:
            log.warning(f"no cover data available, skipping write for {file}")
            return

        self.write_prefetched(path)

    def write_prefetched(self, path: Path) -> None:
        """The pure mutation half of `save_to_directory`, split out so a
        caller that needs to run a check immediately before the write (e.g.
        a destination-identity guard) can fetch `self.data` well ahead of
        time and call this with no network I/O in between — a network fetch
        between a passing check and the actual write would otherwise widen
        the check-to-write window by however long the fetch's retry backoff
        took (implementation-audit finding, 2026-08-18, P1 #3).

        This method NEVER performs network I/O — it does not call
        `_get_data()` under any circumstance. An earlier version had a
        "defensive" fallback (`if not self.data: self.data =
        self._get_data()`) that looked harmless but was NOT: `_get_data()`
        returns `b""` on a network/HTTP failure WITHOUT ever assigning
        `self.data`, so `not self.data` stayed True and every legitimately-
        empty first fetch triggered a second network fetch here — silently
        reopening the exact check-to-write race this split was meant to
        close (second implementation-audit finding, 2026-08-18, P1 #2).
        Raises `CoverDataNotPrefetched` instead if `self.data` isn't
        already a non-empty `bytes` — a programming-error signal to the
        caller, never a silent no-op or a silent fetch.
        """
        file = path.with_suffix(".jpg")

        if file.exists():
            log.debug(f"cover exists ({file})")
            return

        if not self.data:
            raise CoverDataNotPrefetched(
                "write_prefetched() requires self.data to already be "
                "populated with a non-empty fetch result — it will not "
                "fetch it itself. Call _get_data() (or set .data directly) "
                "and check the result before calling this."
            )

        file.parent.mkdir(parents=True, exist_ok=True)

        try:
            file.write_bytes(self.data)
        except FileNotFoundError as e:
            log.error(f"could not save cover. {file} -> {e}")
