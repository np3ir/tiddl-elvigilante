"""Retry-policy coverage for `TidalAPI._fetch_with_retry`.

The HTTP layer is faked (a client whose `.fetch` yields a scripted sequence of
results/exceptions) so the policy — 429 backoff, no-retry on 4xx, bounded
network retries — is exercised deterministically. `sleep`/jitter are patched.
"""
from __future__ import annotations

import json

import pytest
from requests import Response
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import HTTPError

from tiddl.core.api.api import TidalAPI


class _FakeClient:
    """A client whose fetch() replays a scripted sequence (values or raises)."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def fetch(self, *args, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _http_error(status: int, retry_after=None, sub_status=None) -> HTTPError:
    # A REAL requests.Response. Crucially it is *falsy* at 4xx/5xx
    # (Response.__bool__ == Response.ok), which is exactly the case the
    # production classifier must handle — a Mock() is always truthy and hides it.
    resp = Response()
    resp.status_code = status
    body = {"subStatus": sub_status} if sub_status is not None else {}
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return HTTPError(response=resp)


@pytest.fixture
def sleeps(monkeypatch):
    """Capture sleep durations and zero out the jitter for determinism."""
    captured: list = []
    monkeypatch.setattr("tiddl.core.api.api.time.sleep", lambda s: captured.append(s))
    monkeypatch.setattr("tiddl.core.api.api.random.uniform", lambda *a, **k: 0.0)
    return captured


def test_429_honors_retry_after_then_succeeds(sleeps):
    client = _FakeClient([_http_error(429, retry_after=2), {"ok": True}])
    api = TidalAPI(client, "1", "US")

    result = api._fetch_with_retry("Model", "path", {})

    assert result == {"ok": True}
    assert client.calls == 2
    assert sleeps and sleeps[0] == 2.0  # Retry-After honored (jitter patched to 0)


@pytest.mark.parametrize("status,sub_status", [(401, 1234), (403, 1234), (404, None)])
def test_client_errors_are_not_retried(sleeps, status, sub_status):
    client = _FakeClient([_http_error(status, sub_status=sub_status)])
    api = TidalAPI(client, "1", "US")

    with pytest.raises(HTTPError):
        api._fetch_with_retry("Model", "path", {})

    assert client.calls == 1   # raised immediately, no retry
    assert sleeps == []


def test_network_errors_retry_up_to_the_limit(sleeps):
    # max_retries = 10 -> 11 fetches total (10 slept retries) before giving up.
    client = _FakeClient([ReqConnectionError() for _ in range(11)])
    api = TidalAPI(client, "1", "US")

    with pytest.raises(ReqConnectionError):
        api._fetch_with_retry("Model", "path", {})

    assert client.calls == 11
    assert len(sleeps) == 10
