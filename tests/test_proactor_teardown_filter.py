"""The benign Windows ProactorEventLoop socket-teardown error must be muted.

On Windows, asyncio's ProactorEventLoop raises OSError [WinError 10022]
(WSAEINVAL) from _ProactorBasePipeTransport._call_connection_lost when aiohttp
closes an already-disconnected socket. It fires AFTER the transfer completes, so
it is cosmetic, but its traceback is emitted by the loop's default exception
handler (not the warnings system, so the ResourceWarning filter cannot mute it)
and floods the CLI log / GUI console.

These tests pin the predicate and the loop-handler installer. They are
cross-platform: the WinError is simulated by setting `.winerror` on a plain
OSError, and the teardown callback is simulated by a handle whose `_callback`
carries the matching `__qualname__`, so the True path is exercised on
Linux/macOS CI too.
"""
import asyncio

from tiddl.cli.commands.download import (
    _install_proactor_teardown_filter,
    _is_benign_proactor_teardown,
)


def _oserror(winerror):
    exc = OSError("simulated")
    exc.winerror = winerror
    return exc


def _teardown_handle(qualname="_ProactorBasePipeTransport._call_connection_lost"):
    """A fake asyncio Handle whose _callback mimics the teardown callback."""
    def _cb():  # pragma: no cover - never called
        ...
    _cb.__qualname__ = qualname

    class _Handle:
        _callback = _cb

    return _Handle()


def _teardown_ctx(winerror=10022, qualname="_ProactorBasePipeTransport._call_connection_lost"):
    return {"exception": _oserror(winerror), "handle": _teardown_handle(qualname)}


def test_predicate_matches_only_proactor_teardown_10022():
    # Benign: WinError 10022 raised from the Proactor teardown callback.
    assert _is_benign_proactor_teardown(_teardown_ctx()) is True
    # Same winerror but a DIFFERENT source (unrelated task) must NOT be swallowed.
    assert _is_benign_proactor_teardown(_teardown_ctx(qualname="SomeOther.run")) is False
    # A qualname that only *ends with* the teardown suffix (not exactly it) must
    # NOT be swallowed — the match is exact, not endswith.
    assert _is_benign_proactor_teardown(
        _teardown_ctx(qualname="evil._ProactorBasePipeTransport._call_connection_lost")
    ) is False
    # WinError 10022 with no handle context is not the teardown callback either.
    assert _is_benign_proactor_teardown({"exception": _oserror(10022)}) is False
    # A different OSError winerror is a real failure — do not swallow it.
    assert _is_benign_proactor_teardown(_teardown_ctx(winerror=10054)) is False
    # A non-OSError exception is unrelated.
    assert _is_benign_proactor_teardown({"exception": ValueError("x")}) is False
    # A message-only context (no exception) must not be swallowed.
    assert _is_benign_proactor_teardown({"message": "boom"}) is False


def test_installer_swallows_benign_and_delegates_others():
    loop = asyncio.new_event_loop()
    try:
        _install_proactor_teardown_filter(loop)
        handler = loop.get_exception_handler()
        assert handler is not None

        delegated = []

        class _FakeLoop:
            def default_exception_handler(self, context):
                delegated.append(context)

        fake = _FakeLoop()
        benign = _teardown_ctx()                          # Proactor teardown 10022
        other = {"exception": _oserror(10054)}            # real error
        unrelated_10022 = {"exception": _oserror(10022)}  # 10022 from elsewhere

        handler(fake, benign)            # swallowed -> not delegated
        handler(fake, other)             # real error -> delegated to default
        handler(fake, unrelated_10022)   # not the teardown callback -> delegated

        assert delegated == [other, unrelated_10022]
    finally:
        loop.close()
