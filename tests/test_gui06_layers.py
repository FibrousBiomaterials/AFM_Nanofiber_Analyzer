# -*- coding: utf-8 -*-
"""
Tests for the layer functions of GUI06 that need no window.
GUI06 のレイヤー関連の関数のうち、ウィンドウを必要としないもののテスト。

The image pane composites its image layers with one function and lists only
the layers a bundle has data for. Both decide what the user sees over the
height image, so they are checked here against a blend written out pixel by
pixel and against sessions that lack the raw image.
画像ペインは、画像のレイヤーを 1 つの関数で合成し、バンドルがデータを持つレイヤー
だけを並べる。どちらも、利用者が高さ画像の上に何を見るかを決めるので、画素ごとに
書き下した混合と、生の画像を持たないセッションに照らして確かめる。
"""

import os
import shutil

import numpy as np
import pytest

import guis.GUI06_Bundle_Editor as gui06
from afm_nanofiber_analyzer.bundle_edit import load_edit_session
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt


def _reference_over(layers, shape):
    """
    Composite layers with the "over" operator written out directly.
    「上に重ねる」演算をそのまま書き下して、レイヤーを合成する。

    Returns straight-alpha RGBA as floats in 0..255.
    乗算済みでないアルファの RGBA を、0〜255 の浮動小数で返す。
    """
    rgb = np.zeros(shape + (3,))
    alpha = np.zeros(shape)
    for layer in layers:
        if layer.kind == gui06.KIND_HEIGHT:
            source_rgb = np.repeat(np.asarray(layer.data, dtype=float)[..., None], 3, axis=2)
            source_alpha = np.full(shape, layer.opacity)
        else:
            source_rgb = np.broadcast_to(np.array(layer.color, dtype=float), shape + (3,))
            source_alpha = np.asarray(layer.data, dtype=float) * layer.opacity
        new_alpha = source_alpha + alpha * (1.0 - source_alpha)
        blended = (source_rgb * source_alpha[..., None]
                   + rgb * (alpha * (1.0 - source_alpha))[..., None])
        rgb = np.where(new_alpha[..., None] > 0,
                       blended / np.where(new_alpha > 0, new_alpha, 1.0)[..., None], 0.0)
        alpha = new_alpha
    return np.concatenate([rgb * 255.0, (alpha * 255.0)[..., None]], axis=2)


def _layers():
    """
    Two height images and two masks of a small random image.
    小さな乱数画像の、高さ画像 2 枚とマスク 2 枚。
    """
    rng = np.random.default_rng(0)
    shape = (6, 8)
    grey = [rng.random(shape).astype(np.float32) for _ in range(2)]
    masks = [rng.random(shape) > 0.5 for _ in range(2)]
    return shape, grey, masks


@pytest.mark.parametrize("stack", [
    "mask alone",
    "opaque height under a mask",
    "two translucent heights under two masks",
    "mask under an opaque height",
])
def test_composite_matches_the_over_operator(stack):
    """
    The composite equals layer-by-layer "over" blending to the rounding step.
    合成結果は、レイヤーごとの「上に重ねる」混合と、丸めの範囲で一致する。
    """
    shape, grey, masks = _layers()
    height = lambda data, opacity: gui06.Layer(  # noqa: E731 - local shorthand
        "h", gui06.KIND_HEIGHT, (0.5, 0.5, 0.5), True, opacity, data)
    mask = lambda data, color, opacity: gui06.Layer(  # noqa: E731 - local shorthand
        "m", gui06.KIND_MASK, color, True, opacity, data)
    stacks = {
        "mask alone": [mask(masks[0], (0.2, 0.8, 0.4), 0.5)],
        "opaque height under a mask": [
            height(grey[0], 1.0), mask(masks[0], (0.2, 0.8, 0.4), 0.45)],
        "two translucent heights under two masks": [
            height(grey[0], 0.5), height(grey[1], 0.3),
            mask(masks[0], (0.2, 0.8, 0.4), 0.45), mask(masks[1], (0.9, 0.1, 1.0), 1.0)],
        "mask under an opaque height": [
            mask(masks[0], (0.2, 0.8, 0.4), 0.5), height(grey[0], 1.0)],
    }
    layers = stacks[stack]

    got = gui06.composite_rasters(layers, shape).astype(float)
    expected = _reference_over(layers, shape)

    assert got.shape == shape + (4,)
    np.testing.assert_allclose(got[..., 3], expected[..., 3], atol=0.51)
    # The color of a fully transparent pixel is never drawn.
    # 完全に透明な画素の色は描かれない。
    visible = expected[..., 3] > 0
    np.testing.assert_allclose(got[..., :3][visible], expected[..., :3][visible], atol=0.51)


def test_mask_leaves_unset_pixels_transparent():
    """
    A mask alone covers only the pixels it sets.
    マスクだけのとき、覆うのは立っている画素だけである。
    """
    where = np.zeros((4, 4), dtype=bool)
    where[1, 2] = True
    layer = gui06.Layer("m", gui06.KIND_MASK, (1.0, 0.0, 0.0), True, 1.0, where)

    rgba = gui06.composite_rasters([layer], (4, 4))

    assert (rgba[..., 3] > 0).tolist() == where.tolist()
    assert rgba[1, 2].tolist() == [255, 0, 0, 255]


def test_hidden_opacity_draws_nothing():
    """
    A layer at zero opacity leaves the composite untouched.
    不透明度 0 のレイヤーは、合成結果を変えない。
    """
    where = np.ones((3, 3), dtype=bool)
    layer = gui06.Layer("m", gui06.KIND_MASK, (1.0, 1.0, 1.0), True, 0.0, where)

    assert not gui06.composite_rasters([layer], (3, 3)).any()


def test_drop_slot_counts_the_rows_above_the_pointer():
    """
    The gap a dragged row falls into is the number of row centers above it.
    ドラッグ中の行が入るすき間は、その上にある行の中心の数である。
    """
    centers = [10.0, 30.0, 50.0]
    assert gui06.drop_slot(centers, 0.0) == 0
    assert gui06.drop_slot(centers, 20.0) == 1
    assert gui06.drop_slot(centers, 49.0) == 2
    assert gui06.drop_slot(centers, 99.0) == 3


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """
    A synthetic scan analyzed beside itself, shared across this module.
    合成走査を、その隣に解析結果を書く形で解析したもの。モジュール内で共有する。
    """
    folder = tmp_path_factory.mktemp("gui06_layers")
    txt = write_synthetic_fiber_txt(folder)
    return process_file(txt, ProcParams()).bundle_path


def test_every_layer_is_listed_when_the_raw_image_is_found(bundle):
    """
    A bundle with its input file beside it shows all seven layers.
    入力ファイルが隣にあるバンドルは、7 枚のレイヤーをすべて表示する。
    """
    session = load_edit_session(bundle)

    layers = gui06.build_layers(session)

    assert [layer.key for layer in layers] == [
        key for key, *_rest in gui06.DEFAULT_STACK]
    shape = session.arrays["calibrated"].shape
    for layer in layers:
        if layer.is_raster:
            assert np.asarray(layer.data).shape == shape
    notes, warnings = gui06.session_messages(session)
    assert notes and not warnings


def test_raw_image_and_ridge_mask_are_left_out_without_the_input_file(bundle, tmp_path):
    """
    Without a raw image the two layers that need it are not listed.
    生の画像が無ければ、それを必要とする 2 枚のレイヤーは並べない。
    """
    alone = shutil.copy2(bundle, os.path.join(tmp_path, os.path.basename(bundle)))
    session = load_edit_session(alone)

    keys = [layer.key for layer in gui06.build_layers(session)]

    assert gui06.LAYER_RAW not in keys
    assert gui06.LAYER_FIBER_MASK not in keys
    assert gui06.LAYER_CALIBRATED in keys
    _notes, warnings = gui06.session_messages(session)
    assert len(warnings) == 1


def test_method_without_a_mask_lists_the_raw_image_only(tmp_path):
    """
    A ``tophat`` bundle shows the raw image, has no ridge mask, and warns of nothing.
    ``tophat`` のバンドルは生の画像を表示し、リッジマスクを持たず、警告も出さない。
    """
    txt = write_synthetic_fiber_txt(tmp_path)
    session = load_edit_session(
        process_file(txt, ProcParams(bg_method="tophat")).bundle_path)

    keys = [layer.key for layer in gui06.build_layers(session)]

    assert gui06.LAYER_RAW in keys
    assert gui06.LAYER_FIBER_MASK not in keys
    notes, warnings = gui06.session_messages(session)
    assert not warnings
    assert any("tophat" in line for line in notes)
