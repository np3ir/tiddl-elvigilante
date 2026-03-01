from __future__ import annotations
import os
import sys
import time
import select
import logging
from pathlib import Path
from requests import Session
from typing import Optional, List, Tuple
from tqdm import tqdm

from tiddl.cli.const import APP_PATH
from tiddl.core.api.models import TrackStream, VideoStream
from .parse import parse_track_stream, parse_video_stream
from .integrity import FileIntegrityChecker, validate_downloaded_file
from .metrics import MetricsCollector

log = logging.getLogger(__name__)

METRICS_COLLECTOR = MetricsCollector(APP_PATH / "metrics.jsonl")

def check_escape_key_pressed() -> bool:
    """Detecta ESC multiplataforma"""
    if sys.platform == 'win32':
        import msvcrt
        if msvcrt.kbhit():
            return msvcrt.getch() == b'\x1b'
    else:
        # Unix/Linux/Mac
        if select.select([sys.stdin], [], [], 0)[0]:
            key = sys.stdin.read(1)
            return key == '\x1b'
    return False

def is_valid_media_container(path: str) -> bool:
    """
    Enhanced validation using FileIntegrityChecker
    """
    return FileIntegrityChecker.quick_check(Path(path))

def download(urls: List[str], output_path: Optional[str] = None, log_metrics: bool = True) -> Optional[bytes]:
    """
    Downloads content with Universal Validation (FLAC + MP4).
    """
    TIMEOUT_SECONDS = 20
    file_created = False
    start_time = time.time()

    try:
        with Session() as s:
            # =========================================================
            # MODE 1: Download to File (Videos or Tracks saved directly)
            # =========================================================
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                with open(output_path, "wb") as f:
                    file_created = True
                    for url in urls:
                        with s.get(url, stream=True, timeout=TIMEOUT_SECONDS) as req:
                            req.raise_for_status()
                            for chunk in req.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)

                                # --- ESC KEY DETECTOR ---
                                if check_escape_key_pressed():
                                    print("\n⏭️ MANUAL SKIP (ESC)...")
                                    raise TimeoutError("User pressed ESC.")
                                # ------------------------

                # --- UNIVERSAL INTEGRITY CHECK ---
                if os.path.exists(output_path):
                    # Update to use validate_downloaded_file
                    is_valid, error_msg = validate_downloaded_file(
                        output_path,
                        expected_size=None,  # Puedes pasar Content-Length si lo obtienes
                        strict=False
                    )

                    if log_metrics:
                        try:
                            file_size = os.path.getsize(output_path)
                            download_time = time.time() - start_time
                            METRICS_COLLECTOR.log_download(
                                file_path=output_path,
                                file_size=file_size,
                                download_time=download_time,
                                retries=0,
                                integrity_check=is_valid
                            )
                        except Exception:
                            pass

                    if not is_valid:
                        raise ValueError(f"File integrity check failed: {error_msg}")

                return None

            # =========================================================
            # MODE 2: Download to Memory (Buffer)
            # =========================================================
            else:
                stream_data = b""
                for url in urls:
                    req = s.get(url, stream=True, timeout=TIMEOUT_SECONDS)
                    req.raise_for_status()
                    for chunk in req.iter_content(chunk_size=8192):
                        if chunk:
                            stream_data += chunk

                        if check_escape_key_pressed():
                            print("\n⏭️ MANUAL SKIP (ESC)...")
                            raise TimeoutError("User pressed ESC.")
                
                # Basic size validation for memory streams
                if len(stream_data) < 2048:
                     raise ValueError(f"Stream corrupt: Insufficient data ({len(stream_data)} bytes).")

                return stream_data

    except Exception as e:
        # CLEANUP: Delete the bad file immediately
        if output_path and file_created and os.path.exists(output_path):
            try:
                log.info(f"Removing invalid file: {output_path}")
                os.remove(output_path)
            except OSError:
                pass 

        if "ESC" in str(e): raise e
        if "Read timed out" in str(e): log.warning("Download timed out.")
        
        log.error(f"Download error: {e}")
        raise e


def download_with_verification(
    urls: List[str],
    output_path: str,
    expected_hash: Optional[str] = None
) -> None:
    """Download with hash verification"""
    
    # Descargar archivo
    download(urls, output_path)
    
    # Verificar integridad
    result = FileIntegrityChecker.verify_file(
        Path(output_path),
        expected_hash=expected_hash,
        hash_algorithm="md5",
        strict=False
    )
    
    if not result.is_valid:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise ValueError(f"Downloaded file failed integrity check: {result.message}")
    
    log.info(f"✅ File verified: {result.message}")


def download_with_retry(
    urls: List[str],
    output_path: str,
    max_retries: int = 3,
    backoff_factor: float = 2.0
) -> None:
    """
    Download with automatic retry and exponential backoff
    
    Args:
        urls: List of URLs
        output_path: Output path
        max_retries: Maximum number of retries
        backoff_factor: Growth factor for delay (2.0 = doubles each time)
    """
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            download(urls, output_path, log_metrics=False)
            
            # Verify integrity
            is_valid, error = validate_downloaded_file(output_path)
            
            if is_valid:
                log.info(f"✅ Download successful on attempt {attempt + 1}")
                
                # Log metrics here to capture retries
                try:
                    file_size = os.path.getsize(output_path)
                    download_time = time.time() - start_time
                    METRICS_COLLECTOR.log_download(
                        file_path=output_path,
                        file_size=file_size,
                        download_time=download_time,
                        retries=attempt,
                        integrity_check=True
                    )
                except Exception:
                    pass

                return
            else:
                # Corrupted file, retry
                log.warning(f"⚠️  File corrupted ({error}), retrying...")
                if os.path.exists(output_path):
                    os.remove(output_path)
                
                if attempt < max_retries - 1:
                    delay = backoff_factor ** attempt  # 1s, 2s, 4s, 8s...
                    log.info(f"Waiting {delay}s before retry...")
                    time.sleep(delay)
                    continue
                else:
                    raise ValueError(f"Download failed after {max_retries} attempts: {error}")
        
        except Exception as e:
            if "ESC" in str(e):
                raise  # Do not retry if user cancelled
            
            if attempt < max_retries - 1:
                delay = backoff_factor ** attempt
                log.warning(f"⚠️  Download failed (attempt {attempt + 1}/{max_retries}): {e}")
                log.info(f"Retrying in {delay}s...")
                time.sleep(delay)
            else:
                log.error(f"❌ Download failed after {max_retries} attempts")
                raise


def download_with_progress(
    urls: List[str],
    output_path: str,
    description: str = "Downloading"
) -> None:
    """Download con barra de progreso"""
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    start_time = time.time()
    
    with Session() as s:
        with open(output_path, "wb") as f:
            for url in urls:
                with s.get(url, stream=True, timeout=20) as req:
                    req.raise_for_status()
                    
                    # Get total size
                    total_size = int(req.headers.get('content-length', 0))
                    
                    # Crear barra de progreso
                    with tqdm(
                        total=total_size,
                        unit='B',
                        unit_scale=True,
                        desc=description,
                        ncols=80
                    ) as pbar:
                        for chunk in req.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
    
    # Verify after downloading
    is_valid, error = validate_downloaded_file(output_path)

    # Log metrics
    try:
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            download_time = time.time() - start_time
            METRICS_COLLECTOR.log_download(
                file_path=output_path,
                file_size=file_size,
                download_time=download_time,
                retries=0,
                integrity_check=is_valid
            )
    except Exception:
        pass

    if not is_valid:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise ValueError(f"File verification failed: {error}")


def get_track_stream_data(track_stream: TrackStream) -> Tuple[bytes, str]:
    urls, file_extension = parse_track_stream(track_stream)
    stream_data = download(urls)
    return stream_data, file_extension


def get_video_stream_data(video_stream: VideoStream, output_path: str) -> None:
    urls = parse_video_stream(video_stream)
    download(urls, output_path=output_path)
    return None
