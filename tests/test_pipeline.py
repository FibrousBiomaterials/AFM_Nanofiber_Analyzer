# -*- coding: utf-8 -*-
"""
Tests for lib/pipeline.py using the synthetic bent-fiber image.
合成の折れ繊維画像を用いた lib/pipeline.py のテスト。

These tests assert physically self-evident properties of the synthetic input
(one fiber, one kink at the drawn bend) so they stay valid when algorithm
details are tuned, unlike golden-value tests on real data.
これらのテストは合成入力の物理的に自明な性質（繊維 1 本・描いた折れ目に
キンク 1 点）を検証する。実データのゴールデン値テストと異なり、アルゴリズム
の調整後も成立し続ける。
"""

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np
import pytest

import lib
from lib.blosc2_io import load_bundle, load_bundle_meta
from lib.pipeline import (
    ProcParams, STAGE_KEYS, REQUIRED_BUNDLE_KEYS,
    build_stages, process_file, merge_params_dict,
    bundle_path_for, param_path_for, existing_min_set,
)

# tophat keeps the unit test fast; the slow integration test covers the
# default inpaint method on a real scan.
# 単体テストは高速な tophat を使い、既定の inpaint 法は実データの統合テスト
# 側でカバーする。
FAST_PARAMS = ProcParams(bg_method="tophat")


@pytest.fixture
def pipeline_result(synthetic_fiber_txt, tmp_path):
    """Run the full pipeline once and share the result across assertions."""
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    events = []
    result = process_file(
        synthetic_fiber_txt,
        FAST_PARAMS,
        output_dir=out_dir,
        on_stage=events.append,
    )
    return result, events


def test_stage_events_in_order(pipeline_result):
    """on_stage receives every stage key exactly once, in pipeline order."""
    _result, events = pipeline_result
    assert tuple(events) == STAGE_KEYS


def test_outputs_written_and_recognized(pipeline_result):
    """The bundle and sidecar JSON exist and pass the analyzed-state check."""
    result, _events = pipeline_result
    assert os.path.isfile(result.bundle_path)
    assert os.path.isfile(result.param_path)

    stem = os.path.splitext(result.bundle_path)[0]
    assert result.bundle_path == bundle_path_for(stem)
    assert result.param_path == param_path_for(stem)

    ok, missing = existing_min_set(stem)
    assert ok, f"missing bundle keys: {missing}"


def test_bundle_contract(pipeline_result):
    """The bundle holds all required keys with the documented shapes/units."""
    result, _events = pipeline_result
    data = load_bundle(result.bundle_path)

    assert set(REQUIRED_BUNDLE_KEYS) <= set(data)

    # The background calibrator trims one pixel per axis, so all image-like
    # outputs are (H-1, W-1) relative to the 192x192 input and must agree.
    # 背景補正器が各軸 1 画素分トリミングするため、画像系出力は入力 192x192
    # に対して (H-1, W-1) となり、全キーで一致していなければならない。
    image_shape = (191, 191)
    assert data["calibrated"].shape == image_shape
    assert data["binarized"].shape == image_shape
    assert data["skeletonized"].shape == image_shape
    assert data["bp"].shape == image_shape
    assert data["ep"].shape == image_shape

    # Point sets are (2, N) coordinate arrays; angles are radians in (0, pi).
    # 座標群は (2, N) 配列、角度は (0, pi) のラジアン値。
    assert data["kp"].ndim == 2 and data["kp"].shape[0] == 2
    assert data["dp"].ndim == 2 and data["dp"].shape[0] == 2
    assert data["ka"].shape == (data["kp"].shape[1],)
    assert np.all(data["ka"] > 0) and np.all(data["ka"] < np.pi)


def test_detects_the_drawn_kink(pipeline_result):
    """The synthetic bend (~147 deg interior angle) is found as one kink."""
    result, _events = pipeline_result
    image = result.image

    assert (image.skeleton_image > 0).sum() > 0
    ka = image.all_kink_angles
    assert len(ka) == 1
    # 147 deg = 2.57 rad; allow tolerance for rasterization effects.
    # 147 度 = 2.57 rad。ラスタライズの影響を考慮した許容幅を設ける。
    assert np.degrees(ka[0]) == pytest.approx(147.0, abs=8.0)

    kp_x, kp_y = image.all_kink_coordinates
    assert kp_x[0] == pytest.approx(100, abs=6)
    assert kp_y[0] == pytest.approx(90, abs=6)


def test_param_json_roundtrips_to_same_params(pipeline_result):
    """The sidecar JSON reloads into ProcParams equal to those used."""
    result, _events = pipeline_result
    with open(result.param_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    params, missing, obsolete = merge_params_dict(d)
    assert params == FAST_PARAMS
    assert missing == [] and obsolete == []


def test_vlmeta_records_params(pipeline_result):
    """Bundle metadata embeds the analysis parameters for provenance."""
    result, _events = pipeline_result
    meta = load_bundle_meta(result.bundle_path)
    assert meta["version"] == "1.0"
    assert meta["params"]["bg_method"] == "tophat"


def test_vlmeta_records_provenance(pipeline_result, synthetic_fiber_txt):
    """Bundle metadata identifies the input file, software release, and time."""
    result, _events = pipeline_result
    meta = load_bundle_meta(result.bundle_path)

    assert meta["software_version"] == lib.__version__
    assert meta["input_file"] == os.path.basename(synthetic_fiber_txt)
    with open(synthetic_fiber_txt, "rb") as f:
        assert meta["input_sha256"] == hashlib.sha256(f.read()).hexdigest()
    # ISO 8601 UTC timestamp, e.g. 2026-06-11T05:00:00+00:00.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", meta["created_utc"])


def test_software_version_matches_pyproject():
    """lib.__version__ is the runtime copy of the pyproject [project] version."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M
    )
    assert match is not None, "version not found in pyproject.toml"
    assert lib.__version__ == match.group(1)


def test_save_original_key_is_optional(synthetic_fiber_txt, tmp_path):
    """The raw image is bundled only when save_original is requested."""
    out_dir = os.path.join(tmp_path, "with_original")
    os.makedirs(out_dir)
    result = process_file(
        synthetic_fiber_txt, FAST_PARAMS,
        output_dir=out_dir, save_original=True,
    )
    data = load_bundle(result.bundle_path)
    assert "original" in data
    assert data["original"].shape == (192, 192)


def test_prebuilt_stages_match_fresh_stages(synthetic_fiber_txt, tmp_path):
    """Reusing batch stages gives the same result as building them inline."""
    out_a = os.path.join(tmp_path, "a")
    out_b = os.path.join(tmp_path, "b")
    os.makedirs(out_a)
    os.makedirs(out_b)

    fresh = process_file(synthetic_fiber_txt, FAST_PARAMS, output_dir=out_a)
    reused = process_file(
        synthetic_fiber_txt, FAST_PARAMS,
        stages=build_stages(FAST_PARAMS), output_dir=out_b,
    )
    np.testing.assert_array_equal(
        fresh.image.skeleton_image, reused.image.skeleton_image
    )
    np.testing.assert_allclose(
        fresh.image.calibrated_image, reused.image.calibrated_image
    )
