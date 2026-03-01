from __future__ import annotations
import os
import hashlib
import logging
from pathlib import Path
from typing import Optional, Union, Tuple, NamedTuple

log = logging.getLogger(__name__)

class IntegrityResult(NamedTuple):
    is_valid: bool
    message: Optional[str] = None

class FileIntegrityChecker:
    """
    Centralized module for file integrity verification.
    Supports Magic Bytes, Size, and Hash checks.
    """

    @staticmethod
    def _check_magic_bytes(header: bytes, ext: str) -> bool:
        """Verifies magic bytes based on extension"""
        if len(header) < 4:
            return False
        
        if ext == '.flac':
            # FLAC files MUST start with "fLaC"
            return header.startswith(b'fLaC')
        elif ext in ['.mp4', '.m4a', '.m4v']:
            # MP4 container usually has 'ftyp' at index 4
            return len(header) >= 8 and header[4:8] == b'ftyp'
        
        # Assume valid for other extensions to avoid blocking unknown formats
        return True

    @staticmethod
    def quick_check(file_path: Union[str, Path]) -> bool:
        """Quick synchronous Magic Bytes check"""
        path = Path(file_path)
        if not path.exists() or path.stat().st_size < 2048:
            return False
        
        try:
            with open(path, "rb") as f:
                header = f.read(12)
                return FileIntegrityChecker._check_magic_bytes(header, path.suffix.lower())
        except Exception:
            return False

    @staticmethod
    def verify_file(
        file_path: Union[str, Path],
        expected_size: Optional[int] = None,
        expected_hash: Optional[str] = None,
        hash_algorithm: str = "md5",
        strict: bool = False
    ) -> IntegrityResult:
        """
        Complete synchronous verification.
        
        Args:
            file_path: Path to the file
            expected_size: Expected size in bytes
            expected_hash: Expected hash (hexdigest)
            hash_algorithm: Hash algorithm (md5, sha256, etc.)
            strict: If True, performs stricter checks (e.g., moov atom)
        """
        path = Path(file_path)
        if not path.exists():
            return IntegrityResult(False, "File not found")

        # 1. Size Check
        try:
            file_size = path.stat().st_size
        except OSError:
            return IntegrityResult(False, "Cannot read file stats")

        if expected_size is not None and expected_size > 0:
            if file_size != expected_size:
                return IntegrityResult(False, f"Size mismatch: expected {expected_size}, got {file_size}")
        
        if file_size < 2048:
            return IntegrityResult(False, "File too small (< 2KB)")

        # 2. Magic Bytes & Structure Check
        try:
            with open(path, "rb") as f:
                header = f.read(12)
                ext = path.suffix.lower()
                if not FileIntegrityChecker._check_magic_bytes(header, ext):
                    return IntegrityResult(False, f"Invalid magic bytes for {ext}")
                
                # MP4 'moov' check
                if strict and ext in ['.mp4', '.m4a', '.m4v']:
                    # Check first 256KB for moov atom (optimized for faststart)
                    f.seek(0)
                    chunk = f.read(262144)
                    if b'moov' not in chunk:
                         # If strict, we require moov at start
                         return IntegrityResult(False, "Missing 'moov' atom in header (faststart required)")
        except Exception as e:
            return IntegrityResult(False, f"Read error: {e}")

        # 3. Hash Check
        if expected_hash:
            try:
                hash_func = getattr(hashlib, hash_algorithm)()
                with open(path, "rb") as f:
                    # Read in 64KB chunks
                    for chunk in iter(lambda: f.read(65536), b""):
                        hash_func.update(chunk)
                calculated_hash = hash_func.hexdigest()
                if calculated_hash.lower() != expected_hash.lower():
                    return IntegrityResult(False, f"Hash mismatch: expected {expected_hash}, got {calculated_hash}")
            except AttributeError:
                 return IntegrityResult(False, f"Unsupported hash algorithm: {hash_algorithm}")
            except Exception as e:
                return IntegrityResult(False, f"Hashing error: {e}")

        return IntegrityResult(True, "Valid")

def validate_downloaded_file(
    file_path: Union[str, Path],
    expected_size: Optional[int] = None,
    strict: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Helper para validar archivo descargado.
    Retorna (is_valid, error_message).
    """
    res = FileIntegrityChecker.verify_file(file_path, expected_size=expected_size, strict=strict)
    return res.is_valid, res.message
