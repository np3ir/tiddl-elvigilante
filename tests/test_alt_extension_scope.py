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
    _wants_atmos,
)


def _atmos_item():
    return types.SimpleNamespace(mediaMetadata={"tags": ["DOLBY_ATMOS", "LOSSLESS"]}, audioModes=[])


def _stereo_item():
    return types.SimpleNamespace(mediaMetadata={"tags": ["LOSSLESS"]}, audioModes=[])


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


def test_extension_case_matches_and_real_casing_is_preserved():
    # 7. `.FLAC` on disk / `.M4A` requested match (case-insensitive), and the
    #    returned path keeps the exact on-disk casing (valid file on a
    #    case-sensitive filesystem, not a lowercased reconstruction).
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".M4A", {"01. T.FLAC"})
    assert res is not None
    assert res.name == "01. T.FLAC"


def test_casing_tie_prefers_exact_match_deterministically():
    # Both `01. T.flac` and `01. T.FLAC` present (only possible on a case-sensitive
    # FS): the exact-case name that matches the requested reconstruction wins.
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.FLAC", "01. T.flac"})
    assert res is not None and res.name == "01. T.flac"


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
# Requested (effective) modality — _wants_atmos: an Atmos TAG is not an Atmos
# REQUEST. Only `-q atmos` on a track that offers it is an Atmos delivery.
# ==========================================================================
def test_wants_atmos_requires_requested_atmos_not_just_the_tag():
    a = _atmos_item()
    assert _wants_atmos("atmos", a) is True         # requested AND offered
    assert _wants_atmos("normal", a) is False        # -q normal -> stereo AAC
    assert _wants_atmos("low", a) is False
    assert _wants_atmos("high", a) is False          # -q high -> climbs to FLAC
    assert _wants_atmos("max", a) is False
    assert _wants_atmos("atmos", _stereo_item()) is False  # track offers no Atmos


def test_atmos_tag_with_normal_quality_accepts_stereo_flac():
    # (1) Atmos tag + `-q normal` + existing FLAC -> stereo contract: the FLAC
    #     (higher quality) satisfies the `.m4a` request, as it always historically did.
    atmos = _wants_atmos("normal", _atmos_item())
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.flac"}, atmos_request=atmos)
    assert res is not None and res.name == "01. T.flac"


def test_atmos_tag_with_atmos_quality_rejects_stereo_flac():
    # (2) Atmos tag + `-q atmos` + FLAC -> a stereo FLAC does NOT satisfy an Atmos
    #     delivery (distinct modality) -> download proceeds.
    atmos = _wants_atmos("atmos", _atmos_item())
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.flac"}, atmos_request=atmos)
    assert res is None


def test_atmos_tag_with_atmos_quality_accepts_atmos_container():
    # (3) Atmos tag + `-q atmos` + MP4/M4A -> another Atmos container satisfies it.
    atmos = _wants_atmos("atmos", _atmos_item())
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.mp4"}, atmos_request=atmos)
    assert res is not None and res.name == "01. T.mp4"


def test_atmos_tag_with_high_quality_preserves_flac_priority():
    # (4) Atmos tag + `-q high` -> FLAC-over-Atmos: the requested file is `.flac`,
    #     which never downgrades to a lower `.m4a`, and it is NOT an Atmos delivery.
    atmos = _wants_atmos("high", _atmos_item())
    assert atmos is False
    res = _find_alt_extension(Path("/x/01. T.flac"), ".flac", {"01. T.m4a"}, atmos_request=atmos)
    assert res is None


def test_non_atmos_track_with_atmos_request_uses_stereo_contract():
    # (5) Non-Atmos track + `-q atmos` -> not an Atmos delivery; the stereo contract
    #     applies and a FLAC still satisfies an `.m4a` fallback.
    atmos = _wants_atmos("atmos", _stereo_item())
    assert atmos is False
    res = _find_alt_extension(Path("/x/01. T.m4a"), ".m4a", {"01. T.flac"}, atmos_request=atmos)
    assert res is not None and res.name == "01. T.flac"


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


def test_resolve_preserves_real_casing_stereo_and_is_a_file(tmp_path):
    # §5. A `Track.FLAC` (uppercase ext on disk) satisfies a stereo `.m4a` request;
    #     the resolved path keeps `Track.FLAC` and is a real file (so it works on a
    #     case-sensitive filesystem, and no download is started).
    d = tmp_path / "Album"
    d.mkdir()
    (d / "01. Track.FLAC").write_bytes(b"x")

    async def run():
        s = _Stub()
        return await s._resolve_alt_existing(d / "01. Track.m4a", ".m4a", False)

    res = asyncio.run(run())
    assert res is not None
    assert res.name == "01. Track.FLAC"   # exact on-disk casing, not lowercased
    assert res.is_file()                  # a real file (no re-download)


def test_resolve_preserves_real_casing_atmos_container(tmp_path):
    # §5. Atmos request: a `.MP4` (uppercase) Atmos container satisfies it and the
    #     resolved path keeps the real name.
    d = tmp_path / "Atmos"
    d.mkdir()
    (d / "01. Track.MP4").write_bytes(b"x")

    async def run():
        s = _Stub()
        return await s._resolve_alt_existing(d / "01. Track.m4a", ".m4a", True)

    res = asyncio.run(run())
    assert res is not None
    assert res.name == "01. Track.MP4"
    assert res.is_file()


def test_stem_index_is_gone():
    # 13. No residual global stem index anywhere in the Downloader.
    assert "_stem_index" not in inspect.getsource(Downloader)
