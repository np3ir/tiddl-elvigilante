"""Per-run shared request budget.

ONE throttle, shared by every client_id of a single :class:`ContextObject`, so
the TV and HiRes clients *together* cannot exceed the configured
``requests_per_minute``. It is created by the ``ContextObject`` and injected into
each client — deliberately **NOT** process-global:

* a new run/context gets a fresh budget, so a prior run cannot contaminate the
  next;
* state cleanup after Cancel / 401 / 429 is trivial (drop the context);
* two independent contexts can coexist in one process;
* tests are deterministic (inject a fake clock);
* the reusable in-process GUI host accrues no extra global state.

Only a **real HTTP request** consumes budget, and the client enforces that by
*peeking the cache first*: a true cache hit returns before :meth:`throttle` is
ever called, so it pays no spacing. There is deliberately **no** "refund" that
moves the spacing clock backward — in concurrent use that could roll back a slot
another thread had already reserved and let a later request burst past the RPM.
A conditional revalidation that comes back ``304`` is a genuine network
round-trip, so it correctly keeps the slot it throttled for. A 429 retry is a
real request too and consumes budget again (and still counts for the run-wide
429 circuit breaker, which is a separate last-resort protection).
"""
from __future__ import annotations

import random
import threading
import time as _time
from typing import Callable, Optional


class SharedRequestBudget:
    """Shared fixed-interval throttle for the combined TV + HiRes traffic of one run.

    ``TV requests + HiRes requests`` are spaced at ``60 / requests_per_minute``
    seconds, so their aggregate rate stays at or below the configured RPM.
    """

    def __init__(
        self,
        requests_per_minute: int = 50,
        *,
        clock: Optional[Callable[[], float]] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        jitter: Optional[Callable[[], float]] = None,
    ) -> None:
        rpm = requests_per_minute if requests_per_minute > 0 else 50
        self._interval = 60.0 / rpm
        self._lock = threading.Lock()
        # -inf so the FIRST request of a run never waits (nothing precedes it),
        # matching the previous per-client behaviour where a 0 timestamp vs a
        # large wall clock left the first request un-throttled.
        self._last = float("-inf")
        # Injectable for deterministic tests; default to real monotonic time.
        self._clock = clock or _time.monotonic
        self._sleep = sleeper or _time.sleep
        self._jitter = jitter if jitter is not None else (lambda: random.uniform(0, 0.3))
        # Count of real HTTP requests admitted (cache hits excluded). For tests
        # and inspection; the combined TV+HiRes total of this run.
        self.request_count = 0

    @property
    def interval(self) -> float:
        return self._interval

    def throttle(self) -> None:
        """Block until a real HTTP request may proceed under the SHARED interval.

        Call exactly once immediately before a real network request — never for
        a cache hit.
        """
        with self._lock:
            now = self._clock()
            wait = self._interval - (now - self._last) + self._jitter()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            self.request_count += 1
