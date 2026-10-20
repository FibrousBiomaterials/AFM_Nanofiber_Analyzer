"""Tests for `lib.pipeline.background_warnings` and `flank_step_ratio`.
`lib.pipeline.background_warnings` と `flank_step_ratio` のテスト。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lib.pipeline import (
    BACKGROUND_CHECKED_MAX_WIDTH_PX,
    MIN_FLANK_STEP_RATIO,
    TOPHAT_MIN_ELEMENT_WIDTHS,
    ProcParams,
    background_warnings,
    flank_step_ratio,
)


def _image(width_px, height_nm=2.0, components=5, fallback=0):
    cal = np.zeros((20, 20))
    skel = np.zeros((20, 20), dtype=np.uint8)
    skel[10, 2:18] = 1
    cal[10, 2:18] = height_nm
    return SimpleNamespace(
        apparent_width_summary={"median_px": width_px, "component_count": components,
                                "fallback_count": fallback, "fallback_px": 8.0},
        calibrated_image=cal, skeleton_image=skel)


def _calibrator(sigma):
    fit = SimpleNamespace(best_values={"pv1_sigma": sigma})
    return SimpleNamespace(outx=fit, outy=fit)


def _sigma_for_ratio(ratio, height_nm, width_px, threshold_factor):
    """The difference spread that makes `flank_step_ratio` equal `ratio`."""
    return flank_step_ratio(height_nm, width_px, 1.0, threshold_factor) / ratio


def test_flank_step_ratio_is_steepest_gaussian_slope_over_mark_step():
    # The steepest slope of a Gaussian of FWHM W is H / (sigma sqrt(e)), sigma = W / 2.355.
    h, w, s, tf = 2.0, 10.0, 0.05, 2.0
    sigma = w / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    expected = h / (sigma * np.sqrt(np.e)) / (tf * s)
    assert flank_step_ratio(h, w, s, tf) == pytest.approx(expected)
    x = np.linspace(-50, 50, 200001)
    slope = np.max(np.abs(np.gradient(h * np.exp(-0.5 * (x / sigma) ** 2), x)))
    assert flank_step_ratio(h, w, s, tf) == pytest.approx(slope / (tf * s), rel=1e-4)


def test_no_warning_inside_limits():
    p = ProcParams(bg_method="trendfill")
    sig = _sigma_for_ratio(MIN_FLANK_STEP_RATIO["trendfill"] * 1.2, 2.0, 8.0, p.threshold_factor)
    assert background_warnings(p, _image(8.0), _calibrator(sig)) == []


def test_trendfill_low_ratio_suggests_spline1d_when_spline1d_holds():
    p = ProcParams(bg_method="trendfill")
    ratio = (MIN_FLANK_STEP_RATIO["trendfill"] + MIN_FLANK_STEP_RATIO["spline1d"]) / 2
    sig = _sigma_for_ratio(ratio, 2.0, 8.0, p.threshold_factor)
    (w,) = background_warnings(p, _image(8.0), _calibrator(sig))
    assert w.reason == "flank_step_low"
    assert w.flank_step_ratio == pytest.approx(ratio)
    assert w.suggest_method == "spline1d" and w.suggest_tophat_se_size is None


def test_trendfill_very_low_ratio_suggests_tophat():
    p = ProcParams(bg_method="trendfill")
    sig = _sigma_for_ratio(MIN_FLANK_STEP_RATIO["spline1d"] * 0.5, 2.0, 12.0, p.threshold_factor)
    (w,) = background_warnings(p, _image(12.0), _calibrator(sig))
    assert w.suggest_method == "tophat"
    assert w.suggest_tophat_se_size == 37  # odd(round(3 * 12)), above the 25-px default


def test_wide_fibers_are_outside_the_checked_range():
    p = ProcParams(bg_method="spline1d")
    width = BACKGROUND_CHECKED_MAX_WIDTH_PX + 5
    sig = _sigma_for_ratio(10.0, 2.0, width, p.threshold_factor)
    (w,) = background_warnings(p, _image(width), _calibrator(sig))
    assert w.reason == "width_unchecked"
    assert w.suggest_method == "tophat"
    assert w.suggest_tophat_se_size % 2 == 1
    assert w.suggest_tophat_se_size >= 3 * width - 1


def test_tophat_element_against_width():
    p = ProcParams(bg_method="tophat", tophat_se_size=25)
    assert background_warnings(p, _image(25 / TOPHAT_MIN_ELEMENT_WIDTHS - 0.5), None) == []
    (w,) = background_warnings(p, _image(25 / TOPHAT_MIN_ELEMENT_WIDTHS + 0.5), None)
    assert w.reason == "element_small" and w.flank_step_ratio is None
    assert w.suggest_method == "tophat" and w.suggest_tophat_se_size > 25


def test_no_warning_without_a_measured_width():
    p = ProcParams(bg_method="tophat", tophat_se_size=25)
    assert background_warnings(p, _image(40.0, components=4, fallback=2), None) == []
    assert background_warnings(p, _image(None, components=0), None) == []
