"""`tiddl recover` — list, recover or purge files retained from a previous
session's failed/incomplete publish (see `tiddl.core.utils.retained_registry`
and PR "safe cross-filesystem publish", #12).

Deliberately a TOP-LEVEL command, not nested under `tiddl download`.

Correction (second audit review): an earlier version of this docstring
claimed nesting under `download` was technically impossible because
`download_callback` unconditionally constructs a `Downloader`/triggers TIDAL
auth. That claim was checked against the actual code and is FALSE:
`download_callback` does register `ctx.call_on_close(run)` unconditionally,
but `run()` itself (in `cli/commands/download/__init__.py`) starts with
`if not ctx.obj.resources: return` — when no subcommand added a resource,
`run()` returns immediately and never touches `ctx.obj.api` or constructs a
`Downloader`. Nesting `recover` under `download` would in fact still work
offline.

The real reason `recover` is top-level is a deliberate UX/discoverability
choice, not a technical necessity: recovery is meant to be reachable and
runnable independent of whether a user has ever touched `download` in a
given session, and keeping it top-level makes the "this never talks to
TIDAL" property obvious from `tiddl --help` rather than resting on an
internal guard clause elsewhere that could change in future refactors.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from filelock import Timeout as FileLockTimeout
from typing_extensions import Annotated

from tiddl.cli.config import CONFIG
from tiddl.cli.ctx import Context
from tiddl.core.utils import destination_anchor as anchor
from tiddl.core.utils import retained_registry as registry
from tiddl.core.utils.publish import publish_verified_file

recover_command = typer.Typer(
    name="recover",
    no_args_is_help=False,
)


def _age(created_at: str) -> str:
    try:
        created = datetime.fromisoformat(created_at)
        delta = datetime.now(timezone.utc) - created
    except (ValueError, TypeError):
        # TypeError covers a naive (tz-less) timestamp, which can't be
        # subtracted from an aware `now()` — defense in depth only; entries
        # reaching this point should already have a validated, tz-aware
        # `created_at` (see RetainedEntry.from_json_dict), but this display
        # helper must never crash the whole `recover` listing over it.
        return "?"
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _resolve(id_or_prefix: str, entries: list) -> Optional[object]:
    exact = [e for e in entries if e.entry.id == id_or_prefix]
    if exact:
        return exact[0]
    prefix_matches = [e for e in entries if e.entry.id.startswith(id_or_prefix)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def _print_registry_status_warning(console, status: str) -> None:
    # NOTE: `report.status` here comes from `registry.reconcile()`'s
    # READ-ONLY pass (`read_entries()`) — nothing has been reset, rewritten,
    # or backed up just because this command ran. A corrupt/unsupported
    # registry is only ever replaced with a backup+fresh-file as part of an
    # actual MUTATION (add/update/remove_entry, e.g. via --publish/--purge).
    # This message must describe only what has verifiably happened, not
    # what a future mutation (if any) would do.
    if status == "corrupt":
        console.print(
            "[yellow]⚠️  The retained-staging registry could not be parsed "
            f"(see {registry.registry_path()}). It has NOT been modified or "
            "reset by this listing. If you next run a command that mutates "
            "the registry (--publish/--all/--purge), the unreadable file will "
            "be backed up alongside it before a fresh one is written — see "
            f"the logs for the exact backup path. Quarantined files under "
            f"{registry.quarantine_dir()}, if any, are untouched.[/]"
        )
    elif status == "unsupported_version":
        console.print(
            "[yellow]⚠️  The retained-staging registry is from a newer/unknown "
            "version of tiddl. It has NOT been modified by this listing, and "
            "any future mutation will back it up before writing a fresh one "
            "(same as for a corrupt registry). Quarantined files, if any, are "
            "untouched.[/]"
        )
    elif status == "unreadable":
        # [P1, third audit finding #1] Distinct from 'corrupt': the file
        # could not even be READ (permissions, a sharing lock, a transient
        # network-share error) — there is no content to back up, so a
        # mutation will REFUSE outright rather than replace it (see
        # RegistryReadError). This is not a transient "nothing to worry
        # about" state; recovery is blocked until it's resolved.
        console.print(
            f"[red]⚠️  The retained-staging registry at {registry.registry_path()} "
            "could not be read (see the logs for the exact I/O error). It has "
            "NOT been modified. Any command that needs to mutate it "
            "(--publish/--all/--purge) will refuse until this is resolved — "
            "check file permissions and that nothing else has it locked.[/]"
        )


def _print_list(console, report) -> None:
    from rich.table import Table

    _print_registry_status_warning(console, report.status)

    if not report.entries and not report.orphans:
        console.print("[green]Nothing retained from a previous session.[/]")
        return

    table = Table(title="Retained files")
    table.add_column("id")
    table.add_column("status")
    table.add_column("reason")
    table.add_column("track")
    table.add_column("destination")
    table.add_column("age")

    status_colors = {
        "ok": "green", "already_published": "cyan", "gone": "red", "corrupt": "red",
    }
    for re in report.entries:
        status_color = status_colors[re.status]
        table.add_row(
            re.entry.id[:8],
            f"[{status_color}]{re.status}[/]",
            re.entry.reason.value,
            re.entry.track_title or "?",
            re.entry.output_path,
            _age(re.entry.created_at),
        )
    console.print(table)

    if report.orphans:
        console.print(
            f"[yellow]⚠️  {len(report.orphans)} file(s) in the quarantine dir with "
            "no matching registry entry (an interrupted relocation or an already-"
            "cleaned-up recovery). Left in place — inspect manually:[/]"
        )
        for p in report.orphans:
            console.print(f"    {p}")

    recoverable = [re for re in report.entries if re.status in ("ok", "already_published")]
    if recoverable:
        console.print(
            f"\n{len(recoverable)} recoverable. Run [bold]tiddl recover --publish <id>[/] "
            "for one, or [bold]tiddl recover --all --yes[/] for all of them."
        )


async def _reverify_against_entry(entry, candidate: Path) -> tuple[bool, Optional[str]]:
    size, digest = await registry.hash_and_size_async(candidate, entry.hash_algorithm)
    if size != entry.observed_size:
        return False, f"size mismatch: expected {entry.observed_size}, got {size}"
    if digest != entry.observed_hash:
        return False, f"{entry.hash_algorithm} mismatch: content differs from what was retained"
    return True, None


async def _recover_one(console, re, tracker: "anchor.IdentityFailureTracker") -> bool:
    """[P2, third audit finding #7] Wraps `_recover_one_inner` so a single
    entry's unexpected I/O failure (e.g. a file vanishing mid-hash due to an
    unrelated concurrent process, a transient network-share error) can't
    abort the rest of an `--all` batch — it's reported and the loop moves
    on, same spirit as `reconcile()`'s own per-entry error isolation.

    Returns True only when this entry reached a fully-resolved, no-further-
    action-needed outcome (a green ✓). Anything that still needs attention
    — a red ✗ error, or a yellow ⚠️ "left for a retry" outcome like a
    best-effort delete failure or a cleanup_pending→publish_pending
    demotion — returns False, so callers (`--publish`/`--all`) can exit
    non-zero instead of silently reporting overall success when something
    didn't fully complete."""
    entry = re.entry
    try:
        return await _recover_one_inner(console, re, tracker)
    except OSError as e:
        console.print(f"[red]✗[/] {entry.id[:8]}: unexpected I/O error during recovery: {e}")
        return False


async def _recover_one_inner(console, re, tracker: "anchor.IdentityFailureTracker") -> bool:
    entry = re.entry
    warnings: list = []

    if re.status == "already_published":
        # See retained_registry.reconcile(): the retained copy is already
        # gone AND the destination independently matches what was observed
        # at retention time — a prior recovery attempt already succeeded but
        # crashed/was killed before it could remove this registry entry.
        # There is no file I/O left to do; only the stale bookkeeping needs
        # to be dropped.
        await asyncio.to_thread(registry.remove_entry, entry.id)
        console.print(
            f"[green]✓[/] {entry.id[:8]}: already converged (a previous recovery "
            "attempt succeeded before it could update the registry); removed "
            "the stale entry. No file was touched."
        )
        return True

    if entry.reason == registry.RetainReason.CLEANUP_PENDING:
        dest = Path(entry.output_path)
        if dest.exists():
            ok, detail = await _reverify_against_entry(entry, dest)
        else:
            ok, detail = False, "destination missing"
        if ok:
            removed_file = await asyncio.to_thread(
                registry.delete_quarantined_file,
                Path(entry.staging_path),
                "recover cleanup-pending",
            )
            if removed_file:
                await asyncio.to_thread(registry.remove_entry, entry.id)
                console.print(
                    f"[green]✓[/] {entry.id[:8]}: destination already correct; "
                    "removed the redundant local copy."
                )
                return True
            console.print(
                f"[yellow]⚠️[/] {entry.id[:8]}: destination is correct, but the local "
                f"copy at {entry.staging_path} could not be deleted (best-effort); "
                "left in the registry, try again later."
            )
            return False
        await asyncio.to_thread(
            registry.update_entry, entry.id,
            reason=registry.RetainReason.PUBLISH_PENDING,
        )
        console.print(
            f"[yellow]⚠️[/] {entry.id[:8]}: the destination no longer matches what was "
            f"published ({detail}) — promoted to publish_pending. Run "
            f"'tiddl recover --publish {entry.id[:8]}' to publish it."
        )
        return False

    # PUBLISH_PENDING
    source = Path(entry.staging_path)
    destination = Path(entry.output_path)

    # Destination-volume identity — triple-identity check (PROPOSAL
    # v2.1 §7, kept local/untracked): entry.destination_anchor_id must equal
    # BOTH the root's current local-state anchor id AND the marker actually
    # on disk right now, not just "is the root currently trusted" — this is
    # what catches a root that was forget-ten and re-trusted with a
    # DIFFERENT anchor since the entry was staged/bound. `off` mode performs
    # no anchor I/O at all (unchanged existing behavior, per
    # destination_anchor.check_write_allowed's own "off" short-circuit).
    if CONFIG.download.destination_identity == "strict":
        if entry.destination_root is None:
            console.print(
                f"[red]✗[/] {entry.id[:8]}: no destination identity recorded for this "
                f"legacy entry — refusing in strict mode. Run 'tiddl recover --bind-root "
                f"{entry.id[:8]} --root <trusted-root>' first."
            )
            tracker.mark_refused(
                anchor.AnchorCheck(False, "unknown_root", destination, "legacy entry")
            )
            return False
        check = anchor.check_write_allowed(
            Path(entry.destination_root), destination, mode="strict",
            expected_anchor_id=entry.destination_anchor_id,
        )
        if not check.allowed:
            console.print(
                f"[red]✗[/] {entry.id[:8]}: destination identity check failed "
                f"({check.reason}); refusing to publish to {destination}. Nothing was "
                "changed — the retained local copy and registry entry are untouched."
            )
            tracker.mark_refused(check)
            return False

    def _on_warning(msg: str) -> None:
        warnings.append(msg)

    async def _reverify(candidate: Path):
        return await _reverify_against_entry(entry, candidate)

    published, retained = await publish_verified_file(
        source, destination, reverify=_reverify, on_warning=_on_warning
    )
    if published and retained is None:
        await asyncio.to_thread(registry.remove_entry, entry.id)
        console.print(f"[green]✓[/] {entry.id[:8]}: published to {destination}.")
        return True
    elif published:
        # [P1, fourth audit finding #3] The destination WAS published, but
        # the redundant local copy could not be removed (best-effort
        # cleanup failure) — that's exactly the "needs a later retry"
        # outcome this function's own contract (see `_recover_one`'s
        # docstring) says must return False, not True. An earlier version
        # printed a green checkmark and returned True here, contradicting
        # that contract: a single `--publish` or a batch `--all` could exit
        # 0 while still leaving unresolved cleanup work sitting in the
        # registry as `cleanup_pending`, with nothing telling the caller
        # that anything was still outstanding.
        await asyncio.to_thread(
            registry.update_entry, entry.id,
            reason=registry.RetainReason.CLEANUP_PENDING,
            staging_path=str(retained),
        )
        console.print(
            f"[yellow]⚠[/] {entry.id[:8]}: published to {destination}, but could not "
            f"remove the now-redundant local copy at {retained} (best-effort); "
            "run recover again later to retry cleanup."
        )
        return False
    else:
        last = warnings[-1] if warnings else "unknown error"
        console.print(
            f"[red]✗[/] {entry.id[:8]}: still could not publish to {destination} ({last})."
        )
        return False


def _is_safe_to_auto_delete(entry) -> bool:
    """Only ever auto-delete a file resolved beneath the quarantine root with
    the expected `<id><ext>` naming — never an arbitrary recorded path (a
    tampered/corrupt registry entry must not be able to trigger deletion of
    something outside tiddl's own quarantine dir)."""
    if not entry.quarantined:
        return False
    try:
        p = Path(entry.staging_path).resolve()
        qdir = registry.quarantine_dir().resolve()
    except OSError:
        return False
    return p.parent == qdir and p.stem == entry.id


@recover_command.callback(invoke_without_command=True)
def recover(
    ctx: Context,
    do_publish: Annotated[
        Optional[str],
        typer.Option("--publish", help="Recover a single entry by id (or id prefix)."),
    ] = None,
    do_all: Annotated[
        bool,
        typer.Option("--all", help="Recover every entry currently in 'ok' status."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y",
            help="Required together with --all (confirms destination-touching recovery).",
        ),
    ] = False,
    do_purge: Annotated[
        Optional[str],
        typer.Option(
            "--purge",
            help=(
                "Remove one 'gone' or 'corrupt' entry from the registry "
                "(id or id prefix). Refused for 'ok' entries."
            ),
        ),
    ] = None,
    do_bind_root: Annotated[
        Optional[str],
        typer.Option(
            "--bind-root",
            help=(
                "Bind a legacy retained entry (id or id prefix, no destination identity "
                "recorded) to an already-trusted destination root. Requires --root; "
                "the root must already be trusted via 'tiddl destination trust'."
            ),
        ),
    ] = None,
    bind_root_target: Annotated[
        Optional[Path],
        typer.Option("--root", help="The trusted root to bind --bind-root's entry to."),
    ] = None,
    bind_confirm: Annotated[
        bool,
        typer.Option(
            "--confirm",
            help="Skip the confirmation prompt for --bind-root (scripted/unattended use).",
        ),
    ] = False,
):
    """List retained files from a previous session, or recover/purge them.

    Runs entirely offline — no TIDAL login required. With no options, lists
    every retained entry and its status (ok / already_published / corrupt /
    gone) without touching any file. `--publish <id>`/`--all --yes` recover
    `ok` entries using the exact same safe-publish contract as a normal
    download (`tiddl.core.utils.publish.publish_verified_file`), and simply
    drop the registry bookkeeping for `already_published` entries (a prior
    recovery attempt already succeeded but crashed before it could update
    the registry — see `retained_registry.reconcile`). `--purge <id>`
    removes one acknowledged `gone`/`corrupt` entry from the registry —
    never an `ok` or `already_published` one. `--bind-root <id> --root
    <trusted-root>` binds a legacy entry (staged before destination-volume
    identity existed, or while it was set to "off") to an already-trusted
    root, so it becomes recoverable under `destination_identity = "strict"`.
    """
    console = ctx.obj.console
    # One tracker per `tiddl recover` invocation - command-scoped, not a
    # module global (PROPOSAL_destination_volume_identity_v2_4.md section 2,
    # kept local/untracked). Only ever touched from this event loop: every
    # identity check this command performs is a plain synchronous call, not
    # dispatched to asyncio.to_thread.
    tracker = anchor.IdentityFailureTracker()

    async def _run() -> None:
        if (
            do_purge is None and do_publish is None and not do_all and do_bind_root is None
        ):
            # Read-only listing: no mutation, no need for the cross-process
            # recovery lock — reconcile and print against a single snapshot.
            _print_list(console, await registry.reconcile())
            return

        # [P2, finding #12] Everything below this point can touch files
        # and/or the registry, and must be serialized against any other
        # `tiddl recover` process doing the same — see
        # `registry.recovery_operation_lock`'s docstring for why this is a
        # dedicated lock file rather than reusing the registry's own
        # transaction lock. The reconcile() snapshot used to decide what's
        # safe to act on is taken AFTER acquiring the lock, not before, so
        # a concurrent process's changes can't be acted on using stale
        # status information.
        try:
            lock_cm = registry.recovery_operation_lock()
            with lock_cm:
                await _run_mutating(console)
        except FileLockTimeout as e:
            console.print(
                "[red]Could not start recovery: another `tiddl recover` process "
                f"appears to be running against the same retained-staging data "
                f"({e}). Wait for it to finish and try again.[/]"
            )
            raise typer.Exit(1)
        except registry.RegistryLockTimeout as e:
            # A registry mutation (add/update/remove_entry) couldn't get the
            # registry's own transaction lock in time — surface this instead
            # of an unhandled traceback. Shouldn't normally happen while we
            # hold `recovery_operation_lock`, but the registry lock can still
            # be briefly contended by an unrelated concurrent download
            # registering a newly-retained file.
            console.print(
                f"[red]Could not complete this operation: the retained-staging "
                f"registry was locked by something else and did not become "
                f"available in time ({e}). Try again.[/]"
            )
            raise typer.Exit(1)
        except registry.RegistryPreservationError as e:
            # A registry mutation (add/update/remove_entry) refused to
            # proceed because the registry was corrupt/unsupported AND its
            # backup copy could not be written either (see
            # `retained_registry._preserve_unreadable`'s fail-closed
            # behavior) — surface this instead of letting an unhandled
            # exception crash the command with a raw traceback.
            console.print(
                f"[red]Could not complete this operation: the retained-staging "
                f"registry needed to be backed up before it could be safely "
                f"rewritten, and that backup failed ({e}). Nothing was changed. "
                "Resolve the underlying problem (disk full, permissions) and "
                "try again.[/]"
            )
            raise typer.Exit(1)
        except registry.RegistryReadError as e:
            # [P1, third audit finding #1] A registry mutation refused to
            # proceed because the registry file could not even be READ
            # (distinct from corrupt content — see RegistryReadError's
            # docstring). Nothing was written; surface this instead of an
            # unhandled traceback.
            console.print(
                f"[red]Could not complete this operation: the retained-staging "
                f"registry at {registry.registry_path()} could not be read "
                f"({e}). Nothing was changed. Resolve the underlying problem "
                "(permissions, a sharing lock, a network-share hiccup) and try "
                "again.[/]"
            )
            raise typer.Exit(1)

    async def _run_mutating(console) -> None:
        report = await registry.reconcile()

        if do_bind_root is not None:
            if bind_root_target is None:
                console.print("[red]--bind-root requires --root <trusted-root>.[/]")
                raise typer.Exit(1)

            match = _resolve(do_bind_root, report.entries)
            if match is None:
                console.print(f"[red]No unique retained entry matches id '{do_bind_root}'.[/]")
                raise typer.Exit(1)
            entry = match.entry

            # v2.2 audit's explicit correction: --bind-root stays
            # legacy-only in this PR. An already-identified entry (even one
            # whose triple-identity check would now fail, e.g. after a
            # forget+re-trust with a different anchor) refuses here, with
            # no rebind path — deliberate, documented scope for this
            # release, not a silent gap.
            if entry.destination_root is not None or entry.destination_anchor_id is not None:
                console.print(
                    f"[red]{entry.id[:8]} already has a destination identity recorded "
                    f"({entry.destination_root}) — refusing to rebind. This release "
                    "has no rebind command; resolve manually if the recorded identity "
                    "is genuinely wrong.[/]"
                )
                raise typer.Exit(1)

            root = Path(bind_root_target)
            check = anchor.check_write_allowed(root, root, mode="strict")
            if not check.allowed:
                console.print(
                    f"[red]'{root}' is not currently trusted ({check.reason}). Run "
                    f"'tiddl destination trust {root}' first.[/]"
                )
                raise typer.Exit(1)

            if not anchor.is_contained(root, Path(entry.output_path)):
                console.print(
                    f"[red]{entry.output_path} is not contained under {root} — "
                    "refusing to bind.[/]"
                )
                raise typer.Exit(1)

            _, live_anchor_id, _ = anchor.read_marker(root)

            console.print(
                f"About to bind {entry.id[:8]} ({entry.output_path}) to trusted root {root}."
            )
            if not bind_confirm and not typer.confirm("Proceed?"):
                console.print("[yellow]Aborted — nothing changed.[/]")
                raise typer.Exit(1)

            await asyncio.to_thread(
                registry.update_entry, entry.id,
                destination_root=anchor.root_key(root),
                destination_anchor_id=live_anchor_id,
            )
            console.print(
                f"[green]✓[/] Bound {entry.id[:8]} to {root} (anchor {live_anchor_id[:8]}...)."
            )
            return

        if do_purge is not None:
            match = _resolve(do_purge, report.entries)
            if match is None:
                console.print(f"[red]No unique retained entry matches id '{do_purge}'.[/]")
                raise typer.Exit(1)
            if match.status in ("ok", "already_published"):
                console.print(
                    f"[red]{match.entry.id[:8]} is still recoverable (status "
                    f"'{match.status}') — refusing to purge it. Use --publish or "
                    "--all instead.[/]"
                )
                raise typer.Exit(1)

            file_path = Path(match.entry.staging_path)
            if match.status == "corrupt" and _is_safe_to_auto_delete(match.entry):
                deleted = await asyncio.to_thread(
                    registry.delete_quarantined_file,
                    file_path,
                    "recover --purge",
                )
                if not deleted and file_path.exists():
                    # Deletion failed and the file is still there: do NOT
                    # remove the registry entry — that would orphan the file
                    # with no record of it anywhere. Leave both in place so
                    # the user (or a retry) can act on accurate information.
                    console.print(
                        f"[red]✗[/] {match.entry.id[:8]}: could not delete the "
                        f"quarantined file at {file_path} (best-effort delete "
                        "failed); the registry entry was NOT removed — try "
                        "again, or delete the file manually and re-run purge."
                    )
                    raise typer.Exit(1)
                await asyncio.to_thread(registry.remove_entry, match.entry.id)
                console.print(f"[green]✓[/] Purged {match.entry.id[:8]} ({match.status}).")
                return

            # Either the file is already gone (nothing to delete), or it's a
            # non-quarantined fallback path that purge must never auto-delete
            # (see _is_safe_to_auto_delete) — only the registry entry itself
            # is removed. Say exactly which of these happened.
            await asyncio.to_thread(registry.remove_entry, match.entry.id)
            if file_path.exists():
                console.print(
                    f"[green]✓[/] Purged {match.entry.id[:8]} ({match.status}) from the "
                    f"registry. NOTE: {file_path} was NOT auto-deleted (not a "
                    "recognized quarantine path) — left in place for manual review."
                )
            else:
                console.print(f"[green]✓[/] Purged {match.entry.id[:8]} ({match.status}).")
            return

        if do_publish is not None or do_all:
            if do_all and not yes:
                console.print(
                    "[red]--all requires --yes (bulk publication touches destinations).[/]"
                )
                raise typer.Exit(1)

            if do_publish is not None:
                match = _resolve(do_publish, report.entries)
                if match is None:
                    console.print(f"[red]No unique retained entry matches id '{do_publish}'.[/]")
                    raise typer.Exit(1)
                if match.status not in ("ok", "already_published"):
                    console.print(
                        f"[red]{match.entry.id[:8]} is not recoverable right now (status "
                        f"'{match.status}'); run 'tiddl recover' to see why.[/]"
                    )
                    raise typer.Exit(1)
                targets = [match]
            else:
                targets = [re for re in report.entries if re.status in ("ok", "already_published")]
                if not targets:
                    console.print("[green]Nothing to recover.[/]")
                    return

            # [P2, third audit finding #7] Process every target regardless
            # of earlier failures (same as before), but track whether ANY
            # of them didn't fully succeed, so the command's exit code
            # reflects that instead of always reporting 0 as long as it
            # didn't crash. A single `--publish <id>` that fails must also
            # exit non-zero — not just `--all` batches.
            all_ok = True
            for re in targets:
                ok = await _recover_one(console, re, tracker)
                all_ok = all_ok and ok
            if not all_ok:
                console.print(
                    "[red]One or more entries were not fully recovered — see the "
                    "output above for details.[/]"
                )
                raise typer.Exit(1)
            return

    asyncio.run(_run())
