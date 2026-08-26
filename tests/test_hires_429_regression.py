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
import sqlite3
import types
from pathlib import Path

import pytest

import tiddl.cli.commands.download.downloader as dl
from tiddl.cli.commands.download import _resolve_prefer_hires
from tiddl.cli.commands.download.downloader import (
    _hires_capable,
    _pick_stream_client,
    _supported_attempts,
)
from tiddl.core import cancel
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
# 2b. Capability/policy filter — HI_RES_LOSSLESS dropped when no HiRes client
# ===========================================================================
def test_hires_capable_matrix():
    assert _hires_capable("hires", None) is True          # HiRes is primary
    assert _hires_capable("tv", object()) is True         # secondary HiRes present
    assert _hires_capable("tv", None) is False            # never / no HiRes token


def test_supported_attempts_drops_max_when_no_hires_client():
    # never, or high+auto without a HiRes token: HI_RES_LOSSLESS must be removed,
    # NOT routed to TV. The remaining tiers are kept in order.
    qs = ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"]
    assert _supported_attempts(qs, "tv", None) == ["LOSSLESS", "HIGH", "LOW"]


def test_supported_attempts_keeps_max_with_a_hires_client():
    qs = ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"]
    # secondary HiRes present (high+auto with token)…
    assert _supported_attempts(qs, "tv", object()) == qs
    # …or HiRes primary (max/always).
    assert _supported_attempts(qs, "hires", None) == qs


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


def test_budget_has_no_backward_rollback_api():
    # A concurrent cache hit must never be able to roll the spacing clock back.
    # The old refund() did exactly that (set _last = now - interval), which under
    # concurrency could erase a reservation another thread already made. It is
    # gone: there is deliberately no public method to move _last backward.
    b = _budget(60, _Clock())
    assert not hasattr(b, "refund")


def test_budget_cache_hit_between_requests_preserves_spacing():
    # The client peeks the cache BEFORE throttle, so a true cache hit simply never
    # calls the budget. Simulate two real requests with a cache hit in between
    # (which touches nothing): the second real request must still wait the full
    # interval — the cache hit cannot let it burst.
    c = _Clock()
    b = _budget(60, c)  # interval 1.0s
    b.throttle()               # first real request (free)
    # ... a cache hit happens here: by contract it calls neither throttle nor any
    # rollback, so the budget state is untouched ...
    c.advance(0.2)             # only 0.2s elapsed since the first request
    b.throttle()               # second real request must wait the remaining 0.8s
    assert b.request_count == 2
    assert sum(s for s in c.sleeps if s > 0) == pytest.approx(0.8)


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


# ===========================================================================
# 8. Effective RPM — the budget is built AFTER the --rpm CLI override resolves
# ===========================================================================
def test_configure_request_budget_uses_effective_rpm():
    # The budget must reflect the EFFECTIVE requests_per_minute (config + any
    # --rpm override), not whatever the config held at ContextObject creation.
    from rich.console import Console

    from tiddl.cli.ctx import ContextObject

    ctx = ContextObject(api_omit_cache=False, debug_path=None, console=Console())
    # Simulate the download command applying `--rpm 120` and then wiring it in.
    ctx.configure_request_budget(120)
    assert ctx.request_budget.interval == pytest.approx(60.0 / 120)
    # Re-resolving (e.g. a different effective value) replaces it cleanly.
    ctx.configure_request_budget(30)
    assert ctx.request_budget.interval == pytest.approx(60.0 / 30)


def test_request_budget_lazy_default_reads_config():
    # A command that never touches --rpm gets a budget spaced at the config value,
    # created lazily on first access.
    from rich.console import Console

    from tiddl.cli.config import CONFIG
    from tiddl.cli.ctx import ContextObject

    ctx = ContextObject(api_omit_cache=False, debug_path=None, console=Console())
    assert ctx._request_budget is None  # not built eagerly
    expected = 60.0 / max(1, CONFIG.download.requests_per_minute)
    assert ctx.request_budget.interval == pytest.approx(expected)


# ===========================================================================
# 9. REAL Downloader.download() with fake clients — the actual call sequence
# ===========================================================================
# These drive the real cascade/routing/de-dup/filter of Downloader.download()
# against fake TIDAL clients that RECORD every get_track_stream(kind, quality)
# call. Only the non-routing collaborators (media transfer, manifest parse,
# stream inspection, tagging, DB, filesystem) are stubbed — the clients under
# assertion are the fakes, so the observed calls are the real routing decisions.
class _StubOut:
    def __init__(self):
        self.console = types.SimpleNamespace(print=lambda *a, **k: None)

    def download_start(self, desc):
        return 1

    def download_finish(self, task_id=None):
        return types.SimpleNamespace(description="d")

    def show_item_result(self, **k):
        pass


class _FakeAPI:
    """Stand-in for TidalAPI: records (kind, quality) per stream request and
    returns a fake manifest whose delivered quality comes from `deliver`
    (dict quality->delivered, or None to raise a non-429/401 failure)."""

    def __init__(self, kind, calls, deliver):
        self.kind = kind
        self._calls = calls
        self._deliver = deliver
        self.country_code = "US"
        self.client = types.SimpleNamespace(
            session=types.SimpleNamespace(headers={})
        )

    def get_track_stream(self, track_id, quality):
        self._calls.append((self.kind, quality))
        delivered = self._deliver.get(quality)
        if delivered is None:
            raise RuntimeError(f"no stream for {quality}")
        return types.SimpleNamespace(
            audioQuality=delivered, audioMode="", bitDepth=16, sampleRate=44100
        )


def _make_track(*, tags, audio_modes=None, quality="LOSSLESS", track_id=101):
    from tiddl.core.api.models import Track

    return Track(
        id=track_id, title="T", duration=180, replayGain=0.0, peak=1.0,
        allowStreaming=True, streamReady=True, adSupportedStreamReady=True,
        djReady=True, stemReady=True, premiumStreamingOnly=False,
        trackNumber=1, volumeNumber=1, popularity=1, url="http://t",
        editable=True, explicit=False, audioQuality=quality,
        audioModes=audio_modes or [], mediaMetadata={"tags": tags},
        artist={"id": 1, "name": "A", "type": "MAIN"},
        artists=[{"id": 1, "name": "A", "type": "MAIN"}],
        album={"id": 9, "title": "Alb", "vibrantColor": "#fff"},
    )


@pytest.fixture
def dl_env(tmp_path, monkeypatch):
    """Stub every non-routing collaborator so download() runs its real cascade
    to a clean success without touching the network/disk/DB machinery."""
    cancel.clear()

    async def _ok_retry(self, task, urls, task_id):
        return True

    async def _no_cache(self, p):
        return False

    monkeypatch.setattr(dl.Downloader, "_download_with_retry", _ok_retry)
    monkeypatch.setattr(dl.Downloader, "_is_file_in_cache", _no_cache)
    monkeypatch.setattr(
        dl.Downloader, "_init_db",
        lambda self: sqlite3.connect(":memory:", check_same_thread=False),
    )
    monkeypatch.setattr(dl.Downloader, "_spawn_bg", lambda self, coro: None)

    monkeypatch.setattr(
        dl, "inspect_track_stream",
        lambda *a, **k: types.SimpleNamespace(accepted=True, reason="ok"),
    )
    monkeypatch.setattr(dl, "parse_track_stream", lambda stream: (["http://u"], None))
    monkeypatch.setattr(
        dl, "get_existing_track_filename", lambda *a, **k: Path("A - T.flac")
    )
    monkeypatch.setattr(dl, "_prepare_long_path", lambda s: s)
    monkeypatch.setattr(dl, "extract_flac", lambda p: p)
    monkeypatch.setattr(dl, "is_mp4_container", lambda p: False)
    monkeypatch.setattr(dl, "report_playback", lambda **k: None)

    def _mkdir(root, path, mode):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return types.SimpleNamespace(reason="off", anchor_id=None)

    monkeypatch.setattr(dl, "_guarded_mkdir", _mkdir)
    yield tmp_path
    cancel.clear()


def _make_downloader(tmp_path, *, primary, primary_kind, hires_api, fallback_api, quality):
    return dl.Downloader(
        tidal_api=primary,
        threads_count=1,
        rich_output=_StubOut(),
        track_quality=quality,
        video_quality="hd",
        videos_filter="include",
        skip_existing=False,
        download_path=tmp_path,
        scan_path=tmp_path,
        video_download_path=None,
        fallback_api=fallback_api,
        hires_api=hires_api,
        primary_client_kind=primary_kind,
    )


async def _run(tmp_path, item, *, primary, primary_kind, hires_api=None, fallback_api=None,
               quality="high"):
    d = _make_downloader(
        tmp_path, primary=primary, primary_kind=primary_kind,
        hires_api=hires_api, fallback_api=fallback_api, quality=quality,
    )
    try:
        path, ok = await d.download(item, file_path=tmp_path / "A - T")
    finally:
        await d.close()
    return path, ok


async def test_download_high_normal_exactly_one_tv_lossless(dl_env):
    # High + auto, ordinary Lossless track: exactly ONE stream request, TV/LOSSLESS.
    calls: list = []
    tv = _FakeAPI("tv", calls, {"LOSSLESS": "LOSSLESS"})
    hires = _FakeAPI("hires", calls, {})  # present but must NOT be called
    _, ok = await _run(
        dl_env, _make_track(tags=["LOSSLESS"]),
        primary=tv, primary_kind="tv", hires_api=hires, quality="high",
    )
    assert ok is True
    assert calls == [("tv", "LOSSLESS")]


async def test_download_high_atmos_exactly_one_hires_call(dl_env):
    # High + auto, Atmos track whose only FLAC is 24-bit: exactly ONE HiRes call
    # (the per-track ascent), and it succeeds — the run is not converted to HiRes.
    calls: list = []
    tv = _FakeAPI("tv", calls, {})
    hires = _FakeAPI("hires", calls, {"HI_RES_LOSSLESS": "HI_RES_LOSSLESS"})
    _, ok = await _run(
        dl_env, _make_track(tags=["DOLBY_ATMOS", "HIRES_LOSSLESS"], quality="HI_RES_LOSSLESS"),
        primary=tv, primary_kind="tv", hires_api=hires, quality="high",
    )
    assert ok is True
    assert calls == [("hires", "HI_RES_LOSSLESS")]


async def test_download_never_zero_hires_zero_hires_quality(dl_env):
    # never: no HiRes client is even built; an Atmos/Max track is only ever asked
    # on TV, and HI_RES_LOSSLESS is never requested of anyone.
    calls: list = []
    tv = _FakeAPI("tv", calls, {"LOSSLESS": "LOSSLESS"})
    _, ok = await _run(
        dl_env, _make_track(tags=["DOLBY_ATMOS", "HIRES_LOSSLESS"], quality="HI_RES_LOSSLESS"),
        primary=tv, primary_kind="tv", hires_api=None, quality="high",
    )
    assert ok is True
    assert all(kind == "tv" for kind, _ in calls)
    assert not any(q == "HI_RES_LOSSLESS" for _, q in calls)


async def test_download_missing_hires_token_does_not_send_max_to_tv(dl_env):
    # high + auto but NO HiRes token (hires_api is None): the cascade would top
    # out at HI_RES_LOSSLESS, but with no HiRes-capable client that rung is
    # dropped — TV must never be asked for HI_RES_LOSSLESS.
    calls: list = []
    tv = _FakeAPI("tv", calls, {"LOSSLESS": "LOSSLESS"})
    _, ok = await _run(
        dl_env, _make_track(tags=["DOLBY_ATMOS", "HIRES_LOSSLESS"], quality="HI_RES_LOSSLESS"),
        primary=tv, primary_kind="tv", hires_api=None, quality="high",
    )
    assert ok is True
    assert ("tv", "HI_RES_LOSSLESS") not in calls
    assert calls[0] == ("tv", "LOSSLESS")


async def test_download_fallback_has_no_duplicate_pairs(dl_env):
    # HiRes-primary (max/auto): primary degrades HI_RES_LOSSLESS -> HIGH, so the
    # TV fallback re-requests LOSSLESS ONCE. No (client, quality) pair repeats —
    # the old HiRes->TV duplicate cycle is gone.
    calls: list = []
    hires = _FakeAPI("hires", calls, {"HI_RES_LOSSLESS": "HIGH"})   # degraded delivery
    tv = _FakeAPI("tv", calls, {"LOSSLESS": "LOSSLESS"})            # fallback fixes it
    _, ok = await _run(
        dl_env, _make_track(tags=["HIRES_LOSSLESS", "LOSSLESS"], quality="HI_RES_LOSSLESS"),
        primary=hires, primary_kind="hires", hires_api=None, fallback_api=tv, quality="max",
    )
    assert ok is True
    assert calls == [("hires", "HI_RES_LOSSLESS"), ("tv", "LOSSLESS")]
    assert len(calls) == len(set(calls))  # no duplicate pairs
