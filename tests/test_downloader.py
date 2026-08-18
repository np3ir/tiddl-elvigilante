"""Downloader coverage (block 2): transport / retry / cancellation.

Uses a real local aiohttp server (aioresponses is incompatible with the pinned
aiohttp 3.14). `_download_with_retry` runs on a minimal host that reuses the real
method + session factory, so streaming, staging → move → integrity → retry runs
end to end. Staging is redirected into the test's tmp dir so we can assert no
`tiddl-*.part.*` leftovers.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import types
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import tiddl.cli.commands.download.downloader as dlmod
import tiddl.core.utils.destination_anchor as da
import tiddl.core.utils.fsio as fsiomod
import tiddl.core.utils.publish as publishmod
import tiddl.core.utils.retained_registry as registrymod
from tiddl.cli.commands.download.downloader import (
    CHUNK_SIZE,
    Downloader,
    DownloadStatus,
    DownloadTask,
)
from tiddl.core import cancel

AUDIO_CT = "audio/flac"  # not json/text/xml -> treated as audio by the downloader


class _StubOutput:
    def __init__(self):
        self.console = types.SimpleNamespace(print=lambda *a, **k: None)
        self.resets = 0

    def download_advance(self, task_id, size=0):
        pass

    def download_reset(self, task_id):
        self.resets += 1


class _StubDownloader:
    """Minimal host that reuses the real download + publish machinery."""

    _get_http_session = Downloader._get_http_session
    _download_with_retry = Downloader._download_with_retry
    _publish_staged = Downloader._publish_staged
    _verify_or_repair = Downloader._verify_or_repair

    def __init__(self, destination_identity="off", identity_tracker=None):
        self._http_session = None
        self.rich_output = _StubOutput()
        self.destination_identity = destination_identity
        self.identity_tracker = identity_tracker or da.IdentityFailureTracker()


def _scripted_app(script: list) -> web.Application:
    """A /track handler replaying `script` (one spec per request):
    ("ok", n)              -> 200 with n bytes
    ("status", code)       -> that status, empty body
    ("truncate", decl, n)  -> 200, Content-Length=decl but only n bytes then abort
    """
    state = {"i": 0}

    async def handler(request):
        spec = script[min(state["i"], len(script) - 1)]
        state["i"] += 1
        if spec[0] == "ok":
            return web.Response(body=b"\x00" * spec[1], content_type=AUDIO_CT)
        if spec[0] == "status":
            return web.Response(status=spec[1], content_type=AUDIO_CT)
        if spec[0] == "truncate":
            declared, sent = spec[1], spec[2]
            resp = web.StreamResponse(status=200, headers={"Content-Type": AUDIO_CT})
            resp.content_length = declared
            await resp.prepare(request)
            await resp.write(b"\x00" * sent)
            request.transport.abort()  # abrupt close -> client ClientPayloadError
            return resp
        raise AssertionError(f"unknown spec {spec!r}")

    app = web.Application()
    app.router.add_get("/track", handler)
    return app


async def _start(script: list) -> TestServer:
    server = TestServer(_scripted_app(script))
    await server.start_server()
    return server


@pytest.fixture(autouse=True)
def _reset_cancel():
    cancel.clear()
    yield
    cancel.clear()


@pytest.fixture(autouse=True)
def _isolate_retained_registry(tmp_path, monkeypatch):
    """Every test in this module gets its own retained-staging registry +
    quarantine dir under pytest's tmp_path, never the real ~/.tiddl."""
    monkeypatch.setattr(registrymod, "APP_PATH", tmp_path / "_app")
    # Same isolation for destination_anchor's local state — the identity
    # tests below call da.establish_anchor()/check_write_allowed() directly,
    # matching the convention every other test file in this suite already
    # follows (test_destination_cli.py, test_recover_cli.py, test_m3u.py).
    monkeypatch.setattr(da, "APP_PATH", tmp_path / "_app")


@pytest.fixture
def fast_sleep(monkeypatch):
    """Skip the downloader's retry back-off without mutating the global asyncio
    module (which the aiohttp server relies on): swap the downloader's `asyncio`
    reference for a proxy whose only override is an instant `sleep`."""
    import asyncio as _asyncio

    import tiddl.cli.commands.download.downloader as dl

    async def _instant(*_a, **_k):
        return None

    class _AsyncioProxy:
        def __getattr__(self, name):
            return _instant if name == "sleep" else getattr(_asyncio, name)

    monkeypatch.setattr(dl, "asyncio", _AsyncioProxy())


@pytest.fixture
def stage_dir(tmp_path, monkeypatch):
    """Redirect the downloader's local staging into a known dir so tests can
    assert no partial `tiddl-*.part.*` file is left behind."""
    d = tmp_path / "stage"
    d.mkdir()
    import tiddl.cli.commands.download.downloader as dl
    monkeypatch.setattr(dl.tempfile, "gettempdir", lambda: str(d))
    return d


def _no_staging_leftovers(stage_dir) -> bool:
    return not list(stage_dir.glob("tiddl-*.part.*"))


async def _download(server: TestServer, task: DownloadTask, **stub_kwargs):
    """Returns (ok, stub) so a test can inspect the stub (e.g. visual resets)."""
    url = str(server.make_url("/track"))
    dl = _StubDownloader(**stub_kwargs)
    try:
        ok = await dl._download_with_retry(task, [url], task_id=0)
    finally:
        if dl._http_session is not None:
            await dl._http_session.close()
    return ok, dl


async def test_short_body_is_detected_and_retried(tmp_path, fast_sleep, stage_dir):
    server = await _start([("ok", 3000), ("ok", 5000)])  # short then full
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok, dl = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
    assert task.error_message is None            # transient error cleared on success
    assert (tmp_path / "out.bin").stat().st_size == 5000
    # The per-attempt counter must reset: not 3000 + 5000 = 8000 (160%).
    assert task.bytes_downloaded == 5000
    assert task.progress_percentage == 100
    assert dl.rich_output.resets == 1            # exactly one visual reset, for the single retry
    assert _no_staging_leftovers(stage_dir)


async def test_http_error_is_retried_then_succeeds(tmp_path, fast_sleep, stage_dir):
    server = await _start([("status", 500), ("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
    assert task.error_message is None
    assert _no_staging_leftovers(stage_dir)


async def test_http_error_exhausted_fails(tmp_path, fast_sleep, stage_dir):
    server = await _start([("status", 500)])  # always 500
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == task.max_attempts == 3
    assert task.status == DownloadStatus.FAILED
    assert task.error_message  # set to the transient error when attempts are exhausted
    assert not (tmp_path / "out.bin").exists()
    assert _no_staging_leftovers(stage_dir)


async def test_real_truncation_is_cleaned_and_retried(tmp_path, fast_sleep, stage_dir):
    # Content-Length says 5000 but the server sends 3000 then aborts -> the client
    # raises ClientPayloadError; the partial is cleaned and the download retries.
    server = await _start([("truncate", 5000, 3000), ("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
    assert task.error_message is None
    assert (tmp_path / "out.bin").stat().st_size == 5000
    assert _no_staging_leftovers(stage_dir)


async def test_cancellation_midstream_aborts_without_retry(tmp_path, monkeypatch, stage_dir):
    # Real midstream cancel: >= 2 chunks; allow the first chunk to be written,
    # then cancel before the second (is_cancelled: top-check False, chunk1 False,
    # chunk2 True).
    calls = {"n": 0}

    def fake_is_cancelled():
        calls["n"] += 1
        return calls["n"] >= 3

    monkeypatch.setattr("tiddl.core.cancel.is_cancelled", fake_is_cancelled)
    server = await _start([("ok", 2 * CHUNK_SIZE)])  # two 1 MiB chunks
    try:
        task = DownloadTask(
            url="x", output_path=tmp_path / "out.bin", expected_size=2 * CHUNK_SIZE
        )
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == 1                     # aborted, did not retry
    assert task.status == DownloadStatus.FAILED
    assert not (tmp_path / "out.bin").exists()    # nothing published
    assert _no_staging_leftovers(stage_dir)       # partial staging file dropped


# ---------------------------------------------------------------------------
# Cross-filesystem safe publish: the destination lives on a different volume
# from the local staging, so the copy -> verify -> atomic os.replace -> drop
# staging path runs (`_same_volume` is forced False). A scripted copy2 injects
# transient NAS errors and silent corruption.
# ---------------------------------------------------------------------------


@pytest.fixture
def cross_volume(monkeypatch):
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: False)


def _dest_leftovers(dest_dir):
    return list(dest_dir.glob("*.part.*"))


def _staging_leftovers(stage_dir):
    return list(stage_dir.glob("tiddl-*.part.*"))


def _scripted_replace(script):
    real = os.replace
    calls = {"n": 0}

    def fake(src, dst, *a, **k):
        spec = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        if spec == "ok":
            return real(src, dst)
        if spec == "oserror":
            raise OSError("simulated atomic-replace failure")
        raise AssertionError(spec)

    return fake, calls


def _scripted_copy2(script):
    real = shutil.copy2
    calls = {"n": 0}

    def fake(src, dst, *a, **k):
        spec = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        if spec == "ok":
            return real(src, dst)
        if spec == "oserror":
            raise OSError("simulated destination write error")
        if spec == "short":
            with open(dst, "wb") as f:
                f.write(b"\x00" * 100)   # wrong size -> verify fails
            return dst
        if spec == "corrupt-hash":
            with open(dst, "wb") as f:
                f.write(b"\xff" * 5000)  # right size, wrong content -> hash fails
            return dst
        raise AssertionError(spec)

    return fake, calls


async def test_cross_volume_publish_success(tmp_path, fast_sleep, stage_dir, cross_volume):
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 1
    assert task.status == DownloadStatus.COMPLETED
    assert dest.stat().st_size == 5000
    assert _no_staging_leftovers(stage_dir)   # local staging removed after publish
    assert not _dest_leftovers(tmp_path)      # no dest-side .part temp left


async def test_cross_volume_retries_transient_copy_error(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    fake, calls = _scripted_copy2(["oserror", "oserror", "ok"])
    monkeypatch.setattr(publishmod.shutil, "copy2", fake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 1        # re-copied from staging, did NOT re-download
    assert calls["n"] == 3           # two transient failures, then success
    assert dest.stat().st_size == 5000
    assert not _dest_leftovers(tmp_path)
    assert task.error_message is None       # a transient copy error must not linger
    assert task.retained_staging is None    # publish was fully clean


async def test_cross_volume_bad_copy_is_reverified_and_recopied(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    fake, calls = _scripted_copy2(["short", "ok"])   # first copy lands corrupt, second good
    monkeypatch.setattr(publishmod.shutil, "copy2", fake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 1        # verify caught the bad copy; staging survived, no re-download
    assert calls["n"] == 2
    assert dest.stat().st_size == 5000
    assert _no_staging_leftovers(stage_dir)
    assert not _dest_leftovers(tmp_path)
    assert task.error_message is None       # the earlier corrupt-copy error must not linger


async def test_cross_volume_hash_mismatch_is_detected(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    good_hash = hashlib.md5(b"\x00" * 5000).hexdigest()
    fake, calls = _scripted_copy2(["corrupt-hash", "ok"])  # right size, wrong content, then good
    monkeypatch.setattr(publishmod.shutil, "copy2", fake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(
            url="x", output_path=dest, expected_size=5000, expected_hash=good_hash
        )
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert calls["n"] == 2           # silent same-size corruption caught by hash -> re-copy
    assert dest.stat().st_size == 5000
    assert not _dest_leftovers(tmp_path)


async def test_cross_volume_exhausted_keeps_staging_no_partial_final(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    fake, _ = _scripted_copy2(["short"])   # every copy corrupts -> never publishes
    monkeypatch.setattr(publishmod.shutil, "copy2", fake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == 1              # publish failure does NOT re-download
    assert task.status == DownloadStatus.FAILED
    assert not dest.exists()              # no incomplete final file
    assert not _dest_leftovers(tmp_path)  # no dest-side .part temp left
    # The verified local download is RETAINED for recovery. It is moved out of
    # the OS temp staging dir into the retained-staging quarantine dir (so it
    # survives an OS temp cleanup) and recorded on the task + the registry.
    assert _no_staging_leftovers(stage_dir)
    assert task.retained_staging is not None
    assert task.retained_staging.exists()
    assert task.retained_staging.parent == registrymod.quarantine_dir()
    report = await registrymod.reconcile()
    assert len(report.entries) == 1
    assert report.entries[0].status == "ok"
    assert report.entries[0].entry.reason == registrymod.RetainReason.PUBLISH_PENDING
    assert report.entries[0].entry.output_path == str(dest)


async def test_cross_volume_replace_retries_then_succeeds(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    rfake, rcalls = _scripted_replace(["oserror", "ok"])
    monkeypatch.setattr(publishmod.os, "replace", rfake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 1        # the atomic publish retried; no re-download
    assert rcalls["n"] == 2
    assert dest.stat().st_size == 5000
    assert not _dest_leftovers(tmp_path)
    assert _no_staging_leftovers(stage_dir)
    assert task.error_message is None       # the transient replace error must not linger
    assert task.retained_staging is None    # publish was fully clean, nothing retained


async def test_cross_volume_replace_exhausted_keeps_prior_final(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"P" * 4000)          # a prior, valid final file
    rfake, _ = _scripted_replace(["oserror"])   # the atomic publish always fails
    monkeypatch.setattr(publishmod.os, "replace", rfake)
    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.status == DownloadStatus.FAILED
    assert dest.read_bytes() == b"P" * 4000        # prior final file left untouched
    assert not _dest_leftovers(tmp_path)           # verified temp cleaned up
    assert len(_staging_leftovers(stage_dir)) == 1  # staging retained


async def test_corrupt_local_staging_detected_before_copy(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    copy_calls = {"n": 0}
    real = shutil.copy2

    def counting_copy(src, dst, *a, **k):
        copy_calls["n"] += 1
        return real(src, dst)

    monkeypatch.setattr(publishmod.shutil, "copy2", counting_copy)
    server = await _start([("ok", 3000)])   # short download -> local staging invalid (size)
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == 3        # invalid local staging -> re-download to the limit
    assert task.status == DownloadStatus.FAILED
    assert copy_calls["n"] == 0      # never copied a bad staging to the destination
    assert not dest.exists()


async def test_publication_order_copy_fsync_verify_replace(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    order = []
    real_copy = shutil.copy2
    real_fsync = publishmod._fsync_path
    real_verify = dlmod.FileIntegrityChecker.verify_file_async
    real_replace = os.replace

    def _copy(src, dst, *a, **k):
        order.append("copy")
        return real_copy(src, dst)

    def _fsync(p):
        order.append("fsync")
        return real_fsync(p)

    async def _verify(*a, **k):
        order.append("verify")
        return await real_verify(*a, **k)

    def _replace(src, dst, *a, **k):
        order.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(publishmod.shutil, "copy2", _copy)
    monkeypatch.setattr(publishmod, "_fsync_path", _fsync)
    monkeypatch.setattr(dlmod.FileIntegrityChecker, "verify_file_async", staticmethod(_verify))
    monkeypatch.setattr(publishmod.os, "replace", _replace)

    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    # local staging verified first, then copy -> fsync -> destination verify -> atomic replace
    assert order == ["verify", "copy", "fsync", "verify", "replace"]


async def test_same_volume_replace_retries_then_succeeds(
    tmp_path, fast_sleep, stage_dir, monkeypatch
):
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: True)
    rfake, rcalls = _scripted_replace(["oserror", "ok"])
    monkeypatch.setattr(publishmod.os, "replace", rfake)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 1          # rename retried in place; no re-download
    assert rcalls["n"] == 2
    assert task.status == DownloadStatus.COMPLETED
    assert task.error_message is None  # the transient rename error must not linger
    assert dest.stat().st_size == 5000


async def test_same_volume_fsyncs_dest_dir_after_rename(
    tmp_path, fast_sleep, stage_dir, monkeypatch
):
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: True)
    order = []
    real_replace = os.replace
    real_fsync_dir = publishmod._fsync_dir

    def _replace(src, dst, *a, **k):
        order.append("replace")
        return real_replace(src, dst)

    def _fsync_dir(p):
        order.append("fsync_dir")
        return real_fsync_dir(p)

    monkeypatch.setattr(publishmod.os, "replace", _replace)
    monkeypatch.setattr(publishmod, "_fsync_dir", _fsync_dir)

    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    # dir fsync happens right after the rename, same durability contract as
    # the cross-filesystem path.
    assert order == ["replace", "fsync_dir"]


async def test_publish_success_survives_staging_unlink_failure(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    """A destination publish must not be reported as failed just because the
    best-effort delete of the now-redundant local staging copy failed (e.g. an
    AV/indexer lock, or a remote filesystem that rejects the unlink). The final
    file must be correct, and the leftover staging must be surfaced via
    task.retained_staging (+ a warning) rather than silently dropped."""
    monkeypatch.setattr(publishmod, "_safe_unlink", lambda p: False)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.status == DownloadStatus.COMPLETED
    assert dest.stat().st_size == 5000            # the final file IS correct
    assert task.error_message is None
    assert task.retained_staging is not None      # leftover staging reported, not hidden
    assert task.retained_staging.exists()
    assert not _dest_leftovers(tmp_path)          # the dest-side .part temp is still cleaned up


async def test_dest_tmp_unlink_failure_is_warned_not_fatal(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch, caplog
):
    """A best-effort dest-side temp cleanup failure must be observable (a
    warning) but must never turn an otherwise-successful copy retry into a
    failure — only the leftover surfaces, nothing silently disappears."""
    fake, calls = _scripted_copy2(["short", "ok"])  # first copy corrupt, then good
    monkeypatch.setattr(publishmod.shutil, "copy2", fake)
    real_unlink = fsiomod._safe_unlink

    def flaky_unlink(path):
        # Fail only the dest-side ".part." cleanup (the corrupt first copy);
        # everything else (e.g. the local staging drop) behaves normally.
        if path is not None and os.path.basename(str(path)).startswith("out.bin.part."):
            return False
        return real_unlink(path)

    # `_safe_unlink_warn` (which logs the "Could not remove leftover..."
    # warning under test) is defined in fsio.py and calls `_safe_unlink` via
    # fsio's OWN module globals — patch it there, not on `publishmod` (which
    # only affects publish.py's *direct* `_safe_unlink` call, a different
    # call site: dropping the local staging copy after a successful publish).
    monkeypatch.setattr(fsiomod, "_safe_unlink", flaky_unlink)

    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    caplog.set_level("WARNING")
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert calls["n"] == 2                     # corrupt copy, then a good re-copy
    assert dest.stat().st_size == 5000
    assert task.status == DownloadStatus.COMPLETED
    assert any(
        "Could not remove leftover destination-side temp" in r.message
        for r in caplog.records
    )


async def test_same_volume_uses_atomic_rename_not_copy(
    tmp_path, fast_sleep, stage_dir, monkeypatch
):
    monkeypatch.setattr(publishmod, "_same_volume", lambda a, b: True)

    def _boom(*a, **k):
        raise AssertionError("copy2 must not be called on the same-volume fast path")

    monkeypatch.setattr(publishmod.shutil, "copy2", _boom)
    server = await _start([("ok", 5000)])
    dest = tmp_path / "out.bin"
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, _ = await _download(server, task)
    finally:
        await server.close()

    assert ok is True                # published via atomic os.replace, no copy
    assert dest.stat().st_size == 5000


# ------------------------------------------------------------------
# Destination-volume identity — operation 3 (media publication), the
# tightest of the nine guarded writes (see tiddl.core.utils.destination_
# anchor and PROPOSAL_destination_volume_identity_v2_1..v2_4.md, kept
# local/untracked). Exercised end to end via _download_with_retry so the
# real staging -> verify -> guard -> publish chain runs, not a mock of it.
# ------------------------------------------------------------------

async def test_publish_refused_by_untrusted_root_retains_staging_as_publish_pending(
    tmp_path, fast_sleep, stage_dir
):
    root = tmp_path / "dest_root"
    root.mkdir()
    dest = root / "out.bin"
    tracker = da.IdentityFailureTracker()

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, root=root, expected_size=5000)
        ok, dl = await _download(
            server, task, destination_identity="strict", identity_tracker=tracker,
        )
    finally:
        await server.close()

    assert ok is False
    assert not dest.exists()  # never published
    assert task.error_message and "destination not trusted" in task.error_message
    assert tracker.any_refused is True
    # Class A (v2.3 §3): treated exactly like any other publish failure —
    # the verified local copy is retained, not deleted, and registered for
    # `tiddl recover` to pick up later once the root is actually trusted.
    assert task.retained_staging is not None
    assert Path(task.retained_staging).exists()
    entries = registrymod.read_entries().entries
    assert len(entries) == 1
    assert entries[0].reason == registrymod.RetainReason.PUBLISH_PENDING
    assert entries[0].output_path == str(dest)


async def test_publish_succeeds_when_root_is_trusted(tmp_path, fast_sleep, stage_dir):
    root = tmp_path / "dest_root"
    root.mkdir()
    da.establish_anchor(root)
    dest = root / "out.bin"

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, root=root, expected_size=5000)
        ok, dl = await _download(server, task, destination_identity="strict")
    finally:
        await server.close()

    assert ok is True
    assert dest.stat().st_size == 5000
    assert dl.identity_tracker.any_refused is False
    assert registrymod.read_entries().entries == []


async def test_publish_off_mode_ignores_an_untrusted_root(tmp_path, fast_sleep, stage_dir):
    # "off" performs zero identity reads (v2.4 §1) — root has no anchor and
    # no local trust record at all, yet the publish proceeds unaffected.
    root = tmp_path / "dest_root"
    root.mkdir()
    dest = root / "out.bin"

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, root=root, expected_size=5000)
        ok, dl = await _download(server, task, destination_identity="off")
    finally:
        await server.close()

    assert ok is True
    assert dest.stat().st_size == 5000
    assert dl.identity_tracker.any_refused is False


async def test_publish_task_without_root_skips_the_guard_entirely(
    tmp_path, fast_sleep, stage_dir
):
    # A DownloadTask built without `root` (e.g. every other test in this
    # file, predating this feature) must behave exactly as before: strict
    # mode configured on the Downloader is irrelevant if this task never
    # got a root, per DownloadTask.root's own docstring.
    dest = tmp_path / "out.bin"

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, expected_size=5000)
        ok, dl = await _download(server, task, destination_identity="strict")
    finally:
        await server.close()

    assert ok is True
    assert dest.stat().st_size == 5000
    assert dl.identity_tracker.any_refused is False


async def test_retained_entry_from_a_trusted_publish_carries_the_verified_identity(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    # Implementation-audit finding (2026-08-18): a retained entry from a real
    # strict-mode download never carried destination_root/destination_anchor_id,
    # so `tiddl recover` always classified it as legacy and refused until a
    # manual --bind-root — defeating the point of capturing identity at all.
    # Reproduced here via the CLEANUP_PENDING path (publish succeeds, the
    # best-effort staging unlink fails) since it's the simplest way to force
    # a retained_registry entry while keeping the root genuinely trusted.
    monkeypatch.setattr(publishmod, "_safe_unlink", lambda p: False)

    root = tmp_path / "dest_root"
    root.mkdir()
    anchor_id = da.establish_anchor(root)
    dest = root / "out.bin"

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, root=root, expected_size=5000)
        ok, dl = await _download(server, task, destination_identity="strict")
    finally:
        await server.close()

    assert ok is True
    assert task.verified_root_key == da.root_key(root)
    assert task.verified_anchor_id == anchor_id

    entries = registrymod.read_entries().entries
    assert len(entries) == 1
    assert entries[0].reason == registrymod.RetainReason.CLEANUP_PENDING
    assert entries[0].destination_root == da.root_key(root)
    assert entries[0].destination_anchor_id == anchor_id

    # And recovery picks it up WITHOUT --bind-root, because the identity was
    # already captured at staging time — this is the actual point of §5.
    check = da.check_write_allowed(
        Path(entries[0].destination_root), dest, mode="strict",
        expected_anchor_id=entries[0].destination_anchor_id,
    )
    assert check.allowed is True


async def test_off_mode_retained_entry_never_carries_identity(
    tmp_path, fast_sleep, stage_dir, cross_volume, monkeypatch
):
    # Requirement #4 (audit correction): off mode must never persist
    # destination_root/destination_anchor_id, even when task.root is set.
    monkeypatch.setattr(publishmod, "_safe_unlink", lambda p: False)

    root = tmp_path / "dest_root"
    root.mkdir()
    da.establish_anchor(root)
    dest = root / "out.bin"

    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=dest, root=root, expected_size=5000)
        ok, dl = await _download(server, task, destination_identity="off")
    finally:
        await server.close()

    assert ok is True
    assert task.verified_root_key is None
    assert task.verified_anchor_id is None
    entries = registrymod.read_entries().entries
    assert entries[0].destination_root is None
    assert entries[0].destination_anchor_id is None
