"""Directory-scoped "Exists (Alt)" check — regression + contract.

The bug: a GLOBAL stem index reported a same-named file from ANOTHER album's
folder (a Deluxe/standard release vs its separate Dolby Atmos Version), so tiddl
falsely skipped an Atmos track and then tried to tag a file that isn't there
(`[WinError 2] The system cannot find the file specified`). The alternative-
extension check is now scoped to each track's OWN directory (`dir_cache`), Atmos
is treated as a distinct audio modality, and a stale listing never yields a
vanished path.
"""
from __future__ import annotations

import asyncio
import inspect
import types
from pathlib import Path, PureWindowsPath

from tiddl.cli.commands.download.downloader import (
    Downloader,
    _find_alt_extension,
    _track_is_atmos,
)


# ==========================================================================
# Pure helper — _find_alt_extension
# ==========================================================================
def test_cross_directory_same_stem_is_not_matched():
    # 1. FLAC lives in album A; album B (same title, Atmos Version) has no file.
    #    Requesting B's .m4a must NOT match a file from A's folder.
    b_target = PureWindowsPath(
        r"Z:\#\21 Savage\(2018) i am (Dolby Atmos Version)\01. a lot.m4a"
    )
    assert _find_alt_extension(b_target, ".m4a", {"cover.jpg"}) is None


def test_real_alternative_in_same_directory_is_returned():
    # 2.
    target = PureWindowsPath(r"Z:\Artist\Album\01. Track.m4a")
    assert _find_alt_extension(target, ".m4a", {"01. Track.flac", "cover.jpg"}) == (
        target.with_suffix(".flac")
    )


def test_same_requested_extension_is_not_an_alternative():
    # 3. requesting .flac, only .flac present — the direct-existence check owns
    #    that ("Exists"); the alt-check returns None.
    assert _find_alt_extension(Path("/x/01. T.flac"), ".flac", {"01. T.flac"}) is None


def test_lower_quality_extension_is_rejected():
    # 4. requesting .flac (score 2); only .m4a (1) present -> no downgrade.
    assert _find_alt_extension(Path("/x/01. T.flac"), ".flac", {"01. T.m4a"}) is None


def test_equal_quality_container_is_accepted():
    # 5. requesting .m4a (1); .mp4 (1) present, different container -> accepted.
    assert _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.mp4"}) == (
        Path("/x/01. T.mp4")
    )


def test_empty_directory_listing_is_none():
    # 6.
    assert _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", set()) is None


def test_extension_case_is_normalised():
    # 7. `.FLAC` on disk / `.M4A` requested still match (Windows/SMB semantics).
    assert _find_alt_extension(Path("/x/01. T.m4a"), ".M4A", {"01. T.FLAC"}) == (
        Path("/x/01. T.flac")
    )


def test_flac_and_m4a_coexisting_is_deterministic_and_atmos_is_distinct():
    # 8. `.flac` AND `.m4a` of the same stem in ONE folder — pin the contract.
    names = {"01. T.flac", "01. T.m4a"}
    target = Path("/x/01. T.m4a")
    # STEREO .m4a request: a higher-quality FLAC satisfies it (historical contract).
    assert _find_alt_extension(target, ".m4a", names) == target.with_suffix(".flac")
    # ATMOS .m4a request: a stereo FLAC is a DIFFERENT modality -> does NOT satisfy;
    # only another Atmos container would (here just the same .m4a) -> None.
    assert _find_alt_extension(target, ".m4a", names, atmos_request=True) is None
    # ATMOS request accepts an equal Atmos container (.mp4), never the FLAC.
    assert _find_alt_extension(
        target, ".m4a", {"01. T.flac", "01. T.mp4"}, atmos_request=True
    ) == target.with_suffix(".mp4")


def test_track_is_atmos_detects_dolby_atmos():
    atmos = types.SimpleNamespace(
        mediaMetadata={"tags": ["DOLBY_ATMOS", "LOSSLESS"]}, audioModes=[]
    )
    stereo = types.SimpleNamespace(mediaMetadata={"tags": ["LOSSLESS"]}, audioModes=["STEREO"])
    via_modes = types.SimpleNamespace(mediaMetadata=None, audioModes=["DOLBY_ATMOS"])
    assert _track_is_atmos(atmos) is True
    assert _track_is_atmos(stereo) is False
    assert _track_is_atmos(via_modes) is True


# ==========================================================================
# Integration — Downloader._resolve_alt_existing over REAL directories
# ==========================================================================
class _Stub:
    """Minimal host reusing the real scan + resolve methods (no network/DB)."""

    _scan_directory = Downloader._scan_directory
    _resolve_alt_existing = Downloader._resolve_alt_existing

    def __init__(self):
        self.dir_cache = {}
        self._dir_locks = {}
        self._dir_locks_meta = asyncio.Lock()


def test_resolve_is_directory_scoped_across_two_albums(tmp_path):
    # 9/10. Scan album A (FLAC) first — which would poison a global stem index —
    #       then resolve album B's (Atmos) .m4a: no false alt -> None -> the real
    #       download proceeds and no vanished path reaches the metadata writer.
    a = tmp_path / "i am (Deluxe)"
    a.mkdir()
    (a / "01. a lot (explicit).flac").write_bytes(b"x")
    b = tmp_path / "i am (Dolby Atmos Version)"
    b.mkdir()

    async def run():
        s = _Stub()
        await s._scan_directory(a)
        return await s._resolve_alt_existing(b / "01. a lot (explicit).m4a", ".m4a", False)

    assert asyncio.run(run()) is None


def test_resolve_returns_real_alternative_in_same_folder(tmp_path):
    # 11. A genuine FLAC in the SAME folder still satisfies skip_existing.
    d = tmp_path / "Album"
    d.mkdir()
    (d / "01. Track.flac").write_bytes(b"x")

    async def run():
        s = _Stub()
        return await s._resolve_alt_existing(d / "01. Track.m4a", ".m4a", False)

    assert asyncio.run(run()) == d / "01. Track.flac"


def test_resolve_refreshes_once_when_cache_is_stale(tmp_path):
    # 12. File present at scan, deleted before acceptance -> one refresh, then None
    #     (download proceeds); never returns a vanished path.
    d = tmp_path / "Album"
    d.mkdir()
    f = d / "01. Track.flac"
    f.write_bytes(b"x")

    async def run():
        s = _Stub()
        await s._scan_directory(d)  # cache lists the .flac
        f.unlink()                  # it vanishes after enumeration
        return await s._resolve_alt_existing(d / "01. Track.m4a", ".m4a", False)

    assert asyncio.run(run()) is None


def test_atmos_request_ignores_a_same_folder_stereo_flac(tmp_path):
    # Atmos-specific: an Atmos track must NOT be skipped just because a homonymous
    # stereo FLAC sits in the same folder.
    d = tmp_path / "Atmos"
    d.mkdir()
    (d / "01. a lot.flac").write_bytes(b"x")

    async def run():
        s = _Stub()
        return await s._resolve_alt_existing(d / "01. a lot.m4a", ".m4a", True)

    assert asyncio.run(run()) is None


def test_stem_index_is_gone():
    # 13. No residual global stem index anywhere in the Downloader.
    assert "_stem_index" not in inspect.getsource(Downloader)
