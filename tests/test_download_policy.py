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


def test_session_limit_counts_new_downloads_and_warns_once():
    # New semantic: the cap counts NEW downloads (record), not admitted tracks.
    # A track is admitted, downloaded, recorded; once the quota of downloads is
    # used up the gate closes and warns exactly once.
    policy = SessionTrackLimit(limit=1)

    assert policy.admit() == (True, False)      # under quota -> admitted
    assert not policy.is_reached()
    policy.record(was_downloaded=True)          # the one allowed NEW download
    assert policy.is_reached()                  # quota used -> run-wide signal
    assert policy.admit() == (False, True)      # now closed, announce once
    assert policy.admit() == (False, False)
    assert policy.admit() == (False, False)


def test_existing_files_do_not_consume_the_cap():
    # Already-present tracks (was_downloaded=False) must NOT eat the quota, so a
    # run over a mostly-downloaded library keeps working on the missing tracks.
    policy = SessionTrackLimit(limit=2)

    assert policy.admit() == (True, False)
    policy.record(was_downloaded=False)         # already on disk -> no charge
    policy.record(was_downloaded=False)
    assert not policy.is_reached()
    assert policy.admit() == (True, False)      # still open after two skips
    policy.record(was_downloaded=True)          # 1st real download
    assert not policy.is_reached()
    policy.record(was_downloaded=True)          # 2nd real download -> quota used
    assert policy.is_reached()
    assert policy.admit() == (False, True)


def test_zero_session_limit_is_unlimited():
    policy = SessionTrackLimit(limit=0)

    assert [policy.admit() for _ in range(3)] == [(True, False)] * 3
    # record is a no-op when disabled and never latches the signal.
    for _ in range(5):
        policy.record(was_downloaded=True)
    assert not policy.is_reached()
    assert policy.admit() == (True, False)


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
