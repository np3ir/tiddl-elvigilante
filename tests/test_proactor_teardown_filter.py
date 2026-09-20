"""The benign Windows ProactorEventLoop socket-teardown error must be muted.

On Windows, asyncio's ProactorEventLoop raises OSError [WinError 10022]
(WSAEINVAL) from _ProactorBasePipeTransport._call_connection_lost when aiohttp
closes an already-disconnected socket. It fires AFTER the transfer completes, so
it is cosmetic, but its traceback is emitted by the loop's default exception
handler (not the warnings system, so the ResourceWarning filter cannot mute it)
and floods the CLI log / GUI console.

These tests pin the predicate and the loop-handler installer. They are
cross-platform: the WinError is simulated by setting `.winerror` on a plain
OSError, so the True path is exercised on Linux/macOS CI too.
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


def test_predicate_matches_only_winerror_10022():
    assert _is_benign_proactor_teardown({"exception": _oserror(10022)}) is True
    # A different OSError winerror is a real failure — do not swallow it.
    assert _is_benign_proactor_teardown({"exception": _oserror(10054)}) is False
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
        benign = {"exception": _oserror(10022)}
        other = {"exception": _oserror(10054)}

        handler(fake, benign)  # swallowed -> not delegated
        handler(fake, other)   # real error -> delegated to default

        assert delegated == [other]
    finally:
        loop.close()
