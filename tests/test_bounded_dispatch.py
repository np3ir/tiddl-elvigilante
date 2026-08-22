"""Coverage for the bounded worker pool that dispatches expanded-run resources.

The pool exists so a huge expanded run (a playlist blown up into hundreds of
thousands of artist resources) never creates one asyncio Task per resource up
front — the memory blow-up that hard-killed the process. These tests assert the
two invariants that matter: every item is handled exactly once, and no more than
``concurrency`` items are ever in flight, regardless of list size.
"""
from __future__ import annotations

import asyncio

import pytest

from tiddl.cli.commands.download import _bounded_dispatch


def test_processes_all_items_exactly_once():
    seen: list = []

    async def handler(item, index):
        seen.append((index, item))

    asyncio.run(_bounded_dispatch(list("abcde"), handler, concurrency=2))

    assert sorted(i for i, _ in seen) == [1, 2, 3, 4, 5]  # 1-based indices
    assert sorted(x for _, x in seen) == list("abcde")     # every item once


def test_respects_concurrency_cap():
    active = 0
    peak = 0

    async def handler(item, index):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        for _ in range(3):        # yield repeatedly so overlap is possible
            await asyncio.sleep(0)
        active -= 1

    asyncio.run(_bounded_dispatch(list(range(20)), handler, concurrency=3))

    assert peak <= 3     # hard invariant: never more than `concurrency` in flight
    assert peak >= 2     # and they really do overlap (not serialized)


def test_more_workers_than_items_is_fine():
    seen: list = []

    async def handler(item, index):
        seen.append(item)

    asyncio.run(_bounded_dispatch([1, 2], handler, concurrency=10))

    assert sorted(seen) == [1, 2]


def test_zero_concurrency_floors_to_one():
    seen: list = []

    async def handler(item, index):
        seen.append(item)

    asyncio.run(_bounded_dispatch([1, 2, 3], handler, concurrency=0))

    assert sorted(seen) == [1, 2, 3]


def test_empty_items_is_a_noop():
    async def handler(item, index):  # pragma: no cover - must never be called
        raise AssertionError("handler called on empty input")

    asyncio.run(_bounded_dispatch([], handler, concurrency=3))


def test_one_failing_item_does_not_stop_others():
    seen: list = []

    async def handler(item, index):
        if item == "boom":
            raise ValueError("boom")
        seen.append(item)

    # A per-item error is swallowed (logged) so the rest still run.
    asyncio.run(_bounded_dispatch(["a", "boom", "b", "c"], handler, concurrency=1))

    assert sorted(seen) == ["a", "b", "c"]


def test_keyboardinterrupt_tears_down_and_propagates():
    processed: list = []

    async def handler(item, index):
        if item == 2:
            raise KeyboardInterrupt
        processed.append(item)
        await asyncio.sleep(0)

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(_bounded_dispatch([1, 2, 3, 4], handler, concurrency=1))

    assert processed == [1]  # stopped at the interrupt, did not finish the list
