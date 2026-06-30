# -*- coding: utf-8 -*-
"""
Golden-value regression test on a bundled real Shimadzu scan.
同梱された島津機の実測スキャンに対するゴールデン値回帰テスト。

The pipeline is deterministic (no random number generators), so summary
statistics from a fixed input and fixed parameters must stay stable. A modest
tolerance absorbs numerical drift across dependency versions. If this test
fails after an intentional algorithm change, re-baseline the constants below
and record the change in the commit message.
パイプラインは決定的（乱数を使わない）なので、固定入力・固定パラメータの
要約統計は安定しているはずである。依存ライブラリのバージョン差による数値
ドリフトは小さな許容幅で吸収する。意図したアルゴリズム変更でこのテストが
失敗した場合は、下記の基準値を更新し、変更内容をコミットメッセージに残すこと。
"""

import os

import numpy as np
import pytest

from lib.pipeline import ProcParams, process_file
from tests.conftest import REAL_DATA

# Baseline statistics recorded with the default parameters (bg_method=inpaint)
# on testdata_tunicateCNF/TunicateACTOCCNF.txt.
# testdata_tunicateCNF/TunicateACTOCCNF.txt に既定パラメータ
# （bg_method=inpaint）を適用して記録した基準統計値。
GOLDEN_SKELETON_PX = 8225
GOLDEN_BINARIZED_PX = 80685
GOLDEN_N_KINKS = 87
RELATIVE_TOLERANCE = 0.05

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not REAL_DATA.exists(), reason="bundled test scan not present"),
]


def test_default_pipeline_golden_stats(tmp_path):
    """Default-parameter results on the real scan match the recorded baseline."""
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)

    result = process_file(str(REAL_DATA), ProcParams(), output_dir=out_dir)
    image = result.image

    skeleton_px = int((image.skeleton_image > 0).sum())
    binarized_px = int((image.binarized_image > 0).sum())
    n_kinks = len(image.all_kink_angles)

    assert skeleton_px == pytest.approx(GOLDEN_SKELETON_PX, rel=RELATIVE_TOLERANCE)
    assert binarized_px == pytest.approx(GOLDEN_BINARIZED_PX, rel=RELATIVE_TOLERANCE)
    assert n_kinks == pytest.approx(GOLDEN_N_KINKS, rel=RELATIVE_TOLERANCE)

    # All kink angles must be valid radians strictly inside (0, pi).
    ka = np.asarray(image.all_kink_angles)
    assert np.all(ka > 0) and np.all(ka < np.pi)
