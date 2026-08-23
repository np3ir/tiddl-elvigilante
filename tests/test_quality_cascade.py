"""Coverage for the fidelity-ordered quality cascade (tiddl.core.quality_cascade)."""
from __future__ import annotations

from tiddl.core.quality_cascade import (
    QUALITY_LADDER,
    available_rungs,
    cascade_api_qualities,
    resolve_cascade,
)

# Tag sets seen in the wild.
HIRES = ["LOSSLESS", "HIRES_LOSSLESS"]                       # normal hi-res track
LOSSLESS_ONLY = ["LOSSLESS"]                                 # CD-quality only
ATMOS_FULL = ["LOSSLESS", "HIRES_LOSSLESS", "DOLBY_ATMOS"]   # e.g. Bryan Adams - Room Service
AAC_ONLY: list = []                                          # no FLAC tags


def test_ladder_is_fidelity_ordered():
    assert QUALITY_LADDER == ["max", "high", "atmos", "normal", "low"]


def test_available_rungs_normal_hires_track():
    a = available_rungs(HIRES)
    assert a == {"max": True, "high": True, "atmos": False, "normal": True, "low": True}


def test_available_rungs_atmos_track_hides_high():
    # An Atmos track's LOSSLESS tier is Atmos, not a 16-bit FLAC, so `high` is NOT
    # offered — its only FLAC is `max`.
    a = available_rungs(ATMOS_FULL)
    assert a["max"] is True
    assert a["high"] is False
    assert a["atmos"] is True


# --- the user's own scenarios -------------------------------------------------

def test_start_max_on_atmos_track_gets_flac_first():
    # "-q max" on a dual-format Atmos track → hi-res FLAC before Atmos.
    assert resolve_cascade("max", ATMOS_FULL) == ["max", "atmos", "normal", "low"]
    assert cascade_api_qualities("max", ATMOS_FULL)[0] == "HI_RES_LOSSLESS"


def test_start_high_on_atmos_track_climbs_to_max_flac_before_atmos():
    # "-q high" on an Atmos track: no 16-bit FLAC exists, but FLAC is preferred
    # over Atmos, so it climbs to `max` (24-bit FLAC) BEFORE dropping to Atmos.
    assert resolve_cascade("high", ATMOS_FULL) == ["max", "atmos", "normal", "low"]
    assert cascade_api_qualities("high", ATMOS_FULL)[0] == "HI_RES_LOSSLESS"


def test_flac_start_tries_both_flac_rungs_before_atmos():
    # The whole point: from either FLAC rung, BOTH FLAC rungs precede Atmos.
    assert resolve_cascade("high", ATMOS_FULL)[:1] == ["max"]      # high→max (FLAC)
    assert "atmos" not in resolve_cascade("high", ATMOS_FULL)[:1]  # FLAC before atmos


def test_start_atmos_prefers_atmos_first():
    # "-q atmos" for someone who collects Atmos.
    assert resolve_cascade("atmos", ATMOS_FULL) == ["atmos", "normal", "low"]


def test_atmos_start_on_non_atmos_track_skips_atmos_rung():
    # A non-Atmos track simply has no atmos rung; the cascade continues down.
    assert resolve_cascade("atmos", HIRES) == ["normal", "low"]


# --- ordinary tracks ----------------------------------------------------------

def test_start_max_normal_track():
    assert resolve_cascade("max", HIRES) == ["max", "high", "normal", "low"]


def test_start_high_normal_track():
    # A normal track offers its 16-bit FLAC, so `high` is taken first; `max` is
    # only a listed fallback (never reached, since high succeeds), Atmos absent.
    assert resolve_cascade("high", HIRES) == ["high", "max", "normal", "low"]


def test_lossless_only_track():
    assert resolve_cascade("max", LOSSLESS_ONLY) == ["high", "normal", "low"]  # no max
    assert resolve_cascade("high", LOSSLESS_ONLY) == ["high", "normal", "low"]


def test_aac_only_track():
    assert resolve_cascade("max", AAC_ONLY) == ["normal", "low"]


def test_start_low():
    assert resolve_cascade("low", ATMOS_FULL) == ["low"]


def test_start_normal():
    assert resolve_cascade("normal", HIRES) == ["normal", "low"]


# --- api mapping & robustness -------------------------------------------------

def test_cascade_api_qualities_dedups():
    # `high` and `atmos` both map to LOSSLESS; a per-track cascade never has both,
    # but the de-dup guard keeps consecutive duplicates from ever appearing.
    apis = cascade_api_qualities("max", ATMOS_FULL)
    assert apis == ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"]
    # no consecutive repeats
    assert all(apis[i] != apis[i + 1] for i in range(len(apis) - 1))


def test_unknown_start_treated_as_top():
    assert resolve_cascade("bogus", HIRES) == resolve_cascade("max", HIRES)
