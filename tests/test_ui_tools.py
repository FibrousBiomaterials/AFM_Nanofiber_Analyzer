# -*- coding: utf-8 -*-
"""
Tests for the automatic heatmap display range in lib/ui_tools.py.
lib/ui_tools.py のヒートマップ表示範囲自動決定のテスト。

`compute_auto_vrange` decides the vmin/vmax that GUI02 and GUI04 hand to
`imshow`, so its failure mode is a figure that is unreadable rather than an
exception. The synthetic tests therefore pin the two properties that make it
readable — one extreme pixel must not set either bound, and sparse fibers
must not be clipped away — and the real-data test checks that the fibers of
every bundled sample actually land in the bright part of the colormap.
`compute_auto_vrange` は GUI02 / GUI04 が `imshow` に渡す vmin/vmax を決める
ため、失敗は例外ではなく「読めない図」として現れる。そこで合成データでは
可読性を成り立たせる 2 つの性質——極値 1 画素が両端を決めないこと、疎な
ファイバーが潰されないこと——を固定し、実データでは同梱各試料のファイバーが
実際にカラーマップの明るい側に載ることを確認する。
"""

import glob
import os

import numpy as np
import pytest

from lib.blosc2_io import load_bundle
from lib.ui_tools import (
    DEFAULT_VMAX,
    DEFAULT_VMIN,
    compute_auto_vrange,
)
from tests.conftest import PROJECT_ROOT

# Height of the synthetic fibers in nanometers, chosen to sit far above the
# 0.1 nm substrate noise so the assertions are about the rule, not about noise.
# 合成ファイバーの高さ (nm)。0.1 nm の基板ノイズより十分高くとり、判定が
# ノイズではなく規則そのものを見るようにする。
FIBER_NM = 5.0
BG_SIGMA_NM = 0.1


def _synthetic_image(coverage=0.01, shape=(256, 256), seed=0, sigma=BG_SIGMA_NM):
    """
    Build a noisy substrate with fibers covering a given fraction of pixels.
    指定被覆率のファイバーを載せたノイズ基板画像を作る。

    Returns the image and its fiber mask, mimicking the ``calibrated`` /
    ``skeletonized`` pair that GUI01 writes into a bundle.
    画像とそのファイバーマスクを返す。GUI01 がバンドルへ書く ``calibrated`` /
    ``skeletonized`` の組を模したもの。
    """
    rng = np.random.default_rng(seed)
    image = rng.normal(0.0, sigma, shape)
    mask = np.zeros(shape, bool)
    count = int(image.size * coverage)
    mask.flat[rng.choice(image.size, count, replace=False)] = True
    image[mask] += FIBER_NM
    return image, mask


def test_contamination_spike_does_not_set_the_upper_bound():
    """
    A single tall contamination pixel must not push vmax above the fibers.
    コンタミ 1 画素で vmax がファイバーより上へ張り付いてはならない。
    """
    image, mask = _synthetic_image()
    image[3, 3] = 300.0

    _, vmax = compute_auto_vrange(image, mask)

    # Well below the spike, and still above the fibers it has to show.
    assert vmax < 2 * FIBER_NM
    assert vmax >= FIBER_NM


def test_negative_noise_does_not_set_the_lower_bound():
    """
    Negative outliers must not drag vmin tens of sigma below the substrate.
    負の外れ値で vmin が基板より数十 σ 下へ引きずられてはならない。
    """
    image, mask = _synthetic_image()
    image[10, 10] = -50.0

    vmin, _ = compute_auto_vrange(image, mask)

    assert vmin > -1.0 - 10 * BG_SIGMA_NM
    assert vmin <= 0.0


def test_sparse_fibers_are_not_clipped_away():
    """
    Fibers stay unsaturated at low coverage, where a whole-image percentile fails.
    低被覆率でもファイバーが飽和しないこと（全画素パーセンタイルが破綻する条件）。

    This is the property that withdrew the earlier percentile-based attempt:
    at 0.2-0.9 % coverage the 99th percentile of *all* pixels is still
    background, so the fibers would be crushed into the top of the range.
    かつてのパーセンタイル方式を撤回させた性質。被覆率 0.2〜0.9 % では全画素の
    99 パーセンタイルがまだ背景であり、ファイバーが表示範囲の上端に潰れる。
    """
    image, mask = _synthetic_image(coverage=0.004)

    assert np.percentile(image, 99) < FIBER_NM / 2   # the failing rule
    for with_mask in (mask, None):
        _, vmax = compute_auto_vrange(image, with_mask)
        assert vmax >= FIBER_NM


def test_mask_survives_a_contamination_blob_that_defeats_the_mask_free_rule():
    """
    A blob larger than the mask-free percentile margin is ignored via the mask.
    マスク非依存版のパーセンタイル余裕を超える大きな異物も、マスク経由なら無視される。
    """
    image, mask = _synthetic_image()
    # 4096 px is ~6 % of the above-background population, so it reaches past
    # the 99.5th percentile the mask-free branch relies on.
    # 4096 px は背景より上の母集団の約 6 % に当たり、マスク非依存版が頼る
    # 99.5 パーセンタイルを超えてしまう大きさ。
    image[100:164, 100:164] = 300.0
    # Segmentation reduces such a blob to a short skeleton rather than to its
    # full area, so the mask population barely notices it.
    # セグメンテーションはこの種の塊を面積そのままではなく短いスケルトンに
    # 縮約するため、マスク母集団はほとんど影響を受けない。
    mask[100:164, 100:164] = False
    mask[132, 100:105] = True

    _, masked_vmax = compute_auto_vrange(image, mask)
    _, unmasked_vmax = compute_auto_vrange(image, None)

    assert masked_vmax < 2 * FIBER_NM
    assert unmasked_vmax > 100.0


def test_bounds_never_widen_past_the_data():
    """
    Both bounds stay inside the actual value range of the image.
    両端が画像の実際の値域を外へ広がらないこと。
    """
    image, mask = _synthetic_image()
    vmin, vmax = compute_auto_vrange(image, mask)

    assert vmin >= np.floor(image.min())
    assert vmax <= np.ceil(image.max())


def test_k_low_and_percentiles_are_tunable():
    """
    Each tuning parameter moves its own bound in the documented direction.
    各調整パラメータが、文書どおりの向きに対応する端だけを動かすこと。
    """
    # A 1 nm noise floor keeps k_low visible after the integer rounding that
    # a 0.1 nm floor would swallow.
    # 整数丸めで差が消えないよう、ノイズ床を 1 nm にとって k_low の効きを見る。
    image, mask = _synthetic_image(sigma=1.0)
    base_min, base_max = compute_auto_vrange(image, mask)

    # A wider low-side margin can only lower vmin (or hit the data minimum).
    wide_min, _ = compute_auto_vrange(image, mask, k_low=50.0)
    assert wide_min < base_min

    # A lower fiber percentile can only lower vmax.
    _, low_pct_max = compute_auto_vrange(image, mask, fiber_pct=1.0)
    assert low_pct_max < base_max

    # fg_pct is the mask-free branch, so it must not affect the masked result.
    _, unchanged = compute_auto_vrange(image, mask, fg_pct=1.0)
    assert unchanged == base_max
    _, mask_free = compute_auto_vrange(image, None, fg_pct=1.0)
    assert mask_free < base_max


def test_low_clip_pct_bounds_the_share_crushed_to_black():
    """
    A tilted uncorrected scan keeps its low corner instead of crushing it black.
    傾斜した未補正スキャンで、低い側の隅が黒く潰れずに残ること。

    GUI02 can open raw instrument files, where the substrate is a ramp several
    nanometers tall rather than a narrow noise band, so a bound placed a few
    sigma below the background level would black out a whole corner.
    GUI02 は生の装置ファイルも開ける。そこでは基板が狭いノイズ帯ではなく数 nm の
    傾斜面になるため、背景レベルの数 σ 下に置いた下端は隅を丸ごと黒く潰す。
    """
    rng = np.random.default_rng(0)
    tilt = np.tile(np.linspace(0.0, 10.0, 256), (256, 1))
    image = tilt + rng.normal(0.0, BG_SIGMA_NM, tilt.shape)

    vmin, _ = compute_auto_vrange(image)
    assert np.mean(image < vmin) <= 0.005

    # Allowing more clipping may only raise the bound, never lower it.
    lenient_min, _ = compute_auto_vrange(image, low_clip_pct=20.0)
    assert lenient_min >= vmin


@pytest.mark.parametrize("image_array", [
    np.array([]),
    np.full((4, 4), np.nan),
    np.array([["a", "b"], ["c", "d"]]),
])
def test_unusable_input_falls_back_to_the_project_defaults(image_array):
    """
    Empty, all-NaN, and non-numeric input return the shared fallback range.
    空・全 NaN・非数値の入力では共通のフォールバック範囲を返す。
    """
    assert compute_auto_vrange(image_array) == (
        int(np.floor(DEFAULT_VMIN)), int(np.ceil(DEFAULT_VMAX)),
    )


def test_flat_image_keeps_a_usable_span():
    """
    A featureless image still yields a non-degenerate range.
    構造の無い画像でも縮退しない表示範囲を返す。
    """
    vmin, vmax = compute_auto_vrange(np.zeros((32, 32)))
    assert vmax > vmin


@pytest.mark.parametrize("mask", [
    np.ones((8, 8), bool),                     # shape mismatch with the image
    np.zeros((256, 256), bool),                # empty mask
])
def test_unusable_mask_falls_back_to_the_mask_free_rule(mask):
    """
    A mismatched or empty mask degrades to the mask-free estimate, not an error.
    形状不一致・空のマスクはエラーではなくマスク非依存推定へ縮退する。
    """
    image, _ = _synthetic_image()
    assert compute_auto_vrange(image, mask) == compute_auto_vrange(image, None)


def test_real_bundles_put_the_fibers_in_the_bright_half():
    """
    Every bundled sample renders its fibers in the upper half of the colormap.
    同梱の全試料で、ファイバーがカラーマップの上半分に載ること。

    This is the readability property the auto range exists for: the previous
    min/max rule left the Bruker sample's fibers at 22 % of the range, which
    is the dark image this test guards against.
    自動レンジが存在する理由である可読性の性質。従来の min/max 規則では
    Bruker 試料のファイバーが範囲の 22 % に留まり、本テストはその「暗い画像」を
    再発させないための番人となる。
    """
    bundles = sorted(glob.glob(os.path.join(str(PROJECT_ROOT), "testdata_*", "*.b2z")))
    if not bundles:
        pytest.skip("no test bundles available")

    for path in bundles:
        data = load_bundle(path, keys=["calibrated", "skeletonized"])
        calibrated = np.asarray(data["calibrated"], float)
        skeleton = np.asarray(data["skeletonized"]).astype(bool)
        vmin, vmax = compute_auto_vrange(calibrated, skeleton)

        # Where the brightest 5 % of the skeleton sits within [vmin, vmax].
        # スケルトンの上位 5 % が [vmin, vmax] のどこに載るか。
        bright = np.percentile(calibrated[skeleton], 95)
        position = (bright - vmin) / (vmax - vmin)
        assert 0.5 <= position <= 1.0, f"{os.path.basename(path)}: {position:.0%}"

        # A percentile upper bound saturates a little by construction; keep
        # that visible-but-small.
        # 上端がパーセンタイルである以上わずかな飽和は原理的に生じる。それが
        # 小さいままであることを確認する。
        saturated = np.mean(calibrated[np.isfinite(calibrated)] > vmax)
        assert saturated < 0.01, f"{os.path.basename(path)}: {saturated:.2%}"
