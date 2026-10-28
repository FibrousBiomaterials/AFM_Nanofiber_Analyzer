# -*- coding: utf-8 -*-
"""
Tests for the pixel-noise check of an analysis, `pipeline.noise_warnings`.
解析の画素ノイズの検査 `pipeline.noise_warnings` のテスト。

A crest height is the largest of noisy samples, so noise lifts it, and noise
defeats the single-crest test the width of a wide fiber is read with. These
tests pin that the check reads the fiber height and the background noise of the
calibrated image, warns below `MIN_FIBER_SNR`, and stays silent above it.
頂点高さは雑音の乗った標本の最大値なのでノイズで持ち上がり、太い繊維の幅を読む
「頂点は 1 つか」の判定もノイズで通らなくなる。本テストは、検査が補正後の画像から
繊維の高さと背景のノイズを読み、`MIN_FIBER_SNR` 未満で警告し、それ以上では警告しない
ことを固定する。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lib.pipeline import MIN_FIBER_SNR, fiber_snr, noise_warnings

SHAPE = (200, 200)
HEIGHT = 2.0


def _analyzed(noise: float, seed: int = 0) -> SimpleNamespace:
    """
    A calibrated image of one straight ridge with its mask, skeleton and width.
    直線の稜線 1 本の補正後画像と、そのマスク・スケルトン・幅。
    """
    rows, _cols = np.mgrid[0:SHAPE[0], 0:SHAPE[1]].astype(float)
    ridge = HEIGHT * np.exp(-0.5 * ((rows - 100.0) / 3.0) ** 2)
    rng = np.random.default_rng(seed)
    calibrated = ridge + rng.normal(0.0, noise, SHAPE)
    skeleton = np.zeros(SHAPE, dtype=np.uint8)
    skeleton[100, 20:180] = 1
    return SimpleNamespace(
        calibrated_image=calibrated,
        binarized_image=ridge > 0.5 * HEIGHT,
        skeleton_image=skeleton,
        apparent_width_summary={"median_px": 7.0, "component_count": 1, "fallback_count": 0},
    )


def test_fiber_snr_reads_the_height_and_the_background_noise():
    height, noise = fiber_snr(_analyzed(0.05))
    assert height == pytest.approx(HEIGHT, abs=0.05)
    assert noise == pytest.approx(0.05, rel=0.1)


@pytest.mark.parametrize("noise", [0.01, 0.05])
def test_no_warning_when_the_noise_is_small(noise):
    assert noise_warnings(_analyzed(noise)) == []


@pytest.mark.parametrize("noise", [0.15, 0.3])
def test_warning_when_the_noise_is_large(noise):
    warnings = noise_warnings(_analyzed(noise))
    assert len(warnings) == 1
    w = warnings[0]
    assert w.snr < MIN_FIBER_SNR
    assert w.snr == pytest.approx(w.height_nm / w.noise_nm)
    assert w.width_px == 7.0


def test_no_warning_without_a_skeleton():
    image = _analyzed(0.3)
    image.skeleton_image = np.zeros(SHAPE, dtype=np.uint8)
    assert noise_warnings(image) == []


def test_cli_line_names_the_ratio_and_the_limit():
    import cli

    line = cli._noise_warning_text(noise_warnings(_analyzed(0.3))[0])
    assert line.startswith("warning:")
    assert f"{MIN_FIBER_SNR:g}" in line
