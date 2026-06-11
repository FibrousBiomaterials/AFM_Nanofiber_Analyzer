# -*- coding: utf-8 -*-
"""
Round-trip tests for the `cli.py export` subcommand.
`cli.py export` サブコマンドのラウンドトリップテスト。

The export subcommand is the escape hatch from the project-specific `.b2z`
format, so these tests verify that every bundle array survives the trip to
the standard formats bit-for-bit and that the metadata sidecar carries the
provenance fields.
export サブコマンドはプロジェクト固有の `.b2z` 形式からの脱出口であるため、
全バンドル配列が標準形式へビット単位で一致したまま変換されること、および
メタデータ併記ファイルが来歴フィールドを含むことを検証する。
"""

import argparse
import json
import os

import numpy as np

import cli
from lib.blosc2_io import load_bundle
from lib.pipeline import ProcParams, process_file

# tophat keeps these tests fast, mirroring tests/test_pipeline.py.
FAST_PARAMS = ProcParams(bg_method="tophat")


def _make_bundle(synthetic_fiber_txt, tmp_path) -> str:
    """Run the pipeline once and return the resulting bundle path."""
    out_dir = os.path.join(tmp_path, "bundle")
    os.makedirs(out_dir)
    result = process_file(synthetic_fiber_txt, FAST_PARAMS, output_dir=out_dir)
    return result.bundle_path


def test_export_npz_roundtrip(synthetic_fiber_txt, tmp_path):
    """Every bundle array is identical after export to .npz."""
    bundle_path = _make_bundle(synthetic_fiber_txt, tmp_path)
    out_dir = os.path.join(tmp_path, "npz")

    rc = cli.cmd_export(argparse.Namespace(
        inputs=[bundle_path], format="npz", output_dir=out_dir,
    ))
    assert rc == 0

    stem = os.path.splitext(os.path.basename(bundle_path))[0]
    with np.load(os.path.join(out_dir, stem + ".npz")) as npz:
        bundle = load_bundle(bundle_path)
        assert set(npz.files) == set(bundle)
        for key, arr in bundle.items():
            np.testing.assert_array_equal(npz[key], arr)

    with open(os.path.join(out_dir, stem + "_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["params"]["bg_method"] == "tophat"
    assert meta["input_sha256"]
    assert meta["software_version"]


def test_export_csv_writes_one_file_per_key(synthetic_fiber_txt, tmp_path):
    """CSV export produces a loadable text file for every array key."""
    bundle_path = _make_bundle(synthetic_fiber_txt, tmp_path)
    out_dir = os.path.join(tmp_path, "csv")

    rc = cli.cmd_export(argparse.Namespace(
        inputs=[bundle_path], format="csv", output_dir=out_dir,
    ))
    assert rc == 0

    stem = os.path.splitext(os.path.basename(bundle_path))[0]
    bundle = load_bundle(bundle_path)
    for key, arr in bundle.items():
        csv_path = os.path.join(out_dir, f"{stem}_{key}.csv")
        assert os.path.isfile(csv_path), f"missing CSV for key {key!r}"
        loaded = np.loadtxt(csv_path, delimiter=",", ndmin=2)
        np.testing.assert_allclose(loaded, np.atleast_2d(arr.astype(float)))


def test_export_missing_input_returns_2(tmp_path):
    """A nonexistent bundle path is reported as a usage error."""
    rc = cli.cmd_export(argparse.Namespace(
        inputs=[os.path.join(tmp_path, "missing.b2z")],
        format="npz", output_dir=None,
    ))
    assert rc == 2
