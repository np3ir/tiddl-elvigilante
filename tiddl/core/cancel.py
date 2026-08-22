"""Cooperative cancellation / safety-stop for in-process (GUI) and CLI use.

A stop can come from two places:

* a **user cancel** — the GUI runs the download command in a worker thread, so
  there is no process to kill; it calls ``request_cancel()`` and the download
  orchestration checks ``is_cancelled()`` at its per-item choke points so queued
  items drain fast and the run ends;
* a **run-wide safety stop** tripped by the engine itself — e.g. TIDAL is
  rate-limiting the account so hard that continuing risks a hard block (see
  :mod:`tiddl.core.ratelimit`), or the account got flagged (refresh-blocked
  401). These call ``request_cancel(reason=...)`` so the SAME drain path runs.

Both set one flag; the optional *reason* lets the run's final message explain
WHY it stopped (user vs. rate-limit vs. flagged account). The CLI relies on this
too now: a safety stop must halt a long terminal run, not only an in-process
GUI run.
"""
import threading
from typing import Optional

_event = threading.Event()
_lock = threading.Lock()
_reason: Optional[str] = None


def request_cancel(reason: str = "user") -> None:
    """Signal that the current download should stop.

    The FIRST reason wins: a rate-limit trip that fires just before the user
    also clicks cancel keeps reporting the rate limit (the real cause), and vice
    versa. ``reason`` defaults to ``"user"`` so existing callers are unchanged.
    """
    global _reason
    with _lock:
        if _reason is None:
            _reason = reason
    _event.set()


def clear() -> None:
    """Reset the flag AND the reason before starting a new run."""
    global _reason
    with _lock:
        _reason = None
    _event.clear()


def is_cancelled() -> bool:
    return _event.is_set()


def stop_reason() -> Optional[str]:
    """Why the run stopped — ``"user"``, ``"tidal_rate_limit"``,
    ``"tidal_account_flagged"``, or ``None`` if it did not stop."""
    with _lock:
        return _reason
