from types import SimpleNamespace

from tiddl.core.stream_policy import inspect_track_stream


def stream(mode="STEREO", quality="LOSSLESS", bit_depth=16, sample_rate=44100):
    return SimpleNamespace(
        audioMode=mode,
        audioQuality=quality,
        bitDepth=bit_depth,
        sampleRate=sample_rate,
    )


def test_stereo_high_is_verified_from_playback_metadata():
    result = inspect_track_stream(stream(), audio_mode="stereo", requested_quality="high")

    assert result.accepted
    assert result.is_stereo
    assert result.meets_requested_quality
    assert result.bit_depth == 16
    assert result.sample_rate == 44100


def test_stereo_max_is_verified_from_playback_metadata():
    result = inspect_track_stream(
        stream(quality="HI_RES_LOSSLESS", bit_depth=24, sample_rate=96000),
        audio_mode="stereo",
        requested_quality="max",
    )

    assert result.accepted
    assert result.meets_requested_quality


def test_atmos_is_rejected_when_stereo_was_requested():
    result = inspect_track_stream(
        stream(mode="DOLBY_ATMOS", quality="HI_RES_LOSSLESS"),
        audio_mode="stereo",
        requested_quality="max",
    )

    assert not result.accepted
    assert not result.is_stereo
    assert "DOLBY_ATMOS" in result.reason


def test_auto_preserves_legacy_atmos_behavior():
    result = inspect_track_stream(
        stream(mode="DOLBY_ATMOS"), audio_mode="auto", requested_quality="high"
    )

    assert result.accepted


def test_max_reports_lossless_delivery_as_below_request_without_rejecting_it():
    result = inspect_track_stream(
        stream(quality="LOSSLESS"), audio_mode="stereo", requested_quality="max"
    )

    assert result.accepted
    assert not result.meets_requested_quality


def test_strict_high_rejects_lossy_fallback():
    result = inspect_track_stream(
        stream(quality="HIGH"),
        audio_mode="stereo",
        requested_quality="high",
        quality_policy="strict",
    )

    assert not result.accepted
    assert "LOSSLESS" in result.reason


def test_strict_max_rejects_standard_lossless_fallback():
    result = inspect_track_stream(
        stream(quality="LOSSLESS"),
        audio_mode="stereo",
        requested_quality="max",
        quality_policy="strict",
    )

    assert not result.accepted
    assert "HI_RES_LOSSLESS" in result.reason


def test_strict_max_accepts_stereo_hires_only():
    result = inspect_track_stream(
        stream(quality="HI_RES_LOSSLESS", bit_depth=24, sample_rate=192000),
        audio_mode="stereo",
        requested_quality="max",
        quality_policy="strict",
    )

    assert result.accepted
    assert result.is_stereo


def test_strict_normal_maps_to_tidal_high_not_lossless():
    accepted = inspect_track_stream(
        stream(quality="HIGH"),
        audio_mode="stereo",
        requested_quality="normal",
        quality_policy="strict",
    )
    rejected = inspect_track_stream(
        stream(quality="LOW"),
        audio_mode="stereo",
        requested_quality="normal",
        quality_policy="strict",
    )

    assert accepted.accepted
    assert not rejected.accepted
    assert "requested exact quality HIGH" in rejected.reason
