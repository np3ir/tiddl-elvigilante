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

These tests pin exactly that, with a faithful minimal replica of the real
group-callback + call_on_close structure (Click's standalone handling does NOT
translate an Exit raised during context teardown — verified below).
"""
import types

import click
import pytest
import typer

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
