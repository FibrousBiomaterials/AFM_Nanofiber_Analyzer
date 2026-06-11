# -*- coding: utf-8 -*-
"""
Tests for the ProcParams schema and its JSON merge behavior.
ProcParams スキーマと JSON マージ挙動のテスト。
"""

import json
from dataclasses import asdict

from lib.pipeline import ProcParams, merge_params_dict


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
