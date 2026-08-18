"""Destination-volume identity — protects against `publish_verified_file`
(and the `mkdir`s that precede it) silently landing bytes on local disk when
a configured destination root (a NAS share, a removable drive) is supposed
to be mounted there but isn't.

Design history (kept local/untracked in the repo, not part of this diff):
`PROPOSAL_destination_volume_identity.md` (v1) through `..._v2_4.md`, each
reviewed by an independent audit before the next revision. This module
implements the contract closed across those rounds — see each file's
"Self-check" section for the exact decision each closed and which audit
finding it responds to. The short version:

* An anchor is a small marker file, `<root>/.tiddl-anchor`, written once
  when a user explicitly runs `tiddl destination trust <root>`. A download
  or `tiddl recover` NEVER creates, replaces, or rotates this file — only
  the `destination` command group mutates it. This is what avoids the v1
  design's real safety hole (an automatic in-download confirmation prompt
  could auto-approve and permanently trust a stale local directory that
  merely happens to sit where the real mount used to be).
* Trust in a root is recorded twice: on the destination itself (the marker
  file, shared by every installation pointed at that root) and locally
  (`APP_PATH/destination_anchors.json`, per-machine, never synced). A write
  is only ever allowed when both agree with each other (and, for recovery,
  with what a `RetainedEntry` was staged against) — see `check_write_allowed`.
* Everything here is read-only except `establish_anchor`/`adopt_anchor`
  (called only from `tiddl destination trust`) and `forget_anchor` (called
  only from `tiddl destination forget`). `check_write_allowed`/
  `assert_write_allowed` — what every guarded write site in the download and
  recovery paths actually calls — never mutate anything and never prompt.
* Fail-closed throughout, mirroring `retained_registry.py`'s own proven
  discipline: an I/O failure while reading the local state file is
  'unreadable' (refuse, don't guess); successfully-read-but-invalid content
  is 'unreadable'/'invalid' for the marker and 'corrupt'/'unsupported_version'
  for local state (still refuse, but this end is safe to overwrite via a
  deliberate `trust` re-run). Every expected filesystem failure a guarded
  write-site check can hit is converted into one of these structured
  outcomes INSIDE this module (see `read_state`/`read_marker`) — nothing
  currently expected propagates as a bare `OSError` out of
  `check_write_allowed`, so a caller's own pre-existing generic
  `except Exception` can never accidentally swallow an identity refusal
  (v2.4 audit, mandatory implementation safeguard #1).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from typing import Literal, NamedTuple, Optional
from uuid import uuid4

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from tiddl.cli.const import APP_PATH

from .fsio import atomic_write_bytes

log = getLogger(__name__)

#: Local-state file schema version. Bumped independently of
#: `retained_registry.REGISTRY_VERSION` — the two files have no shared
#: schema and no reason to version in lockstep.
ANCHOR_STATE_VERSION = 1
DEFAULT_LOCK_TIMEOUT = 10.0

MARKER_FILENAME = ".tiddl-anchor"
MARKER_FORMAT = "tiddl-destination-anchor"
MARKER_VERSION = 1
#: Enforced BEFORE parsing (PROPOSAL v2.1 §3) — an oversized file is
#: 'invalid', never truncated-and-parsed.
MARKER_MAX_BYTES = 4096


def anchor_state_path() -> Path:
    return APP_PATH / "destination_anchors.json"


def _lock_path() -> Path:
    return APP_PATH / "destination_anchors.json.lock"


def marker_path(root: Path) -> Path:
    return Path(root) / MARKER_FILENAME


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_for_comparison(path) -> str:
    """Lexical, comparison-only canonicalization. No `.resolve()`, no
    symlink resolution, no network I/O — deliberately mirrors
    `DownloadConfig.str_to_path`'s own reasoning (`tiddl/cli/config.py`):
    `.resolve()` round-trips over the network for a mapped/NAS drive and
    has already caused a real outage (`WinError 64`) in this codebase.

    Also strips the Windows extended-length aliases `_prepare_long_path()`
    (`tiddl/core/utils/format.py`) may already have applied to a path by the
    time it reaches a guard call downstream of the two `downloader.py` mkdir
    sites (PROPOSAL v2.3 §2) — the same alias-stripping
    `downloader._normalize_dir` already does for its own DB-path comparisons,
    duplicated here (not imported) so this module has no dependency on the
    download package and stays usable from `tiddl recover`/`tiddl destination`
    without constructing a `Downloader`."""
    s = str(path)
    if s.startswith("\\\\?\\UNC\\"):
        s = "\\\\" + s[len("\\\\?\\UNC\\"):]
    elif s.startswith("\\\\?\\"):
        s = s[len("\\\\?\\"):]
    return os.path.normcase(os.path.normpath(os.path.abspath(s)))


def root_key(path) -> str:
    """Public: the normalized lookup key, used both for local-state storage
    and for every comparison this module makes. Mapped-drive letters and
    their UNC equivalents normalize to DIFFERENT keys and are treated as
    genuinely distinct roots — not silently unified (PROPOSAL v2.1 §8)."""
    return _canonical_for_comparison(path)


def is_contained(root: Path, output_path: Path) -> bool:
    """`os.path.commonpath`-based containment — never `str.startswith()`,
    which would treat `/mnt/nas/music-backup` as contained under
    `/mnt/nas/music` (PROPOSAL v2.1 §8). Catches the `ValueError`
    `os.path.commonpath` raises on Windows when the two paths are on
    different drives, treating that exactly like "not contained"
    (PROPOSAL v2.2 §2)."""
    norm_root = root_key(root)
    norm_output = root_key(output_path)
    try:
        return os.path.commonpath([norm_root, norm_output]) == norm_root
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Marker file (`<root>/.tiddl-anchor`) — the shared, destination-side artifact.
# ---------------------------------------------------------------------------

#: 'trusted': the marker was read successfully and is well-formed (this is
#: purely about the MARKER's own readability/shape — whether its anchor_id
#: actually matches local state is a separate comparison one layer up, in
#: `check_write_allowed`). 'absent': no marker file exists yet (first-use
#: case). 'unreadable': the marker could not be physically read at all —
#: permission error, I/O error, or a symlink (refused, never followed, POSIX
#: `Path.is_symlink()` — PROPOSAL v2.1 §3). 'invalid': the marker WAS read
#: but its content doesn't match the structured schema, or exceeds the size
#: cap — mirrors `retained_registry.ReadResult`'s own
#: unreadable-vs-corrupt distinction, applied here from the start
#: (PROPOSAL v2.2 §6).
MarkerStatus = Literal["trusted", "absent", "unreadable", "invalid"]


def read_marker(root: Path) -> "tuple[MarkerStatus, Optional[str], Optional[str]]":
    """Read-only. Returns `(status, anchor_id_or_None, detail_or_None)`.
    Never raises — every filesystem failure this function can encounter
    (permission error, I/O error, a symlink) is converted into a structured
    'unreadable' result here, not left for a caller to catch."""
    p = marker_path(root)
    try:
        if p.is_symlink():
            return "unreadable", None, f"{p} is a symlink; refused, never followed"
    except OSError as e:
        return "unreadable", None, f"could not check {p} for symlink: {e}"

    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return "absent", None, None
    except OSError as e:
        return "unreadable", None, f"could not read {p}: {e}"

    if len(raw) > MARKER_MAX_BYTES:
        return "invalid", None, f"{p} exceeds the {MARKER_MAX_BYTES}-byte limit"

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return "invalid", None, f"{p} is not valid UTF-8/JSON: {e}"

    if (
        not isinstance(data, dict)
        or data.get("format") != MARKER_FORMAT
        or data.get("version") != MARKER_VERSION
    ):
        return "invalid", None, f"{p} has an unexpected format/version"

    anchor_id = data.get("anchor_id")
    if not isinstance(anchor_id, str) or not anchor_id:
        return "invalid", None, f"{p} is missing a valid anchor_id"

    return "trusted", anchor_id, None


class AnchorAlreadyExists(Exception):
    """Raised by `establish_anchor` when the marker already exists — either
    a stale precondition check (something else created it since) or a
    genuine race with another process. Creation is exclusive-only; there is
    no 'atomic replace' path for the marker in this design."""


def establish_anchor(root: Path) -> str:
    """Exclusive create: writes `root/.tiddl-anchor` with a fresh anchor id,
    fsyncs it, then records `root -> anchor_id` in local state. Mechanical
    only — the caller (`tiddl destination trust`) is responsible for
    explicit user confirmation BEFORE calling this (PROPOSAL v2.1 §2).

    If the local-state write fails AFTER the marker was created, the marker
    is left in place — it's the authoritative artifact; re-running `trust
    --adopt-existing` picks it back up (PROPOSAL v2.1 §13)."""
    root = Path(root)
    anchor_id = uuid4().hex
    payload = json.dumps(
        {"format": MARKER_FORMAT, "version": MARKER_VERSION, "anchor_id": anchor_id}
    ).encode("utf-8")
    mpath = marker_path(root)
    try:
        fd = os.open(str(mpath), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as e:
        raise AnchorAlreadyExists(str(mpath)) from e
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    _record_root_locally(root, anchor_id)
    return anchor_id


def adopt_anchor(root: Path) -> str:
    """`trust --adopt-existing`: reads the existing marker's anchor id and
    records it in THIS machine's local state only — never writes the
    destination file (PROPOSAL v2.1 §2)."""
    status, anchor_id, detail = read_marker(root)
    if status != "trusted" or anchor_id is None:
        raise ValueError(
            f"no valid existing marker to adopt at {marker_path(root)} ({status}: {detail})"
        )
    _record_root_locally(root, anchor_id)
    return anchor_id


# ---------------------------------------------------------------------------
# Local state (`APP_PATH/destination_anchors.json`) — per-machine, never
# shared or synced. Same fail-closed contract as `retained_registry.py`,
# deliberately duplicated rather than shared (PROPOSAL v2.1 §4: extracting a
# primitive out of a merged, four-round-hardened module as a side effect of
# an unrelated feature risks destabilizing it for a marginal reduction in
# near-identical, independently-testable code).
# ---------------------------------------------------------------------------

LocalStateStatus = Literal["missing", "valid", "corrupt", "unsupported_version", "unreadable"]


@dataclass
class AnchorRecord:
    root_key: str
    root_display: str
    anchor_id: str
    trusted_at: str = field(default_factory=_utcnow_iso)

    def to_json_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json_dict(d: dict) -> "AnchorRecord":
        """Raises ValueError/TypeError/KeyError on a schema violation —
        callers treat any such failure as making the WHOLE local-state file
        corrupt, not just this one record, matching
        `RetainedEntry.from_json_dict`'s own discipline: a state file that
        can silently drop a malformed record while reporting itself valid
        could lose track of a trusted root with no visible warning."""
        d = dict(d)

        key = d.get("root_key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"invalid 'root_key': {key!r}")
        if not os.path.isabs(key):
            raise ValueError(f"'root_key' is not absolute: {key!r}")

        display = d.get("root_display")
        if not isinstance(display, str) or not display:
            raise ValueError(f"invalid 'root_display': {display!r}")

        anchor_id = d.get("anchor_id")
        if not isinstance(anchor_id, str) or not anchor_id:
            raise ValueError(f"invalid 'anchor_id': {anchor_id!r}")

        trusted_at = d.get("trusted_at")
        if not isinstance(trusted_at, str):
            raise ValueError(f"invalid 'trusted_at': {trusted_at!r}")
        try:
            parsed = datetime.fromisoformat(trusted_at)
        except ValueError as e:
            raise ValueError(f"'trusted_at' is not a valid ISO timestamp: {trusted_at!r}") from e
        if parsed.tzinfo is None:
            raise ValueError(f"'trusted_at' must be timezone-aware: {trusted_at!r}")

        return AnchorRecord(
            root_key=key, root_display=display, anchor_id=anchor_id, trusted_at=trusted_at
        )


@dataclass
class LocalStateReadResult:
    status: LocalStateStatus
    records: list  # list[AnchorRecord]
    #: Exact original bytes, for `_preserve_unreadable_state` — same
    #: byte-for-byte-backup discipline as `retained_registry.ReadResult`.
    raw_bytes: Optional[bytes] = None


def _parse_state_text(text: str, raw_bytes: bytes) -> LocalStateReadResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning(
            f"Destination-anchor local state at {anchor_state_path()} is not valid JSON: {e}"
        )
        return LocalStateReadResult(status="corrupt", records=[], raw_bytes=raw_bytes)

    try:
        version = data["version"]
        raw_roots = data["roots"]
        if not isinstance(raw_roots, list):
            raise TypeError("'roots' is not a list")
    except (KeyError, TypeError) as e:
        log.warning(
            f"Destination-anchor local state at {anchor_state_path()} has an unexpected shape: {e}"
        )
        return LocalStateReadResult(status="corrupt", records=[], raw_bytes=raw_bytes)

    # Version 1 is the only version this build ever wrote or reads. Unlike
    # `retained_registry.py`, there is no legacy pre-feature format to stay
    # compatible with here — this file did not exist before this feature.
    if version != ANCHOR_STATE_VERSION:
        log.warning(
            f"Destination-anchor local state at {anchor_state_path()} is version {version!r}, "
            f"this build understands version {ANCHOR_STATE_VERSION}. Leaving it untouched."
        )
        return LocalStateReadResult(status="unsupported_version", records=[], raw_bytes=raw_bytes)

    records = []
    seen_keys = set()
    for raw in raw_roots:
        try:
            record = AnchorRecord.from_json_dict(raw)
        except (KeyError, TypeError, ValueError) as e:
            log.warning(
                f"Destination-anchor local state at {anchor_state_path()} has an unreadable "
                f"entry ({e}); treating the whole file as corrupt so nothing is silently dropped."
            )
            return LocalStateReadResult(status="corrupt", records=[], raw_bytes=raw_bytes)
        if record.root_key in seen_keys:
            # Can only happen via manual tampering or a bug — silently
            # picking one would hide that (PROPOSAL v2.1 §4).
            log.warning(
                f"Destination-anchor local state at {anchor_state_path()} has a duplicate "
                f"root_key ({record.root_key!r}); treating the whole file as corrupt."
            )
            return LocalStateReadResult(status="corrupt", records=[], raw_bytes=raw_bytes)
        seen_keys.add(record.root_key)
        records.append(record)

    return LocalStateReadResult(status="valid", records=records, raw_bytes=raw_bytes)


def read_state() -> LocalStateReadResult:
    """Read-only. Never raises — an I/O failure is 'unreadable' (nothing to
    back up, no way to know it's safe to replace); successfully-read-but-
    invalid content is 'corrupt'/'unsupported_version' (safe to back up and
    replace on a future mutation). Same byte-first-then-decode split as
    `retained_registry.read_entries` (that module's own fourth-audit-round
    fix, applied here from the start)."""
    path = anchor_state_path()
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        return LocalStateReadResult(status="missing", records=[])
    except OSError as e:
        log.warning(f"Could not read the destination-anchor local state at {path}: {e}")
        return LocalStateReadResult(status="unreadable", records=[])

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        log.warning(f"Destination-anchor local state at {path} is not valid UTF-8: {e}")
        return LocalStateReadResult(status="corrupt", records=[], raw_bytes=raw_bytes)

    return _parse_state_text(text, raw_bytes)


def find_record(records: list, key: str) -> Optional[AnchorRecord]:
    for r in records:
        if r.root_key == key:
            return r
    return None


def _write_state(records: list) -> None:
    payload = {
        "version": ANCHOR_STATE_VERSION,
        "roots": [r.to_json_dict() for r in records],
    }
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    atomic_write_bytes(anchor_state_path(), data, fsync_dir=True)


class LocalStatePreservationError(Exception):
    """Raised when a corrupt/unsupported-version local-state file could not
    be backed up before a mutation would otherwise overwrite it. The
    mutation is aborted; the original file is untouched."""


def _preserve_unreadable_state(read: LocalStateReadResult) -> None:
    if read.raw_bytes is None:
        return
    ts = _utcnow_iso().replace(":", "").replace("-", "")
    backup = anchor_state_path().with_name(f"{anchor_state_path().name}.{read.status}-{ts}.bak")
    try:
        atomic_write_bytes(backup, read.raw_bytes, fsync_dir=True)
        if backup.read_bytes() != read.raw_bytes:
            raise OSError(f"backup at {backup} did not read back identical to what was written")
    except OSError as e:
        log.error(
            f"Destination-anchor local state was {read.status} AND the backup copy could "
            f"not be written and verified ({e}); refusing to proceed with this mutation so "
            f"the original content at {anchor_state_path()} is not lost."
        )
        raise LocalStatePreservationError(str(e)) from e
    log.warning(
        f"Destination-anchor local state was {read.status}; preserved and verified the "
        f"original at {backup} before writing a fresh one."
    )


class LocalStateLockTimeout(Exception):
    """Raised when a local-state mutation could not acquire the transaction
    lock in time."""


class LocalStateReadError(Exception):
    """Raised when a local-state mutation could not even READ the file (as
    opposed to reading it and finding invalid content). Nothing is written —
    same reasoning as `retained_registry.RegistryReadError`."""


def _transaction(timeout: Optional[float] = None):
    from contextlib import contextmanager

    if timeout is None:
        timeout = DEFAULT_LOCK_TIMEOUT

    @contextmanager
    def _cm():
        lock = FileLock(str(_lock_path()), timeout=timeout)
        try:
            with lock:
                result = read_state()
                if result.status == "unreadable":
                    log.error(
                        f"Refusing to mutate the destination-anchor local state at "
                        f"{anchor_state_path()}: it could not be read, so there is nothing "
                        "to safely back up and no way to know this mutation wouldn't "
                        "silently discard whatever is actually on disk. Nothing was written."
                    )
                    raise LocalStateReadError(
                        f"could not read {anchor_state_path()} before mutating it"
                    )
                if result.status in ("corrupt", "unsupported_version"):
                    _preserve_unreadable_state(result)
                    records = []
                else:
                    records = list(result.records)
                box = {"records": records}
                yield box
                _write_state(box["records"])
        except FileLockTimeout as e:
            log.warning(
                f"Could not acquire the destination-anchor local-state lock within "
                f"{timeout}s ({e}); skipping this update (best-effort — the file itself, "
                "if any, is untouched)."
            )
            raise LocalStateLockTimeout(str(e)) from e

    return _cm()


def _record_root_locally(root: Path, anchor_id: str) -> None:
    record = AnchorRecord(root_key=root_key(root), root_display=str(root), anchor_id=anchor_id)
    with _transaction() as box:
        box["records"] = [r for r in box["records"] if r.root_key != record.root_key]
        box["records"].append(record)


def forget_anchor(root: Path) -> bool:
    """Removes `root` from LOCAL state only. Never touches the shared
    marker file — another installation, or this same machine later, may
    still depend on it existing (PROPOSAL v2.1 §2)."""
    key = root_key(root)
    removed = False
    with _transaction() as box:
        before = len(box["records"])
        box["records"] = [r for r in box["records"] if r.root_key != key]
        removed = len(box["records"]) != before
    return removed


# ---------------------------------------------------------------------------
# The guard — every write site in the download and recovery paths calls
# `assert_write_allowed`, never anything else in this module directly.
# ---------------------------------------------------------------------------

AnchorCheckReason = Literal[
    "disabled",                # mode == "off" — allowed, unverified, no anchor I/O
    "trusted",                 # allowed — local/marker agree (and expected_anchor_id, if given)
    "not_contained",           # output_path is not under root at all
    "unknown_root",            # no local-state record exists for this root yet
    "local_state_unreadable",  # local state file exists but couldn't be read
    "local_state_invalid",     # local state file read but corrupt/unsupported-version
    "marker_absent",           # no marker at root at all
    "marker_unreadable",       # marker could not be physically read (or is a symlink)
    "marker_invalid",          # marker read but structurally wrong
    "id_mismatch",             # local record, marker, and/or expected_anchor_id disagree
    "no_root_configured",      # strict mode, but the call site had no root to check at
                                # all (never produced by check_write_allowed/
                                # assert_write_allowed themselves — those always require
                                # a root argument; this reason exists for a call site,
                                # e.g. Downloader._publish_staged, that fails closed when
                                # its own root-bearing task/config is missing a root
                                # while running in strict mode. Implementation-audit
                                # finding, P1 #2: previously such a call site skipped
                                # the guard entirely instead of refusing).
]


class AnchorCheck(NamedTuple):
    allowed: bool
    reason: AnchorCheckReason
    root: Path
    detail: Optional[str] = None
    #: Set only when reason == "trusted" — the live, verified anchor id
    #: (i.e. local-state record and on-disk marker already agreed, and
    #: matched expected_anchor_id when one was given). None for every other
    #: reason, including "disabled" (off mode never reads it) — a caller
    #: that wants to persist "this write happened against a verified
    #: anchor" (e.g. retained_registry.register_retained_file's
    #: destination_root/destination_anchor_id pair) reads this field
    #: instead of re-deriving it, added after an audit finding that no
    #: caller could actually recover this value from a passing check.
    anchor_id: Optional[str] = None


class DestinationNotTrusted(Exception):
    """Raised only by `assert_write_allowed`. Carries the full structured
    `AnchorCheck` that caused the refusal (never a bare string) so a
    catching call site can read `check.reason`/`check.root` for CLI/log
    messages without re-deriving anything."""

    def __init__(self, check: AnchorCheck) -> None:
        self.check = check
        super().__init__(f"destination write refused ({check.reason}) for root {check.root}")


def check_write_allowed(
    root: Path,
    output_path: Path,
    mode: Literal["off", "strict"],
    expected_anchor_id: Optional[str] = None,
) -> AnchorCheck:
    """Pure, read-only decision. Never raises for any anchor-domain outcome
    — including every "expected untrusted" case (unknown root, absent/
    invalid marker, id mismatch) AND every expected filesystem failure
    while checking (an unreadable local-state file, an unreadable/symlinked
    marker) — all of those become a structured `AnchorCheck` with
    `allowed=False`, never a propagated `OSError` (v2.4 audit, mandatory
    safeguard #1: `read_state`/`read_marker` already convert every I/O
    failure they can encounter into a structured result before it ever
    reaches this function). A genuinely unexpected exception (a bug in this
    module itself) is not something this function tries to catch."""
    root = Path(root)
    output_path = Path(output_path)

    if mode == "off":
        return AnchorCheck(True, "disabled", root)

    if not is_contained(root, output_path):
        return AnchorCheck(False, "not_contained", root, f"{output_path} is not under {root}")

    state = read_state()
    if state.status == "unreadable":
        return AnchorCheck(
            False, "local_state_unreadable", root, "local anchor state could not be read"
        )
    if state.status in ("corrupt", "unsupported_version"):
        return AnchorCheck(
            False, "local_state_invalid", root, f"local anchor state is {state.status}"
        )

    record = find_record(state.records, root_key(root))
    if record is None:
        return AnchorCheck(False, "unknown_root", root, "no trust record for this root")

    marker_status, marker_anchor_id, marker_detail = read_marker(root)
    if marker_status == "absent":
        return AnchorCheck(False, "marker_absent", root, marker_detail)
    if marker_status == "unreadable":
        return AnchorCheck(False, "marker_unreadable", root, marker_detail)
    if marker_status == "invalid":
        return AnchorCheck(False, "marker_invalid", root, marker_detail)

    # marker_status == "trusted" (present & well-formed) from here on.
    if marker_anchor_id != record.anchor_id:
        return AnchorCheck(False, "id_mismatch", root, "local state and marker anchor ids disagree")
    if expected_anchor_id is not None and expected_anchor_id != marker_anchor_id:
        return AnchorCheck(
            False, "id_mismatch", root,
            "the recorded entry's anchor id does not match the currently live anchor",
        )

    return AnchorCheck(True, "trusted", root, anchor_id=marker_anchor_id)


def assert_write_allowed(
    root: Path,
    output_path: Path,
    mode: Literal["off", "strict"],
    expected_anchor_id: Optional[str] = None,
) -> AnchorCheck:
    """Thin wrapper: every one of the guarded write sites calls THIS
    function, never `check_write_allowed` directly — a site's job is
    'proceed' or 'stop this operation', which is exactly what a raise/return
    split gives without a separate if-allowed branch at every call site."""
    check = check_write_allowed(root, output_path, mode, expected_anchor_id)
    if not check.allowed:
        raise DestinationNotTrusted(check)
    return check


def anchor_status(root: Path) -> AnchorCheck:
    """Read-only status report for `tiddl destination status`. Always
    evaluated as if mode='strict', regardless of the configured
    `destination_identity` — status reporting must reflect the real state
    of the world, not whatever a user currently has downloads set to."""
    root = Path(root)
    return check_write_allowed(root, root, mode="strict")


# ---------------------------------------------------------------------------
# Command-scoped, monotonic partial-failure tracking for concurrent
# downloads (PROPOSAL v2.4 §2). One instance per `tiddl download`/`tiddl
# recover` invocation, passed explicitly by the caller — never a module
# global. Only ever touched from the event-loop thread: every guarded call
# site in this feature places its `assert_write_allowed()` check BEFORE
# dispatching the corresponding write to `asyncio.to_thread(...)`, never
# inside the threaded function itself (see downloader.py/download/__init__.py
# for the call sites) — so `mark_refused` is never invoked from a worker
# thread by construction, and a plain `asyncio.Event` is safe (v2.4 audit,
# mandatory implementation safeguard #2).
# ---------------------------------------------------------------------------


class IdentityFailureTracker:
    def __init__(self) -> None:
        import asyncio

        self._event = asyncio.Event()
        self._first: Optional[AnchorCheck] = None

    def mark_refused(self, check: AnchorCheck) -> None:
        if not self._event.is_set():
            self._first = check
        self._event.set()

    @property
    def any_refused(self) -> bool:
        return self._event.is_set()

    @property
    def first_refusal(self) -> Optional[AnchorCheck]:
        return self._first
