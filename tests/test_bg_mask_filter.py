# -*- coding: utf-8 -*-
"""
Pin `lib.bg_mask_filter` to the cleanup `BGCalibrator` actually performs.
`lib.bg_mask_filter` を `BGCalibrator` が実際に行う整形処理へ固定する。

The cleanup in `lib.bg_mask_filter` is a deliberate duplicate of the block
inside ``BGCalibrator._bg_generate`` (see that module's docstring for why it is
not shared code). These tests are what stops the duplicate from drifting: the
calibrator blanks exactly the masked pixels when it builds ``bg_only``, so the
NaN pattern of ``bg_only`` *is* the cleaned mask, and comparing against it
checks the real behavior rather than a restatement of the same code.
`lib.bg_mask_filter` の整形処理は ``BGCalibrator._bg_generate`` 内のブロックの
意図的な複製である（共有コードにしない理由は当該モジュールの docstring 参照）。
本テストはその複製が乖離するのを防ぐためにある。補正器は ``bg_only`` を作る際に
マスクされた画素をちょうど空にするため、``bg_only`` の NaN 分布が整形後マスク
そのものであり、これと比較することで同じコードの言い換えではなく実挙動を検証
できる。
"""

import numpy as np
import pytest

from lib.afm_io import load_afm_text
from lib.bg_mask_filter import filter_bg_fiber_mask
from lib.pipeline import ProcParams, build_stages
from lib.processed_image import ProcessedImage
from tests.conftest import write_synthetic_fiber_txt


@pytest.fixture(scope="module")
def afm_image(tmp_path_factory):
    """
    Load the synthetic bent-fiber image once for every case below.
    以下の全ケース共通の合成折れ繊維画像を 1 回だけ読み込む。
    """
    path = write_synthetic_fiber_txt(str(tmp_path_factory.mktemp("bg_mask_filter")))
    return load_afm_text(path)


# Both cleanup steps are gated: the area filter runs only alongside dilation,
# and dilation itself is disabled at radius 0. Cover every combination so a
# future change to either gate is caught.
# 整形の両工程には条件がある。面積フィルタは膨張と併用のときだけ走り、膨張自体は
# 半径 0 で無効になる。将来どちらの条件が変わっても気付けるよう全組み合わせを網羅する。
@pytest.mark.parametrize(
    "mask_dilation, min_mask_component_area",
    [(3, 10), (3, 1), (1, 50), (0, 10), (0, 1)],
)
def test_matches_calibrator_cleanup(afm_image, mask_dilation, min_mask_component_area):
    """
    The module reproduces the mask the calibrator excludes from the background.
    本モジュールが、補正器の背景から除外するマスクを再現する。
    """
    params = ProcParams(
        bg_method="inpaint",
        mask_dilation=mask_dilation,
        min_mask_component_area=min_mask_component_area,
    )
    calibrator = build_stages(params).bg_calibrator
    image = ProcessedImage(original_AFM=afm_image, name="bg_mask_filter_test")
    calibrator(image)

    # The raw gradient-ridge mask, combined exactly as the calibrator does
    # before cleanup; `lib.ml_dataset` recovers a `bg_mask` label the same way.
    # 整形前に補正器が行うのと厳密に同じ合成による、生の勾配リッジマスク。
    # `lib.ml_dataset` も同じ方法で `bg_mask` のラベルを復元する。
    raw_mask = (np.abs(calibrator.tri_difx_fill[1:, :])
                + np.abs(calibrator.tri_dify_fill[:, 1:])) > 0

    cleaned = filter_bg_fiber_mask(
        raw_mask,
        mask_dilation=mask_dilation,
        min_mask_component_area=min_mask_component_area,
    )

    assert np.array_equal(cleaned, np.isnan(calibrator.bg_only))


def test_area_filter_and_dilation_change_the_mask(afm_image):
    """
    Guard the comparison above against passing because nothing ever changes.
    上の比較が「何も変わらないから通る」状態にならないよう防護する。

    A mask that survives both cleanup steps unchanged would make every case
    above pass even if the steps were dropped entirely, so assert that the
    settings actually move pixels on this image.
    両工程を通しても不変のマスクでは、工程を完全に削っても上の全ケースが通って
    しまうため、この画像で設定が実際に画素を動かすことを表明する。
    """
    raw = np.zeros((64, 64), dtype=bool)
    raw[10:40, 10:40] = True   # Large component: survives the area filter.
    raw[50, 50] = True         # Single pixel: dropped by the area filter.

    kept = filter_bg_fiber_mask(raw, mask_dilation=0, min_mask_component_area=10)
    assert np.array_equal(kept, raw)

    cleaned = filter_bg_fiber_mask(raw, mask_dilation=2, min_mask_component_area=10)
    assert not cleaned[50, 50]
    assert cleaned[8, 8]  # Dilation widened the surviving component.
