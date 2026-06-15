# -*- coding: utf-8 -*-
"""
Tests for lib/blosc2_io.py array and bundle round trips.
lib/blosc2_io.py の配列・バンドル往復テスト。
"""

import os

import numpy as np
import pytest

import lib.blosc2_io as blosc2_io
from lib.blosc2_io import (
    save_blosc2, load_blosc2,
    save_bundle, load_bundle, load_bundle_meta,
    bundle_keys, bundle_has_keys,
)


def test_save_load_blosc2_roundtrip(tmp_path):
    """A regular array survives a save/load round trip unchanged."""
    x = np.arange(48, dtype=np.float64).reshape(6, 8)
    path = os.path.join(tmp_path, "x.bl2")
    save_blosc2(path, x)
    y = load_blosc2(path)
    np.testing.assert_array_equal(x, y)


def test_save_load_blosc2_empty_array_fallback(tmp_path):
    """The empty-array .npy fallback round-trips for any target extension.

    Regression test: np.save(path, ...) used to append '.npy' to non-.npy
    paths, desynchronizing the saved filename from the one load_blosc2 reads;
    save_blosc2 now writes through an open file handle.
    """
    x = np.empty((2, 0), dtype=np.float64)
    path = os.path.join(tmp_path, "empty.bl2")
    save_blosc2(path, x)
    assert os.path.isfile(path)            # No '.npy' suffix appended.
    y = load_blosc2(path)
    assert y.shape == (2, 0)


def test_save_load_blosc2_empty_array_with_npy_path(tmp_path):
    """The empty-array fallback round-trips when the path already ends in .npy."""
    x = np.empty((2, 0), dtype=np.float64)
    path = os.path.join(tmp_path, "empty.npy")
    save_blosc2(path, x)
    y = load_blosc2(path)
    assert y.shape == (2, 0)


def test_bundle_roundtrip_with_vlmeta(tmp_path):
    """save_bundle/load_bundle preserve arrays and root metadata."""
    arrays = {
        "calibrated": np.random.default_rng(0).normal(size=(16, 16)),
        "kp": np.array([[1, 2, 3], [4, 5, 6]]),
    }
    meta = {"params": {"bg_method": "tophat"}, "version": "1.0"}
    path = os.path.join(tmp_path, "out.b2z")

    save_bundle(path, arrays, vlmeta=meta)
    loaded = load_bundle(path)

    assert set(loaded) == {"calibrated", "kp"}
    np.testing.assert_allclose(loaded["calibrated"], arrays["calibrated"])
    np.testing.assert_array_equal(loaded["kp"], arrays["kp"])

    loaded_meta = load_bundle_meta(path)
    assert loaded_meta["version"] == "1.0"
    assert loaded_meta["params"]["bg_method"] == "tophat"


def test_save_bundle_failure_preserves_existing_file(tmp_path, monkeypatch):
    """A failed rewrite must not corrupt the previous valid bundle."""
    path = os.path.join(tmp_path, "out.b2z")
    save_bundle(path, {"a": np.array([1])})

    class FailingTreeStore:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("simulated write failure")

    with monkeypatch.context() as m:
        m.setattr(blosc2_io.blosc2, "TreeStore", FailingTreeStore)
        with pytest.raises(RuntimeError, match="simulated write failure"):
            save_bundle(path, {"a": np.array([2])})

    loaded = load_bundle(path)
    np.testing.assert_array_equal(loaded["a"], np.array([1]))


def test_load_bundle_key_subset(tmp_path):
    """load_bundle returns only the requested keys when a subset is given."""
    path = os.path.join(tmp_path, "out.b2z")
    save_bundle(path, {"a": np.zeros(3), "b": np.ones(3)})
    loaded = load_bundle(path, keys=["b"])
    assert set(loaded) == {"b"}


def test_bundle_has_keys_reports_missing(tmp_path):
    """bundle_has_keys detects both present and missing keys."""
    path = os.path.join(tmp_path, "out.b2z")
    save_bundle(path, {"a": np.zeros(3)})

    ok, missing = bundle_has_keys(path, ["a"])
    assert ok and missing == []

    ok, missing = bundle_has_keys(path, ["a", "zz"])
    assert not ok and missing == ["/zz"]

    # A nonexistent file conservatively reports all keys as missing.
    ok, missing = bundle_has_keys(os.path.join(tmp_path, "nope.b2z"), ["a"])
    assert not ok and missing == ["/a"]


def test_bundle_keys_lists_leaves(tmp_path):
    """bundle_keys enumerates all stored leaf datasets with leading slashes."""
    path = os.path.join(tmp_path, "out.b2z")
    save_bundle(path, {"a": np.zeros(3), "b": np.ones((2, 2))})
    assert sorted(bundle_keys(path)) == ["/a", "/b"]
