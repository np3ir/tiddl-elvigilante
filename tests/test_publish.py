"""Focused unit coverage for `tiddl.core.utils.publish.publish_verified_file`,
independent of the full download/CLI machinery that exercises it indirectly
elsewhere (`test_downloader.py`, `test_recover_cli.py`). Each test here pins
one specific finding from the third audit review of the retained-staging-
recovery branch.
"""
from __future__ import annotations

import tiddl.core.utils.publish as publishmod
from tiddl.core.utils.publish import publish_verified_file


async def _ok_reverify(_candidate):
    return True, None


def test_missing_destination_parent_refuses_without_creating_anything(tmp_path):
    """[P1, third audit finding #2] `publish_verified_file` must NOT create
    the destination directory at any depth — a missing destination parent
    is refused outright rather than guessed to be safe to (re)create, since
    directory depth says nothing about whether the real filesystem (e.g. a
    NAS share) is actually mounted."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"hello")
    destination = tmp_path / "does-not-exist-yet" / "dest.bin"

    import asyncio

    published, retained = asyncio.run(
        publish_verified_file(source, destination, reverify=_ok_reverify)
    )

    assert published is False
    assert retained == source
    assert source.exists()  # untouched
    assert not destination.parent.exists()  # NOT created
    assert not destination.exists()


def test_reverify_exception_does_not_leak_destination_temp(tmp_path, monkeypatch):
    """[P1, third audit finding #4] If `reverify` raises (e.g. the dest-side
    temp vanishes mid-hash due to an unrelated concurrent process, or a
    flaky network share raises on read), `publish_verified_file` must not
    let that propagate straight out — skipping every bit of its own
    cleanup and leaking the `destination.part.*` temp file on disk forever.
    The exception must be treated the same as a failed verification: the
    temp is cleaned up, the source is preserved untouched, and any prior
    destination content is left exactly as it was."""
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: False)

    source = tmp_path / "source.bin"
    source.write_bytes(b"hello world")
    destination = tmp_path / "dest" / "track.bin"
    destination.parent.mkdir(parents=True, exist_ok=True)
    prior_content = b"PRIOR FINAL CONTENT - MUST SURVIVE"
    destination.write_bytes(prior_content)

    async def _boom_reverify(_candidate):
        raise OSError("simulated: dest temp vanished mid-verify")

    import asyncio

    published, retained = asyncio.run(
        publish_verified_file(source, destination, reverify=_boom_reverify)
    )

    assert published is False
    assert retained == source
    assert source.exists() and source.read_bytes() == b"hello world"  # source untouched
    assert destination.read_bytes() == prior_content  # prior final NEVER touched
    # No destination.part.* temp left behind anywhere under tmp_path.
    leftovers = list(tmp_path.rglob("*.part.*"))
    assert leftovers == [], f"leaked temp file(s): {leftovers}"


def test_reverify_exception_on_one_attempt_still_recovers_on_retry(tmp_path, monkeypatch):
    """A reverify failure (exception or a plain False) is retried like any
    other destination-validation failure — it isn't a fatal, un-retryable
    condition by itself. This proves the exception path feeds into the
    SAME retry loop as a normal `(False, "reason")` return, not a dead end."""
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: False)

    source = tmp_path / "source.bin"
    source.write_bytes(b"hello world")
    destination = tmp_path / "dest" / "track.bin"
    destination.parent.mkdir(parents=True, exist_ok=True)

    calls = {"n": 0}

    async def _flaky_reverify(_candidate):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated transient failure on the first attempt")
        return True, None

    import asyncio

    published, retained = asyncio.run(
        publish_verified_file(source, destination, reverify=_flaky_reverify)
    )

    assert published is True
    assert retained is None
    assert destination.read_bytes() == b"hello world"
    assert not source.exists()  # cleaned up after a successful publish
    assert calls["n"] == 2  # first attempt raised, second attempt succeeded
