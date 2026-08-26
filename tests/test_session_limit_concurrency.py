"""`max_tracks_per_session` must hold EXACTLY under concurrency.

The earlier design bumped the counter after the download finished, so several
concurrent tasks could all pass the check and overshoot the cap. The fix is an
atomic per-track reservation on `SessionTrackLimit`:

    admitted = await reserve()          # takes a slot up front (or waits / rejects)
    path, new = await download()
    commit() if new else release()      # new keeps the slot; existing gives it back

These tests pin the invariant `downloaded + reserved <= limit`, that existing
files don't consume the cap while a waiter takes their freed slot, the immediate
one-shot warning on the reaching commit, and clean release on cancel/error.
"""
from __future__ import annotations

import asyncio

import pytest

from tiddl.cli.commands.download import _resource_resume_done
from tiddl.core.download_policy import SessionTrackLimit


async def _process(limit, track, observed_max):
    """Mirror handle_item for ONE track: reserve -> download -> commit/release.

    `track` is ("new"|"existing"|"error", id). Returns (outcome, id, announced)."""
    admitted = await limit.reserve()
    if not admitted:
        return ("rejected", track[1], False)
    # Probe the invariant while THIS task holds its reservation (no await between
    # reserve() returning and here, so the sample is consistent).
    observed_max[0] = max(observed_max[0], limit.downloaded + limit.reserved)
    await asyncio.sleep(0)  # yield so tasks genuinely interleave
    kind = track[0]
    if kind == "error":
        limit.release()     # handle_item's except path frees the reservation
        return ("error", track[1], False)
    if kind == "existing":
        limit.release()     # already on disk: slot back, no charge
        return ("existing", track[1], False)
    announced = limit.commit()          # a real new download
    return ("downloaded", track[1], announced)


async def _run(limit_value, tracks):
    limit = SessionTrackLimit(limit=limit_value)
    observed_max = [0]
    results = await asyncio.gather(
        *[_process(limit, t, observed_max) for t in tracks]
    )
    return limit, results, observed_max[0]


async def test_limit3_concurrency5_five_new_tracks_exactly_three_downloads():
    # 1. Limit 3, concurrency 5, five NEW tracks -> exactly 3 downloads.
    limit, results, mx = await _run(3, [("new", i) for i in range(5)])
    downloads = [r for r in results if r[0] == "downloaded"]
    assert len(downloads) == 3
    assert limit.downloaded == 3
    assert mx <= 3                                   # never exceeded the cap
    assert limit.reserved == 0                       # everything settled
    assert limit.is_reached()
    assert sum(1 for _, _, announced in results if announced) == 1  # warned once


async def test_limit3_concurrency5_existing_tracks_do_not_consume_quota():
    # 2. Limit 3, concurrency 5, several EXISTING tracks -> three NEW downloads,
    #    and the existing ones do not consume the quota.
    tracks = [("existing", "e1"), ("existing", "e2"),
              ("new", "n1"), ("new", "n2"), ("new", "n3")]
    limit, results, mx = await _run(3, tracks)
    downloaded_ids = {r[1] for r in results if r[0] == "downloaded"}
    assert downloaded_ids == {"n1", "n2", "n3"}      # exactly the 3 new tracks
    assert limit.downloaded == 3
    assert mx <= 3
    assert not (downloaded_ids & {"e1", "e2"})       # no existing track counted


async def test_waiter_proceeds_when_another_track_turns_out_existing():
    # 3(a). A waiting NEW task must proceed when another track releases (existing).
    #       Limit 1: the existing track frees its slot for a waiting new track.
    limit, results, mx = await _run(1, [("existing", "e1"), ("new", "n1"), ("new", "n2")])
    downloads = [r for r in results if r[0] == "downloaded"]
    assert len(downloads) == 1                       # exactly one new download
    assert limit.downloaded == 1
    assert mx <= 1
    assert ("existing", "e1", False) in results      # e1 released, not counted


async def test_announce_fires_once_when_the_last_track_reaches_the_limit():
    # 3(b). Exact finish on the final track: the reaching commit announces
    #       immediately, even with no later track. Sequential so the last commit
    #       is the reaching one.
    limit = SessionTrackLimit(limit=3)
    announced = []
    for i in range(3):
        assert await limit.reserve() is True
        if limit.commit():
            announced.append(i)
    assert announced == [2]                          # only the 3rd (last) commit
    assert limit.is_reached()


async def test_error_during_reservation_releases_it_no_deadlock():
    # 4(a). A task that errors AFTER reserving frees its slot (handle_item's
    #       except -> release), so the cap never leaks and others aren't blocked.
    limit, results, mx = await _run(
        2, [("error", "x1"), ("new", "n1"), ("new", "n2"), ("error", "x2")]
    )
    downloads = [r for r in results if r[0] == "downloaded"]
    assert len(downloads) == 2                       # both new tracks got through
    assert limit.downloaded == 2
    assert mx <= 2
    assert limit.reserved == 0                       # no reservation leaked
    assert limit.is_reached()


async def test_reserve_cancelled_while_waiting_is_cleaned_up():
    # 4(b). A task cancelled WHILE parked in reserve() removes itself from the
    #       wait list — no leak, no deadlock for the rest.
    limit = SessionTrackLimit(limit=1)
    assert await limit.reserve() is True             # slot taken; next one waits
    waiter = asyncio.ensure_future(limit.reserve())
    await asyncio.sleep(0)                            # let it park on its future
    assert limit._waiters                            # it is waiting
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert limit._waiters == []                      # cleaned itself up
    limit.release()                                  # freeing the held slot is safe
    assert limit.reserved == 0


async def test_wakeup_is_passed_on_when_a_woken_waiter_is_cancelled():
    # Race: release() wakes waiter A, but A is cancelled BEFORE it reserves. The
    # freed slot must not be orphaned — A hands the wakeup to waiter B, which then
    # obtains the slot. No deadlock, no negative counter, invariant preserved.
    limit = SessionTrackLimit(limit=1)
    assert await limit.reserve() is True          # H holds the only slot
    a = asyncio.ensure_future(limit.reserve())    # A parks
    b = asyncio.ensure_future(limit.reserve())    # B parks
    await asyncio.sleep(0)                         # let both park on their futures
    assert len(limit._waiters) == 2

    limit.release()                               # frees the slot -> wakes A (first)
    assert len(limit._waiters) == 1               # A dequeued; B still waiting

    a.cancel()                                    # cancel A before it can reserve
    with pytest.raises(asyncio.CancelledError):
        await a

    # B must get the slot handed on from A's aborted wakeup.
    assert await b is True
    assert limit.reserved == 1                    # exactly B holds it now
    assert limit.downloaded == 0
    assert limit.reserved >= 0                    # never went negative
    assert limit.downloaded + limit.reserved <= limit.limit
    assert limit._waiters == []                   # no stranded waiter


async def test_resume_does_not_checkpoint_a_cap_truncated_resource():
    # 5. --resume after the cap: a resource cut short by the limit must NOT be
    #    marked complete, so a later --resume retries its missing tracks.
    limit = SessionTrackLimit(limit=1)
    assert await limit.reserve() is True
    limit.commit()                                   # reaches the cap mid-resource
    assert limit.is_reached()
    # ok=True (no error) but cut short by the cap -> not checkpointable.
    assert _resource_resume_done(
        ok=True, resume_enabled=True, cancelled=False,
        session_limit_reached=limit.is_reached(),
    ) is False
