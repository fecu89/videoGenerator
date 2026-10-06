from __future__ import annotations

from video_harness.render_benchmark import BackendQualityResult, compare_repeat_hashes


def test_same_backend_requires_exact_rgba_hashes() -> None:
    """Changing one decoded frame must block same-backend reuse."""
    assert compare_repeat_hashes(["a", "b"], ["a", "b"]) is None

    issue = compare_repeat_hashes(["a", "b"], ["a", "c"])

    assert issue is not None
    assert issue.frame == 1


def test_cross_backend_quality_does_not_control_cache_eligibility() -> None:
    """A visual regression result must not become a cache-reuse decision."""
    result = BackendQualityResult(
        ssim=0.998,
        psnr=48.0,
        encode_baseline_ssim=0.997,
    )

    assert result.cache_eligible is None
    assert result.visual_regression_passed is True
