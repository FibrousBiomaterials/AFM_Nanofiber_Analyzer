# -*- coding: utf-8 -*-
"""
Tests for the ProcParams schema and its JSON merge behavior.
ProcParams スキーマと JSON マージ挙動のテスト。
"""

import json
from dataclasses import asdict

import pytest

from lib.pipeline import ProcParams, merge_params_dict, process_file, validate_params

# Serialized schema contract: these names are written verbatim into
# <input_stem>_param.json and the GUI01 startup-settings file. Renaming or
# removing one silently breaks parameter reload, so this snapshot makes any
# schema change an explicit, test-visible decision.
# シリアライズ契約: 以下の名前は <input_stem>_param.json と GUI01 の起動時
# 設定にそのまま書き込まれる。リネームや削除はパラメータ再読込を静かに
# 壊すため、このスナップショットでスキーマ変更を明示的な判断にする。
EXPECTED_FIELDS = {
    # Background calibration.
    "bg_method", "tophat_se_size", "spline1d_axis", "spline1d_degree",
    "spline2d_degree", "spline2d_subsample", "spline2d_smoothing",
    "threshold_factor", "fiber_detect_factor", "noise_detect_factor",
    "savgol_window", "savgol_polyorder", "apply_median",
    "mask_dilation", "min_mask_component_area",
    # Binarization.
    "wsize_localbin", "global_threshold", "area_min", "area_min_connecting",
    "apply_no_connecting", "h_length", "h_sratio", "low_threshold",
    # Skeletonization.
    "bp_height", "branch_length", "min_area",
    # Kink detection.
    "kinkangle_deg",
}


def test_full_dict_roundtrip():
    """A complete parameter dict reconstructs identical ProcParams."""
    original = ProcParams(bg_method="tophat", kinkangle_deg=120.0)
    d = json.loads(json.dumps(asdict(original)))
    params, missing, obsolete = merge_params_dict(d)
    assert params == original
    assert missing == []
    assert obsolete == []


def test_missing_keys_fall_back_to_defaults():
    """Keys absent from old settings files are filled from defaults."""
    d = asdict(ProcParams())
    removed = d.pop("kinkangle_deg")
    assert removed == ProcParams().kinkangle_deg

    params, missing, obsolete = merge_params_dict(d)
    assert params.kinkangle_deg == ProcParams().kinkangle_deg
    assert missing == ["kinkangle_deg"]
    assert obsolete == []


def test_unknown_keys_are_ignored_and_reported():
    """Keys outside the current schema are dropped but reported to callers."""
    d = asdict(ProcParams())
    d["legacy_option"] = 123

    params, missing, obsolete = merge_params_dict(d)
    assert params == ProcParams()
    assert missing == []
    assert obsolete == ["legacy_option"]


def test_empty_dict_yields_pure_defaults():
    """An empty dict produces defaults and reports every key as missing."""
    params, missing, obsolete = merge_params_dict({})
    assert params == ProcParams()
    assert set(missing) == set(asdict(ProcParams()))
    assert obsolete == []


def test_schema_field_names_are_frozen():
    """Schema changes must update EXPECTED_FIELDS deliberately, not by accident."""
    assert set(asdict(ProcParams())) == EXPECTED_FIELDS


def test_default_params_are_valid():
    """The shipped defaults must pass validation for every background method."""
    assert validate_params(ProcParams()) == []
    for method in ("inpaint", "tophat", "spline1d", "spline2d"):
        assert validate_params(ProcParams(bg_method=method)) == []


def test_unknown_bg_method_is_reported():
    """A typo such as 'spline2dd' is rejected instead of selecting a method silently."""
    problems = validate_params(ProcParams(bg_method="spline2dd"))
    assert any("bg_method" in p for p in problems)


def test_savgol_polyorder_must_be_less_than_window():
    """scipy.signal.savgol_filter requires polyorder < window_length."""
    problems = validate_params(ProcParams(savgol_window=5, savgol_polyorder=5))
    assert any("savgol_polyorder" in p for p in problems)


def test_wsize_localbin_must_be_odd():
    """skimage.filters.threshold_local requires an odd block size."""
    problems = validate_params(ProcParams(wsize_localbin=16))
    assert any("wsize_localbin" in p for p in problems)


def test_all_problems_are_collected_at_once():
    """Validation reports every violation so a JSON can be fixed in one pass."""
    problems = validate_params(
        ProcParams(bg_method="typo", wsize_localbin=16, branch_length=0)
    )
    text = "\n".join(problems)
    assert "bg_method" in text
    assert "wsize_localbin" in text
    assert "branch_length" in text
    assert len(problems) >= 3


def test_process_file_rejects_invalid_params_before_io(tmp_path):
    """process_file validates parameters before touching the input file."""
    missing_input = str(tmp_path / "does_not_exist.txt")
    with pytest.raises(ValueError, match="wsize_localbin"):
        process_file(missing_input, ProcParams(wsize_localbin=16))
