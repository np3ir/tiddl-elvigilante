"""Opt-in resume checkpoint for long download runs.

A giant run (a playlist expanded into every artist's discography) that a
rate-limit safety-stop or Ctrl-C interrupts is expensive to restart: even with
``skip_existing``, the engine RE-ENUMERATES every artist (``get_artist_albums``
+ ``get_album_items`` per album) just to discover there is nothing left to
download — the same API storm that risks re-tripping the rate limit. With
``--resume``, resources fully processed in a prior run of the SAME job are
skipped before any API call.

Scope & trust:

* Keyed by a **signature** of the job — its requested resources plus the options
  that change what "done" means (destination, quality, audio mode, expansion,
  exclude filters, singles). A different job or different options → a different
  checkpoint, so runs never contaminate each other.
* It **trusts the checkpoint over the filesystem**: a resource marked done is
  skipped without re-checking files. If you deleted files or want a full
  re-verify, run WITHOUT ``--resume``.
* A resource is marked done only on a **clean, error-free completion** of that
  resource, so a resource that hit an error is retried on the next ``--resume``
  run. (A per-item failure swallowed *inside* a resource — e.g. one geo-blocked
  album within an artist — is the documented exception: it does not un-mark the
  resource; run without ``--resume`` to retry those.)

The checkpoint lives at ``TIDDL_PATH/resume/<signature>.json`` and every write is
best-effort — a failed checkpoint write must never break a download.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Optional


def _base_dir() -> Path:
    base = os.environ.get("TIDDL_PATH") or str(Path.home() / ".tiddl")
    return Path(base) / "resume"


def compute_signature(fields: dict) -> str:
    """A stable short hex digest over the job-identity ``fields``.

    ``sort_keys`` makes it order-independent, so the same job always maps to the
    same checkpoint regardless of dict insertion order."""
    blob = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def resource_key(resource) -> str:
    """Stable identity for a resource: ``"<type>/<id>"``."""
    return f"{resource.type}/{resource.id}"


def job_signature(
    *,
    resources,
    download_path,
    video_download_path,
    quality,
    video_quality,
    audio_mode,
    edition_match,
    quality_policy,
    hires_client,
    expand,
    exclude_compilations,
    exclude_live_albums,
    singles,
    videos_filter,
    templates,
    metadata,
    cover_file,
    m3u,
) -> str:
    """Signature of EVERYTHING that changes what a `--resume` resource produces on
    disk — its selection, content, embedded metadata, standalone files, paths and
    names. Changing any of these must start a fresh checkpoint rather than skip a
    resource completed under the old settings. Grouped dicts (``templates``,
    ``metadata``, ``cover_file``, ``m3u``) let callers pass the whole sub-config;
    callers pre-sort any set-like ``allowed`` lists so the hash is stable."""
    fields = {
        "resources": sorted(str(r) for r in resources),
        # destinations
        "download_path": str(download_path or ""),
        "video_download_path": str(video_download_path or ""),
        # selection + content
        "quality": quality,
        "video_quality": video_quality,
        "audio_mode": audio_mode,
        "edition_match": edition_match,
        "quality_policy": quality_policy,
        "hires_client": hires_client,
        "expand": expand,
        "exclude_compilations": bool(exclude_compilations),
        "exclude_live_albums": bool(exclude_live_albums),
        "singles": singles,
        "videos_filter": videos_filter,
        # names + written outputs
        "templates": dict(templates),
        "metadata": dict(metadata),
        "cover_file": dict(cover_file),
        "m3u": dict(m3u),
    }
    return compute_signature(fields)


class ResumeLog:
    """Persistent set of completed resource keys for one job signature."""

    def __init__(self, signature: str, base_dir: Optional[Path] = None) -> None:
        self.signature = signature
        self._dir = Path(base_dir) if base_dir is not None else _base_dir()
        self._path = self._dir / f"{signature}.json"
        self._done: set[str] = set()

    def load(self) -> "ResumeLog":
        """Read any prior checkpoint for this signature (missing/corrupt = empty)."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            done = data.get("completed", [])
            self._done = {str(k) for k in done} if isinstance(done, list) else set()
        except (FileNotFoundError, ValueError, OSError):
            self._done = set()
        return self

    def is_done(self, key: str) -> bool:
        return key in self._done

    def mark_done(self, key: str) -> None:
        if key in self._done:
            return
        self._done.add(key)
        self._persist()

    def mark_many(self, keys: Iterable[str]) -> None:
        new = {str(k) for k in keys} - self._done
        if not new:
            return
        self._done |= new
        self._persist()

    def clear(self) -> None:
        self._done = set()
        try:
            self._path.unlink()
        except OSError:
            pass

    @property
    def count(self) -> int:
        return len(self._done)

    def _persist(self) -> None:
        # Best-effort atomic write: a failed checkpoint write must never break a
        # download, and a crash mid-write must not corrupt the existing file.
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {"signature": self.signature, "completed": sorted(self._done)},
                    indent=0,
                ),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except OSError:
            pass
