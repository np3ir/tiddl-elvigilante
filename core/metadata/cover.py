from __future__ import annotations
import requests
import time

from pathlib import Path
from logging import getLogger
from requests.exceptions import RequestException

log = getLogger(__name__)


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
                return req.content

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

        file.parent.mkdir(parents=True, exist_ok=True)

        try:
            file.write_bytes(self.data)
        except FileNotFoundError as e:
            log.error(f"could not save cover. {file} -> {e}")
