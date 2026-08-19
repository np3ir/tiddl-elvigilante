from types import SimpleNamespace

from tiddl.cli.commands.download.downloader import (
    _abort_for_authentication_error,
    _is_authentication_error,
    _is_rate_limit_error,
)
from tiddl.core import cancel
from tiddl.core.download_policy import SessionTrackLimit


class ResponseError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.response = SimpleNamespace(status_code=status)


def test_session_limit_warns_only_once_for_remaining_scheduled_tracks():
    policy = SessionTrackLimit(limit=1)

    assert policy.admit() == (True, False)
    assert policy.admit() == (False, True)
    assert policy.admit() == (False, False)
    assert policy.admit() == (False, False)


def test_zero_session_limit_is_unlimited():
    policy = SessionTrackLimit(limit=0)

    assert [policy.admit() for _ in range(3)] == [(True, False)] * 3


def test_http_401_is_authentication_not_rate_limit():
    error = ResponseError("401 Client Error: Limit reached while refreshing", 401)

    assert _is_authentication_error(error)
    assert not _is_rate_limit_error(error)


def test_http_429_is_rate_limit_not_authentication():
    error = ResponseError("Too Many Requests", 429)

    assert _is_rate_limit_error(error)
    assert not _is_authentication_error(error)


def test_unrelated_limit_or_rate_words_are_not_misclassified():
    assert not _is_rate_limit_error(Exception("quality Limit fallback failed"))
    assert not _is_rate_limit_error(Exception("Rate selection failed"))


def test_status_text_fallback_requires_exact_numeric_code():
    assert _is_authentication_error(Exception("401 Client Error"))
    assert _is_rate_limit_error(Exception("HTTP 429"))
    assert not _is_rate_limit_error(Exception("error 1429"))


def test_http_401_sets_run_wide_cooperative_stop():
    cancel.clear()
    try:
        assert _abort_for_authentication_error(ResponseError("Unauthorized", 401))
        assert cancel.is_cancelled()
    finally:
        cancel.clear()


def test_non_401_does_not_stop_the_run():
    cancel.clear()
    try:
        assert not _abort_for_authentication_error(ResponseError("Too Many Requests", 429))
        assert not cancel.is_cancelled()
    finally:
        cancel.clear()
