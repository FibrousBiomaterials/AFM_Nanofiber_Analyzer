# -*- coding: utf-8 -*-
"""
Tests for opening a bundle as an editing session (`bundle_edit`).
バンドルを編集セッションとして開く処理（`bundle_edit`）のテスト。

What the session adds to the stored arrays is the raw height image and the
fiber mask of the background stage, neither of which a bundle is sure to hold.
These tests pin down where the raw image is taken from, when it is refused,
and that the repeated background stage gives the stored heights back, which is
the only ground on which the mask it yields can be called the analysis's own.
セッションが保存された配列に加えるのは、生の高さ画像と背景補正の繊維マスクで、
どちらもバンドルが必ず持つとは限らない。以下のテストは、生の画像をどこから取るか、
どんなときに拒否するか、そして、やり直した背景補正が保存済みの高さを返すことを
固定する。最後の点は、得られたマスクを解析時のものと呼べる唯一の根拠である。
"""

import os
import shutil

import numpy as np
import pytest
from scipy.ndimage import distance_transform_edt

from afm_nanofiber_analyzer.bundle_edit import (
    RAW_FROM_BUNDLE, RAW_FROM_INPUT_FILE, RAW_MISSING_CHANGED,
    RAW_MISSING_NOT_FOUND, align_raw, load_edit_session,
)
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_gwy, write_synthetic_fiber_txt


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    """
    A synthetic scan analyzed beside itself, shared across this module.
    合成走査を、その隣に解析結果を書く形で解析したもの。モジュール内で共有する。

    Returns the input path and the bundle path; the bundle holds no
    ``original``, so a session has to read the raw image from the input file.
    入力のパスとバンドルのパスを返す。バンドルは ``original`` を持たないので、
    セッションは生の画像を入力ファイルから読むことになる。
    """
    folder = tmp_path_factory.mktemp("bundle_edit")
    txt = write_synthetic_fiber_txt(folder)
    result = process_file(txt, ProcParams())
    return txt, result.bundle_path


def _copy_bundle(bundle_path, folder):
    """
    Copy a bundle alone into another folder and return the new path.
    バンドルだけを別のフォルダへコピーし、新しいパスを返す。
    """
    os.makedirs(folder, exist_ok=True)
    return shutil.copy2(bundle_path, os.path.join(folder, os.path.basename(bundle_path)))


def test_raw_image_is_read_from_the_input_file_beside_the_bundle(analyzed):
    """
    Without ``original``, the raw image comes from the recorded input file.
    ``original`` が無ければ、生の画像は記録された入力ファイルから読む。
    """
    txt, bundle = analyzed
    session = load_edit_session(bundle)

    assert session.raw.source == RAW_FROM_INPUT_FILE
    assert session.raw.detail == os.path.basename(txt)
    written = np.loadtxt(txt, delimiter=",")
    np.testing.assert_array_equal(session.raw.height, written)
    # The stored arrays start at raw pixel (1, 1).
    # 保存された配列は、生の画像の画素 (1, 1) から始まる。
    assert session.raw_aligned.shape == session.arrays["calibrated"].shape
    np.testing.assert_array_equal(session.raw_aligned, written[1:, 1:])


def test_repeated_background_gives_the_stored_heights_and_a_mask(analyzed):
    """
    The repeated stage reproduces ``calibrated`` and yields the fiber mask.
    やり直した補正は ``calibrated`` を再現し、繊維マスクを返す。
    """
    _txt, bundle = analyzed
    session = load_edit_session(bundle)

    background = session.background
    assert background.reproduces
    assert background.max_difference_nm == 0.0
    mask = session.fiber_mask
    assert mask.dtype == bool
    assert mask.shape == session.arrays["calibrated"].shape
    assert mask.any() and not mask.all()


def test_raw_image_in_the_bundle_is_used_without_an_input_file(tmp_path):
    """
    A bundle analyzed with ``save_original`` needs no file beside it.
    ``save_original`` を付けて解析したバンドルは、隣にファイルが無くてよい。
    """
    source = tmp_path / "source"
    source.mkdir()
    txt = write_synthetic_fiber_txt(source)
    out = tmp_path / "out"
    out.mkdir()
    result = process_file(txt, ProcParams(), output_dir=str(out), save_original=True)

    session = load_edit_session(result.bundle_path)

    assert session.raw.source == RAW_FROM_BUNDLE
    assert session.background.reproduces
    assert session.fiber_mask is not None


def test_missing_input_file_leaves_the_stored_arrays_usable(analyzed, tmp_path):
    """
    Without a raw image the session still opens, and says what is missing.
    生の画像が無くてもセッションは開き、何が無いかを示す。
    """
    _txt, bundle = analyzed
    alone = _copy_bundle(bundle, tmp_path / "alone")

    session = load_edit_session(alone)

    assert session.raw.height is None
    assert session.raw.problem == RAW_MISSING_NOT_FOUND
    assert session.raw_aligned is None
    assert session.background is None
    assert session.fiber_mask is None
    assert session.arrays["calibrated"].ndim == 2
    assert session.centerlines


def test_input_file_with_other_contents_is_refused(analyzed, tmp_path):
    """
    A file of the recorded name whose digest differs is not read as the raw image.
    記録された名前でもダイジェストが違うファイルは、生の画像として読まない。
    """
    txt, bundle = analyzed
    folder = tmp_path / "changed"
    moved = _copy_bundle(bundle, folder)
    heights = np.loadtxt(txt, delimiter=",")
    heights[0, 0] += 1.0
    np.savetxt(os.path.join(folder, os.path.basename(txt)), heights,
               delimiter=",", fmt="%.4f")

    session = load_edit_session(moved)

    assert session.raw.height is None
    assert session.raw.problem == RAW_MISSING_CHANGED
    assert session.background is None


def test_method_without_a_mask_reproduces_but_has_no_mask(tmp_path):
    """
    A ``tophat`` bundle is checked like any other and has no fiber mask.
    ``tophat`` のバンドルも同じように照合され、繊維マスクは持たない。
    """
    txt = write_synthetic_fiber_txt(tmp_path)
    result = process_file(txt, ProcParams(bg_method="tophat"))

    session = load_edit_session(result.bundle_path)

    assert session.raw.source == RAW_FROM_INPUT_FILE
    assert session.background.reproduces
    assert session.fiber_mask is None


def test_analyzed_scan_lines_are_cut_from_the_input_file(tmp_path):
    """
    A bundle of a scan-line range is compared with the same lines of its input.
    走査線の範囲を解析したバンドルは、入力の同じ走査線と照合される。
    """
    txt = write_synthetic_fiber_txt(tmp_path)
    result = process_file(txt, ProcParams(), row_range=(20, 170))

    session = load_edit_session(result.bundle_path)

    assert session.raw.height.shape[0] == 150
    assert session.raw_aligned.shape == session.arrays["calibrated"].shape
    assert session.background.reproduces


def test_gwy_input_is_read_through_the_recorded_channel(tmp_path):
    """
    A bundle analyzed from a ``.gwy`` file finds its raw image there.
    ``.gwy`` ファイルから解析したバンドルは、生の画像をそこから読む。
    """
    pytest.importorskip("gwyfile")
    gwy = write_synthetic_fiber_gwy(tmp_path)
    result = process_file(gwy, ProcParams())

    session = load_edit_session(result.bundle_path)

    assert session.raw.source == RAW_FROM_INPUT_FILE
    assert session.background.reproduces


def test_centerlines_are_in_the_coordinates_of_the_stored_arrays(analyzed):
    """
    Each fiber's line lies on its skeleton, not at its bounding-box offset.
    各繊維の線は、外接矩形の原点だけずれた位置ではなく、スケルトンの上にある。
    """
    _txt, bundle = analyzed
    session = load_edit_session(bundle)

    skeleton = np.asarray(session.arrays["skeletonized"]).astype(bool)
    distance = distance_transform_edt(~skeleton)
    rows, columns = skeleton.shape
    assert session.centerlines
    for x, y in session.centerlines:
        assert x.min() >= -0.5 and x.max() <= columns - 0.5
        assert y.min() >= -0.5 and y.max() <= rows - 0.5
        column = np.clip(np.rint(x).astype(int), 0, columns - 1)
        row = np.clip(np.rint(y).astype(int), 0, rows - 1)
        # The line is placed within the fiber's width of its skeleton pixel;
        # a line left in bounding-box coordinates is tens of pixels away.
        # 線は、スケルトン画素から繊維の幅の範囲内に置かれる。外接矩形の座標の
        # ままの線は、数十画素離れる。
        assert distance[row, column].max() <= 5.0


def test_align_raw_refuses_an_image_of_another_size():
    """
    A raw image that does not give the stored shape is not aligned.
    保存された形状にならない生の画像は、位置合わせしない。
    """
    raw = np.zeros((10, 12))
    assert align_raw(raw, (9, 11)).shape == (9, 11)
    assert align_raw(raw, (10, 12)) is None
    assert align_raw(np.zeros(5), (4,)) is None
