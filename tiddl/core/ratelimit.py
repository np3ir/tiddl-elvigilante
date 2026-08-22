"""Process-wide rate-limit circuit breaker.

Every download task — and BOTH the main and the fallback ``TidalAPI`` — share
ONE guard, so the 429s they each see are counted together for the whole run.
Each strike is a full ``429`` that already cost its mandatory ``Retry-After``
wait, so a run that accumulates a dozen of them is being actively and
repeatedly throttled by TIDAL. Pushing further risks escalating a soft
rate-limit into a hard account block (the failure the user actually hit on a
giant playlist-expanded-to-artists run). At that point the safe move is to trip
a run-wide cooperative stop and let the user resume later — ``skip_existing`` +
``max_tracks_per_session`` make resuming cheap — rather than let thousands of
queued tasks keep hammering.

The guard only COUNTS and decides; it never sleeps and never cancels on its own.
The caller (``TidalAPI._fetch_with_retry``) turns a trip into the actual
cooperative stop via :mod:`tiddl.core.cancel`, keeping this module free of any
dependency on the download/cancel machinery. Reset once per ``tiddl download``
invocation.
"""
from __future__ import annotations

import threading
from typing import Optional

# 429 strikes tolerated in a single run before the breaker trips. Each strike is
# a full 429 (with its Retry-After wait already paid), so this many means TIDAL
# is throttling the run hard. Deliberately generous so a handful of transient
# 429s never aborts a legitimate long run.
DEFAULT_STRIKE_LIMIT = 12


class RateLimitGuard:
    """Thread-safe 429 strike counter with a one-shot trip.

    ``note_rate_limited`` returns ``True`` exactly once — on the call that
    crosses the limit — so the caller trips the cooperative stop a single time.
    """

    def __init__(self, strike_limit: int = DEFAULT_STRIKE_LIMIT) -> None:
        self._lock = threading.Lock()
        self._strike_limit = strike_limit
        self._strikes = 0
        self._tripped = False

    def reset(self, strike_limit: Optional[int] = None) -> None:
        """Clear the counter before a new run (optionally re-arm the limit)."""
        with self._lock:
            self._strikes = 0
            self._tripped = False
            if strike_limit is not None and strike_limit > 0:
                self._strike_limit = strike_limit

    def note_rate_limited(self) -> bool:
        """Record one 429. Return ``True`` on the single call that trips the
        breaker; ``False`` before the limit and on every call after the trip."""
        with self._lock:
            self._strikes += 1
            if self._strikes >= self._strike_limit and not self._tripped:
                self._tripped = True
                return True
            return False

    @property
    def strikes(self) -> int:
        with self._lock:
            return self._strikes

    @property
    def strike_limit(self) -> int:
        with self._lock:
            return self._strike_limit

    @property
    def tripped(self) -> bool:
        with self._lock:
            return self._tripped


_guard = RateLimitGuard()


def guard() -> RateLimitGuard:
    """The shared, process-wide guard."""
    return _guard
