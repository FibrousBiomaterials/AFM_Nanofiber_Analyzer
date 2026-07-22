# -*- coding: utf-8 -*-
"""
Tests for hand-painted mask corrections reaching training in lib/ml_dataset.py.
手描きのマスク修正が lib/ml_dataset.py で学習まで届くことのテスト。

These run the real pipeline once to obtain a bundle, then write a correction
sidecar beside it. The point of interest is not that corrections load -- that is
covered in test_ml_mask_labels.py -- but that they change the label the trainer
sees and survive the per-image subsampling that would otherwise discard them
without any error.
本テストは実際のパイプラインを 1 回実行してバンドルを得てから、その隣に修正 sidecar を
書く。関心事は修正が読めることではなく（それは test_ml_mask_labels.py が扱う）、修正が
学習側の見るラベルを実際に変え、放置すれば何のエラーも出さずに修正を捨ててしまう画像
ごとのサブサンプリングを生き延びることである。
"""

import os

import numpy as np
import pytest

from lib import ml_dataset as md
from lib.blosc2_io import load_bundle
from lib.ml_mask_labels import (
    BASE_BUNDLE_BINARIZED,
    BASE_SEGMENTER_INTERMEDIATE,
    EDIT_BACKGROUND,
    EDIT_FIBER,
    image_sha256,
    label_path_for,
    make_mask_meta,
    new_edit_layer,
    save_mask_labels,
)
from lib.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt

# tophat is the fastest background method and is enough for the binarize task,
# whose label comes from the Segmenter rather than the calibrator.
# tophat は最速の背景方式であり、ラベルが補正器ではなく Segmenter 由来である
# binarize タスクにはこれで十分である。
FAST_PARAMS = ProcParams(bg_method="tophat")

CREATED = "2026-07-22T00:00:00Z"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """
    Run the pipeline once and share the resulting bundle path.
    パイプラインを 1 回実行し、生成されたバンドルパスを共用する。
    """
    work = tmp_path_factory.mktemp("corrections")
    src = write_synthetic_fiber_txt(str(work))
    result = process_file(src, FAST_PARAMS, output_dir=str(work))
    return result.bundle_path


@pytest.fixture
def clean_sidecar(bundle):
    """
    Remove any sidecar left by a previous test around each test.
    各テストの前後で、直前のテストが残した sidecar を削除する。
    """
    path = label_path_for(bundle)
    for _phase in range(1):
        if os.path.exists(path):
            os.remove(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def _write_corrections(bundle_path, edits, *, image=None,
                       base=BASE_SEGMENTER_INTERMEDIATE, task="binarize"):
    """
    Write a correction sidecar bound to the bundle's calibrated image.
    バンドルの calibrated 画像へ束縛した修正 sidecar を書き込む。
    """
    if image is None:
        image = load_bundle(bundle_path, keys=["calibrated"])["calibrated"]
    meta = make_mask_meta(
        bundle_path, task, base, image_sha256(image), created_utc=CREATED)
    return save_mask_labels(label_path_for(bundle_path), edits, meta)


def _calibrated(bundle_path):
    return load_bundle(bundle_path, keys=["calibrated"])["calibrated"]


# ----- The corrections reach the label ---------------------------------------

def test_corrections_change_the_label_the_trainer_sees(bundle, clean_sidecar):
    image = _calibrated(bundle)
    base_image, base_label = md.load_image_and_label(
        bundle, task="binarize", label_source=md.LABEL_SEGMENTER_INTERMEDIATE)

    # Flip one pixel of each class, chosen from the base label so the
    # correction is guaranteed to be a real change.
    fiber_px = np.argwhere(base_label == md.LABEL_FIBER)[0]
    bg_px = np.argwhere(base_label == md.LABEL_BACKGROUND)[0]
    edits = new_edit_layer(image.shape)
    edits[tuple(fiber_px)] = EDIT_BACKGROUND
    edits[tuple(bg_px)] = EDIT_FIBER
    _write_corrections(bundle, edits, image=image)

    _img, corrected = md.load_image_and_label(
        bundle, task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)

    assert corrected[tuple(fiber_px)] == md.LABEL_BACKGROUND
    assert corrected[tuple(bg_px)] == md.LABEL_FIBER
    # Nothing else moved: the sidecar records only what a person changed.
    assert np.count_nonzero(corrected != base_label) == 2
    assert np.array_equal(base_image, _img)


def test_corrected_pixels_survive_a_tiny_sample_cap(bundle, clean_sidecar):
    """The failure this guards against is silent: training simply ignores them."""
    image = _calibrated(bundle)
    _img, base_label = md.load_image_and_label(
        bundle, task="binarize", label_source=md.LABEL_SEGMENTER_INTERMEDIATE)

    bg_pixels = np.argwhere(base_label == md.LABEL_BACKGROUND)[:20]
    edits = new_edit_layer(image.shape)
    for y, x in bg_pixels:
        edits[y, x] = EDIT_FIBER
    _write_corrections(bundle, edits, image=image)

    # A cap far below the number of pixels in the image: a plain random draw
    # would keep essentially none of the 20 corrected pixels.
    dataset = md.build_pixel_dataset(
        [bundle], task="binarize", label_source=md.LABEL_EXPERT_CORRECTED,
        max_samples_per_image=40, balance=True, random_state=0)

    corrected_rows = np.count_nonzero(dataset.y == md.LABEL_FIBER)
    assert corrected_rows >= len(bg_pixels)
    assert dataset.provenance[0]["n_edited"] == len(bg_pixels)
    assert dataset.provenance[0]["label_source"] == md.LABEL_EXPERT_CORRECTED


def test_provenance_records_the_label_source_without_corrections(bundle, clean_sidecar):
    dataset = md.build_pixel_dataset(
        [bundle], task="binarize",
        label_source=md.LABEL_SEGMENTER_INTERMEDIATE,
        max_samples_per_image=200, random_state=0)
    record = dataset.provenance[0]
    assert record["label_source"] == md.LABEL_SEGMENTER_INTERMEDIATE
    assert "n_edited" not in record


# ----- Refusals rather than silent fallbacks ---------------------------------

def test_a_bundle_without_corrections_is_reported_not_ignored(bundle, clean_sidecar):
    info = md.inspect_bundle(
        bundle, task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)
    assert info.usable is False
    assert "no mask corrections" in info.reason

    # The same bundle is perfectly usable for the distilled label.
    assert md.inspect_bundle(
        bundle, task="binarize",
        label_source=md.LABEL_SEGMENTER_INTERMEDIATE).usable is True


def test_corrections_drawn_over_the_final_mask_are_refused(bundle, clean_sidecar):
    # Reintroducing the component filters through the base would recreate the
    # double-application problem the intermediate label exists to avoid.
    image = _calibrated(bundle)
    edits = new_edit_layer(image.shape)
    edits[0, 0] = EDIT_FIBER
    _write_corrections(bundle, edits, image=image, base=BASE_BUNDLE_BINARIZED)

    info = md.inspect_bundle(
        bundle, task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)
    assert info.usable is True, "the sidecar itself is readable"

    with pytest.raises(ValueError, match="do not describe the same mask"):
        md.load_image_and_label(
            bundle, task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)


def test_corrections_for_another_image_are_refused(bundle, clean_sidecar):
    image = _calibrated(bundle)
    edits = new_edit_layer(image.shape)
    edits[0, 0] = EDIT_FIBER
    _write_corrections(bundle, edits, image=image + 1.0)

    with pytest.raises(ValueError, match="image hash mismatch"):
        md.load_image_and_label(
            bundle, task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)


def test_build_skips_a_mismatched_bundle_with_a_reason(bundle, clean_sidecar):
    image = _calibrated(bundle)
    edits = new_edit_layer(image.shape)
    edits[0, 0] = EDIT_FIBER
    _write_corrections(bundle, edits, image=image + 1.0)

    with pytest.raises(ValueError, match="no usable bundle produced samples"):
        md.build_pixel_dataset(
            [bundle], task="binarize", label_source=md.LABEL_EXPERT_CORRECTED)


def test_corrections_do_not_apply_to_a_regression_target(bundle):
    with pytest.raises(ValueError, match="does not apply to task"):
        md.inspect_bundle(bundle, task="background_surface",
                          label_source=md.LABEL_EXPERT_CORRECTED)
    with pytest.raises(ValueError, match="does not apply to task"):
        md.build_pixel_dataset([bundle], task="background_surface",
                               label_source=md.LABEL_EXPERT_CORRECTED)


# ----- The distilled path is unchanged ---------------------------------------

def test_distilled_labels_are_unaffected_by_a_present_sidecar(bundle, clean_sidecar):
    """A sidecar must not leak into a run that did not ask for corrections."""
    image = _calibrated(bundle)
    _img, before = md.load_image_and_label(
        bundle, task="binarize", label_source=md.LABEL_SEGMENTER_INTERMEDIATE)

    edits = new_edit_layer(image.shape)
    edits[np.unravel_index(np.argmax(before == md.LABEL_FIBER), before.shape)] = (
        EDIT_BACKGROUND)
    _write_corrections(bundle, edits, image=image)

    _img2, after = md.load_image_and_label(
        bundle, task="binarize", label_source=md.LABEL_SEGMENTER_INTERMEDIATE)
    assert np.array_equal(before, after)
