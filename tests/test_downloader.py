"""Downloader coverage (block 2): a short/mismatched body is detected and
retried, an HTTP error is retried, and a mid-stream cancel aborts without
retrying and without publishing a partial file.

Uses a real local aiohttp server (aioresponses is incompatible with aiohttp
3.14), so the client stack, streaming, staging → move → integrity → retry path
is exercised end to end. `_download_with_retry` runs on a minimal host that
reuses the real method + session factory.
"""
from __future__ import annotations

import types

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tiddl.cli.commands.download.downloader import Downloader, DownloadTask
from tiddl.core import cancel

AUDIO_CT = "audio/flac"  # not json/text/xml -> treated as audio by the downloader


class _StubOutput:
    def __init__(self):
        self.console = types.SimpleNamespace(print=lambda *a, **k: None)

    def download_advance(self, task_id, size=0):
        pass


class _StubDownloader:
    """Minimal host for the real _download_with_retry / _get_http_session."""

    _get_http_session = Downloader._get_http_session
    _download_with_retry = Downloader._download_with_retry

    def __init__(self):
        self._http_session = None
        self.rich_output = _StubOutput()


def _scripted_app(script: list) -> web.Application:
    """A /track handler that replays `script` (one spec per request):
    ("ok", n) -> 200 with n bytes; ("status", code) -> that status."""
    state = {"i": 0}

    async def handler(request):
        spec = script[min(state["i"], len(script) - 1)]
        state["i"] += 1
        if spec[0] == "ok":
            return web.Response(body=b"\x00" * spec[1], content_type=AUDIO_CT)
        if spec[0] == "status":
            return web.Response(status=spec[1], content_type=AUDIO_CT)
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
    """Skip the downloader's 2s retry back-off so retry tests stay fast."""
    async def _instant(*_a, **_k):
        return None

    import tiddl.cli.commands.download.downloader as dl
    monkeypatch.setattr(dl.asyncio, "sleep", _instant)


async def _download(server: TestServer, task: DownloadTask) -> bool:
    url = str(server.make_url("/track"))
    dl = _StubDownloader()
    try:
        return await dl._download_with_retry(task, [url], task_id=0)
    finally:
        if dl._http_session is not None:
            await dl._http_session.close()


async def test_short_body_is_detected_and_retried(tmp_path, fast_sleep):
    server = await _start([("ok", 3000), ("ok", 5000)])  # short then full
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2
    assert (tmp_path / "out.bin").stat().st_size == 5000


async def test_http_error_is_retried_then_succeeds(tmp_path, fast_sleep):
    server = await _start([("status", 500), ("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is True
    assert task.attempts == 2


async def test_cancellation_midstream_aborts_without_retry(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_is_cancelled():
        calls["n"] += 1
        return calls["n"] >= 2  # False at the top-of-loop check, True at the first chunk

    monkeypatch.setattr("tiddl.core.cancel.is_cancelled", fake_is_cancelled)
    server = await _start([("ok", 5000)])
    try:
        task = DownloadTask(url="x", output_path=tmp_path / "out.bin", expected_size=5000)
        ok = await _download(server, task)
    finally:
        await server.close()

    assert ok is False
    assert task.attempts == 1                    # aborted, did not retry
    assert not (tmp_path / "out.bin").exists()   # partial dropped, nothing published
