from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class SessionTrackLimit:
    """Per-run gate for ``max_tracks_per_session`` with an ATOMIC reservation.

    **The concurrency problem it solves.** Tracks download concurrently. A naive
    "check a counter in ``admit()``, bump it after the download finishes" lets
    several tasks pass the check at once (all see ``downloaded < limit``) and
    overshoot the cap. So the cap is enforced with a per-track reservation:

        admitted = await reserve()   # takes a slot up front (or waits / is rejected)
        path, new = await download()
        commit() if new else release()   # a real download keeps the slot; an
                                         # existing file gives it back

    **Invariant:** ``downloaded + reserved <= limit`` at all times. ``reserve``
    only takes a slot while ``downloaded + reserved < limit``; when every slot is
    reserved it WAITS, and a ``release`` (an existing file, or a cancelled/errored
    task) wakes one waiter so it can take the freed slot. Once ``downloaded``
    reaches ``limit`` the cap is latched (:attr:`reached`) and every pending
    waiter is woken to be rejected — a run-wide stop signal DISTINCT from
    Cancel/401/429 (the run still exits 0).

    **What counts (defined):** only a NEW download (``commit``) consumes the cap;
    an already-present file (``release``) does not, and a waiter proceeds in its
    place — so a run over a mostly-downloaded library keeps making progress on
    the genuinely-missing tracks.

    **Thread-safety.** asyncio is single-threaded; every counter read-modify-write
    below happens WITHOUT an ``await`` in between (the only await is a waiter
    parking on its own future), so the counters are never seen half-updated by
    another task. This is the same discipline ``asyncio.Semaphore`` uses — a
    future-based wait list, not an unguarded counter shared across ``await``s.
    """

    limit: int
    downloaded: int = 0
    reserved: int = 0
    reached: bool = False
    announced: bool = False
    _waiters: "list[asyncio.Future]" = field(default_factory=list, repr=False)

    def is_enabled(self) -> bool:
        return self.limit > 0

    def is_reached(self) -> bool:
        """Run-wide 'quota used up' signal. Monotonic once set."""
        return self.reached

    async def reserve(self) -> bool:
        """Take a slot for ONE track before downloading it.

        Returns ``True`` if admitted (a slot was reserved — the caller MUST later
        ``commit`` or ``release`` it), ``False`` if the cap is already used up.
        Blocks while every remaining slot is reserved but not yet resolved, and
        resumes when a ``release`` frees one or the cap is reached (then rejects).
        """
        if self.limit <= 0:
            return True  # unlimited: no reservation needed
        while True:
            if self.downloaded >= self.limit:
                return False  # cap used up — reject (already latched by commit)
            if self.downloaded + self.reserved < self.limit:
                self.reserved += 1  # atomic: no await between the check and here
                return True
            # Every slot is reserved (in flight). Wait for a release or the latch.
            fut = asyncio.get_running_loop().create_future()
            self._waiters.append(fut)
            try:
                await fut
            except asyncio.CancelledError:
                if fut in self._waiters:
                    # Cancelled BEFORE being woken: just drop out of the queue.
                    self._waiters.remove(fut)
                elif self.downloaded + self.reserved < self.limit:
                    # Cancelled AFTER a release woke us but BEFORE we reserved: we
                    # consumed a wakeup we can't use while a slot is still free. Pass
                    # it on to the next waiter, or the freed slot is orphaned and the
                    # remaining waiters deadlock. (Same re-wake asyncio.Lock does.)
                    self._wake_one()
                raise
            # woken: re-check from the top

    def commit(self) -> bool:
        """Confirm the reserved slot was a REAL new download.

        Returns ``True`` iff THIS commit is the one that reached the cap and the
        "limit reached" warning should be printed now — immediately, without
        depending on a later track ever calling :meth:`reserve`."""
        if self.limit <= 0:
            return False
        self.reserved -= 1
        self.downloaded += 1
        if self.downloaded >= self.limit:
            self.reached = True
            announce = self._announce()
            self._wake_all()  # reject every pending waiter; stop the dispatcher
            return announce
        return False

    def release(self) -> None:
        """Give the reserved slot back WITHOUT counting it — an already-present
        file, or a cancelled/errored task. Synchronous (never awaits), so it can
        run safely from an ``except``/``finally`` during cancellation. Wakes one
        waiter so it can take the freed slot."""
        if self.limit <= 0:
            return
        self.reserved -= 1
        self._wake_one()

    def _announce(self) -> bool:
        if not self.announced:
            self.announced = True
            return True
        return False

    def _wake_one(self) -> None:
        while self._waiters:
            fut = self._waiters.pop(0)
            if not fut.done():
                fut.set_result(None)
                return

    def _wake_all(self) -> None:
        waiters, self._waiters = self._waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(None)
