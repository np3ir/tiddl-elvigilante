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


async def test_session_limit_counts_new_downloads_and_warns_once():
    # The cap counts NEW downloads (commit), not admitted tracks. A track is
    # reserved, downloaded, committed; the commit that reaches the cap latches the
    # signal and returns the one-shot warning flag.
    policy = SessionTrackLimit(limit=1)

    assert await policy.reserve() is True       # under quota -> reserved
    assert not policy.is_reached()
    assert policy.commit() is True              # the one allowed NEW download
    assert policy.is_reached()                  # quota used -> run-wide signal
    assert await policy.reserve() is False      # now closed
    assert await policy.reserve() is False


async def test_existing_files_release_their_reservation_without_charge():
    # An already-present track releases its reserved slot (was_downloaded=False)
    # and does NOT eat the quota, so a run over a mostly-downloaded library keeps
    # working on the missing tracks.
    policy = SessionTrackLimit(limit=2)

    assert await policy.reserve() is True
    policy.release()                            # already on disk -> slot back
    assert not policy.is_reached()
    assert await policy.reserve() is True       # still open after the release
    assert policy.commit() is False             # downloaded=1 < 2
    assert await policy.reserve() is True
    assert policy.commit() is True              # downloaded=2 == 2 -> reached
    assert policy.is_reached()


async def test_zero_session_limit_is_unlimited():
    policy = SessionTrackLimit(limit=0)

    for _ in range(3):
        assert await policy.reserve() is True
    # commit/release are no-ops when disabled and never latch the signal.
    for _ in range(5):
        assert policy.commit() is False
    assert not policy.is_reached()
    assert await policy.reserve() is True


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
