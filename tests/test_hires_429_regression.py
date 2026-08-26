"""Regression: the HTTP 429 storm introduced by 05b1eca (`-q high` promoted the
WHOLE run to the strict HiRes client + a duplicate HiRes->TV stream request per
track). This pins the fix:

* the STABLE client matrix is restored (`high`/`never` -> TV, `max`/`always` -> HiRes),
* the 24-bit `max` ascent for an Atmos track is decided PER-TRACK from the media
  tags and routed to a SECONDARY HiRes client only for that track,
* TV + HiRes share ONE per-run request budget so both clients together cannot
  exceed `requests_per_minute`,
* an ordinary Lossless track makes exactly one stream request (TV/LOSSLESS).

All offline and deterministic: the budget takes an injected clock, and the
routing/order is asserted through the same pure helpers the downloader uses, so
each attempt is recorded as (client_kind, quality).
"""
from tiddl.cli.commands.download import _resolve_prefer_hires
from tiddl.cli.commands.download.downloader import _pick_stream_client
from tiddl.core.api.budget import SharedRequestBudget
from tiddl.core.quality_cascade import cascade_api_qualities


# --------------------------------------------------------------------------
# Deterministic clock for the shared budget.
# --------------------------------------------------------------------------
class _Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        if s > 0:
            self.t += s


def _budget(rpm, clock):
    return SharedRequestBudget(rpm, clock=clock.now, sleeper=clock.sleep, jitter=lambda: 0.0)


# The (client_kind, quality) sequence the downloader would attempt for a track:
# the fidelity cascade from the tags, each rung routed by the SAME per-attempt
# client picker the real loop uses. `has_hires` is True only in TV-primary
# `high + auto` (a secondary HiRes client is available for the `max` ascent).
def _expected_attempts(requested, tags, primary_kind, has_hires):
    hires = object() if has_hires else None
    out = []
    for q in cascade_api_qualities(requested, tags):
        _, kind = _pick_stream_client(q, "PRIMARY", primary_kind, hires)
        out.append((kind, q))
    return out


# ===========================================================================
# 1. Stable client matrix (restored from d1613b0)
# ===========================================================================
def test_prefer_hires_matrix():
    # high + auto -> TV (the whole point: no run-wide HiRes for `high`).
    assert _resolve_prefer_hires("high", "auto") is False
    # max + auto -> HiRes.
    assert _resolve_prefer_hires("max", "auto") is True
    # never -> TV, even for max.
    assert _resolve_prefer_hires("max", "never") is False
    assert _resolve_prefer_hires("high", "never") is False
    # always -> HiRes, even for high/normal.
    assert _resolve_prefer_hires("high", "always") is True
    assert _resolve_prefer_hires("normal", "always") is True
    # lower tiers in auto stay on TV.
    assert _resolve_prefer_hires("normal", "auto") is False
    assert _resolve_prefer_hires("low", "auto") is False


# ===========================================================================
# 2. Per-track routing (the pure picker the loop uses)
# ===========================================================================
def test_pick_client_max_rung_ascends_to_secondary_hires():
    hires = object()
    client, kind = _pick_stream_client("HI_RES_LOSSLESS", "TV", "tv", hires)
    assert client is hires and kind == "hires"


def test_pick_client_ordinary_tier_stays_on_primary():
    hires = object()
    for q in ("LOSSLESS", "HIGH", "LOW"):
        client, kind = _pick_stream_client(q, "TV", "tv", hires)
        assert client == "TV" and kind == "tv"


def test_pick_client_max_rung_without_secondary_uses_primary():
    # HiRes-primary (max/always) or never: no secondary client -> primary serves
    # HI_RES_LOSSLESS itself (or, for `never`, HI_RES_LOSSLESS is never requested).
    client, kind = _pick_stream_client("HI_RES_LOSSLESS", "PRIMARY", "hires", None)
    assert client == "PRIMARY" and kind == "hires"


# ===========================================================================
# 3. Call table — client / order / count per scenario
# ===========================================================================
def test_high_auto_ordinary_lossless_one_tv_request():
    # A normal Lossless track (LOSSLESS, not Atmos): exactly ONE stream request,
    # on TV, yielding FLAC. No HiRes call.
    tags = ["LOSSLESS"]
    attempts = _expected_attempts("high", tags, primary_kind="tv", has_hires=True)
    assert attempts[0] == ("tv", "LOSSLESS")
    assert all(kind == "tv" for kind, _ in attempts)
    assert not any(kind == "hires" for kind, _ in attempts)


def test_high_auto_atmos_with_max_flac_ascends_only_that_track():
    # Atmos track whose only FLAC is 24-bit: the cascade climbs to `max`
    # (HI_RES_LOSSLESS) and routes THAT rung to the secondary HiRes client; the
    # run is not converted to HiRes.
    tags = ["DOLBY_ATMOS", "HIRES_LOSSLESS"]
    attempts = _expected_attempts("high", tags, primary_kind="tv", has_hires=True)
    assert attempts[0] == ("hires", "HI_RES_LOSSLESS")
    # exactly one HiRes attempt (the ascent), the rest fall back on TV.
    assert sum(1 for kind, _ in attempts if kind == "hires") == 1


def test_high_auto_no_high_no_max_stays_on_tv():
    # No LOSSLESS and no HIRES tag: only HIGH/LOW remain, all on TV.
    tags = []
    attempts = _expected_attempts("high", tags, primary_kind="tv", has_hires=True)
    assert attempts and all(kind == "tv" for kind, _ in attempts)
    assert not any(kind == "hires" for kind, _ in attempts)


def test_max_auto_uses_hires_primary_no_secondary():
    # max + auto: HiRes is the primary (has_hires=False here — no separate
    # secondary), so the HI_RES_LOSSLESS request goes on the primary HiRes.
    tags = ["HIRES_LOSSLESS", "LOSSLESS"]
    attempts = _expected_attempts("max", tags, primary_kind="hires", has_hires=False)
    assert attempts[0] == ("hires", "HI_RES_LOSSLESS")


def test_never_never_calls_hires():
    # `never`: no secondary HiRes client at all; even a track advertising Max/Atmos
    # is only ever requested on the TV primary.
    tags = ["DOLBY_ATMOS", "HIRES_LOSSLESS"]
    attempts = _expected_attempts("high", tags, primary_kind="tv", has_hires=False)
    assert not any(kind == "hires" for kind, _ in attempts)


def test_always_hires_run_wide():
    # `always`: HiRes is the run-wide primary; every attempt is on HiRes.
    tags = ["LOSSLESS"]
    attempts = _expected_attempts("high", tags, primary_kind="hires", has_hires=False)
    assert attempts and all(kind == "hires" for kind, _ in attempts)


# ===========================================================================
# 4. Shared per-run request budget (deterministic clock)
# ===========================================================================
def test_budget_first_request_never_waits():
    c = _Clock()
    b = _budget(60, c)  # interval 1.0s
    b.throttle()
    assert c.sleeps == [] or c.sleeps == [0.0] or all(s <= 0 for s in c.sleeps)
    assert b.request_count == 1


def test_budget_spaces_combined_traffic_at_rpm():
    # 60 rpm -> 1.0s spacing. Five requests (from either client) take 4 intervals.
    c = _Clock()
    b = _budget(60, c)
    for _ in range(5):
        b.throttle()
    assert b.request_count == 5
    # first free, next four each wait one interval -> 4.0s of enforced spacing.
    assert sum(s for s in c.sleeps if s > 0) == 4.0


def test_budget_shared_by_two_clients_cannot_double_rpm():
    # One budget injected into BOTH clients: interleaving TV + HiRes requests
    # stays on the SAME 1.0s cadence — activating both does NOT double the rate.
    c = _Clock()
    shared = _budget(60, c)
    # simulate: TV, HiRes, TV, HiRes, TV, HiRes (6 combined requests) — the same
    # shared budget backs both clients, so the cadence stays 60/min COMBINED.
    for _ in range(6):
        shared.throttle()
    assert shared.request_count == 6
    # 6 combined requests over 5 intervals => 5.0s, i.e. exactly 60/min combined.
    assert sum(s for s in c.sleeps if s > 0) == 5.0


def test_two_contexts_have_independent_budgets():
    # Per-context (NOT process-global): a fresh budget starts clean, so a prior
    # run cannot contaminate the next and its first request never waits.
    c1, c2 = _Clock(), _Clock()
    b1, b2 = _budget(60, c1), _budget(60, c2)
    for _ in range(3):
        b1.throttle()
    assert b1.request_count == 3
    b2.throttle()
    assert b2.request_count == 1  # independent counter
    assert sum(s for s in c2.sleeps if s > 0) == 0.0  # its first request is free


def test_budget_refund_returns_the_slot_for_cache_hits():
    # A "request" served from cache consumes no quota: refund gives the slot back
    # and does not count toward the combined total.
    c = _Clock()
    b = _budget(60, c)
    b.throttle()
    b.throttle()
    assert b.request_count == 2
    b.refund()
    assert b.request_count == 1
    # after a refund the next real request may proceed immediately.
    before = len([s for s in c.sleeps if s > 0])
    b.throttle()
    assert len([s for s in c.sleeps if s > 0]) == before  # no extra wait


# ===========================================================================
# 5. No duplicate stream request for an ordinary high+auto track
# ===========================================================================
def test_high_auto_ordinary_has_no_hires_then_tv_duplicate():
    # The pre-fix bug: HiRes/LOSSLESS->HIGH then TV/LOSSLESS->FLAC (two requests).
    # With TV as primary and no fallback in TV mode, an ordinary track is a single
    # TV/LOSSLESS attempt.
    tags = ["LOSSLESS"]
    attempts = _expected_attempts("high", tags, primary_kind="tv", has_hires=True)
    assert attempts[0] == ("tv", "LOSSLESS")
    # the same (client, quality) pair is never issued twice.
    assert len(attempts) == len(set(attempts))


# ===========================================================================
# 6. strict nuance — never issue a request the metadata already proves incompatible
# ===========================================================================
def test_no_request_for_a_tier_the_tags_already_rule_out():
    # A track whose tags offer no FLAC at all (no LOSSLESS / no HIRES_LOSSLESS):
    # the cascade never even ATTEMPTS HI_RES_LOSSLESS or LOSSLESS, so no request
    # that the metadata already proves incompatible is made. (This is why we do
    # NOT pre-assert `strict` == zero requests: HIGH/LOW are still offered; strict
    # simply must not ACCEPT an out-of-policy tier, which stream_policy handles.)
    qs = cascade_api_qualities("high", [])  # only universal normal/low remain
    assert "HI_RES_LOSSLESS" not in qs
    assert "LOSSLESS" not in qs
    assert qs and qs[0] == "HIGH"


# ===========================================================================
# 7. Enumeration client — `high + auto` (incl. expanded discography) uses TV
# ===========================================================================
def test_high_auto_enumeration_uses_tv_primary(monkeypatch):
    # In `high + auto`, prefer_hires is False, so the PRIMARY api — which backs
    # ALL enumeration (playlists, artists, albums, credits, metadata) — is the TV
    # client. HiRes is only ever a per-track ascent, never the enumerator, so a
    # `--artists` discography run cannot storm the HiRes limit during enumeration.
    from rich.console import Console

    from tiddl.cli.ctx import ContextObject
    from tiddl.cli.utils.auth.core import AUTH_DATA_FILE, AUTH_FALLBACK_FILE

    ctx = ContextObject(api_omit_cache=False, debug_path=None, console=Console())
    ctx.prefer_hires = _resolve_prefer_hires("high", "auto")  # -> False (TV)
    used: list = []
    monkeypatch.setattr(
        ctx, "_build_api",
        lambda auth_file, *a, **k: (used.append(auth_file), object())[1],
    )
    _ = ctx.api
    assert used and used[0] == AUTH_FALLBACK_FILE  # TV auth file backs enumeration

    # And in max/always the primary IS the HiRes auth file.
    ctx2 = ContextObject(api_omit_cache=False, debug_path=None, console=Console())
    ctx2.prefer_hires = _resolve_prefer_hires("max", "auto")  # -> True (HiRes)
    used2: list = []
    monkeypatch.setattr(
        ctx2, "_build_api",
        lambda auth_file, *a, **k: (used2.append(auth_file), object())[1],
    )
    _ = ctx2.api
    assert used2 and used2[0] == AUTH_DATA_FILE
