# -*- coding: utf-8 -*-
"""
Tests for lib/bundle_schema.py and its enforcement at the IO boundaries.
lib/bundle_schema.py と入出力境界での契約強制のテスト。

Unit tests build tiny handmade arrays so each contract rule can be violated
in isolation. Integration tests confirm that real pipeline output conforms,
that `lib.measure` rejects malformed bundles at load time, and that
`cli.py validate` reports them.
単体テストは小さな手作り配列で契約規則を 1 つずつ違反させて検証する。統合
テストでは、実パイプライン出力が契約に適合すること、`lib.measure` が読み込み
時に不正バンドルを拒否すること、`cli.py validate` がそれを報告することを確認
する。
"""

import json
import os

import numpy as np
import pytest

import cli
from lib.blosc2_io import load_bundle, load_bundle_meta, save_bundle
from lib.bundle_schema import (
    BUNDLE_FORMAT_VERSION,
    REQUIRED_BUNDLE_KEYS,
    SUPPORTED_BUNDLE_VERSIONS,
    TRACKING_BUNDLE_KEYS,
    validate_bundle,
)
from lib.measure import load_tracking_image, skeleton_height_values
from lib.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt

FAST_PARAMS = ProcParams(bg_method="tophat")


def _valid_arrays(shape=(8, 8)):
    """
    Build a minimal conforming bundle-array dict for unit tests.
    単体テスト用に、契約へ適合する最小のバンドル配列辞書を作る。
    """
    h, w = shape
    skeleton = np.zeros(shape, np.uint8)
    skeleton[4, 1:6] = 1
    ep = np.zeros(shape, np.uint8)
    ep[4, 1] = ep[4, 5] = 1
    return {
        "calibrated":   np.random.default_rng(0).normal(size=shape),
        "binarized":    skeleton.astype(bool),
        "skeletonized": skeleton,
        "bp":           np.zeros(shape, np.uint8),
        "ep":           ep,
        "kp":           np.array([[3], [4]]),   # x=3, y=4
        "dp":           np.zeros((2, 0), np.int64),
        "ka":           np.array([2.5]),        # radians, inside (0, pi)
    }


def _valid_meta():
    return {"version": BUNDLE_FORMAT_VERSION}


# ---------------------------------------------------------------------------
# Unit tests on validate_bundle
# ---------------------------------------------------------------------------

def test_valid_bundle_passes():
    """A conforming array set with current version yields no problems."""
    problems = validate_bundle(
        _valid_arrays(), meta=_valid_meta(), require=REQUIRED_BUNDLE_KEYS
    )
    assert problems == []


def test_current_version_is_supported():
    """The version the writer records must be readable by this release."""
    assert BUNDLE_FORMAT_VERSION in SUPPORTED_BUNDLE_VERSIONS


def test_missing_required_key_reported():
    arrays = _valid_arrays()
    del arrays["ka"]
    problems = validate_bundle(arrays, require=REQUIRED_BUNDLE_KEYS)
    assert any("missing required keys" in p and "ka" in p for p in problems)


def test_transposed_kp_rejected():
    """(N, 2) point arrays are the most likely accidental layout."""
    arrays = _valid_arrays()
    arrays["kp"] = arrays["kp"].T.copy()   # (1, 2) instead of (2, 1)
    problems = validate_bundle(arrays)
    assert any(p.startswith("kp:") and "(2, N)" in p for p in problems)


def test_ka_count_must_match_kp():
    arrays = _valid_arrays()
    arrays["ka"] = np.array([2.5, 2.6])    # two angles, one kink point
    problems = validate_bundle(arrays)
    assert any(p.startswith("ka:") and "kp" in p for p in problems)


def test_ka_degrees_rejected():
    """A degree value (e.g. 147.0) stored in ka must be flagged as a unit bug."""
    arrays = _valid_arrays()
    arrays["ka"] = np.array([147.0])
    problems = validate_bundle(arrays)
    assert any("radians" in p for p in problems)


def test_ka_non_finite_rejected():
    arrays = _valid_arrays()
    arrays["ka"] = np.array([np.nan])
    problems = validate_bundle(arrays)
    assert any("ka:" in p and "finite" in p for p in problems)


def test_image_shape_mismatch_reported():
    arrays = _valid_arrays()
    arrays["skeletonized"] = np.zeros((9, 9), np.uint8)
    problems = validate_bundle(arrays)
    assert any("skeletonized" in p and "differs" in p for p in problems)


def test_non_binary_mask_rejected():
    arrays = _valid_arrays()
    arrays["skeletonized"] = arrays["skeletonized"] * 255
    problems = validate_bundle(arrays)
    assert any("skeletonized" in p and "0 or 1" in p for p in problems)


def test_non_finite_height_image_rejected():
    arrays = _valid_arrays()
    arrays["calibrated"][0, 0] = np.nan
    problems = validate_bundle(arrays)
    assert any("calibrated:" in p and "finite" in p for p in problems)


def test_point_coordinates_must_be_integer_dtype():
    arrays = _valid_arrays()
    arrays["kp"] = np.array([[3.5], [4.0]], dtype=float)
    problems = validate_bundle(arrays)
    assert any("kp:" in p and "integer dtype" in p for p in problems)


def test_swapped_xy_detected_on_non_square_image():
    """On a non-square image, x/y swapped coordinates go out of bounds."""
    arrays = _valid_arrays(shape=(8, 16))
    arrays["kp"] = np.array([[12], [4]])    # x=12 < 16, y=4 < 8: valid
    assert validate_bundle(arrays) == []

    arrays["kp"] = np.array([[4], [12]])    # swapped: y=12 >= height 8
    problems = validate_bundle(arrays)
    assert any(p.startswith("kp:") and "y coordinates" in p for p in problems)


def test_unsupported_version_rejected():
    problems = validate_bundle(_valid_arrays(), meta={"version": "9.9"})
    assert any("unsupported bundle format version" in p for p in problems)


def test_missing_version_accepted_for_old_bundles():
    """Bundles from releases before provenance metadata must stay readable."""
    assert validate_bundle(_valid_arrays(), meta={}) == []


def test_partial_load_validated_without_presence_check():
    """GUI03-style partial loads validate just the keys they read."""
    arrays = _valid_arrays()
    partial = {k: arrays[k] for k in ("calibrated", "skeletonized")}
    assert validate_bundle(partial) == []

    partial["skeletonized"] = np.zeros((9, 9), np.uint8)
    assert validate_bundle(partial) != []


def test_original_exempt_from_shape_consistency():
    """`original` is pre-trim and may differ in shape from the image keys."""
    arrays = _valid_arrays()
    arrays["original"] = np.zeros((9, 9))
    assert validate_bundle(arrays) == []


# ---------------------------------------------------------------------------
# Integration with the real pipeline and the IO boundaries
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_bundle(tmp_path_factory):
    """Run the pipeline once; share its bundle across integration tests."""
    tmp_path = tmp_path_factory.mktemp("schema")
    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    result = process_file(txt, FAST_PARAMS, output_dir=out_dir)
    return result.bundle_path


def _corrupted_copy(real_bundle, tmp_path, mutate):
    """Write a mutated copy of the real bundle and return its path."""
    arrays = load_bundle(real_bundle)
    meta = load_bundle_meta(real_bundle)
    mutate(arrays, meta)
    path = os.path.join(tmp_path, "corrupted.b2z")
    save_bundle(path, arrays, vlmeta=meta)
    return path


def test_real_pipeline_output_conforms(real_bundle):
    """What process_file writes passes the full contract check."""
    arrays = load_bundle(real_bundle)
    meta = load_bundle_meta(real_bundle)
    assert validate_bundle(arrays, meta=meta, require=REQUIRED_BUNDLE_KEYS) == []
    assert meta["version"] == BUNDLE_FORMAT_VERSION
    assert np.issubdtype(arrays["kp"].dtype, np.integer)
    assert np.issubdtype(arrays["dp"].dtype, np.integer)


def test_load_tracking_image_rejects_degree_angles(real_bundle, tmp_path):
    """The measure loader fails loudly on a unit-violating bundle."""
    def mutate(arrays, meta):
        arrays["ka"] = np.degrees(arrays["ka"])
    bad = _corrupted_copy(real_bundle, tmp_path, mutate)
    with pytest.raises(ValueError, match="bundle contract violation"):
        load_tracking_image(bad, 10.0)


def test_load_tracking_image_rejects_future_version(real_bundle, tmp_path):
    """A bundle from an incompatible future format version is refused."""
    def mutate(arrays, meta):
        meta["version"] = "9.9"
    bad = _corrupted_copy(real_bundle, tmp_path, mutate)
    with pytest.raises(ValueError, match="unsupported bundle format version"):
        load_tracking_image(bad, 10.0)


def test_skeleton_height_values_flags_malformed_bundle(real_bundle, tmp_path):
    """A shape-violating bundle becomes an error entry, not pooled data."""
    def mutate(arrays, meta):
        arrays["skeletonized"] = arrays["skeletonized"][:-5, :-5]
    bad = _corrupted_copy(real_bundle, tmp_path, mutate)

    heights, errors = skeleton_height_values([bad, real_bundle])
    assert len(errors) == 1
    assert errors[0][0] == bad
    assert "contract violation" in errors[0][1]
    # Heights from the valid bundle are still collected.
    assert heights.size > 0


def test_cli_validate_accepts_real_bundle(real_bundle):
    assert cli.main(["validate", real_bundle]) == 0


def test_cli_validate_rejects_corrupted_bundle(real_bundle, tmp_path):
    def mutate(arrays, meta):
        arrays["kp"] = arrays["kp"].T.copy()
    bad = _corrupted_copy(real_bundle, tmp_path, mutate)
    assert cli.main(["validate", bad, real_bundle]) == 1


def test_cli_process_strict_rejects_unknown_param_key(tmp_path):
    """--strict turns a typoed parameter key into exit code 2."""
    txt = write_synthetic_fiber_txt(tmp_path)
    params_path = os.path.join(tmp_path, "typo_params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump({"bg_method": "tophat", "kinkangle_degg": 150.0}, f)

    rc = cli.main([
        "process", txt, "--params", params_path,
        "--output-dir", os.path.join(tmp_path, "out"), "--strict",
    ])
    assert rc == 2
    # Without --strict the same file is accepted (unknown key ignored).
    assert cli._load_params(params_path).bg_method == "tophat"


def test_tracking_keys_subset_of_required():
    """The GUI04/measure contract must stay a subset of the writer contract."""
    assert set(TRACKING_BUNDLE_KEYS) <= set(REQUIRED_BUNDLE_KEYS)
