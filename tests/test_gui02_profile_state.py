# -*- coding: utf-8 -*-
"""
Tests that GUI02's profile and scale always describe the image on screen.
GUI02 のプロファイルとスケールが常に画面上の画像を表すことのテスト。

Each test reproduces one way the profile, its CSV, or the scale could come to
describe something other than the pixels shown and read: a channel switch, a
failed load, a channel with another extent, a non-height channel chosen by the
automatic selection, a point off the image or on the colorbar, an interpolated
height, and an invalid line width.
各テストは、プロファイル・CSV・スケールが表示・読み取り中の画素以外を表して
しまう経路を 1 つずつ再現する。チャンネル切替、読み込み失敗、範囲の違う
チャンネル、自動選択が選んだ高さ以外のチャンネル、画像外やカラーバー上の点、
補間された高さ、不正な線幅。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from conftest import requires_tk

from lib.blosc2_io import save_bundle
from lib.bundle_schema import (
    BUNDLE_FORMAT_VERSION, CENTERLINE_KEY, SPATIAL_CALIBRATION_KEY,
    make_spatial_calibration,
)
from lib.centerline import DEFAULT_CENTERLINE_METHOD

import guis.GUI02_PlotProfiler as gui02

pytestmark = requires_tk
pytest.importorskip("gwyfile")


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


def _ridge(n, height_nm):
    """A vertical Gaussian ridge, sigma 3 px, across an n x n image."""
    x = np.arange(n)
    return np.tile(height_nm * np.exp(-((x - n / 2) ** 2) / (2 * 3.0 ** 2)), (n, 1))


def _write_gwy(path, channels):
    """
    Write a .gwy holding `channels`, each (title, values, extent_um, z_unit).
    `channels`（各要素は (タイトル, 値, 範囲 µm, z 単位)）を持つ .gwy を書く。
    """
    from gwyfile.objects import GwyContainer, GwyDataField, GwySIUnit

    container = GwyContainer()
    for i, (title, values, extent_um, z_unit) in enumerate(channels):
        container[f"/{i}/data"] = GwyDataField(
            np.asarray(values, dtype=float),
            xreal=extent_um * 1e-6, yreal=extent_um * 1e-6,
            si_unit_xy=GwySIUnit(unitstr="m"),
            si_unit_z=GwySIUnit(unitstr=z_unit),
        )
        container[f"/{i}/data/title"] = title
    container.tofile(str(path))
    return path


def _write_bundle(path, image, scan_um):
    """Write a bundle whose `calibrated` array is `image`, with a scan size."""
    meta = {
        "version": BUNDLE_FORMAT_VERSION,
        CENTERLINE_KEY: DEFAULT_CENTERLINE_METHOD,
        SPATIAL_CALIBRATION_KEY: make_spatial_calibration(scan_um, scan_um, "manual"),
    }
    save_bundle(str(path), {"calibrated": np.asarray(image, dtype=float)}, meta)
    return path


def _open(app, path):
    app.path = str(path)
    app.file_select(str(path))


def _draw_profile(app, frac0=(0.25, 0.5), frac1=(0.75, 0.5)):
    """Place two points at fractions of the extent and compute the profile."""
    ex, ey = app._image_extent_um()
    app.xlist = [frac0[0] * ex, frac1[0] * ex]
    app.ylist = [frac0[1] * ey, frac1[1] * ey]
    app.make_profile()


def _switch_channel(app, index):
    app.gwy_channel_box.current(index)
    app._on_gwy_channel_change()


def _right_click(app, axes, xdata, ydata):
    app.click1(SimpleNamespace(inaxes=axes, xdata=xdata, ydata=ydata, button=3))


# ----- Channel switch (.gwy) ------------------------------------------------

def test_a_channel_switch_drops_the_previous_channels_profile(
    tk_app, tmp_path, dialogs,
):
    path = _write_gwy(tmp_path / "two.gwy", [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Height retrace", _ridge(64, 12.0) * 1e-9, 2.0, "m"),
    ])
    app = tk_app(gui02.App)
    _open(app, path)
    _draw_profile(app)
    assert app.flag2

    _switch_channel(app, 1)

    assert app.img.max() == pytest.approx(12.0)
    # The 5 nm profile of channel 0 can no longer be shown or saved.
    assert not app.flag2
    assert app.xlist == [] and app.ylist == []
    assert dialogs["error"] == []


def test_a_channel_that_cannot_be_read_keeps_the_previous_channel(
    tk_app, tmp_path, dialogs,
):
    broken = _ridge(64, 12.0) * 1e-9
    broken[3, 3] = np.nan
    path = _write_gwy(tmp_path / "broken_second.gwy", [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Height retrace", broken, 2.0, "m"),
    ])
    app = tk_app(gui02.App)
    _open(app, path)
    _draw_profile(app)
    profile = app.profiley.copy()

    _switch_channel(app, 1)

    assert len(dialogs["error"]) == 1
    assert app._gwy_channel_id == app._gwy_channels[0].channel_id
    assert app.gwy_channel_box.current() == 0
    assert app.img.max() == pytest.approx(5.0)
    assert app.flag2 and len(app.xlist) == 2
    assert np.array_equal(app.profiley, profile)


def test_a_channel_with_another_extent_is_measured_with_that_extent(
    tk_app, tmp_path, dialogs,
):
    path = _write_gwy(tmp_path / "extents.gwy", [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Height 4um", _ridge(64, 5.0) * 1e-9, 4.0, "m"),
    ])
    app = tk_app(gui02.App)
    _open(app, path)
    assert app._image_extent_um() == (2.0, 2.0)

    _switch_channel(app, 1)

    assert app.scale_um == 4.0
    assert app._image_extent_um() == (4.0, 4.0)
    _draw_profile(app)
    assert app.profilex[-1] == pytest.approx(2.0)


def test_a_channel_with_the_same_extent_keeps_a_typed_scale(
    tk_app, tmp_path, dialogs,
):
    path = _write_gwy(tmp_path / "same.gwy", [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Height retrace", _ridge(64, 12.0) * 1e-9, 2.0, "m"),
    ])
    app = tk_app(gui02.App)
    _open(app, path)
    app.entryas.delete(0, "end")
    app.entryas.insert(0, "3")
    assert app.validate_input1()

    _switch_channel(app, 1)

    # The switch happened: the 12 nm channel is on screen.
    assert dialogs["error"] == []
    assert app._gwy_channel_id == app._gwy_channels[1].channel_id
    assert app.img.max() == pytest.approx(12.0)
    assert app.scale_um == 3.0
    assert app.entryas.get() == app._fmt_num(3.0)


# ----- Failed load ----------------------------------------------------------

def test_a_file_that_cannot_be_read_leaves_the_shown_image_as_it_was(
    tk_app, tmp_path, dialogs,
):
    good = _write_bundle(tmp_path / "good.b2z", _ridge(64, 5.0), 2.0)
    broken = _ridge(64, 5.0) * 1e-9
    broken[3, 3] = np.nan
    bad = _write_gwy(tmp_path / "bad_5um.gwy", [("Topography", broken, 5.0, "m")])
    app = tk_app(gui02.App)
    _open(app, good)
    _draw_profile(app)
    before = dict(
        scale=(app.scale_um, app.scale_y_um),
        entries=(app.entryas.get(), app.entry_scale_y.get()),
        extent=app._image_extent_um(),
        path=app.path, filename=app.filename, title=app.ax.get_title(),
        label=app.showfilename.cget("text"),
        points=(list(app.xlist), list(app.ylist)),
        profile=app.profiley.copy(),
    )

    _open(app, bad)

    assert len(dialogs["error"]) == 1
    after = dict(
        scale=(app.scale_um, app.scale_y_um),
        entries=(app.entryas.get(), app.entry_scale_y.get()),
        extent=app._image_extent_um(),
        path=app.path, filename=app.filename, title=app.ax.get_title(),
        label=app.showfilename.cget("text"),
        points=(list(app.xlist), list(app.ylist)),
        profile=app.profiley.copy(),
    )
    for key in ("scale", "entries", "extent", "path", "filename", "title",
                "label", "points"):
        assert after[key] == before[key], key
    assert app.flag2
    assert np.array_equal(after["profile"], before["profile"])
    assert app._loaded_path == str(good)


# ----- Non-height channel chosen automatically ------------------------------

# Files with no channel in a length unit; an empty z unit is stored as none.
NO_LENGTH_CHANNEL = {
    "volts": [("Amplitude", _ridge(64, 0.8), 2.0, "V")],
    "no_unit_metres": [("Height", _ridge(64, 5.0) * 1e-9, 2.0, "")],
    "no_unit_volts": [("Amplitude", _ridge(64, 0.8), 2.0, "")],
    "degrees_and_volts": [
        ("Phase", _ridge(64, 30.0), 2.0, "deg"),
        ("Amplitude", _ridge(64, 0.8), 2.0, "V"),
    ],
}


@pytest.mark.parametrize("name", sorted(NO_LENGTH_CHANNEL))
def test_a_gwy_without_a_length_channel_is_refused(
    tk_app, tmp_path, dialogs, name,
):
    path = _write_gwy(tmp_path / f"{name}.gwy", NO_LENGTH_CHANNEL[name])
    app = tk_app(gui02.App)
    _open(app, path)

    assert len(dialogs["error"]) == 1
    assert "no channel with a length unit" in dialogs["error"][0][1]
    assert getattr(app, "img", None) is None
    assert not app.flag1


@pytest.mark.parametrize("name", sorted(NO_LENGTH_CHANNEL) + ["height_and_volts"])
def test_gui02_refuses_the_gwy_files_the_pipeline_refuses(
    tk_app, tmp_path, dialogs, name,
):
    # The rule is written in lib.pipeline.process_file and in GUI02; this
    # keeps the two from drifting apart.
    # 規則は lib.pipeline.process_file と GUI02 の 2 か所にあるため、
    # 両者がずれないことをここで確かめる。
    from lib.pipeline import ProcParams, process_file

    channels = NO_LENGTH_CHANNEL.get(name) or [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Amplitude", _ridge(64, 0.8), 2.0, "V"),
    ]
    path = _write_gwy(tmp_path / f"{name}.gwy", channels)
    try:
        process_file(str(path), ProcParams(), output_dir=str(tmp_path))
        pipeline_refused = False
    except ValueError as exc:
        pipeline_refused = "no channel with a length unit" in str(exc)

    app = tk_app(gui02.App)
    _open(app, path)
    gui02_refused = any(
        "no channel with a length unit" in message
        for _title, message, *_rest in dialogs["error"]
    )

    assert gui02_refused == pipeline_refused
    assert pipeline_refused == (name != "height_and_volts")


def test_an_explicitly_chosen_non_length_channel_still_loads(
    tk_app, tmp_path, dialogs,
):
    path = _write_gwy(tmp_path / "height_and_amplitude.gwy", [
        ("Height", _ridge(64, 5.0) * 1e-9, 2.0, "m"),
        ("Amplitude", _ridge(64, 0.8), 2.0, "V"),
    ])
    app = tk_app(gui02.App)
    _open(app, path)
    assert app.img.max() == pytest.approx(5.0)

    _switch_channel(app, 1)

    assert dialogs["error"] == []
    assert app.img.max() == pytest.approx(0.8)


# ----- Points off the image -------------------------------------------------

def test_a_point_off_the_image_is_not_placed(tk_app, tmp_path, dialogs):
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    ex, ey = app._image_extent_um()

    _right_click(app, app.ax, -0.2 * ex, 0.5 * ey)
    _right_click(app, app.ax, 0.5 * ex, 1.2 * ey)
    assert app.xlist == []

    _right_click(app, app.ax, 0.3 * ex, 0.5 * ey)
    assert app.xlist == [0.3 * ex]


def test_a_point_on_the_right_edge_is_not_placed(tk_app, tmp_path, dialogs):
    # x equal to the extent lies on the border, in no pixel of the image.
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    ex, ey = app._image_extent_um()

    _right_click(app, app.ax, ex, 0.5 * ey)

    assert app.xlist == []


# ----- Sampling band beyond the image edge ----------------------------------

def _rows_image():
    """A 64 x 64 image whose row r holds the value r."""
    return np.tile(np.arange(64, dtype=float)[:, None], (1, 64))


def _profile_along_row(app, row, linewidth, aggregation):
    """Profile along one pixel row, with the aggregation chosen in the combobox."""
    app.rfbox.set(gui02._(aggregation))
    app.rf_selected(None)
    app.linewidth = linewidth
    h, w = app.image_h, app.image_w
    ex, ey = app._image_extent_um()
    y = (h - row - 0.5) * ey / h
    app.xlist = [5.5 * ex / w, 58.5 * ex / w]
    app.ylist = [y, y]
    app.make_profile()
    return app.profiley


@pytest.mark.parametrize("row, linewidth, inside_mean", [
    (0, 3, 0.5),   # rows -1, 0, 1: only rows 0 and 1 are in the image
    (0, 5, 1.0),   # rows -2 .. 2: rows 0, 1, 2
    (1, 5, 1.5),   # rows -1 .. 3: rows 0 .. 3
    (2, 5, 2.0),   # rows 0 .. 4: the whole band is in the image
])
def test_the_mean_leaves_out_samples_beyond_the_image_edge(
    tk_app, tmp_path, dialogs, row, linewidth, inside_mean,
):
    path = _write_bundle(tmp_path / "rows.b2z", _rows_image(), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)

    profile = _profile_along_row(app, row, linewidth, "平均")

    assert np.allclose(profile, inside_mean)


@pytest.mark.parametrize("aggregation, want", [("最大", 12.0), ("最小", 10.0)])
def test_max_and_min_at_the_image_edge_read_only_image_pixels(
    tk_app, tmp_path, dialogs, aggregation, want,
):
    # Offset by 10 so no pixel holds 0: a sample read beyond the edge as a
    # constant 0 would then show as the minimum.
    path = _write_bundle(tmp_path / "rows.b2z", _rows_image() + 10.0, 2.0)
    app = tk_app(gui02.App)
    _open(app, path)

    profile = _profile_along_row(app, 0, 5, aggregation)

    assert np.array_equal(profile, np.full(len(profile), want))


def test_a_line_from_the_outer_half_of_an_edge_pixel_has_no_gap(
    tk_app, tmp_path, dialogs,
):
    path = _write_bundle(tmp_path / "rows.b2z", _rows_image(), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    ex, ey = app._image_extent_um()
    app.linewidth = 1
    # Both ends inside the first and last pixel, near the outer border.
    app.xlist = [0.001 * ex, 0.999 * ex]
    app.ylist = [0.999 * ey, 0.001 * ey]
    app.make_profile()

    assert np.isfinite(app.profiley).all()
    assert app.profiley[0] == 0.0 and app.profiley[-1] == 63.0


def test_a_click_on_the_colorbar_is_not_placed(tk_app, tmp_path, dialogs):
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    ex, ey = app._image_extent_um()

    # Inside the image's numeric range, but on the colorbar axes.
    _right_click(app, app.cax, 0.5 * ex, 0.75 * ey)

    assert app.xlist == []


# ----- Heights are pixel values ---------------------------------------------

@pytest.mark.parametrize("linewidth", [1, 3])
def test_every_profile_height_is_a_pixel_value(
    tk_app, tmp_path, dialogs, linewidth,
):
    image = np.random.default_rng(3).normal(0.0, 1.0, (40, 40))
    path = _write_bundle(tmp_path / "noise.b2z", image, 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    app.linewidth = linewidth

    # End points off the pixel centres, as a mouse click places them.
    _draw_profile(app, (0.137, 0.211), (0.861, 0.773))

    assert np.isin(app.profiley, app.img).all()


# ----- Line width -----------------------------------------------------------

@pytest.mark.parametrize("typed", ["0", "-2"])
def test_a_line_width_below_one_is_refused(tk_app, tmp_path, dialogs, typed):
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    _draw_profile(app)
    profile = app.profiley.copy()

    app.entrylw.delete(0, "end")
    app.entrylw.insert(0, typed)

    assert app.input_lw() is False
    assert app.linewidth == 3
    assert len(dialogs["error"]) == 1
    assert np.array_equal(app.profiley, profile)


@pytest.mark.parametrize("typed", ["2", "4"])
def test_an_even_line_width_is_refused(tk_app, tmp_path, dialogs, typed):
    # An even width puts no sample on the line itself (profile_line spreads
    # the samples (width - 1) / 2 to either side), so only odd widths centre
    # the band on the line.
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    _draw_profile(app)
    profile = app.profiley.copy()

    app.entrylw.delete(0, "end")
    app.entrylw.insert(0, typed)

    assert app.input_lw() is False
    assert app.linewidth == 3
    assert dialogs["error"] == [(gui02._("エラー"), gui02._("1 以上の奇数を入力してください。"))]
    assert np.array_equal(app.profiley, profile)


@pytest.mark.parametrize("typed", ["1", "5"])
def test_an_odd_line_width_is_committed_and_redraws(
    tk_app, tmp_path, dialogs, typed,
):
    path = _write_bundle(tmp_path / "scan.b2z", _ridge(64, 5.0), 2.0)
    app = tk_app(gui02.App)
    _open(app, path)
    _draw_profile(app)

    app.entrylw.delete(0, "end")
    app.entrylw.insert(0, typed)

    assert app.input_lw() is True
    assert app.linewidth == int(typed)
    assert dialogs["error"] == []
    # The profile was recomputed at the new width.
    want = app.profile_between_points(app.xlist[0], app.xlist[1],
                                      app.ylist[0], app.ylist[1])[1]
    assert np.array_equal(app.profiley, want)
