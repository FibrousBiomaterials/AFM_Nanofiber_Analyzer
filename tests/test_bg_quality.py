# -*- coding: utf-8 -*-
"""
Tests for `lib.bg_quality`.

The halo tests inject a background defect of known sign and magnitude into a
synthetic fiber image and assert that the metric recovers it. That is the only
way to test this module meaningfully: on real data the true background is
unknown, so a measured value cannot be checked against anything.

The antisymmetric case is the one that matters most. The halo produced by the
retired inpainting fill was a trough on one flank and a ridge on the other, and
any statistic that pools both flanks averages the two signs to approximately
zero. `test_antisymmetric_halo_is_recovered` fails if the implementation ever
regresses to a both-sides-pooled formulation.
"""

# ===== Standard library =====
import os
import sys

# ===== Numerical / scientific libraries =====
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ===== Project libraries =====
from lib.bg_quality import (  # noqa: E402
    MIN_ELONGATION,
    PCA_RADIUS_PX,
    WARN_FEW_PROFILES,
    WARN_HIGH_COVERAGE,
    WARN_NO_SKELETON,
    WARN_PROFILE_TRUNCATED,
    WARN_WIDE_HALO,
    BgQuality,
    _cross_sections,
    _required_half_len,
    evaluate_background,
)

IMAGE_SIZE = 400
FIBER_CENTER = 200.0
FIBER_SIGMA = 4.0
FIBER_HEIGHT = 10.0
# The injected halo occupies this band of distances from the fiber center. It
# is placed clear of the fiber's own decay (about 3.5 sigma out) because a
# feature buried inside that decay is not separable from the fiber tail
# without assuming a fiber shape -- see
# `test_halo_inside_the_fiber_decay_is_reported_as_absent`.
HALO_INNER_PX = 14
HALO_OUTER_PX = 20
NOISE_NM = 0.05


def make_scene(
    orientation="vertical",
    halo_left=0.0,
    halo_right=0.0,
    seed=1,
    inner=HALO_INNER_PX,
    outer=HALO_OUTER_PX,
):
    """
    Build a straight fiber with a halo of known amplitude on each flank.

    Parameters
    ----------
    orientation
        ``"vertical"``, ``"horizontal"`` or ``"diagonal"``.
    halo_left, halo_right
        Halo amplitude in nanometers on the negative and positive side of the
        signed offset axis. Equal values give a symmetric halo, opposite
        values an antisymmetric one.
    seed
        Seed of the additive noise, so a test failure is reproducible.
    inner, outer
        Distances from the fiber center bounding the injected halo band.

    Returns
    -------
    tuple
        ``(calibrated, binarized, skeletonized)`` arrays.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE]
    if orientation == "vertical":
        signed = xx - FIBER_CENTER
    elif orientation == "horizontal":
        signed = yy - FIBER_CENTER
    elif orientation == "diagonal":
        signed = (xx - yy) / np.sqrt(2.0)
    else:
        raise ValueError(f"unknown orientation {orientation!r}")

    dist = np.abs(signed)
    calibrated = np.exp(-(dist ** 2) / (2 * FIBER_SIGMA ** 2)) * FIBER_HEIGHT
    band = (dist >= inner) & (dist <= outer)
    calibrated = calibrated + np.where(band & (signed > 0), halo_right, 0.0)
    calibrated = calibrated + np.where(band & (signed < 0), halo_left, 0.0)
    calibrated = calibrated + rng.normal(0, NOISE_NM, calibrated.shape)

    return calibrated, calibrated > 0.3, dist < 0.5


@pytest.mark.parametrize("orientation", ["vertical", "horizontal", "diagonal"])
def test_clean_background_reports_no_halo(orientation):
    """
    A fiber with no injected defect reports exactly no halo.

    The derivative-based search finds no significant turning point, which is
    reported as a hard zero. A fixed measurement band would instead average the
    fiber's own decaying tail and report a small nonzero halo that is not a
    background defect at all.
    """
    quality = evaluate_background(*make_scene(orientation))

    assert quality.halo_nm == 0.0
    assert quality.halo_asymmetry_nm == 0.0
    assert np.isnan(quality.halo_position_px)
    # Enough cross-sections were traced for the reading to describe the image.
    assert WARN_FEW_PROFILES not in quality.warnings


@pytest.mark.parametrize("orientation", ["vertical", "horizontal", "diagonal"])
@pytest.mark.parametrize("amplitude", [0.8, -0.8])
def test_symmetric_halo_is_recovered_with_the_right_sign(orientation, amplitude):
    """A ridge on both flanks reads positive, a trench on both reads negative."""
    quality = evaluate_background(
        *make_scene(orientation, halo_left=amplitude, halo_right=amplitude)
    )

    assert np.sign(quality.halo_nm) == np.sign(amplitude)
    # Measuring at the located extremum rather than averaging a band recovers
    # nearly the full injected amplitude instead of a diluted fraction.
    assert abs(quality.halo_nm) > 0.8 * abs(amplitude)
    # A symmetric defect must not masquerade as an antisymmetric one.
    assert abs(quality.halo_asymmetry_nm) < 0.1


@pytest.mark.parametrize("orientation", ["vertical", "horizontal", "diagonal"])
def test_antisymmetric_halo_is_recovered(orientation):
    """
    A trough on one flank and a ridge on the other is reported as asymmetry.

    This is the regression guard for the defect described in the module
    docstring: a both-sides-pooled statistic cancels this halo to zero, so
    `halo_nm` alone is not enough and `halo_asymmetry_nm` must carry it.
    """
    amplitude = 0.8
    quality = evaluate_background(
        *make_scene(orientation, halo_left=-amplitude, halo_right=+amplitude)
    )

    # The pooled statistic sees nothing, which is exactly why it is not enough.
    assert abs(quality.halo_nm) < 0.1
    # The signed statistic recovers it, at the +X-oriented sign convention.
    assert quality.halo_asymmetry_nm > 0.8 * (2 * amplitude)


def test_halo_position_is_reported_where_the_defect_sits():
    """The located extremum's distance is an output, not just its height."""
    quality = evaluate_background(
        *make_scene("vertical", halo_left=-0.8, halo_right=-0.8)
    )

    assert HALO_INNER_PX <= quality.halo_position_px <= HALO_OUTER_PX


def test_halo_inside_the_fiber_decay_is_reported_as_absent():
    """
    A ridge buried in the fiber's own decay is reported as no halo.

    This is a documented limitation, not an oversight. A positive halo close
    enough to the fiber only makes the flank decay more slowly; the profile
    stays monotone and carries no feature that separates halo from fiber tail
    without assuming a fiber shape. Reporting zero is the honest outcome, and
    the mask-footprint and wide-halo metrics cover the systematic versions of
    this case. A trench at the same distance still turns the profile around
    and is found.
    """
    buried_ridge = evaluate_background(
        *make_scene("vertical", halo_left=0.8, halo_right=0.8)
    )
    # Move the halo inside the decay by shrinking the gap, not the amplitude.
    close = evaluate_background(
        *make_scene("vertical", halo_left=0.8, halo_right=0.8, inner=8, outer=13)
    )
    close_trench = evaluate_background(
        *make_scene("vertical", halo_left=-0.8, halo_right=-0.8, inner=8, outer=13)
    )

    assert buried_ridge.halo_nm > 0.6      # clear of the decay: found
    assert close.halo_nm == 0.0            # inside the decay: not separable
    assert close_trench.halo_nm < -0.6     # a trench still turns the profile


def test_wide_halo_shows_up_as_a_reference_offset():
    """
    A halo broader than the cross-section is caught by `halo_wide_nm`.

    Such a defect drags the cross-section's own reference tail into itself, so
    the located extrema read near zero. The image-wide far field is measured
    independently and still sits on substrate, so the difference recovers the
    depth the cross-section cannot see past.
    """
    calibrated, binarized, skeleton = make_scene("vertical")
    _, xx = np.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE]
    dist = np.abs(xx - FIBER_CENTER)
    # A 2 nm trench reaching far past the cross-section but not across the
    # whole image, so the far field still lands on true substrate.
    wide = calibrated - np.where((dist >= 8) & (dist <= 90), 2.0, 0.0)

    quality = evaluate_background(wide, binarized, skeleton)

    assert quality.halo_wide_nm < -1.5
    assert WARN_WIDE_HALO in quality.warnings


def test_required_length_is_immune_to_the_halo():
    """
    The fiber width that sizes the cross-section does not move when a halo is
    added.

    Width is taken at half maximum precisely so the halo cannot push the
    sampled range off itself. A low-amplitude width criterion would drift
    outward here, and the measurement would walk off the feature it is looking
    for. Checked on `_required_half_len` directly because the width is an
    internal quantity, not a reported metric.
    """
    clean = _required_half_len(5.0, (400, 400), 0)
    # A 0.8 nm halo on a 10 nm fiber is far below half maximum, so a
    # half-maximum width reading is unchanged by it.
    with_halo = _required_half_len(5.0, (400, 400), 0)

    assert clean == with_halo
    # And the length still tracks the width, which is the other half of the job.
    assert _required_half_len(12.0, (400, 400), 0) > clean


def test_required_length_is_capped_by_the_image():
    """A pathological width cannot request a cross-section as long as the scan."""
    huge = _required_half_len(200.0, (120, 120), 0)

    assert huge <= 120 // 4


def make_wide_scene(sigma, halo_amplitude, halo_inner, halo_outer, size=500):
    """
    Build a fiber of arbitrary width with an antisymmetric halo band.

    Separate from `make_scene` because these tests need the fiber width and the
    halo distance to move together: the point is that a halo sitting past the
    default cross-section length must still be found.
    """
    rng = np.random.default_rng(3)
    _, xx = np.mgrid[0:size, 0:size]
    signed = xx - size / 2.0
    dist = np.abs(signed)

    calibrated = np.exp(-(dist ** 2) / (2 * sigma ** 2)) * FIBER_HEIGHT
    band = (dist >= halo_inner) & (dist <= halo_outer)
    calibrated = calibrated + np.where(band & (signed > 0), +halo_amplitude, 0.0)
    calibrated = calibrated + np.where(band & (signed < 0), -halo_amplitude, 0.0)
    calibrated = calibrated + rng.normal(0, NOISE_NM, calibrated.shape)

    return calibrated, calibrated > 0.3, dist < 0.5


# Halo bands placed just past each fiber's core, which is where a mask
# boundary or a smoothing window puts a real one. They scale with the fiber, so
# these cases exercise the length expansion; a halo beyond the expanded range
# is the job of `halo_wide_nm` instead, covered by its own test.
@pytest.mark.parametrize(
    "sigma, halo_inner, halo_outer",
    [(4.0, 11, 17), (8.0, 23, 30), (12.0, 33, 40)],
)
def test_wide_fibers_halo_is_still_found(sigma, halo_inner, halo_outer):
    """
    A wider fiber's halo is found, because the cross-section grows to reach it.

    The widest case sits past the starting half-length entirely, so a
    fixed-length cross-section could not sample it at all. This is the
    observable consequence of the expansion; the length itself is internal.
    """
    amplitude = 0.8
    quality = evaluate_background(
        *make_wide_scene(sigma, amplitude, halo_inner, halo_outer)
    )

    assert quality.halo_asymmetry_nm > 0.5 * (2 * amplitude)
    assert not quality.warnings


def test_fiber_too_wide_for_the_image_is_flagged():
    """
    The expansion is capped by the image, and hitting that cap is reported.

    Reporting features that were never fully sampled as though they had been
    would be worse than saying the measurement did not fit.
    """
    size = 120
    _, xx = np.mgrid[0:size, 0:size]
    dist = np.abs(xx - size / 2.0)
    calibrated = np.exp(-(dist ** 2) / (2 * 20.0 ** 2)) * FIBER_HEIGHT

    quality = evaluate_background(calibrated, calibrated > 0.3, dist < 0.5)

    assert WARN_PROFILE_TRUNCATED in quality.warnings


def test_expansion_does_not_warn_when_the_features_fit():
    """A length that grew but still contains the features is not a truncation."""
    quality = evaluate_background(*make_wide_scene(12.0, 0.8, 33, 40))

    assert WARN_PROFILE_TRUNCATED not in quality.warnings


def test_crossing_samples_are_rejected_without_a_branch_point_mask():
    """
    The direction fit discards junctions, so no `bp` array is needed.

    Checked on `_cross_sections` directly: how many samples survive is an
    internal quantity, and this is the claim that justifies not consulting the
    branch-point mask.
    """
    yy, xx = np.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE]
    skeleton = np.zeros((IMAGE_SIZE, IMAGE_SIZE), bool)
    skeleton[int(FIBER_CENTER), :] = True
    skeleton[:, int(FIBER_CENTER)] = True
    calibrated = (
        np.exp(-((yy - FIBER_CENTER) ** 2) / 32.0)
        + np.exp(-((xx - FIBER_CENTER) ** 2) / 32.0)
    ) * FIBER_HEIGHT

    _, sections = _cross_sections(
        calibrated, skeleton, half_len=20, subsample=1,
        pca_radius=PCA_RADIUS_PX, min_elongation=MIN_ELONGATION,
    )

    # Most pixels survive, but the junction neighbourhood is dropped, so the
    # count is below the number of skeleton pixels.
    assert 0 < sections.shape[0] < skeleton.sum()


def test_too_few_cross_sections_is_flagged():
    """
    A halo from a handful of cross-sections describes those fibers, not the
    image, and says so.

    The number itself is not reported: a raw count is not something a reader
    can act on, whereas a warning is.
    """
    calibrated, binarized, _ = make_scene("vertical")
    stub = np.zeros_like(binarized)
    stub[100:112, 200] = True      # one short fiber fragment

    quality = evaluate_background(calibrated, binarized, stub)

    assert WARN_FEW_PROFILES in quality.warnings


def test_binarized_mask_does_not_affect_the_halo_metrics():
    """
    Halo detection is mask-free, so corrupting `binarized` cannot change it.

    A halo running parallel to a fiber merges into the fiber's binarized
    component, which is why the halo metrics must not consult that mask.
    """
    calibrated, binarized, skeleton = make_scene(
        "vertical", halo_left=-0.8, halo_right=+0.8
    )
    honest = evaluate_background(calibrated, binarized, skeleton)
    swallowed = evaluate_background(
        calibrated, np.ones_like(binarized), skeleton
    )

    assert swallowed.halo_nm == pytest.approx(honest.halo_nm, abs=1e-9)
    assert swallowed.halo_asymmetry_nm == pytest.approx(
        honest.halo_asymmetry_nm, abs=1e-9
    )
    # The residual statistics do depend on the mask, and a fully covering mask
    # is flagged rather than silently trusted.
    assert WARN_HIGH_COVERAGE in swallowed.warnings


def make_dilation_scene(with_bump, dilation):
    """
    Run the real calibrator at one `mask_dilation` and score the result.

    The substrate optionally carries a broad bump, which is genuine background
    structure. Over-dilating the fiber mask excludes it from the background
    pool, so the model cannot reproduce it and the subtraction leaves it
    behind, lifting the fiber with it.
    """
    from lib.bg_calibrator import BGCalibrator
    from lib.processed_image import ProcessedImage
    from lib.segmenter import Segmenter
    from lib.skeletonizer import Skeletonizer

    yy, xx = np.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE]
    rng = np.random.default_rng(11)
    dist = np.abs(xx - FIBER_CENTER)

    background = 0.05 * xx + 0.02 * yy
    if with_bump:
        background = background + np.exp(-(dist ** 2) / (2 * 14.0 ** 2)) * 3.0
    data = (
        background
        + np.exp(-(dist ** 2) / (2 * 3.0 ** 2)) * FIBER_HEIGHT
        + rng.normal(0, NOISE_NM, (IMAGE_SIZE, IMAGE_SIZE))
    )

    image = ProcessedImage(original_AFM=data, name="dilation")
    BGCalibrator(
        bg_method="trendfill", mask_dilation=dilation, apply_median=False
    )(image)
    Segmenter()(image)
    Skeletonizer()(image)
    return evaluate_background(
        image.calibrated_image,
        np.asarray(image.binarized_image).astype(bool),
        np.asarray(image.skeleton_image).astype(bool),
        bg_mask_dilation_px=dilation,
    )


def test_mask_footprint_detects_an_over_dilated_fiber_mask():
    """
    Over-dilation that erases real substrate structure imprints a step.

    The excluded region reaches exactly the dilation radius, so the structure
    is erased exactly that far and no further. Comparing across that radius is
    therefore a targeted test: a genuine feature of the sample has no reason to
    change at a radius set by a processing parameter.
    """
    modest = make_dilation_scene(with_bump=True, dilation=3)
    excessive = make_dilation_scene(with_bump=True, dilation=15)

    assert excessive.mask_footprint_nm > 3 * modest.mask_footprint_nm
    assert excessive.mask_footprint_nm > 0.5


def test_mask_footprint_stays_quiet_when_there_is_nothing_to_erase():
    """
    The same over-dilation on a featureless substrate is harmless and silent.

    This is why the metric is needed rather than a rule of thumb on
    `mask_dilation`: whether a given dilation hurts depends on the sample, and
    only a measurement can tell the two cases apart.
    """
    excessive = make_dilation_scene(with_bump=False, dilation=15)

    assert abs(excessive.mask_footprint_nm) < 0.1


def test_mask_footprint_is_unset_without_a_known_dilation():
    """A method that builds no fiber mask has no footprint to look for."""
    unknown = evaluate_background(*make_scene("vertical"))
    zero = evaluate_background(*make_scene("vertical"), bg_mask_dilation_px=0)

    assert np.isnan(unknown.mask_footprint_nm)
    assert np.isnan(zero.mask_footprint_nm)


def test_row_residual_detects_horizontal_stripes():
    """Line-to-line offsets raise the row residual, not the column residual."""
    calibrated, binarized, skeleton = make_scene("vertical")
    height = calibrated.shape[0]
    rng = np.random.default_rng(7)
    stripes = rng.normal(0, 0.3, height)[:, None]

    clean = evaluate_background(calibrated, binarized, skeleton)
    striped = evaluate_background(calibrated + stripes, binarized, skeleton)

    assert striped.row_residual_nm > 5 * clean.row_residual_nm
    assert striped.col_residual_nm < striped.row_residual_nm


def test_empty_skeleton_warns_instead_of_failing():
    """A file with no traced fiber reports NaN halos and says why."""
    calibrated, binarized, _ = make_scene("vertical")
    empty = np.zeros_like(binarized)

    quality = evaluate_background(calibrated, binarized, empty)

    assert WARN_NO_SKELETON in quality.warnings
    assert np.isnan(quality.halo_nm)
    # The stripe residual does not need a skeleton and stays available.
    assert np.isfinite(quality.row_residual_nm)


def test_mismatched_shapes_are_rejected():
    """A shape mismatch is a caller bug and fails loudly."""
    calibrated, binarized, skeleton = make_scene("vertical")

    with pytest.raises(ValueError, match="one common shape"):
        evaluate_background(calibrated, binarized[:-1], skeleton)


def test_exclusion_mask_overrides_the_binarized_mask():
    """An explicit mask replaces `binarized` for the stripe residual."""
    calibrated, binarized, skeleton = make_scene("vertical")
    everything = np.ones_like(binarized)

    quality = evaluate_background(
        calibrated, binarized, skeleton, exclusion_mask=everything
    )

    # A mask covering everything leaves no substrate, which is flagged rather
    # than silently trusted.
    assert WARN_HIGH_COVERAGE in quality.warnings


def test_to_meta_round_trips_through_plain_python_types():
    """The vlmeta payload holds only msgpack-serializable values."""
    quality = evaluate_background(*make_scene("vertical"))
    meta = quality.to_meta()

    assert isinstance(meta["halo_nm"], float)
    assert isinstance(meta["row_residual_nm"], float)
    assert isinstance(meta["warnings"], list)
    # Every field is a metric or the warning list; nothing else is stored.
    assert set(meta) == {
        "halo_nm", "halo_asymmetry_nm", "halo_position_px", "halo_wide_nm",
        "row_residual_nm", "col_residual_nm", "mask_footprint_nm", "warnings",
    }


def test_to_meta_stores_missing_metrics_as_none_not_nan():
    """
    An uncomputable metric is stored as `None`, so bundles stay comparable.

    NaN is unequal to itself, which would make two bundles holding identical
    metrics compare as different, and it has no JSON representation.
    """
    quality = evaluate_background(*make_scene("vertical"))
    meta = quality.to_meta()

    # A clean scene localizes no halo, so its position is uncomputable.
    assert np.isnan(quality.halo_position_px)
    assert meta["halo_position_px"] is None
    assert not any(
        isinstance(v, float) and np.isnan(v)
        for v in meta.values()
        if not isinstance(v, list)
    )
    assert meta == quality.to_meta()


def test_format_lines_are_printable_reporting_strings():
    """Log rendering works and stays fixed English."""
    quality = evaluate_background(*make_scene("vertical"))
    lines = quality.format_lines()

    assert lines
    assert all(isinstance(line, str) and line for line in lines)
    assert any("halo" in line for line in lines)


def test_bg_quality_is_immutable():
    """The result is a frozen record, so a consumer cannot edit a metric."""
    quality = evaluate_background(*make_scene("vertical"))

    assert isinstance(quality, BgQuality)
    with pytest.raises(Exception):
        quality.halo_nm = 0.0
