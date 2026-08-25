"""Phase 1: a cooperative safety stop (Cancel / 401 / 429) must NOT terminate
the host process.

Root cause fixed here: `download`'s group callback runs the actual download in a
`ctx.call_on_close(run)` closure (so it runs AFTER the url/fav/search subcommand
has populated the resources). Previously `run()` -> `_finish_download_run()` ->
`sys.exit()`; under the Flet-embedded interpreter that `sys.exit()` from the
teardown hard-killed the whole GUI. Now `_finish_download_run()` only RETURNS the
code, and `run()` raises `click.exceptions.Exit(code)`, which:

* the CLI entry point `tiddl.cli.app:main()` maps to a non-zero `SystemExit`, and
* the in-process host catches around `tiddl_app(standalone_mode=False)`.

These tests pin exactly that. The first group uses a faithful minimal replica
of the group-callback + call_on_close structure (Click's standalone handling
does NOT translate an Exit raised during context teardown — verified below).
The `test_real_download_*` group at the bottom then drives the REAL production
wiring end to end — the actual `tiddl download url ...` command through the real
`main()` entry point — stubbing only the orthogonal auth-refresh and the
download execution, so the fix is proven on the production path, not a replica.
"""
import sys
import types

import click
import pytest
import typer

from tiddl.cli.app import main as app_main
from tiddl.cli.commands.download import _finish_download_run


def _make_download_app(*, refused: bool = False, coop: bool = False):
    """Minimal faithful replica of the real `download` group: a sub-group whose
    callback registers a `call_on_close(run)` where `run()` calls the REAL
    `_finish_download_run` and raises `click.exceptions.Exit(code)` on non-zero —
    exactly the fixed control flow, without needing auth/network."""
    top = typer.Typer()
    dl = typer.Typer()

    @dl.callback()
    def cb(ctx: typer.Context):
        console = types.SimpleNamespace(print=lambda *a, **k: None)

        def run():
            code = _finish_download_run(console, refused, cooperative_stop=coop)
            if code:
                raise click.exceptions.Exit(code)

        ctx.call_on_close(run)

    @dl.command()
    def url():  # the subcommand "populates resources"; then close -> run()
        pass

    top.add_typer(dl, name="download")
    return typer.main.get_command(top)


def _sim_host(cmd) -> int:
    """Mirror the approved (separate) GUI `run_tiddl` contract: catch
    `click.exceptions.Exit` around the in-process `standalone_mode=False` call
    and return its code — the host must survive."""
    try:
        return int(cmd(args=["download", "url"], standalone_mode=False) or 0)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
    except SystemExit as exc:  # defensive only
        return int(exc.code or 0) if isinstance(exc.code, int) else (0 if exc.code is None else 1)


def test_exit_propagates_from_call_on_close_in_process():
    # Documents WHY the fix lives in run_tiddl/main and not in a return value:
    # an Exit raised from call_on_close PROPAGATES under standalone_mode=False
    # (Click does not translate it to a return). Click 8.4 / Typer 0.27.
    cmd = _make_download_app(coop=True)
    with pytest.raises(click.exceptions.Exit) as exc:
        cmd(args=["download", "url"], standalone_mode=False)
    assert exc.value.exit_code == 1


def test_simulated_host_survives_cancel_and_second_run_works():
    # THE key acceptance criterion: a cooperative stop must not kill the host,
    # and a SECOND in-process run must work in the same process.
    stop = _make_download_app(coop=True)   # 1st run: cooperative stop -> 1
    clean = _make_download_app(coop=False)  # 2nd run: clean -> None -> 0
    assert _sim_host(stop) == 1
    assert _sim_host(clean) == 0


def test_identity_refused_also_propagates_host_safe():
    refused = _make_download_app(refused=True)
    assert _sim_host(refused) == 1


def test_clean_run_returns_zero_in_process():
    ok = _make_download_app()  # nothing refused, no stop
    assert _sim_host(ok) == 0


def test_cli_main_translates_exit_to_systemexit(monkeypatch):
    # CLI contract: main() maps a propagated click.exceptions.Exit to a non-zero
    # SystemExit so `tiddl download ...` still exits non-zero on a safety stop.
    from tiddl.cli import app as app_mod

    def boom(*a, **k):
        raise click.exceptions.Exit(1)

    monkeypatch.setattr(app_mod, "app", boom)
    with pytest.raises(SystemExit) as exc:
        app_mod.main()
    assert exc.value.code == 1


def test_cli_main_normal_exit_is_not_translated(monkeypatch):
    from tiddl.cli import app as app_mod

    monkeypatch.setattr(app_mod, "app", lambda *a, **k: None)
    # A clean run must not raise SystemExit.
    app_mod.main()


@pytest.mark.parametrize(
    "reason, needle",
    [
        ("tidal_rate_limit", "rate-limited"),
        ("tidal_account_flagged", "flagged the account"),
        (None, "stopped the run for safety"),
        ("user", "stopped the run for safety"),
    ],
)
def test_cooperative_stop_reason_messages_return_nonzero(monkeypatch, reason, needle):
    # Cancel ("user"/None) and the engine's 429 (tidal_rate_limit) / 401
    # (tidal_account_flagged) all funnel through cooperative_stop -> return 1
    # (never raise) with a reason-specific message.
    import tiddl.core.cancel as cancel_mod

    monkeypatch.setattr(cancel_mod, "stop_reason", lambda: reason)
    printed = []
    console = types.SimpleNamespace(print=lambda *a, **k: printed.append(a))

    code = _finish_download_run(console, False, cooperative_stop=True)

    assert code == 1
    assert any(needle in str(p[0]) for p in printed if p)


# --------------------------------------------------------------------------
# REAL production-wiring tests
#
# The replica above proves the control-flow contract in isolation. These drive
# the ACTUAL `tiddl download url ...` command through the REAL `main()` entry
# point, so the real group callback, the real `ctx.call_on_close(run)`, the real
# `_finish_download_run`, the real `raise click.exceptions.Exit`, and the real
# `main()` Exit->SystemExit mapping are all exercised together. Only two
# orthogonal, network-touching pieces are stubbed so the test stays offline /
# CI-safe (no auth.json, no TIDAL calls):
#   * the auth refresh the group callback invokes (`ctx.invoke(refresh, ...)`),
#   * the download execution itself (`asyncio.run(download_resources())`),
# and `is_cancelled()` is driven to choose the cooperative-stop vs clean outcome.
# --------------------------------------------------------------------------


def _arm_real_download_via_main(monkeypatch, tmp_path, *, cancelled: bool, refused: bool):
    """Arm the REAL `tiddl download url track/<id>` invocation through the real
    `main()` and return the app module. Stubs only the auth refresh and the
    download run; leaves the exit wiring (callback -> call_on_close -> run ->
    _finish_download_run -> Exit -> main -> SystemExit) fully real."""
    import tiddl.cli.commands.download as dlinit
    from tiddl.cli import app as app_mod
    from tiddl.cli.config import CONFIG

    # 1) Auth refresh the group callback runs (ctx.invoke(refresh, ...)) — no
    #    auth.json / no network. `refresh` is a module global in download.
    monkeypatch.setattr(dlinit, "refresh", lambda *a, **k: None)
    # 2) Drive the cooperative-stop decision. `is_cancelled` is imported into the
    #    download module and read both by run() (cooperative_stop=is_cancelled())
    #    and by the (skipped) download loops.
    monkeypatch.setattr(dlinit, "is_cancelled", lambda: cancelled)

    # 3) Skip the real download; return `any_identity_refused` directly. This is
    #    the ONE seam that avoids auth/network while keeping run() 100% real.
    def _fake_asyncio_run(coro):
        coro.close()  # never awaited -> close to avoid a RuntimeWarning
        return refused

    monkeypatch.setattr(dlinit.asyncio, "run", _fake_asyncio_run)

    # Keep any (unreached) path resolution off the user's real library.
    monkeypatch.setattr(CONFIG.download, "download_path", str(tmp_path), raising=False)
    monkeypatch.setattr(CONFIG.download, "scan_path", str(tmp_path), raising=False)

    monkeypatch.setattr(sys, "argv", ["tiddl", "download", "url", "track/123"])
    return app_mod


def test_real_download_cooperative_stop_exits_nonzero_via_main(monkeypatch, tmp_path):
    # REAL wiring: a cooperative safety stop must exit NON-ZERO through main()'s
    # Exit->SystemExit — the exact production path the GUI bundles in-process.
    app_mod = _arm_real_download_via_main(monkeypatch, tmp_path, cancelled=True, refused=False)
    with pytest.raises(SystemExit) as exc:
        app_mod.main()
    assert exc.value.code == 1


def test_real_download_identity_refused_exits_nonzero_via_main(monkeypatch, tmp_path):
    # REAL wiring: an identity-refused run (no cancel) also exits non-zero.
    app_mod = _arm_real_download_via_main(monkeypatch, tmp_path, cancelled=False, refused=True)
    with pytest.raises(SystemExit) as exc:
        app_mod.main()
    assert exc.value.code == 1


def test_real_download_clean_run_is_not_nonzero_via_main(monkeypatch, tmp_path):
    # REAL wiring control: a clean run (nothing refused, no stop) must never be a
    # non-zero exit — it either returns or exits 0.
    app_mod = _arm_real_download_via_main(monkeypatch, tmp_path, cancelled=False, refused=False)
    try:
        app_mod.main()
    except SystemExit as exc:
        assert (exc.code or 0) == 0


def test_real_typer_host_reusable_survives_cancel_then_clean(monkeypatch, tmp_path):
    # THE reusable-host acceptance criterion on the REAL Typer app object (the
    # exact object the GUI bundles as `tiddl_app`), NOT the `_make_download_app`
    # replica:
    #   1. first call to the real Typer app with standalone_mode=False,
    #   2. simulated Cancel -> the host catches click.exceptions.Exit(1),
    #   3. clear the Cancel WITHOUT recreating the app object or the interpreter,
    #   4. second call to the SAME real object -> clean return 0.
    # Proves the host survives a cooperative stop and stays reusable in-process.
    import tiddl.cli.commands.download as dlinit
    from tiddl.cli.app import app as typer_app
    from tiddl.cli.config import CONFIG

    monkeypatch.setattr(dlinit, "refresh", lambda *a, **k: None)

    def _fake_asyncio_run(coro):
        coro.close()
        return False  # any_identity_refused = False (download itself not under test)

    monkeypatch.setattr(dlinit.asyncio, "run", _fake_asyncio_run)
    monkeypatch.setattr(CONFIG.download, "download_path", str(tmp_path), raising=False)
    monkeypatch.setattr(CONFIG.download, "scan_path", str(tmp_path), raising=False)

    cancelled = {"v": True}
    monkeypatch.setattr(dlinit, "is_cancelled", lambda: cancelled["v"])

    def host_call():
        """The in-process host contract (mirrors the GUI's run_tiddl): call the
        REAL Typer app with standalone_mode=False and catch the propagated exit.
        Returns (exit_code, caught_type) — caught_type pins that a cooperative
        stop reaches the host as click.exceptions.Exit, not a bare SystemExit."""
        try:
            rv = typer_app(args=["download", "url", "track/123"], standalone_mode=False)
            return int(rv or 0), None
        except click.exceptions.Exit as exc:
            return int(exc.exit_code or 0), "Exit"
        except SystemExit as exc:  # defensive; the real object raises Exit here
            code = exc.code
            return (code if isinstance(code, int) else (0 if code is None else 1)), "SystemExit"

    # 1st call: Cancel active -> host catches click.exceptions.Exit(1).
    assert host_call() == (1, "Exit")
    # Clear the Cancel WITHOUT recreating the app object or the interpreter.
    cancelled["v"] = False
    # 2nd call on the SAME real Typer object -> clean return 0. Host survived.
    assert host_call() == (0, None)


def test_python_dash_m_routes_through_the_same_main():
    # `python -m tiddl` runs tiddl/__main__.py, which must call the SAME main()
    # that maps click.exceptions.Exit -> SystemExit, so the host-safe exit
    # applies to the module entry point as well as the installed console script.
    import tiddl.__main__ as dunder

    assert dunder.main is app_main
