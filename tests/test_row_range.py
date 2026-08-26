# -*- coding: utf-8 -*-
"""
Tests for analyzing a scan-line sub-range (`process_file(row_range=...)`).
走査線の部分範囲を解析する機能（`process_file(row_range=...)`）のテスト。

The point of the feature is that a sub-range is analyzed *as its own image*:
several stages take a threshold from a statistic over the whole array, so
excluding disturbed scan lines changes what the remaining lines are compared
against. What must NOT change is the physical scale — a fiber has to measure
the same whether or not the scan was cropped — and that is what most of these
tests pin down.
この機能の要点は、部分範囲を *それ自体を 1 枚の画像として* 解析することにある。
複数の段が配列全体の統計からしきい値を決めるため、乱れた走査線を除くと残りの
走査線が何と比較されるかが変わる。変わってはならないのは物理スケールであり、
切り出しの有無で同じ繊維の計測長が変わってはならない。以下のテストの大半は
その点を固定するものである。
"""

import os

import numpy as np
import pytest

from lib.blosc2_io import load_bundle, load_bundle_meta
from lib.bundle_schema import SOURCE_REGION_KEY, SPATIAL_CALIBRATION_KEY
from lib.pipeline import ProcParams, process_file, row_range_suffix
from tests.conftest import write_synthetic_fiber_txt

# tophat needs no gradient-histogram fit, so these tests stay fast.
FAST_PARAMS = ProcParams(bg_method="tophat")


@pytest.fixture
def scan(tmp_path):
    """
    A synthetic scan plus the output directory the runs write into.
    合成走査と、各実行の出力先ディレクトリ。
    """
    path = write_synthetic_fiber_txt(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    return str(path), str(out)


def _pixel_size_um(bundle_path):
    """
    Return the (x, y) pixel size a measurement would derive from a bundle.
    バンドルから計測時に導かれる (x, y) 画素サイズを返す。
    """
    arrays = load_bundle(bundle_path, keys=["calibrated"])
    meta = load_bundle_meta(bundle_path)
    cal = arrays["calibrated"]
    cal_um = meta[SPATIAL_CALIBRATION_KEY]
    return (
        cal_um["scan_size_x_um"] / cal.shape[1],
        cal_um["scan_size_y_um"] / cal.shape[0],
    )


def test_suffix_formatting():
    assert row_range_suffix(None) == ""
    assert row_range_suffix((0, 10)) == "_r0-10"
    assert row_range_suffix((473, 696)) == "_r473-696"


def test_crop_writes_its_own_bundle(scan):
    path, out = scan
    whole = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0))
    part = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                        row_range=(40, 130))

    assert whole.bundle_path != part.bundle_path
    assert "_r40-130" in os.path.basename(part.bundle_path)
    # Both sidecars survive: one range must not overwrite another's outputs.
    assert os.path.isfile(whole.bundle_path) and os.path.isfile(part.bundle_path)
    assert os.path.isfile(whole.param_path) and os.path.isfile(part.param_path)


def test_crop_analyzes_only_the_requested_lines(scan):
    path, out = scan
    whole = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0))
    part = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                        row_range=(40, 130))

    rows_whole = load_bundle(whole.bundle_path, keys=["calibrated"])["calibrated"].shape[0]
    rows_part = load_bundle(part.bundle_path, keys=["calibrated"])["calibrated"].shape[0]
    # The stages drop one row, so 90 kept input lines become 89 stored ones.
    # ステージが 1 行落とすため、残した入力 90 行は保存時 89 行になる。
    assert rows_whole == 192 - 1
    assert rows_part == 90 - 1


def test_pixel_size_is_unchanged_by_cropping(scan):
    """
    Cropping must not rescale the image: a fiber measures the same either way.
    切り出しで画像がスケールされてはならない。同じ繊維は同じ長さで測れること。
    """
    path, out = scan
    whole = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0))
    part = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                        row_range=(40, 130))

    wx, wy = _pixel_size_um(whole.bundle_path)
    px, py = _pixel_size_um(part.bundle_path)
    assert px == pytest.approx(wx, rel=1e-9)
    assert py == pytest.approx(wy, rel=1e-9)
    # And the crop's own grid stays square, as the scan's was.
    assert px == pytest.approx(py, rel=1e-9)


def test_source_region_is_recorded_only_for_a_crop(scan):
    path, out = scan
    whole = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0))
    part = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                        row_range=(40, 130))

    assert SOURCE_REGION_KEY not in load_bundle_meta(whole.bundle_path)
    region = load_bundle_meta(part.bundle_path)[SOURCE_REGION_KEY]
    assert region["row_start"] == 40
    assert region["row_stop"] == 130
    # The input's full scan-line count, so the crop can be located in the source.
    assert region["row_total"] == 192


def test_crop_content_matches_the_same_lines_of_the_source(scan):
    """
    The analyzed array must be the requested lines, not some other window.
    解析される配列が、要求した走査線そのものであること。
    """
    path, out = scan
    part = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                        row_range=(40, 130), save_original=True)
    original = load_bundle(part.bundle_path, keys=["original"])["original"]

    from lib.afm_io import load_afm_image
    expected = load_afm_image(path)[40:130]
    assert original.shape == expected.shape
    assert np.allclose(original, expected)


@pytest.mark.parametrize("bad", [(0, 0), (130, 40), (-1, 20), (0, 100000)])
def test_invalid_ranges_are_rejected(scan, bad):
    """
    A range outside the image must fail loudly, never clamp silently.
    画像外の範囲は黙って丸めず、明示的に失敗すること。
    """
    path, out = scan
    with pytest.raises(ValueError, match="row_range"):
        process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                     row_range=bad)


def test_full_range_matches_the_uncropped_run(scan):
    """
    Asking for every scan line explicitly must analyze the same pixels.
    全走査線を明示的に指定した場合、解析される画素が同じであること。
    """
    path, out = scan
    from lib.afm_io import load_afm_image
    n_rows = load_afm_image(path).shape[0]

    whole = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0))
    explicit = process_file(path, FAST_PARAMS, output_dir=out, scan_size_um=(2.0, 2.0),
                            row_range=(0, n_rows))

    a = load_bundle(whole.bundle_path, keys=["calibrated"])["calibrated"]
    b = load_bundle(explicit.bundle_path, keys=["calibrated"])["calibrated"]
    assert a.shape == b.shape
    assert np.array_equal(a, b)
    assert _pixel_size_um(whole.bundle_path) == pytest.approx(
        _pixel_size_um(explicit.bundle_path), rel=1e-9
    )


# ---------- Command-line interface ----------

def test_parse_row_ranges_accepts_the_documented_forms():
    from cli import _parse_row_ranges

    assert _parse_row_ranges(None) == [None]
    assert _parse_row_ranges("") == [None]
    assert _parse_row_ranges("473-696") == [(473, 696)]
    assert _parse_row_ranges("473-696,709-842") == [(473, 696), (709, 842)]
    # Whitespace around a range is a normal thing to type or paste.
    assert _parse_row_ranges(" 10-20 , 30-40 ") == [(10, 20), (30, 40)]


@pytest.mark.parametrize("bad", ["abc", "10", "500-100", "0-0", "x-y", "-"])
def test_parse_row_ranges_rejects_malformed_input(bad):
    from cli import _parse_row_ranges

    with pytest.raises(ValueError):
        _parse_row_ranges(bad)


def test_cli_rows_writes_one_bundle_per_range(scan, capsys):
    """
    `process --rows a-b,c-d` must produce one bundle per range.
    `process --rows a-b,c-d` は範囲ごとに 1 バンドルを生成すること。
    """
    import cli

    path, out = scan
    rc = cli.main([
        "process", path, "--rows", "40-130,140-190", "--output-dir", out,
    ])
    assert rc == 0
    names = sorted(f for f in os.listdir(out) if f.endswith(".b2z"))
    assert len(names) == 2
    assert any("_r40-130" in n for n in names)
    assert any("_r140-190" in n for n in names)

    # A second run skips both, so the existing-output check looks at the same
    # suffixed paths the first run wrote.
    capsys.readouterr()
    assert cli.main([
        "process", path, "--rows", "40-130,140-190", "--output-dir", out,
    ]) == 0
    # Count the per-job lines, not the word (the summary repeats it).
    out_text = capsys.readouterr().out
    assert out_text.count("(outputs exist; use --overwrite)") == 2


def test_cli_rejects_a_malformed_rows_value(scan, capsys):
    import cli

    path, out = scan
    assert cli.main(["process", path, "--rows", "nonsense", "--output-dir", out]) == 2
    assert "--rows" in capsys.readouterr().err


# ---------- GUI01 scan-line-range cell ----------

def _gui():
    """
    Import GUI01 without creating a window (module import is side-effect free).
    ウィンドウを作らずに GUI01 を import する（モジュール import に副作用は無い）。
    """
    import guis.GUI01_Image_Preprocessor as gui
    return gui


@pytest.mark.parametrize("text,expected", [
    ("", []),
    ("473-696", [(473, 696)]),
    ("473-696,709-842", [(473, 696), (709, 842)]),
    (" 10-20 , 30-40 ", [(10, 20), (30, 40)]),
    # Out of order in, sorted out: the table lists ranges in scan-line order.
    ("30-40,10-20", [(10, 20), (30, 40)]),
])
def test_cell_text_parses_to_ranges(text, expected):
    assert _gui().parse_row_ranges_text(text, 1024) == (True, expected)


@pytest.mark.parametrize("text", [
    "abc", "10", "30-10", "0-0", "-", "10-20,15-30",  # last one overlaps
])
def test_cell_text_rejects_malformed_or_overlapping(text):
    ok, _ranges = _gui().parse_row_ranges_text(text, 1024)
    assert not ok


def test_cell_text_rejects_a_range_past_the_end_of_the_scan():
    gui = _gui()
    assert gui.parse_row_ranges_text("900-2000", 1024)[0] is False
    # Without a known scan-line count the bound cannot be checked, and the
    # pipeline rejects it later rather than the cell refusing valid input.
    assert gui.parse_row_ranges_text("900-2000", None)[0] is True


def test_discover_row_ranges_reads_them_back_from_the_output_names(tmp_path):
    """
    Scan-line ranges must survive a folder being closed and reopened.
    走査線範囲は、フォルダを閉じて開き直しても失われないこと。
    """
    gui = _gui()
    path = write_synthetic_fiber_txt(tmp_path)
    assert gui.discover_row_ranges(path) == []

    stem = os.path.splitext(path)[0]
    for name in ("_r40-130", "_r140-190"):
        open(stem + name + ".b2z", "wb").close()
    # A whole-image bundle is not a range and must not appear.
    open(stem + ".b2z", "wb").close()
    assert gui.discover_row_ranges(path) == [(40, 130), (140, 190)]


def test_file_item_derives_its_outputs_and_extent_from_the_range():
    gui = _gui()
    whole = gui.FileItem(txt_path=os.path.join("d", "scan.txt"),
                         scale_x_um=10.0, scale_y_um=10.0, full_rows=1024)
    part = gui.FileItem(txt_path=os.path.join("d", "scan.txt"),
                        scale_x_um=10.0, scale_y_um=10.0, full_rows=1024,
                        row_range=(473, 696))

    # Separate outputs, so one range cannot overwrite another's bundle.
    assert whole.stem != part.stem
    assert part.stem.endswith("_r473-696")
    assert part.row_range_display == "473-696"
    assert whole.row_range_display == ""

    # The stored scan size stays the whole scan's; only the derived extent
    # follows the range, so clearing the range restores the full height.
    assert part.scan_size_um == (10.0, 10.0)
    assert part.analyzed_scan_size_um[0] == 10.0
    assert part.analyzed_scan_size_um[1] == pytest.approx(10.0 * 223 / 1024)
    assert whole.analyzed_scan_size_um == (10.0, 10.0)


def test_clearing_the_range_cell_collapses_the_whole_family():
    """
    Emptying one range cell must restore the whole image, not just that entry.
    範囲セルを 1 つ空にしたら、その項目だけでなく画像全体へ戻ること。

    This is what the "分割を解除" button drives, and it has to collapse every
    sibling of the same input: leaving the others split would turn one undo
    into one undo per range.
    「分割を解除」ボタンが駆動するのはこの動作であり、同じ入力の兄弟項目を
    すべてまとめる必要がある。他が分割されたまま残ると、1 回の解除が範囲の数
    だけの解除に化けてしまう。
    """
    gui = _gui()
    ok, ranges = gui.parse_row_ranges_text("", 1024)
    # An empty cell is valid and means "no ranges", which the caller turns
    # into a single whole-image entry.
    assert ok and ranges == []
