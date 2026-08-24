"""Coverage for the opt-in resume checkpoint (tiddl.core.resume)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tiddl.core.resume import ResumeLog, compute_signature, job_signature, resource_key


def _base_job():
    """A full, valid set of job_signature() inputs to mutate one field at a time."""
    return dict(
        resources=["artist/1", "album/2"],
        download_path="Z:/Music",
        video_download_path="Z:/Videos",
        quality="high",
        video_quality="fhd",
        audio_mode="auto",
        edition_match="best",
        quality_policy="flexible",
        hires_client="auto",
        expand="artists",
        exclude_compilations=False,
        exclude_live_albums=False,
        singles="include",
        videos_filter="none",
        templates={
            "default": "d", "track": "t", "album": "a", "playlist": "p",
            "video": "v", "mix": "m", "artist_separator": " / ",
        },
        metadata={
            "enable": True, "cover": True, "lyrics": True, "save_lyrics": False,
            "album_review": False, "update_mtime": False, "rewrite": False,
        },
        cover_file={
            "save": False, "size": 1280, "allowed": [],
            "tpl_track": "", "tpl_album": "", "tpl_playlist": "",
        },
        m3u={
            "save": False, "allowed": [],
            "tpl_album": "", "tpl_playlist": "", "tpl_mix": "",
        },
    )


def test_job_signature_is_stable():
    assert job_signature(**_base_job()) == job_signature(**_base_job())


# One mutation per output-affecting option/group — each MUST change the signature
# so a resource completed under the old settings is not wrongly skipped.
@pytest.mark.parametrize("mutate", [
    lambda k: k.update(resources=["artist/1"]),
    lambda k: k.update(download_path="D:/Other"),
    lambda k: k.update(video_download_path="D:/V"),
    lambda k: k.update(quality="max"),
    lambda k: k.update(video_quality="hd"),
    lambda k: k.update(audio_mode="stereo"),
    lambda k: k.update(edition_match="ask"),
    lambda k: k.update(quality_policy="strict"),
    lambda k: k.update(hires_client="never"),
    lambda k: k.update(expand="albums"),
    lambda k: k.update(exclude_compilations=True),
    lambda k: k.update(exclude_live_albums=True),
    lambda k: k.update(singles="only"),
    lambda k: k.update(videos_filter="all"),
    lambda k: k.__setitem__("templates", {**k["templates"], "album": "CHANGED"}),
    lambda k: k.__setitem__("templates", {**k["templates"], "artist_separator": ", "}),
    lambda k: k.__setitem__("metadata", {**k["metadata"], "cover": False}),
    lambda k: k.__setitem__("metadata", {**k["metadata"], "enable": False}),
    lambda k: k.__setitem__("metadata", {**k["metadata"], "rewrite": True}),
    lambda k: k.__setitem__("cover_file", {**k["cover_file"], "save": True}),
    lambda k: k.__setitem__("cover_file", {**k["cover_file"], "size": 640}),
    lambda k: k.__setitem__("cover_file", {**k["cover_file"], "allowed": ["album"]}),
    lambda k: k.__setitem__("cover_file", {**k["cover_file"], "tpl_album": "X"}),
    lambda k: k.__setitem__("m3u", {**k["m3u"], "save": True}),
    lambda k: k.__setitem__("m3u", {**k["m3u"], "allowed": ["playlist"]}),
    lambda k: k.__setitem__("m3u", {**k["m3u"], "tpl_mix": "X"}),
])
def test_job_signature_sensitive_to_every_output_option(mutate):
    base = _base_job()
    changed = _base_job()
    mutate(changed)
    assert job_signature(**changed) != job_signature(**base)


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
