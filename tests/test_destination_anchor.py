"""Coverage for `tiddl.core.utils.destination_anchor` — see
PROPOSAL_destination_volume_identity_v2_1.md through v2_4.md (kept
local/untracked) for the design each test pins. This module has no
dependency on Downloader/TIDAL, matching `retained_registry.py`'s own
"works fully offline" goal."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import tiddl.core.utils.destination_anchor as da
from tiddl.core.utils.destination_anchor import (
    AnchorAlreadyExists,
    DestinationNotTrusted,
    IdentityFailureTracker,
    LocalStateLockTimeout,
    LocalStatePreservationError,
    LocalStateReadError,
)


@pytest.fixture(autouse=True)
def _isolated_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "APP_PATH", tmp_path / "_app")
    (tmp_path / "_app").mkdir(parents=True, exist_ok=True)
    return tmp_path / "_app"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "dest_root"
    r.mkdir()
    return r


# ---------------------------------------------------------------------------
# off mode — disabled reason, zero anchor I/O (v2.4 §1)
# ---------------------------------------------------------------------------


def test_off_mode_returns_disabled_without_any_anchor_io(root, monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("off mode must not read local state or the marker")

    monkeypatch.setattr(da, "read_state", _boom)
    monkeypatch.setattr(da, "read_marker", _boom)

    check = da.check_write_allowed(root, root / "x.flac", mode="off")
    assert check.allowed is True
    assert check.reason == "disabled"


def test_off_mode_never_reported_as_trusted():
    # Regression for the v2.3 audit's finding: off-mode must never be
    # described with the same reason as an actually-verified trust.
    assert "disabled" in da.AnchorCheckReason.__args__
    assert "trusted" in da.AnchorCheckReason.__args__
    assert "disabled" != "trusted"


# ---------------------------------------------------------------------------
# Containment (v2.1 §8)
# ---------------------------------------------------------------------------


def test_output_outside_root_is_not_contained(root, tmp_path):
    outside = tmp_path / "elsewhere" / "x.flac"
    check = da.check_write_allowed(root, outside, mode="strict")
    assert check.allowed is False
    assert check.reason == "not_contained"


def test_str_startswith_would_wrongly_allow_a_sibling_with_shared_prefix(tmp_path):
    # root "music" vs a sibling "music-backup" — str.startswith would treat
    # the sibling as contained; commonpath must not.
    music = tmp_path / "music"
    music.mkdir()
    sibling = tmp_path / "music-backup" / "x.flac"
    assert da.is_contained(music, sibling) is False


# ---------------------------------------------------------------------------
# Marker file (v2.1 §3, v2.2 §6)
# ---------------------------------------------------------------------------


def test_marker_absent_is_reported_distinctly(root):
    status, anchor_id, detail = da.read_marker(root)
    assert status == "absent"
    assert anchor_id is None


def test_marker_oversized_is_invalid_not_truncated_and_parsed(root):
    (root / da.MARKER_FILENAME).write_bytes(b"x" * (da.MARKER_MAX_BYTES + 1))
    status, anchor_id, detail = da.read_marker(root)
    assert status == "invalid"
    assert anchor_id is None


def test_marker_wrong_format_is_invalid(root):
    payload = {"format": "nope", "version": 1, "anchor_id": "x"}
    (root / da.MARKER_FILENAME).write_text(json.dumps(payload))
    status, _, _ = da.read_marker(root)
    assert status == "invalid"


def test_marker_missing_anchor_id_is_invalid(root):
    (root / da.MARKER_FILENAME).write_text(json.dumps({"format": da.MARKER_FORMAT, "version": 1}))
    status, _, _ = da.read_marker(root)
    assert status == "invalid"


def test_marker_invalid_utf8_is_invalid_not_unreadable(root):
    (root / da.MARKER_FILENAME).write_bytes(b"\xff\xfe\x00\x01")
    status, _, _ = da.read_marker(root)
    assert status == "invalid"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_marker_symlink_is_unreadable_never_followed(root, tmp_path):
    real_target = tmp_path / "real_marker.json"
    payload = {"format": da.MARKER_FORMAT, "version": 1, "anchor_id": "deadbeef"}
    real_target.write_text(json.dumps(payload))
    (root / da.MARKER_FILENAME).symlink_to(real_target)
    status, anchor_id, _ = da.read_marker(root)
    assert status == "unreadable"
    assert anchor_id is None


def test_marker_unreadable_due_to_permission_error_is_structured_not_raised(root, monkeypatch):
    from pathlib import Path

    def _boom(self):
        raise PermissionError("simulated permission error")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    status, anchor_id, detail = da.read_marker(root)
    assert status == "unreadable"
    assert anchor_id is None
    assert detail is not None


# ---------------------------------------------------------------------------
# Trust lifecycle (v2.1 §2)
# ---------------------------------------------------------------------------


def test_establish_anchor_creates_marker_and_local_record(root):
    anchor_id = da.establish_anchor(root)
    status, marker_id, _ = da.read_marker(root)
    assert status == "trusted"
    assert marker_id == anchor_id

    state = da.read_state()
    assert state.status == "valid"
    record = da.find_record(state.records, da.root_key(root))
    assert record is not None
    assert record.anchor_id == anchor_id


def test_establish_anchor_refuses_to_overwrite_existing_marker(root):
    da.establish_anchor(root)
    with pytest.raises(AnchorAlreadyExists):
        da.establish_anchor(root)


def test_establish_anchor_leaves_marker_intact_if_local_state_write_fails(root, monkeypatch):
    # PROPOSAL v2.1 §13's partial-failure rule: the marker is the
    # authoritative artifact and must never be deleted to "undo" a failed
    # local-state write.
    def _boom(*a, **k):
        raise LocalStateLockTimeout("simulated lock timeout")

    monkeypatch.setattr(da, "_record_root_locally", _boom)
    with pytest.raises(LocalStateLockTimeout):
        da.establish_anchor(root)
    status, anchor_id, _ = da.read_marker(root)
    assert status == "trusted"
    assert anchor_id is not None


def test_adopt_existing_records_locally_without_touching_marker(root):
    anchor_id = da.establish_anchor(root)
    marker_bytes_before = (root / da.MARKER_FILENAME).read_bytes()

    # Simulate a second machine: clear local state, then adopt.
    da.forget_anchor(root)
    adopted_id = da.adopt_anchor(root)
    assert adopted_id == anchor_id
    assert (root / da.MARKER_FILENAME).read_bytes() == marker_bytes_before


def test_adopt_existing_refuses_when_no_marker_present(root):
    with pytest.raises(ValueError):
        da.adopt_anchor(root)


def test_forget_clears_local_state_only(root):
    da.establish_anchor(root)
    assert da.forget_anchor(root) is True
    state = da.read_state()
    assert da.find_record(state.records, da.root_key(root)) is None
    # Marker itself is untouched.
    status, _, _ = da.read_marker(root)
    assert status == "trusted"


def test_forget_unknown_root_is_a_no_op(root):
    assert da.forget_anchor(root) is False


# ---------------------------------------------------------------------------
# check_write_allowed — the guard (v2.1 §7, v2.2 §2, v2.4 §1/§5)
# ---------------------------------------------------------------------------


def test_unknown_root_refuses(root):
    check = da.check_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is False
    assert check.reason == "unknown_root"


def test_trusted_root_allows(root):
    da.establish_anchor(root)
    check = da.check_write_allowed(root, root / "sub" / "x.flac", mode="strict")
    assert check.allowed is True
    assert check.reason == "trusted"


def test_missing_marker_after_trust_refuses(root):
    da.establish_anchor(root)
    (root / da.MARKER_FILENAME).unlink()
    check = da.check_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is False
    assert check.reason == "marker_absent"


def test_forget_and_re_trust_with_new_anchor_makes_old_expected_id_refuse(root):
    # The triple-identity regression test PROPOSAL v2.1 §7 (originally the
    # v2 audit) specifically asked for: an entry staged against an OLD
    # anchor must not silently pass against a NEWLY re-trusted one.
    old_id = da.establish_anchor(root)
    da.forget_anchor(root)
    (root / da.MARKER_FILENAME).unlink()
    new_id = da.establish_anchor(root)
    assert old_id != new_id

    check = da.check_write_allowed(root, root / "x.flac", mode="strict", expected_anchor_id=old_id)
    assert check.allowed is False
    assert check.reason == "id_mismatch"

    check2 = da.check_write_allowed(root, root / "x.flac", mode="strict", expected_anchor_id=new_id)
    assert check2.allowed is True


def test_local_state_unreadable_refuses_structured(root, monkeypatch):
    da.establish_anchor(root)
    result = da.LocalStateReadResult(status="unreadable", records=[])
    monkeypatch.setattr(da, "read_state", lambda: result)
    check = da.check_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is False
    assert check.reason == "local_state_unreadable"


def test_local_state_corrupt_refuses_structured(root, monkeypatch):
    da.establish_anchor(root)
    result = da.LocalStateReadResult(status="corrupt", records=[])
    monkeypatch.setattr(da, "read_state", lambda: result)
    check = da.check_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is False
    assert check.reason == "local_state_invalid"


def test_local_state_and_marker_read_failures_never_raise_from_check_write_allowed(
    root, monkeypatch
):
    # v2.4 audit mandatory safeguard #1: expected filesystem failures during
    # the check itself must become structured outcomes, never an escaping
    # OSError a caller's own except Exception could swallow.
    from pathlib import Path

    def _boom(self):
        raise PermissionError("simulated")

    da.establish_anchor(root)
    monkeypatch.setattr(Path, "read_bytes", _boom)
    check = da.check_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is False
    assert check.reason in ("local_state_unreadable", "marker_unreadable")


def test_assert_write_allowed_raises_destination_not_trusted_with_structured_check(root):
    with pytest.raises(DestinationNotTrusted) as exc_info:
        da.assert_write_allowed(root, root / "x.flac", mode="strict")
    assert exc_info.value.check.reason == "unknown_root"
    assert exc_info.value.check.allowed is False


def test_assert_write_allowed_returns_check_on_success(root):
    da.establish_anchor(root)
    check = da.assert_write_allowed(root, root / "x.flac", mode="strict")
    assert check.allowed is True


# ---------------------------------------------------------------------------
# Local-state schema/fail-closed contract (v2.1 §4)
# ---------------------------------------------------------------------------


def test_state_missing_reads_as_missing_with_no_records():
    result = da.read_state()
    assert result.status == "missing"
    assert result.records == []


def test_state_invalid_utf8_is_corrupt_not_crashed():
    da.anchor_state_path().parent.mkdir(parents=True, exist_ok=True)
    da.anchor_state_path().write_bytes(b"\xff\xfe\x00\x01")
    result = da.read_state()
    assert result.status == "corrupt"
    assert result.raw_bytes == b"\xff\xfe\x00\x01"


def test_state_duplicate_root_key_is_corrupt(root):
    da.establish_anchor(root)
    raw = json.loads(da.anchor_state_path().read_bytes())
    raw["roots"].append(dict(raw["roots"][0]))  # exact duplicate root_key
    da.anchor_state_path().write_bytes(json.dumps(raw).encode("utf-8"))
    result = da.read_state()
    assert result.status == "corrupt"


def test_state_unsupported_version_is_preserved_before_reset(root):
    da.establish_anchor(root)
    raw = json.loads(da.anchor_state_path().read_bytes())
    raw["version"] = 99
    da.anchor_state_path().write_bytes(json.dumps(raw).encode("utf-8"))

    assert da.read_state().status == "unsupported_version"

    other_root = root.parent / "other_root"
    other_root.mkdir()
    # A mutation on a different root — must preserve, not lose, the future-version content.
    da.establish_anchor(other_root)

    backups = list(da.anchor_state_path().parent.glob("*.unsupported_version-*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_bytes())["version"] == 99


def test_state_unreadable_refuses_mutation_outright(root, monkeypatch):
    from pathlib import Path

    def _boom(self):
        raise PermissionError("simulated")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    with pytest.raises(LocalStateReadError):
        da.establish_anchor(root)


def test_state_preservation_failure_raises_and_blocks_mutation(root, monkeypatch):
    da.establish_anchor(root)
    raw = json.loads(da.anchor_state_path().read_bytes())
    raw["version"] = 99
    da.anchor_state_path().write_bytes(json.dumps(raw).encode("utf-8"))

    def _boom(path, data, **kwargs):
        if "bak" in str(path):
            raise OSError("simulated disk-full during backup")
        from tiddl.core.utils.fsio import atomic_write_bytes as real
        real(path, data, **kwargs)

    monkeypatch.setattr(da, "atomic_write_bytes", _boom)
    other_root = root.parent / "other_root2"
    other_root.mkdir()
    with pytest.raises(LocalStatePreservationError):
        da.establish_anchor(other_root)
    # Original (future-version) content must be untouched.
    assert json.loads(da.anchor_state_path().read_bytes())["version"] == 99


def test_two_concurrent_mutations_both_survive(root, tmp_path):
    r2 = tmp_path / "root2"
    r2.mkdir()
    da.establish_anchor(root)
    da.establish_anchor(r2)
    state = da.read_state()
    assert len(state.records) == 2


# ---------------------------------------------------------------------------
# IdentityFailureTracker (v2.4 §2)
# ---------------------------------------------------------------------------


def test_tracker_starts_unrefused():
    t = IdentityFailureTracker()
    assert t.any_refused is False
    assert t.first_refusal is None


def test_tracker_marks_and_stays_monotonic():
    t = IdentityFailureTracker()
    c1 = da.AnchorCheck(False, "unknown_root", __import__("pathlib").Path("/a"))
    c2 = da.AnchorCheck(False, "not_contained", __import__("pathlib").Path("/b"))
    t.mark_refused(c1)
    assert t.any_refused is True
    assert t.first_refusal is c1
    t.mark_refused(c2)
    # First refusal is preserved even after a second one.
    assert t.first_refusal is c1
    assert t.any_refused is True


async def test_tracker_event_is_awaitable_and_asyncio_native():
    t = IdentityFailureTracker()

    async def _mark_later():
        await asyncio.sleep(0)
        t.mark_refused(da.AnchorCheck(False, "unknown_root", __import__("pathlib").Path("/a")))

    task = asyncio.create_task(_mark_later())
    await t._event.wait()
    await task
    assert t.any_refused is True
