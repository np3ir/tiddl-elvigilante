"""End-to-end coverage for `tiddl destination trust/status/forget` — the
only commands allowed to mutate destination-anchor trust state (see
`tiddl.core.utils.destination_anchor` and
PROPOSAL_destination_volume_identity_v2_1.md §2, kept local/untracked).

Uses Typer's CliRunner against the real `app`, isolated to a tmp_path-backed
APP_PATH, matching tests/test_recover_cli.py's own convention.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import tiddl.core.utils.destination_anchor as da
import tiddl.core.utils.retained_registry as reg
from tiddl.cli.app import app

runner = CliRunner()


def _flat(text: str) -> str:
    """Rich's Console word-wraps long lines at terminal width, which can
    split an assertion's substring across a newline. Normalize whitespace
    before substring-checking CLI output, same idea as
    tests/test_recover_cli.py's own output assertions avoid by checking
    short fragments — these messages are long enough to need it."""
    return " ".join(text.split())


@pytest.fixture(autouse=True)
def _isolated_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "APP_PATH", tmp_path / "_app")
    # cli/app.py's root callback prints a retained-staging startup notice
    # using the registry module's own (real, unpatched) APP_PATH — isolate
    # it too so a stray real ~/.tiddl/retained_staging.json can't leak
    # unrelated warning text into this file's output assertions.
    monkeypatch.setattr(reg, "APP_PATH", tmp_path / "_app")
    return tmp_path / "_app"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "dest_root"
    r.mkdir()
    return r


def test_trust_refuses_nonexistent_path(tmp_path):
    result = runner.invoke(app, ["destination", "trust", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "does not exist" in _flat(result.output)
    assert da.read_state().records == []


def test_trust_refuses_non_directory(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    result = runner.invoke(app, ["destination", "trust", str(f)])
    assert result.exit_code == 1
    assert "not a directory" in _flat(result.output)


def test_trust_confirm_mounted_establishes_anchor(root):
    result = runner.invoke(app, ["destination", "trust", str(root), "--confirm-mounted"])
    assert result.exit_code == 0
    assert "Trusted" in result.output
    status, anchor_id, _ = da.read_marker(root)
    assert status == "trusted"
    assert anchor_id is not None


def test_trust_declined_confirmation_writes_nothing(root):
    result = runner.invoke(app, ["destination", "trust", str(root)], input="n\n")
    assert result.exit_code == 1
    status, _, _ = da.read_marker(root)
    assert status == "absent"
    assert da.read_state().records == []


def test_trust_confirmed_via_prompt_establishes_anchor(root):
    result = runner.invoke(app, ["destination", "trust", str(root)], input="y\n")
    assert result.exit_code == 0
    status, _, _ = da.read_marker(root)
    assert status == "trusted"


def test_trust_already_trusted_is_a_no_op_success(root):
    runner.invoke(app, ["destination", "trust", str(root), "--confirm-mounted"])
    before = (root / da.MARKER_FILENAME).read_bytes()
    result = runner.invoke(app, ["destination", "trust", str(root), "--confirm-mounted"])
    assert result.exit_code == 0
    assert "already trusted" in result.output
    assert (root / da.MARKER_FILENAME).read_bytes() == before


def test_trust_existing_marker_without_local_state_refuses_without_adopt_existing(root):
    da.establish_anchor(root)
    da.forget_anchor(root)  # simulate a second, fresh machine's local state
    result = runner.invoke(app, ["destination", "trust", str(root), "--confirm-mounted"])
    assert result.exit_code == 1
    assert "--adopt-existing" in result.output


def test_trust_adopt_existing_records_without_touching_destination(root):
    anchor_id = da.establish_anchor(root)
    da.forget_anchor(root)
    marker_before = (root / da.MARKER_FILENAME).read_bytes()

    result = runner.invoke(
        app, ["destination", "trust", str(root), "--adopt-existing", "--confirm-mounted"]
    )
    assert result.exit_code == 0
    assert "Adopted" in result.output
    assert (root / da.MARKER_FILENAME).read_bytes() == marker_before
    state = da.read_state()
    record = da.find_record(state.records, da.root_key(root))
    assert record is not None
    assert record.anchor_id == anchor_id


def test_trust_refuses_unreadable_marker_never_silently_adopted(root):
    (root / da.MARKER_FILENAME).write_bytes(b"\xff\xfe not json")
    result = runner.invoke(
        app, ["destination", "trust", str(root), "--adopt-existing", "--confirm-mounted"]
    )
    assert result.exit_code == 1
    assert da.read_state().records == []


def test_forget_clears_only_local_state(root):
    da.establish_anchor(root)
    result = runner.invoke(app, ["destination", "forget", str(root)])
    assert result.exit_code == 0
    assert "Forgot" in result.output
    assert da.find_record(da.read_state().records, da.root_key(root)) is None
    # Marker still exists on the "destination".
    status, _, _ = da.read_marker(root)
    assert status == "trusted"


def test_forget_unknown_root_is_informational_not_an_error(root):
    result = runner.invoke(app, ["destination", "forget", str(root)])
    assert result.exit_code == 0
    assert "nothing to do" in result.output.lower()


def test_status_single_path_trusted(root):
    da.establish_anchor(root)
    result = runner.invoke(app, ["destination", "status", str(root)])
    assert result.exit_code == 0
    assert "trusted" in result.output


def test_status_single_path_unknown(root):
    result = runner.invoke(app, ["destination", "status", str(root)])
    assert result.exit_code == 0
    assert "unknown_root" in result.output


def test_status_no_path_lists_all_known_roots(root, tmp_path):
    r2 = tmp_path / "root2"
    r2.mkdir()
    da.establish_anchor(root)
    da.establish_anchor(r2)
    result = runner.invoke(app, ["destination", "status"])
    assert result.exit_code == 0
    # The table column truncates long paths, so check structurally instead
    # of for the full path string: two roots listed, both currently trusted.
    state = da.read_state()
    assert {r.root_key for r in state.records} == {da.root_key(root), da.root_key(r2)}
    # Title ("Trusted destination roots") + two per-row "trusted" reasons.
    # \b excludes the "trusted_at" column header ("d"/"_" is not a word
    # boundary), so this counts only whole-word "trusted" occurrences.
    import re

    assert len(re.findall(r"\btrusted\b", result.output, re.IGNORECASE)) == 3


def test_status_no_roots_yet(tmp_path):
    result = runner.invoke(app, ["destination", "status"])
    assert result.exit_code == 0
    assert "No roots trusted yet" in result.output


def test_status_warns_on_corrupt_local_state(root):
    da.establish_anchor(root)
    da.anchor_state_path().write_bytes(b"not json at all")
    result = runner.invoke(app, ["destination", "status"])
    assert result.exit_code == 0
    assert "could not be parsed" in result.output


def test_trust_never_touches_registry_or_download_paths(root):
    # Sanity: `tiddl destination trust` only writes the marker + local
    # state, nothing else under APP_PATH.
    before = set((da.APP_PATH).glob("**/*")) if da.APP_PATH.exists() else set()
    runner.invoke(app, ["destination", "trust", str(root), "--confirm-mounted"])
    after = set((da.APP_PATH).glob("**/*"))
    new_files = {p.name for p in (after - before) if p.is_file()}
    assert new_files == {"destination_anchors.json", "destination_anchors.json.lock"}


def test_marker_json_matches_documented_schema(root):
    da.establish_anchor(root)
    data = json.loads((root / da.MARKER_FILENAME).read_bytes())
    assert data["format"] == "tiddl-destination-anchor"
    assert data["version"] == 1
    assert isinstance(data["anchor_id"], str) and data["anchor_id"]
