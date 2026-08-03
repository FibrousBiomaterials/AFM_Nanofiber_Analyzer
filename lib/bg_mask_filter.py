# -*- coding: utf-8 -*-
"""
Apply the background stage's fiber-mask cleanup to an externally produced mask.
背景段の繊維マスク整形処理を、外部で生成したマスクへ適用する。

`BGCalibrator` does not hand its raw gradient-ridge fiber mask straight to the
background fill: it first drops tiny 8-connected components and then dilates
what remains, and only that cleaned mask decides which pixels are excluded from
the background pool. A machine-learning ``bg_mask`` model reproduces the raw
mask, so comparing its prediction against the classical result at the stage the
pipeline actually uses requires running the prediction through the same cleanup.
This module provides that step for callers outside the calibrator (today
GUI06's model comparison), mirroring how `Segmenter.apply_component_filters`
exposes the binarization stage's post-thresholding filters.
`BGCalibrator` は勾配リッジ由来の生の繊維マスクをそのまま背景埋めへ渡さない。
まず微小な 8 連結成分を落とし、残りを膨張させ、その整形後のマスクだけが
背景プールから除外する画素を決める。機械学習の ``bg_mask`` モデルが再現するのは
生のマスクなので、その予測をパイプラインが実際に使う段で古典的な結果と比較する
には、同じ整形処理を通す必要がある。本モジュールは補正器の外側の呼び出し側
（現在は GUI06 のモデル比較）向けにその工程を提供する。二値化段のしきい値後
フィルタを `Segmenter.apply_component_filters` が公開しているのと同じ関係である。

Relationship to `lib.bg_calibrator` / `lib.bg_calibrator` との関係
------------------------------------------------------------------
The cleanup implemented here is a deliberate duplicate of the block inside
``BGCalibrator._bg_generate``, kept separate so exposing it cannot change the
background-correction result by even one pixel. ``tests/test_bg_mask_filter.py``
pins the two together by running the calibrator and checking that the NaN
pattern of its ``bg_only`` -- which *is* the cleaned mask, since ``bg_only``
blanks exactly the masked pixels -- matches this module's output. If the
calibrator's cleanup ever changes, that test fails rather than letting the two
drift apart silently.
ここで実装する整形処理は ``BGCalibrator._bg_generate`` 内のブロックの意図的な
複製である。公開のために背景補正の結果が 1 画素たりとも変わらないよう、あえて
分離している。``tests/test_bg_mask_filter.py`` が両者を結び付けており、補正器を
実行し、その ``bg_only`` の NaN 分布（``bg_only`` はマスクされた画素をちょうど
空にするため、これが整形後マスクそのものである）が本モジュールの出力と一致する
ことを確認する。補正器側の整形処理が変われば、黙って乖離するのではなくその
テストが落ちる。
"""

# ===== Standard library =====
from typing import Optional

# ===== Numerical / scientific libraries =====
import cv2
import numpy as np


def filter_bg_fiber_mask(
    mask: np.ndarray,
    *,
    mask_dilation: int,
    min_mask_component_area: int,
) -> np.ndarray:
    """
    Clean a raw background-stage fiber mask the way the calibrator does.
    背景段の生の繊維マスクを、補正器と同じ方法で整形する。

    Parameters
    ----------
    mask
        Raw fiber-candidate mask; nonzero marks a candidate.
        生の繊維候補マスク。非ゼロが候補。
    mask_dilation
        Dilation radius in pixels; ``0`` disables both steps below.
        膨張半径（画素）。``0`` で以下の両工程を無効化する。
    min_mask_component_area
        Minimum 8-connected component area kept before dilation; ``1``
        disables the area filter.
        膨張前に残す 8 連結成分の最小面積。``1`` で面積フィルタを無効化する。

    Returns
    -------
    ndarray
        Boolean mask of the pixels the background fill would exclude.
        背景埋めが除外する画素の真偽マスク。

    Notes
    -----
    The area filter runs only when dilation is enabled, because it exists to
    stop dilation from amplifying the ridge detector's few-pixel false
    positives into a salt-and-pepper field; with ``mask_dilation == 0`` the
    calibrator keeps its original behavior bit-identically, and so does this
    function.
    面積フィルタは膨張が有効なときにのみ走る。これは、リッジ検出器が拾う数画素の
    偽検出が膨張によってゴマ塩状に増幅されるのを防ぐために存在するからである。
    ``mask_dilation == 0`` では補正器が従来動作と完全に一致する挙動を保ち、本関数も
    同様である。
    """
    cleaned = np.asarray(mask).astype(bool)

    if mask_dilation > 0 and min_mask_component_area > 1:
        n_cc, cc_labels, cc_stats, _cc_centroids = cv2.connectedComponentsWithStats(
            cleaned.astype(np.uint8), connectivity=8,
        )
        # Background label 0 is never kept as a fiber component.
        keep = np.zeros(n_cc, dtype=bool)
        if n_cc > 1:
            keep[1:] = cc_stats[1:, cv2.CC_STAT_AREA] >= min_mask_component_area
        cleaned = keep[cc_labels]

    if mask_dilation > 0:
        kernel = np.ones(
            (mask_dilation * 2 + 1, mask_dilation * 2 + 1), dtype=np.uint8,
        )
        cleaned = cv2.dilate(cleaned.astype(np.uint8), kernel).astype(bool)

    return cleaned


def filter_bg_fiber_mask_for_bundle(
    path: str, mask: np.ndarray, params: Optional[object] = None
) -> np.ndarray:
    """
    Clean a fiber mask using the cleanup settings recorded in a bundle.
    バンドルに記録された整形設定で繊維マスクを整形する。

    The bundle-aware counterpart of `filter_bg_fiber_mask`, matching how
    `lib.ml_dataset.apply_pipeline_component_filters` takes a bundle path: a
    prediction is only comparable with the bundle's own classical result when
    both are cleaned with the parameters that produced that bundle.
    `filter_bg_fiber_mask` のバンドル対応版。`lib.ml_dataset.apply_pipeline_component_filters`
    がバンドルパスを受け取るのと同じ形にしてある。予測がそのバンドルの古典的な
    結果と比較可能なのは、両者を当該バンドルを生んだパラメータで整形したときだけ
    だからである。

    Parameters
    ----------
    path
        Bundle whose stored analysis parameters supply the cleanup settings.
        整形設定を供給する解析パラメータを保存しているバンドル。
    mask
        Raw fiber-candidate mask; nonzero marks a candidate.
        生の繊維候補マスク。非ゼロが候補。
    params
        Already-loaded `lib.pipeline.ProcParams` for this bundle; when given,
        the bundle metadata is not read again.
        このバンドルについて読み込み済みの `lib.pipeline.ProcParams`。指定した
        場合はバンドルのメタデータを再読み込みしない。

    Returns
    -------
    ndarray
        Boolean mask of the pixels the background fill would exclude.
        背景埋めが除外する画素の真偽マスク。

    Raises
    ------
    ValueError
        If the bundle stores no analysis parameters.
        バンドルに解析パラメータが保存されていない場合。
    """
    resolved = read_bundle_params(path) if params is None else params
    return filter_bg_fiber_mask(
        mask,
        mask_dilation=resolved.mask_dilation,
        min_mask_component_area=resolved.min_mask_component_area,
    )


def read_bundle_params(path: str):
    """
    Return the `ProcParams` recorded in a bundle.
    バンドルに記録された `ProcParams` を返す。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルのパス。

    Returns
    -------
    lib.pipeline.ProcParams
        Parameters merged with the current defaults for fields a bundle
        written by an older version may not carry.
        古い版が書いたバンドルに欠けうるフィールドを現在の既定値で補完した
        パラメータ。

    Raises
    ------
    ValueError
        If the bundle stores no analysis parameters, so no stage of it can be
        reproduced.
        バンドルに解析パラメータが無く、いかなる段も再現できない場合。
    """
    # Local imports: the pipeline stack is heavy and only this bundle-aware
    # path needs it, so `import lib.bg_mask_filter` stays cheap for callers
    # that pass the cleanup settings directly.
    # ローカル import：パイプライン一式は重く、必要なのはこのバンドル対応経路
    # だけなので、整形設定を直接渡す呼び出し側のために
    # `import lib.bg_mask_filter` を軽く保つ。
    from .blosc2_io import load_bundle_meta
    from .pipeline import merge_params_dict

    try:
        meta = load_bundle_meta(path)
    except Exception as exc:  # noqa: BLE001 - report any read failure as a reason.
        raise ValueError(f"cannot read bundle metadata: {exc}") from exc

    params_dict = meta.get("params") if isinstance(meta, dict) else None
    if not isinstance(params_dict, dict) or not params_dict:
        raise ValueError(
            "no analysis parameters in bundle; cannot reproduce the background "
            "stage's fiber-mask cleanup"
        )
    params, _unknown, _missing = merge_params_dict(params_dict)
    return params
