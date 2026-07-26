"""Cooperative cancellation for in-process (GUI) use.

The CLI never sets this flag — killing the process is enough there. But when
tiddl runs *inside* another process (e.g. the single-binary GUI, which invokes
the download command in a worker thread), there is no process to kill. The GUI
calls `request_cancel()`, and the download orchestration checks `is_cancelled()`
at its per-item choke point so queued items drain fast and the run ends.
"""
import threading

_event = threading.Event()


def request_cancel() -> None:
    """Signal that the current in-process download should stop."""
    _event.set()


def clear() -> None:
    """Reset the flag before starting a new run."""
    _event.clear()


def is_cancelled() -> bool:
    return _event.is_set()
