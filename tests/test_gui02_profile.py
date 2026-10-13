# -*- coding: utf-8 -*-
"""
Tests of the distances and scale handling of GUI02's height profiles.
GUI02 の高さプロファイルの距離とスケールの扱いのテスト。

A profile's distance axis is computed from the scale entries and the array
size, so it has to use the pixel size the rest of the project measures with:
for a bundle, `lib.bundle_schema.pixel_size_nm`, because the stored arrays are
one pixel smaller per axis than the scan the recorded scan size describes.
プロファイルの距離軸はスケール欄と配列の大きさから計算されるため、プロジェクト
の他の計測と同じ画素サイズを使う必要がある。バンドルでは保存配列が記録された走査
範囲より各軸 1 画素小さいため、`lib.bundle_schema.pixel_size_nm` を使う。
"""

import math

import numpy as np
import pytest

from conftest import requires_tk

from lib.blosc2_io import save_bundle
from lib.bundle_schema import (
    BUNDLE_FORMAT_VERSION, CENTERLINE_KEY, SPATIAL_CALIBRATION_KEY,
    make_spatial_calibration, pixel_size_nm,
)
from lib.centerline import DEFAULT_CENTERLINE_METHOD

import guis.GUI02_PlotProfiler as gui02

pytestmark = requires_tk


@pytest.fixture
def dialogs(monkeypatch):
    """
    Record message boxes instead of showing them.
    メッセージボックスを表示せずに記録する。
    """
    shown = {"warning": [], "error": []}
    monkeypatch.setattr(
        gui02.messagebox, "showwarning",
        lambda *a, **k: shown["warning"].append(a),
    )
    monkeypatch.setattr(
        gui02.messagebox, "showerror",
        lambda *a, **k: shown["error"].append(a),
    )
    return shown


def _write_bundle(path, shape, scan_um):
    """Write a bundle whose `calibrated` array has `shape`, with a scan size."""
    calibrated = np.arange(shape[0] * shape[1], dtype=float).reshape(shape)
    meta = {
        "version": BUNDLE_FORMAT_VERSION,
        CENTERLINE_KEY: DEFAULT_CENTERLINE_METHOD,
    }
    if scan_um is not None:
        meta[SPATIAL_CALIBRATION_KEY] = make_spatial_calibration(
            scan_um[0], scan_um[1], "manual",
        )
    save_bundle(str(path), {"calibrated": calibrated}, meta)


def _open(app, path):
    app.path = str(path)
    app.file_select(str(path))


def _profile_length_nm(app, c0, r0, c1, r1):
    """
    Profile between two pixel centres, entered as the heatmap places them.
    ヒートマップが描く位置で指定した 2 画素中心間のプロファイルの長さ (nm)。
    """
    h, w = app.image_h, app.image_w
    ex, ey = app._image_extent_um()

    def to_um(c, r):
        return (c + 0.5) * ex / w, (h - r - 0.5) * ey / h

    (x0, y0), (x1, y1) = to_um(c0, r0), to_um(c1, r1)
    app.xlist, app.ylist = [x0, x1], [y0, y1]
    app.linewidth = 1
    app.make_profile()
    return app.profilex[-1] * 1000.0, app.profiley


def test_bundle_profile_uses_the_measured_pixel_size(tk_app, tmp_path, dialogs):
    # Rectangular so a swapped or shared axis would show; small so the
    # trimmed pixel is a large fraction of the length.
    path = tmp_path / "scan.b2z"
    _write_bundle(path, (9, 15), (2.0, 1.5))
    app = tk_app(gui02.App)
    _open(app, path)

    length, heights = _profile_length_nm(app, 1, 2, 13, 7)
    want = math.hypot(12 * pixel_size_nm(2.0, 15), 5 * pixel_size_nm(1.5, 9))
    assert length == pytest.approx(want, rel=1e-12)
    # The end points sample the pixels they were placed on.
    assert heights[0] == app.img[2, 1]
    assert heights[-1] == app.img[7, 13]
    assert dialogs["warning"] == []


def test_untrimmed_input_divides_the_scale_by_the_pixel_count(
    tk_app, tmp_path, dialogs,
):
    path = tmp_path / "scan.npy"
    np.save(path, np.zeros((9, 15)))
    app = tk_app(gui02.App)
    _open(app, path)

    length, _heights = _profile_length_nm(app, 1, 2, 13, 7)
    x_um, y_um = app._scale_xy_um()
    want = math.hypot(12 * x_um * 1000 / 15, 5 * y_um * 1000 / 9)
    assert length == pytest.approx(want, rel=1e-12)


def test_a_file_without_a_scan_size_warns_with_the_kept_scale(
    tk_app, tmp_path, dialogs,
):
    sized = tmp_path / "sized.b2z"
    _write_bundle(sized, (9, 15), (3.0, 1.5))
    unsized = tmp_path / "unsized.npy"
    np.save(unsized, np.zeros((9, 15)))
    app = tk_app(gui02.App)

    _open(app, sized)
    assert dialogs["warning"] == []
    _open(app, unsized)

    # The scale carried over from the previous file is kept and named.
    assert app._scale_xy_um() == (3.0, 1.5)
    assert len(dialogs["warning"]) == 1
    message = dialogs["warning"][0][1]
    assert f"X {app._fmt_num(3.0)} µm" in message
    assert f"Y {app._fmt_num(1.5)} µm" in message


def test_a_bundle_without_a_scan_size_warns(tk_app, tmp_path, dialogs):
    path = tmp_path / "old.b2z"
    _write_bundle(path, (9, 15), None)
    app = tk_app(gui02.App)
    _open(app, path)
    assert len(dialogs["warning"]) == 1


def test_an_unreadable_file_gets_its_error_and_no_scan_size_warning(
    tk_app, tmp_path, dialogs,
):
    path = tmp_path / "broken.npy"
    path.write_bytes(b"not an array")
    app = tk_app(gui02.App)
    _open(app, path)
    assert len(dialogs["error"]) == 1
    assert dialogs["warning"] == []
