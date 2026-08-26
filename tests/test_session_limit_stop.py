"""Reaching `max_tracks_per_session` must STOP the run, not just refuse further
downloads while the dispatcher keeps enumerating the remaining resources.

The reproduced bug: after printing "Límite de sesión alcanzado … Reinicia para
continuar", the engine kept emitting `[53/69]`, `[54/69]` and hitting the API for
the remaining resources, because `SessionTrackLimit.admit()` only returned False
inside `handle_item()` without a run-wide stop.

The fix latches a run-wide `reached` signal (distinct from Cancel/401/429) that
`_bounded_dispatch` (via `should_stop`), `dispatch_one` and `wrapper` all honour.
These tests pin the dispatch-level behaviour on the REAL `_bounded_dispatch`.
"""
from __future__ import annotations

import asyncio

from tiddl.cli.commands.download import _bounded_dispatch, _resource_resume_done
from tiddl.core.download_policy import SessionTrackLimit


def test_bounded_dispatch_should_stop_halts_pulling_new_items():
    # Once should_stop() flips True, the pool stops dequeuing NEW items.
    handled: list = []
    stop = {"v": False}

    async def handler(item, idx):
        handled.append(item)
        if item == "b":
            stop["v"] = True  # stop after handling b

    asyncio.run(
        _bounded_dispatch(list("abcde"), handler, concurrency=1,
                          should_stop=lambda: stop["v"])
    )
    assert handled == ["a", "b"]  # c, d, e were never pulled or handled


def test_should_stop_true_from_the_start_handles_nothing():
    async def handler(item, idx):  # pragma: no cover - must never run
        raise AssertionError("handler ran despite should_stop=True")

    asyncio.run(
        _bounded_dispatch([1, 2, 3], handler, concurrency=2, should_stop=lambda: True)
    )


def test_mandatory_no_heartbeat_or_api_for_remaining_resources_after_limit():
    # MANDATORY: small cap + several albums. After the cap is reached mid-run,
    # NO further `[n/total]` heartbeat appears and NO API call is made for the
    # remaining resources. Drives the REAL _bounded_dispatch with a handler that
    # mirrors dispatch_one -> wrapper -> handle_resource -> handle_item.
    limit = SessionTrackLimit(limit=6)
    albums = [f"album{i}" for i in range(1, 7)]  # 6 albums
    tracks_per_album = 4
    heartbeats: list = []
    api_calls: list = []
    announces: list = []

    async def dispatch_one_like(album, idx):
        # dispatch_one guard: no heartbeat and no wrapper() once reached.
        if limit.is_reached():
            return
        heartbeats.append((idx, album))          # the `[idx/total]` line
        # wrapper -> handle_resource: enumerating a resource IS an API call.
        api_calls.append(("enumerate", album))
        # handle_item per track: admit-gate, then a real download is an API call.
        for _t in range(tracks_per_album):
            admitted, announce = limit.admit()
            if announce:
                announces.append(album)
            if not admitted:
                break                            # cap hit: stop admitting more
            api_calls.append(("stream", album))
            limit.record(was_downloaded=True)

    asyncio.run(
        _bounded_dispatch(albums, dispatch_one_like, concurrency=1,
                          should_stop=limit.is_reached)
    )

    # album1 downloads 4 (4<6), album2 downloads 2 -> total 6 == cap, reached
    # during album2; its remaining tracks and albums 3..6 are never touched.
    assert limit.is_reached()
    assert limit.downloaded == 6
    # Heartbeats only for the two albums that actually ran — none afterwards.
    assert [a for _, a in heartbeats] == ["album1", "album2"]
    # No enumeration / stream API for any remaining resource.
    touched = {a for _, a in api_calls}
    assert touched == {"album1", "album2"}
    for gone in ["album3", "album4", "album5", "album6"]:
        assert ("enumerate", gone) not in api_calls
        assert ("stream", gone) not in api_calls
    # The warning fired exactly once, during the album where the cap was hit.
    assert announces == ["album2"]


def test_resource_resume_done_truth_table():
    # Point 6: a resource is checkpointed done ONLY on a clean completion that was
    # not stopped underneath it — never when cut short by the cap or cancel.
    done = _resource_resume_done
    assert done(ok=True, resume_enabled=True, cancelled=False,
                session_limit_reached=False) is True
    # cap reached during it -> NOT done (its remaining tracks weren't fetched).
    assert done(True, True, False, True) is False
    # cancelled -> NOT done.
    assert done(True, True, True, False) is False
    # errored (ok False) -> NOT done.
    assert done(False, True, False, False) is False
    # --resume disabled -> nothing to checkpoint.
    assert done(True, False, False, False) is False


def test_session_limit_is_not_user_cancel_or_rate_limit():
    # Point 7: the cap must NOT masquerade as Cancel/401/429 — it is its own
    # run-local signal on the policy object, leaving global cancel untouched.
    from tiddl.core import cancel

    cancel.clear()
    try:
        limit = SessionTrackLimit(limit=1)
        limit.record(was_downloaded=True)
        assert limit.is_reached()
        assert not cancel.is_cancelled()  # reaching the cap never cancels the run
    finally:
        cancel.clear()
