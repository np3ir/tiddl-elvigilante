"""Downloader coverage (block 2): transport / retry / cancellation.

Uses a real local aiohttp server (aioresponses is incompatible with the pinned
aiohttp 3.14). `_download_with_retry` runs on a minimal host that reuses the real
method + session factory, so streaming, staging → move → integrity → retry runs
end to end. Staging is redirected into the test's tmp dir so we can assert no
`tiddl-*.part.*` leftovers.
"""
from __future__ import annotations

import types

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

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
    """Minimal host for the real _download_with_retry / _get_http_session."""

    _get_http_session = Downloader._get_http_session
    _download_with_retry = Downloader._download_with_retry

    def __init__(self):
        self._http_session = None
        self.rich_output = _StubOutput()


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


async def _download(server: TestServer, task: DownloadTask) -> bool:
    url = str(server.make_url("/track"))
    dl = _StubDownloader()
    try:
        return await dl._download_with_retry(task, [url], task_id=0)
    finally:
        if dl._http_session is not None:
            await dl._http_session.close()


async def test_short_body_is_detected_and_retried(tmp_path, fast_sleep, stage_dir):
    server = await _start([("ok", 3000), ("ok", 5000)])  # short then full
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
    assert (tmp_path / "out.bin").stat().st_size == 5000
    # The per-attempt counter must reset: not 3000 + 5000 = 8000 (160%).
    assert task.bytes_downloaded == 5000
    assert task.progress_percentage == 100
    assert _no_staging_leftovers(stage_dir)


async def test_http_error_is_retried_then_succeeds(tmp_path, fast_sleep, stage_dir):
    server = await _start([("status", 500), ("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
    assert _no_staging_leftovers(stage_dir)


async def test_http_error_exhausted_fails(tmp_path, fast_sleep, stage_dir):
    server = await _start([("status", 500)])  # always 500
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == task.max_attempts == 3
    assert task.status == DownloadStatus.FAILED
    assert not (tmp_path / "out.bin").exists()
    assert _no_staging_leftovers(stage_dir)


async def test_real_truncation_is_cleaned_and_retried(tmp_path, fast_sleep, stage_dir):
    # Content-Length says 5000 but the server sends 3000 then aborts -> the client
    # raises ClientPayloadError; the partial is cleaned and the download retries.
    server = await _start([("truncate", 5000, 3000), ("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert task.status == DownloadStatus.COMPLETED
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
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == 1                     # aborted, did not retry
    assert task.status == DownloadStatus.FAILED
    assert not (tmp_path / "out.bin").exists()    # nothing published
    assert _no_staging_leftovers(stage_dir)       # partial staging file dropped
