# -*- coding: utf-8 -*-
"""
Tests for lib/ml_mask_labels.py, the manual mask-correction sidecar contract.
手動マスク修正 sidecar の契約 lib/ml_mask_labels.py のテスト。

The sidecar's whole purpose is that a human judgement reaches training intact,
so these tests concentrate on the ways it could silently fail to: corrections
applied to the wrong image, drawn over the wrong base mask, or reduced to a
finished mask that no longer says which pixels a person actually touched.
sidecar の目的は人の判断が学習まで無傷で届くことにある。したがって本テストは、
それが黙って失敗しうる経路に集中する。すなわち、誤った画像への適用、誤ったベース
マスクの上に描かれた修正、そしてどの画素を人が実際に触ったかを失った完成マスクへの
還元である。
"""

import os

import numpy as np
import pytest

from lib.blosc2_io import load_bundle_meta, save_bundle
from lib.ml_mask_labels import (
    BASE_BG_CALIBRATOR_MASK,
    BASE_BUNDLE_BINARIZED,
    BASE_SEGMENTER_INTERMEDIATE,
    EDIT_BACKGROUND,
    EDIT_FIBER,
    EDIT_NONE,
    EDITS_KEY,
    MASK_LABEL_SCHEMA_VERSION,
    MASK_LABEL_SUFFIX,
    apply_edits,
    edit_counts,
    edited_indices,
    has_mask_labels,
    image_sha256,
    inspect_mask_labels,
    label_path_for,
    load_mask_labels,
    make_mask_meta,
    new_edit_layer,
    save_mask_labels,
    validate_mask_labels,
)

CREATED = "2026-07-22T00:00:00Z"


def _image(shape=(8, 8), seed=0):
    """
    Build a small deterministic height image for hashing tests.
    ハッシュ検査用の小さな決定的高さ画像を作る。
    """
    rng = np.random.default_rng(seed)
    return rng.normal(size=shape)


def _meta(bundle="sample.b2z", task="binarize",
          base=BASE_SEGMENTER_INTERMEDIATE, image_hash="a" * 64):
    """
    Build conforming sidecar metadata for unit tests.
    単体テスト用に契約へ適合する sidecar メタデータを作る。
    """
    return make_mask_meta(bundle, task, base, image_hash, created_utc=CREATED)


# ----- Paths -----------------------------------------------------------------

def test_label_path_is_a_sibling_of_the_bundle():
    path = label_path_for(os.path.join("data", "scan01.b2z"))
    assert path == os.path.join("data", "scan01" + MASK_LABEL_SUFFIX)


def test_has_mask_labels_reports_absence(tmp_path):
    bundle = str(tmp_path / "scan01.b2z")
    assert has_mask_labels(bundle) is False


# ----- Image binding ---------------------------------------------------------

def test_image_hash_ignores_memory_layout_but_not_content():
    """A sliced view and its contiguous copy must agree; different data must not."""
    image = _image((9, 9))
    aligned = image[1:, 1:]
    assert image_sha256(aligned) == image_sha256(np.array(aligned))
    assert image_sha256(aligned) != image_sha256(image)


def test_image_hash_separates_equal_bytes_with_different_shapes():
    # The shape is mixed into the digest, so a reshaped image is a different
    # image even though its flattened bytes are identical.
    flat = _image((4, 16))
    assert image_sha256(flat) != image_sha256(flat.reshape(16, 4))


# ----- Overlay semantics -----------------------------------------------------

def test_apply_edits_only_changes_edited_pixels():
    base = np.zeros((4, 4), np.uint8)
    base[1, :] = 1
    edits = new_edit_layer((4, 4))
    edits[0, 0] = EDIT_FIBER
    edits[1, 3] = EDIT_BACKGROUND

    label = apply_edits(base, edits)

    assert label[0, 0] == 1        # forced to fiber
    assert label[1, 3] == 0        # forced to background
    assert label[1, 0] == 1        # untouched base fiber survives
    assert label[3, 3] == 0        # untouched base background survives
    # Exactly the two edited pixels differ from the base.
    assert np.count_nonzero(label != base) == 2


def test_apply_edits_rejects_a_shape_mismatch():
    with pytest.raises(ValueError, match="shape"):
        apply_edits(np.zeros((4, 4), np.uint8), new_edit_layer((4, 5)))


def test_edit_bookkeeping_distinguishes_untouched_from_background():
    edits = new_edit_layer((3, 3))
    edits[0, 0] = EDIT_FIBER
    edits[0, 1] = EDIT_FIBER
    edits[2, 2] = EDIT_BACKGROUND

    assert edit_counts(edits) == {"fiber": 2, "background": 1, "total": 3}
    # EDIT_NONE pixels carry no judgement and must not be offered to the
    # sampler as if a person had marked them background.
    assert sorted(edited_indices(edits).tolist()) == [0, 1, 8]


# ----- Round trip ------------------------------------------------------------

def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    image = _image()
    edits = new_edit_layer(image.shape)
    edits[2, 2] = EDIT_FIBER
    edits[5, 1] = EDIT_BACKGROUND
    meta = _meta(image_hash=image_sha256(image))

    save_mask_labels(path, edits, meta)
    loaded = load_mask_labels(
        path,
        expected_image_sha256=image_sha256(image),
        expected_task="binarize",
        expected_base_source=BASE_SEGMENTER_INTERMEDIATE,
        expected_shape=image.shape,
    )

    assert np.array_equal(loaded.edits, edits)
    assert loaded.task == "binarize"
    assert loaded.base_label_source == BASE_SEGMENTER_INTERMEDIATE
    assert loaded.n_edited == 2
    assert load_bundle_meta(path)["schema_version"] == MASK_LABEL_SCHEMA_VERSION


def test_edit_counts_are_not_stored_in_metadata(tmp_path):
    """Derived values are recomputed, so a stale count cannot mislead a reader."""
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    edits = new_edit_layer((8, 8))
    edits[0, 0] = EDIT_FIBER
    save_mask_labels(path, edits, _meta())

    stored = load_bundle_meta(path)
    assert not any("n_edit" in key or "count" in key for key in stored)


# ----- Binding failures ------------------------------------------------------

def test_load_rejects_corrections_made_for_another_image(tmp_path):
    """The failure this guards against is silent: nothing else would notice."""
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    image = _image(seed=0)
    other = _image(seed=1)
    edits = new_edit_layer(image.shape)
    edits[0, 0] = EDIT_FIBER
    save_mask_labels(path, edits, _meta(image_hash=image_sha256(image)))

    with pytest.raises(ValueError, match="image hash mismatch"):
        load_mask_labels(path, expected_image_sha256=image_sha256(other))


def test_load_rejects_corrections_drawn_over_another_base(tmp_path):
    # Corrections drawn over the final stored mask do not describe the
    # pre-filter intermediate decision the binarize model replaces.
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    edits = new_edit_layer((8, 8))
    edits[0, 0] = EDIT_FIBER
    save_mask_labels(path, edits, _meta(base=BASE_BUNDLE_BINARIZED))

    with pytest.raises(ValueError, match="do not describe the same mask"):
        load_mask_labels(path, expected_base_source=BASE_SEGMENTER_INTERMEDIATE)


def test_load_rejects_corrections_made_for_another_task(tmp_path):
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    edits = new_edit_layer((8, 8))
    edits[0, 0] = EDIT_FIBER
    save_mask_labels(
        path, edits, _meta(task="bg_mask", base=BASE_BG_CALIBRATOR_MASK))

    with pytest.raises(ValueError, match="task"):
        load_mask_labels(path, expected_task="binarize")


def test_load_rejects_a_shape_mismatch(tmp_path):
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    edits = new_edit_layer((8, 8))
    edits[0, 0] = EDIT_FIBER
    save_mask_labels(path, edits, _meta())

    with pytest.raises(ValueError, match="target image shape"):
        load_mask_labels(path, expected_shape=(9, 9))


# ----- Contract validation ---------------------------------------------------

@pytest.mark.parametrize("key, value, expected", [
    ("schema_version", "9.9", "unsupported mask label schema version"),
    ("task", "background_surface", "task must be one of"),
    ("base_label_source", "guesswork", "base_label_source must be one of"),
    ("image_sha256", "", "missing 'image_sha256'"),
    ("created_utc", "", "missing 'created_utc'"),
])
def test_validate_reports_each_broken_metadata_key(key, value, expected):
    meta = _meta()
    meta[key] = value
    problems = validate_mask_labels(new_edit_layer((4, 4)), meta)
    assert any(expected in p for p in problems), problems


def test_validate_reports_a_missing_edit_layer():
    problems = validate_mask_labels(None, _meta())
    assert any(f"missing '{EDITS_KEY}'" in p for p in problems), problems


def test_validate_reports_values_outside_the_vocabulary():
    edits = new_edit_layer((4, 4))
    edits[0, 0] = 7
    problems = validate_mask_labels(edits, _meta())
    assert any("outside" in p for p in problems), problems


def test_validate_reports_a_non_2d_edit_layer():
    problems = validate_mask_labels(np.zeros((2, 2, 2), np.uint8), _meta())
    assert any("must be 2D" in p for p in problems), problems


def test_save_refuses_to_write_a_broken_sidecar(tmp_path):
    path = str(tmp_path / ("scan01" + MASK_LABEL_SUFFIX))
    meta = _meta()
    meta["task"] = "background_surface"

    with pytest.raises(ValueError, match="mask label contract violation"):
        save_mask_labels(path, new_edit_layer((4, 4)), meta)
    assert not os.path.exists(path)


# ----- Folder-scan reporting -------------------------------------------------

def test_inspect_separates_absent_broken_and_empty_sidecars(tmp_path):
    bundle = str(tmp_path / "scan01.b2z")
    ok, reason = inspect_mask_labels(bundle)
    assert ok is False and "not found" in reason

    # A sidecar that exists but records nothing is not usable training data.
    save_mask_labels(label_path_for(bundle), new_edit_layer((8, 8)), _meta())
    ok, reason = inspect_mask_labels(bundle)
    assert ok is False and "no edited pixels" in reason

    edits = new_edit_layer((8, 8))
    edits[3, 3] = EDIT_FIBER
    save_mask_labels(label_path_for(bundle), edits, _meta())
    ok, reason = inspect_mask_labels(bundle)
    assert ok is True and reason == ""


def test_inspect_reports_a_sidecar_without_an_edit_layer(tmp_path):
    bundle = str(tmp_path / "scan01.b2z")
    save_bundle(label_path_for(bundle), {"something_else": np.zeros((2, 2))},
                vlmeta=_meta())
    ok, reason = inspect_mask_labels(bundle)
    assert ok is False and EDITS_KEY in reason


def test_edit_none_is_zero_so_a_new_layer_is_empty():
    # The sampler and `apply_edits` both rely on EDIT_NONE being falsy.
    assert EDIT_NONE == 0
    assert edited_indices(new_edit_layer((5, 5))).size == 0
