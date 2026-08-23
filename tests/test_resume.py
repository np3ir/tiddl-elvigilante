"""Coverage for the opt-in resume checkpoint (tiddl.core.resume)."""
from __future__ import annotations

from types import SimpleNamespace

from tiddl.core.resume import ResumeLog, compute_signature, resource_key


def test_resource_key_format():
    r = SimpleNamespace(type="artist", id="26125")
    assert resource_key(r) == "artist/26125"


def test_signature_is_stable_and_order_independent():
    a = compute_signature({"resources": ["artist/1", "artist/2"], "quality": "high"})
    b = compute_signature({"quality": "high", "resources": ["artist/1", "artist/2"]})
    assert a == b
    assert len(a) == 16


def test_signature_changes_with_fields():
    base = {"resources": ["artist/1"], "quality": "high", "audio_mode": "auto"}
    changed = {**base, "audio_mode": "stereo"}
    assert compute_signature(base) != compute_signature(changed)


def test_empty_when_no_file(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    assert log.count == 0
    assert log.is_done("artist/1") is False


def test_mark_done_persists_across_reload(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    log.mark_done("artist/1")
    log.mark_done("album/9")
    # A fresh instance for the same signature/dir sees the persisted set.
    reloaded = ResumeLog("sig", base_dir=tmp_path).load()
    assert reloaded.is_done("artist/1")
    assert reloaded.is_done("album/9")
    assert reloaded.is_done("artist/2") is False
    assert reloaded.count == 2


def test_mark_done_is_idempotent(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    log.mark_done("artist/1")
    log.mark_done("artist/1")
    assert log.count == 1


def test_different_signatures_do_not_share(tmp_path):
    a = ResumeLog("sigA", base_dir=tmp_path).load()
    a.mark_done("artist/1")
    b = ResumeLog("sigB", base_dir=tmp_path).load()
    assert b.is_done("artist/1") is False
    assert b.count == 0


def test_corrupt_file_loads_as_empty(tmp_path):
    (tmp_path / "sig.json").write_text("{ this is not json", encoding="utf-8")
    log = ResumeLog("sig", base_dir=tmp_path).load()
    assert log.count == 0  # never raises, just starts fresh


def test_clear_removes_the_checkpoint(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    log.mark_done("artist/1")
    assert (tmp_path / "sig.json").exists()
    log.clear()
    assert log.count == 0
    assert not (tmp_path / "sig.json").exists()


def test_mark_many(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    log.mark_many(["artist/1", "artist/2", "artist/1"])
    assert log.count == 2
    assert ResumeLog("sig", base_dir=tmp_path).load().is_done("artist/2")


def test_no_temp_file_left_behind(tmp_path):
    log = ResumeLog("sig", base_dir=tmp_path).load()
    log.mark_done("artist/1")
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []  # atomic rename cleaned up the temp
