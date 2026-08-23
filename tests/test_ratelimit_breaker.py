"""Run-wide 429 circuit breaker + cooperative-stop coverage.

The guard (``tiddl.core.ratelimit``) and the cancel flag (``tiddl.core.cancel``)
are process-wide, so every test resets them to the default budget. ``time.sleep``
is patched so the backoff waits don't slow the suite.
"""
from __future__ import annotations

import json

import pytest
from requests import Response
from requests.exceptions import HTTPError

from tiddl.core import cancel, ratelimit
from tiddl.core.api.api import TidalAPI


@pytest.fixture(autouse=True)
def _reset_and_no_sleep(monkeypatch):
    cancel.clear()
    ratelimit.guard().reset(strike_limit=ratelimit.DEFAULT_STRIKE_LIMIT)
    monkeypatch.setattr("tiddl.core.api.api.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("tiddl.core.api.api.random.uniform", lambda *a, **k: 0.0)
    yield
    cancel.clear()
    ratelimit.guard().reset(strike_limit=ratelimit.DEFAULT_STRIKE_LIMIT)


def _http_error(status: int, retry_after=None, sub_status=None) -> HTTPError:
    resp = Response()
    resp.status_code = status
    body = {"subStatus": sub_status} if sub_status is not None else {}
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return HTTPError(response=resp)


class _Always429:
    def __init__(self, refresh_blocked: bool = False):
        self.calls = 0
        self._refresh_blocked = refresh_blocked

    def fetch(self, *a, **k):
        self.calls += 1
        raise _http_error(429, retry_after=0)


# --------------------------------------------------------------------------
# Guard unit
# --------------------------------------------------------------------------

def test_guard_trips_exactly_once_at_limit():
    g = ratelimit.RateLimitGuard(strike_limit=3)
    assert g.note_rate_limited() is False  # strike 1
    assert g.note_rate_limited() is False  # strike 2
    assert g.note_rate_limited() is True   # strike 3 -> trips
    assert g.note_rate_limited() is False  # already tripped, never re-fires
    assert g.tripped is True
    assert g.strikes == 4


def test_guard_reset_rearms():
    g = ratelimit.RateLimitGuard(strike_limit=2)
    g.note_rate_limited()
    assert g.note_rate_limited() is True
    g.reset()
    assert g.strikes == 0
    assert g.tripped is False
    assert g.note_rate_limited() is False  # counts from zero again


# --------------------------------------------------------------------------
# _fetch_with_retry integration
# --------------------------------------------------------------------------

def test_sustained_429_trips_cooperative_stop():
    # A low budget so the breaker trips within one request's retry schedule.
    ratelimit.guard().reset(strike_limit=3)
    client = _Always429()
    api = TidalAPI(client, "1", "US")

    with pytest.raises(HTTPError):
        api._fetch_with_retry("Model", "path", {})

    # 3rd 429 trips the breaker; the is_cancelled() check then bails the retry.
    assert client.calls == 3
    assert cancel.is_cancelled() is True
    assert cancel.stop_reason() == "tidal_rate_limit"


def test_transient_429_below_limit_does_not_stop():
    ratelimit.guard().reset(strike_limit=5)
    # One 429 then success: a normal transient blip must NOT trip anything.
    class _OneThenOk:
        def __init__(self):
            self.calls = 0

        def fetch(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise _http_error(429, retry_after=1)
            return {"ok": True}

    client = _OneThenOk()
    api = TidalAPI(client, "1", "US")

    assert api._fetch_with_retry("Model", "path", {}) == {"ok": True}
    assert client.calls == 2
    assert cancel.is_cancelled() is False
    assert cancel.stop_reason() is None


def test_flagged_account_401_trips_stop():
    class _Flagged:
        def __init__(self):
            self.calls = 0
            self._refresh_blocked = True

        def fetch(self, *a, **k):
            self.calls += 1
            raise _http_error(401, sub_status=1234)

    client = _Flagged()
    api = TidalAPI(client, "1", "US")

    with pytest.raises(HTTPError):
        api._fetch_with_retry("Model", "path", {})

    assert client.calls == 1  # 401 is not retried
    assert cancel.stop_reason() == "tidal_account_flagged"


def test_unflagged_401_does_not_stop_the_run():
    # A plain 401 whose refresh is NOT blocked must still just raise for this
    # one call, without stopping the whole run.
    class _Plain401:
        def __init__(self):
            self.calls = 0
            self._refresh_blocked = False

        def fetch(self, *a, **k):
            self.calls += 1
            raise _http_error(401, sub_status=1234)

    client = _Plain401()
    api = TidalAPI(client, "1", "US")

    with pytest.raises(HTTPError):
        api._fetch_with_retry("Model", "path", {})

    assert client.calls == 1
    assert cancel.is_cancelled() is False
    assert cancel.stop_reason() is None


def test_user_cancel_stops_retry_storm():
    # A user cancel mid-run must make an in-flight retrying request give up at
    # once instead of sleeping through its whole backoff schedule.
    cancel.request_cancel("user")
    client = _Always429()
    api = TidalAPI(client, "1", "US")

    with pytest.raises(HTTPError):
        api._fetch_with_retry("Model", "path", {})

    assert client.calls == 1  # one 429, then bail — no retry storm
    assert cancel.stop_reason() == "user"
