"""
Background calibration utilities for line-scan AFM height images.
ラインスキャン AFM 高さ画像に対する背景補正ユーティリティ。

This module estimates line-to-line height differences, separates candidate
fiber regions from background, reconstructs a smooth background surface, and
subtracts it from the original image.
このモジュールは、ライン間の高さ差を推定し、繊維候補領域を背景から分離し、
平滑な背景面を再構成して元画像から減算する処理を提供する。

The algorithms are general line-scan AFM background corrections, used on
data from several instruments (e.g. Shimadzu SPM-9600 and Bruker NanoScope
text exports). The import path ``bg_calibrator_shimadzu`` and the class name
``BG_Calibrator_shimadzu`` remain available through a compatibility shim.
アルゴリズムはラインスキャン AFM 一般の背景補正であり、複数の装置（例: 島津
SPM-9600、Bruker NanoScope のテキストエクスポート）のデータに使う。import パス
``bg_calibrator_shimadzu`` とクラス名 ``BG_Calibrator_shimadzu`` は、互換シム
経由で引き続き利用できる。
"""

from typing import TYPE_CHECKING

import numpy as np
import cv2
from scipy import signal
from scipy.ndimage import distance_transform_edt

from .processed_image import ProcessedImage

if TYPE_CHECKING:
    # Annotation only: lmfit is imported inside `BGCalibrator._bg_fit`, the one
    # place that needs it at run time, because importing it is slow.
    from lmfit.model import ModelResult

# Background-estimation methods, in the spelling written to `_param.json`.
# 背景推定方式の一覧。`_param.json` へ書き出される綴りで保持する。
BG_METHOD_NAMES = ("trendfill", "tophat", "spline1d")

# Retired spellings mapped to their current name. A parameter file can record
# the retired spelling ``"inpaint"``, and re-running an old analysis must keep
# working, so the value is translated on load rather than rejected.
# 廃止された綴りから現行名への対応表。パラメータファイルは廃止された綴り
# ``"inpaint"`` を記録していることがあり、過去の解析を再実行できる必要があるため、
# 値は拒否せず読み込み時に変換する。
BG_METHOD_ALIASES = {"inpaint": "trendfill"}

# Methods that are no longer available, mapped to the guidance shown when a
# stored parameter file still selects one. Unlike `BG_METHOD_ALIASES` these are *not*
# translated to a surviving method: substituting one silently would change the
# numbers a saved `_param.json` reproduces, which is a reproducibility break in
# research software. The run stops instead and the user re-selects a method.
# 利用できなくなった方式と、保存済みパラメータファイルがそれを指していた
# ときに示す案内の対応表。`BG_METHOD_ALIASES` と違い、生き残った方式へ読み
# 替えることはしない。黙って置換すると保存済み `_param.json` が再現する数値が
# 変わり、研究ソフトウェアとしての再現性を損なうためである。実行を止めて
# 利用者に方式を選び直させる。
BG_METHOD_REMOVED = {
    "spline2d": (
        "bg_method 'spline2d' was removed after 1.0.0. Its tensor-product "
        "B-spline left the largest background residual of all methods on "
        "every test image, and the smoothing factor that could have improved "
        "it was not settable from the GUI. Use 'trendfill', or 'spline1d' for "
        "line-noise-dominated scans, and re-run the analysis."
    ),
}


def canonical_bg_method(value: str) -> str:
    """
    Translate a retired ``bg_method`` spelling to its current name.
    廃止された ``bg_method`` の綴りを現行名へ変換する。

    Parameters
    ----------
    value
        The ``bg_method`` value supplied by a caller or read from a file.
        呼び出し側が指定した、またはファイルから読み込んだ ``bg_method`` の値。

    Returns
    -------
    str
        The current name, or ``value`` unchanged when it is not an alias.
        現行名。エイリアスでない場合は ``value`` をそのまま返す。

    Notes
    -----
    Unknown values pass through untouched so that reporting an invalid method
    stays the caller's job (`BGCalibrator.__init__` and
    `lib.pipeline.validate_params`).
    未知の値はそのまま通し、不正な方式の報告は呼び出し側
    (`BGCalibrator.__init__` と `lib.pipeline.validate_params`) の責務に保つ。
    """
    return BG_METHOD_ALIASES.get(value, value)


class BGCalibrator:
    """
    Calibrate and remove background trend from line-scan AFM images.
    ラインスキャン AFM 画像の背景トレンドを補正・除去するクラス。

    The class identifies likely non-fiber regions from gradient statistics and
    builds a smooth background model from those regions.
    このクラスは、勾配統計から非繊維領域を推定し、
    その領域を使って平滑な背景モデルを構築する。

    Notes
    -----
    When run through the preprocessing pipeline, every constructor argument is
    supplied explicitly from `lib.pipeline.ProcParams` (via
    `pipeline.build_stages`), so `ProcParams` is the source of truth for
    pipeline, GUI, and CLI runs. The constructor defaults below apply only to
    direct, standalone construction and intentionally differ from some
    `ProcParams` defaults; do not assume the two default sets match.
    前処理パイプライン経由で使う場合、全コンストラクタ引数は
    `lib.pipeline.ProcParams` から `pipeline.build_stages` を介して明示的に
    渡されるため、パイプライン／GUI／CLI 実行では `ProcParams` がソース・
    オブ・トゥルースとなる。以下のコンストラクタ既定値は直接単体構築した
    ときにのみ効き、一部は `ProcParams` の既定値と意図的に異なる。両者の
    既定値が一致する前提で扱わないこと。

    Examples
    --------
    In the pipeline the stage is built from `ProcParams` by
    `pipeline.build_stages`. The input path is relative to the repository
    root:

    >>> from lib.afm_io import load_afm_text
    >>> from lib.pipeline import ProcParams, build_stages
    >>> from lib.processed_image import ProcessedImage
    >>> heights = load_afm_text("testdata_artificial/sample_isotropic.txt")
    >>> image = ProcessedImage(original_AFM=heights, name="sample_isotropic")
    >>> calibrator = build_stages(ProcParams()).bg_calibrator
    >>> calibrator.bg_method
    'trendfill'
    >>> calibrator(image)
    >>> heights.shape, image.calibrated_image.shape
    ((256, 256), (255, 255))
    """

    def __init__(self, threshold_factor=3, fiber_detect_factor=10, noise_detect_factor=2,
                 savgol_window=51, savgol_polyorder=2, apply_median=True,
                 mask_dilation=3,
                 min_mask_component_area=10, bg_method='trendfill', tophat_se_size=25,
                 spline1d_axis='x', spline1d_degree=2) -> None:
        """
        Initialize background calibration parameters.
        背景補正の各種パラメータを初期化する。

        Parameters
        ----------
        threshold_factor : float, optional
            Sigma multiplier used when separating background-like differences.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline1d'``.
            背景らしい差分を分離する際に使うシグマ倍率。
            ``bg_method`` が ``'trendfill'`` または ``'spline1d'`` のときに
            使用される。
        fiber_detect_factor : int, optional
            Maximum inner-gap length for the [1, 0, -1] fiber pattern.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline1d'``.
            [1, 0, -1] の繊維パターンで許容する内側ギャップ長の最大値。
            ``bg_method`` が ``'trendfill'`` または ``'spline1d'`` のときに
            使用される。
        noise_detect_factor : int, optional
            Minimum span for the [1, -1] pattern to avoid tiny noise segments.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline1d'``.
            微小ノイズを避けるための [1, -1] パターン最小スパン。
            ``bg_method`` が ``'trendfill'`` または ``'spline1d'`` のときに
            使用される。
        savgol_window : int
            Window length used by the Savitzky-Golay smoothing filter.
            Applied to the background estimate in both methods.
            Savitzky-Golay 平滑化フィルタで使う窓長。
            両方式とも背景推定値に適用される。
        savgol_polyorder : int
            Polynomial order used by the Savitzky-Golay filter.
            Savitzky-Golay フィルタで使う多項式次数。
        apply_median : bool
            If True, apply a 3x3 median blur after background subtraction.
            True の場合、背景減算後に 3x3 のメディアンぼかしを適用する。
        mask_dilation : int, optional
            Number of pixels used to dilate the detected fiber mask before
            background estimation. Fiber-edge pixels that escape detection in
            `_extract_fiber` would otherwise leak into the background pool
            and bias interpolation/smoothing, causing over-subtraction around
            fibers. Larger values exclude more neighboring pixels from the
            background pool. Set to 0 to disable dilation. Used when
            ``bg_method`` is ``'trendfill'`` or ``'spline1d'``.
            ファイバーマスクを膨張させるピクセル数。
            `_extract_fiber` で検出しきれないファイバー端ピクセルが背景推定に
            混入すると、補間・平滑化でファイバー周辺の背景推定値が過大になり、
            減算後に過剰減算（ファイバー両脇のえぐれ）が生じる。
            値を大きくするほど周辺の背景点も除外される。
            0 を指定するとdilationなし。
            ``bg_method`` が ``'trendfill'`` または ``'spline1d'`` のときに
            使用される。
        min_mask_component_area : int, optional
            Minimum 8-connected component area (in pixels) kept in the raw
            fiber mask before dilation. Spurious 2- to 10-pixel detections
            from the `[1, -1]` ridge pattern in `_extract_fiber` scatter
            across noisy or wide-field images. Without filtering, each one
            is expanded to `(2 * mask_dilation + 1)^2` pixels by dilation
            and creates a salt-and-pepper field of holes that destabilises
            background interpolation (visible as a tiled / cellular pattern
            in the calibrated image at `mask_dilation >= 3`). Real fibers
            form much larger connected components and are kept. Set to 1
            to disable filtering.
            Applied when `mask_dilation > 0` and ``bg_method`` is
            ``'trendfill'`` or ``'spline1d'``.
            dilation 前の生ファイバーマスクから残す 8 連結成分の最小面積
            （ピクセル単位）。`_extract_fiber` の `[1, -1]` リッジパターンが
            拾う 2〜10 px 程度の偽検出が、ノイズの多い画像や広視野画像で
            画面全体に散らばる。フィルタを掛けないと、これらは dilation で
            `(2 * mask_dilation + 1)^2` ピクセルに膨張し、bg_only にゴマ塩状の
            穴を作って背景補間を不安定化させる（`mask_dilation >= 3` で補正
            画像にタイル状・細胞状パターンとして現れる）。本物のファイバーは
            十分大きな連結成分を形成するため残る。1 を指定するとフィルタなし。
            `mask_dilation > 0` かつ ``bg_method`` が
            ``'trendfill'`` または ``'spline1d'`` のときに適用される。
        bg_method : {'trendfill', 'tophat', 'spline1d'}, optional
            Background estimation strategy.

            ``'trendfill'`` (default): the two-stage approach. Detect
            fiber-like ridges via gradient histogram thresholds and pattern
            matching, mask them out, then fit and subtract a second-order
            trend surface, fill the mask from the nearest background pixel,
            smooth, and restore the trend. Configurable via
            ``threshold_factor``, ``fiber_detect_factor``,
            ``noise_detect_factor``, ``mask_dilation``,
            ``min_mask_component_area``. Sensitive to ridge-detection
            failures (fiber shoulders leaking through the mask bias the
            background upward).

            ``'tophat'``: morphological opening with a circular structuring
            element of diameter ``tophat_se_size``. Background equals the
            opened image, i.e. the result of erosion followed by dilation.
            Bright structures narrower than ``tophat_se_size`` are removed
            and treated as foreground; broader features remain in the
            background model. Because the opening is a lower-envelope
            estimator, the subtracted image is re-centered by its median so
            the substrate level sits at 0 nm and calibrated heights stay
            comparable with the interpolating methods. No fiber mask is
            computed, so ridge-detection parameters (``threshold_factor``
            etc.) are ignored. Its run time against the other methods is in
            docs/validation.md section 1.5.

            ``'spline1d'``: per-line 1D spline interpolation of the
            background-candidate pixels along a single axis, chosen by
            ``spline1d_axis``. With ``spline1d_axis='x'`` (default) each row
            is filled from its own values, which is each scan line when the
            fast-scan axis lies along the image rows (the usual AFM
            geometry); each line keeps its own level in the background, so
            subtracting the background removes *horizontal* stripes, i.e.
            line-to-line offsets where each scan line is shifted up or down.
            With ``spline1d_axis='y'`` each column is filled from its own
            values instead; a hole is then filled from the rows above and
            below it, so horizontal stripes are not removed there. Uses the same
            trendfill-style fiber mask (with ``mask_dilation`` and
            ``min_mask_component_area``) to choose background-candidate
            pixels, and the same ``pandas`` spline of order
            ``spline1d_degree``, applied to a detrended copy. Beyond the
            first/last background pixel of a line there is nothing to
            interpolate between, so those runs hold the mean of that line's
            nearest ``savgol_window`` background samples rather than an
            extrapolated shape; a single-line extrapolation there stripes the
            image edge, whether it holds the last sample constant or follows
            the fitted spline. Only a line with fewer than two
            background samples is filled from the nearest background pixel
            in 2D.
            The background is then Savitzky-Golay smoothed and subtracted in
            full (no exact restore of background-candidate pixels); its effect
            on scan-line offsets is in docs/validation.md section 1.6.
            Configurable via ``spline1d_axis`` and ``spline1d_degree``.

            背景推定方式の選択。

            ``'trendfill'`` (デフォルト): 2段構えの方式。勾配ヒストグラムの
            閾値とパターンマッチでファイバー状リッジを検出してマスクし、
            2 次のトレンド曲面をフィットして減算し、マスク領域を最近傍の
            背景画素の値で埋め、平滑化してからトレンドを復元する。
            ``threshold_factor``, ``fiber_detect_factor``,
            ``noise_detect_factor``, ``mask_dilation``,
            ``min_mask_component_area`` で挙動を制御する。リッジ検出の
            取りこぼし（ファイバーの肩がマスクを抜けて境界画素として残る現象）
            に弱く、背景推定値が上方にバイアスする傾向がある。

            ``'tophat'``: 直径 ``tophat_se_size`` の円形構造要素を用いる
            形態学的 opening。背景は opening 後の画像（収縮→膨張）そのもの。
            ``tophat_se_size`` より細い明るい構造は除去されて前景扱いに、
            それより太い構造は背景モデルに残る。opening は下側包絡線の
            推定量であるため、減算後の画像は中央値で再センタリングして
            基板レベルを 0 nm に揃え、補正後の高さが補間系方式と比較可能に
            なるようにする。ファイバーマスクを一切
            使わないため、リッジ検出系パラメータ (``threshold_factor`` 等)
            は無視される。他方式との実行時間の比較は docs/validation.ja.md の
            1.5 節にある。

            ``'spline1d'``: 背景候補画素を1軸に沿って行/列ごとに 1D スプライン
            補間する方式。
            補間の向きは ``spline1d_axis`` で選ぶ。``'x'`` (デフォルト) は各行を
            その行自身の値から埋める。画像の行方向が高速走査軸である一般的な
            AFM の撮り方では、各行は走査ライン 1 本にあたる。各ラインが背景に
            自身の水準を保つので、背景を引くと *横縞* (各走査ラインが上下に
            ずれるライン間オフセット) も消える。``'y'`` は代わりに各列をその列
            自身の値から埋める。このとき穴は上下の行の値から埋まるので、横縞は
            そこでは消えない。背景候補画素の選択には trendfill と同じファイバーマスク
            (``mask_dilation``, ``min_mask_component_area`` 込み) を使い、
            補間にはデトレンドした写しへ order ``spline1d_degree`` の
            ``pandas`` スプラインを適用する。各ラインの最初/最後の背景画素
            より外側は補間する材料が無いため、形を外挿するのではなく、その
            ライン自身の最近傍 ``savgol_window`` 個の背景サンプルの平均を保持
            する。ここでライン単独の外挿を行うと、最終サンプルの値を一定に
            保つ場合でも、フィットしたスプラインに従う場合でも、画像端に縞が
            出る。背景
            サンプルが 2 点未満のラインだけは 2 次元の最近傍背景画素から埋める。
            その後 Savitzky-Golay で
            平滑化し、背景候補画素を厳密復元せずそのまま全面減算する。走査ラインの
            オフセットへの効果は docs/validation.ja.md の 1.6 節にある。
            ``spline1d_axis`` と ``spline1d_degree`` で挙動を制御する。

        tophat_se_size : int, optional
            Diameter (in pixels) of the circular structuring element used
            when ``bg_method='tophat'``. Should be larger than the widest
            fiber in the image (rule of thumb: 2-3x the typical fiber
            width). Too small leaves fibers in the background; too large
            also flattens the broader substrate features the background
            should preserve. Must be odd; even values are silently
            incremented by 1.
            ``bg_method='tophat'`` のときに使う円形構造要素の直径 (px)。
            画像中の最も太いファイバーより大きく取る (目安: 典型ファイバー幅の
            2〜3 倍)。小さすぎるとファイバーが背景に残り、大きすぎると本来
            背景として残すべき基板の局所構造も削られる。奇数のみ有効で、
            偶数を渡した場合は黙って +1 される。
        spline1d_axis : {'x', 'y'}, optional
            Interpolation axis when ``bg_method='spline1d'``. ``'x'``
            (default) fills each row from its own values; when the image rows
            are the fast-scan axis (the usual AFM geometry) each row is one
            scan line, so its own level stays in the background and
            subtracting the background removes *horizontal* stripes --
            line-to-line offsets where each scan line is shifted up or down.
            ``'y'`` fills each column from its own values instead, so a hole
            is filled from the rows above and below and horizontal stripes
            are not removed there. Default ``'x'``, as in
            ``pipeline.ProcParams``.
            ``bg_method='spline1d'`` のときの補間の向き。``'x'`` (デフォルト) は
            各行をその行自身の値から埋める。画像の行方向が高速走査軸である
            一般的な AFM の撮り方では各行が走査ライン 1 本にあたり、その水準が
            背景に残るので、背景を引くと *横縞* (各走査ラインが上下にずれる
            ライン間オフセット) も消える。``'y'`` は代わりに各列をその列自身の
            値から埋めるので、穴は上下の行の値から埋まり、横縞はそこでは
            消えない。デフォルトは ``pipeline.ProcParams`` と同じ ``'x'``。
        spline1d_degree : int, optional
            Polynomial order of the per-line ``pandas`` spline used when
            ``bg_method='spline1d'``. Practical range is 1-3; must be a
            positive integer. Lines with fewer valid points than the spline
            order fall back to linear (or nearest) interpolation
            automatically.
            ``bg_method='spline1d'`` のときの行/列ごと ``pandas`` スプライン
            の多項式 order。実用
            範囲は 1〜3 で正の整数のみ。スプライン order に満たない有効点数
            のラインは自動的に線形 (または最近傍) 補間にフォールバックする。

        Raises
        ------
        ValueError
            If ``bg_method`` names a removed method listed in
            `BG_METHOD_REMOVED`, if it is not one of {'trendfill', 'tophat',
            'spline1d'} nor the retired alias ``'inpaint'``, if
            ``tophat_se_size`` is not a positive integer, if
            ``spline1d_axis`` is not ``'y'`` or ``'x'``, or if
            ``spline1d_degree`` is not a positive integer.
            ``bg_method`` が `BG_METHOD_REMOVED` に載る削除済み方式である、
            {'trendfill', 'tophat', 'spline1d'} でも廃止済みエイリアス
            ``'inpaint'`` でもない、``tophat_se_size`` が正の整数でない、
            ``spline1d_axis`` が ``'y'`` でも ``'x'`` でもない、または
            ``spline1d_degree`` が正の整数でない場合。

        Notes
        -----
        Only parameters are stored here. Actual calibration runs in __call__.
        ここではパラメータのみ保持し、実際の補正処理は __call__ で実行する。
        """
        # Accept the retired spelling so a `_param.json` recording it still runs.
        # 旧綴りを記録した `_param.json` がそのまま動くよう、旧綴りも受け付ける。
        bg_method = canonical_bg_method(bg_method)
        # Report a removed method by name, before the generic "unknown value"
        # error, so a stored parameter file explains itself instead of looking
        # like a typo.
        # 削除済みの方式は、汎用の「未知の値」エラーより先に名指しで報告する。
        # 保存済みパラメータファイルが打ち間違いに見えないようにするため。
        if bg_method in BG_METHOD_REMOVED:
            raise ValueError(BG_METHOD_REMOVED[bg_method])
        if bg_method not in BG_METHOD_NAMES:
            raise ValueError(
                f"bg_method must be one of {BG_METHOD_NAMES} "
                f"(or the retired alias {tuple(BG_METHOD_ALIASES)}), "
                f"got {bg_method!r}"
            )
        if not isinstance(tophat_se_size, (int, np.integer)) or tophat_se_size < 1:
            raise ValueError(
                f"tophat_se_size must be a positive int, got {tophat_se_size!r}"
            )
        if spline1d_axis not in ('y', 'x'):
            raise ValueError(
                f"spline1d_axis must be 'y' or 'x', got {spline1d_axis!r}"
            )
        if not isinstance(spline1d_degree, (int, np.integer)) \
                or isinstance(spline1d_degree, bool) or spline1d_degree < 1:
            # Reject bool explicitly because it satisfies isinstance(int).
            # bool は isinstance(int) を満たすので個別に弾く
            raise ValueError(
                f"spline1d_degree must be a positive int, got {spline1d_degree!r}"
            )

        self.threshold_factor = threshold_factor
        self.fiber_detect_factor = fiber_detect_factor
        self.noise_detect_factor = noise_detect_factor

        self.savgol_window = savgol_window
        self.savgol_polyorder = savgol_polyorder

        self.apply_median = apply_median
        self.mask_dilation = mask_dilation
        self.min_mask_component_area = min_mask_component_area

        self.bg_method = bg_method
        # Structuring elements must have odd side length; coerce silently
        # so callers don't have to worry about parity.
        # 構造要素は奇数サイズである必要があるため、偶数なら +1 する。
        self.tophat_se_size = int(tophat_se_size) | 1

        # TODO(review): the docstrings say 'y' (per column) evens out horizontal
        # stripes and 'x' (per row) targets vertical ones, but each line's fill
        # uses only that line's samples, so 'x' is the axis that keeps a row's
        # own scan-line offset, and `_spline1d_fill` justifies its end-run
        # level by that offset. Author to confirm which axis removes which
        # stripe before these docstrings are rewritten.
        self.spline1d_axis = spline1d_axis
        self.spline1d_degree = int(spline1d_degree)

    def __call__(self, image: ProcessedImage) -> None:
        """
        Execute the full background calibration pipeline on one image.
        1枚の画像に対して背景補正パイプライン全体を実行する。

        Parameters
        ----------
        image
            Input image container that must hold `original_image`.
            `original_image` を保持する入力画像コンテナ。

        Returns
        -------
        None
            The result is written in-place to `image.calibrated_image`.
            結果は `image.calibrated_image` にインプレースで格納される。

        Raises
        ------
        ValueError
            If `image.original_image` is None.

        Notes
        -----
        Reads `image.original_image`; writes `image.calibrated_image`.

        This method intentionally uses staged intermediate arrays so each step
        can be inspected during debugging or parameter tuning. The set of
        intermediates available on ``self`` depends on ``bg_method``:

        - ``'trendfill'``: ``dif_x``, ``dif_y``, ``histx``, ``histy``,
          ``outx``, ``outy``, ``tri_difx``, ``tri_dify``, ``tri_difx_fill``,
          ``tri_dify_fill``, ``bg_only``, ``bg_sm``.
        - ``'tophat'``: only ``bg_open`` (raw morphological opening) and
          ``bg_sm`` (after Savitzky-Golay). The ridge-detection
          intermediates are set to ``None`` since the method does not
          compute them.
        - ``'spline1d'``: the trendfill-style ridge-detection intermediates
          (``dif_x`` ... ``bg_only``) are computed for the fiber mask, plus
          ``bg_spline1d`` (the assembled background surface before
          smoothing: per-line interpolation, 2D nearest fill at the line
          ends, trend restored) and ``bg_sm`` (after Savitzky-Golay).
          ``bg_open`` is set to ``None``.

        このメソッドは中間配列を段階的に保持する設計になっており、
        デバッグ時やパラメータ調整時に各段階を確認しやすい。``self`` に
        残る中間配列の集合は ``bg_method`` に依存する:

        - ``'trendfill'``: ``dif_x``, ``dif_y``, ``histx``, ``histy``,
          ``outx``, ``outy``, ``tri_difx``, ``tri_dify``,
          ``tri_difx_fill``, ``tri_dify_fill``, ``bg_only``, ``bg_sm``。
        - ``'tophat'``: ``bg_open`` (生の opening 結果) と ``bg_sm``
          (Savitzky-Golay 後) のみ。リッジ検出系の中間配列は計算しないため
          ``None`` を設定する。
        - ``'spline1d'``: ファイバーマスクのため trendfill と同じリッジ検出系
          中間配列 (``dif_x`` 〜 ``bg_only``) を計算し、加えて
          ``bg_spline1d`` (平滑化前の背景曲面。行/列補間 + ライン端の 2 次元
          最近傍充填 + トレンド復元まで済んだもの) と ``bg_sm``
          (Savitzky-Golay 後) を保持。``bg_open`` は ``None``。
        """
        # Fail loudly at the stage boundary instead of deep inside the method.
        if image.original_image is None:
            raise ValueError(
                "BGCalibrator requires image.original_image; "
                "construct ProcessedImage with the raw AFM height array."
            )

        if self.bg_method == 'tophat':
            self._call_tophat(image)
        elif self.bg_method == 'spline1d':
            self._call_spline1d(image)
        else:
            self._call_trendfill(image)

    def _detect_fiber_mask(self, original: np.ndarray) -> None:
        """
        Run trendfill-style ridge detection up to the fiber mask intermediates.
        trendfill 系のリッジ検出をファイバーマスク中間配列まで実行する。

        Shared prelude of `_call_trendfill` and `_call_spline1d`: both need
        the same gradient-histogram fiber mask before they diverge on how
        they fill the background. The intermediates ``dif_x`` ...
        ``tri_difx_fill``/``tri_dify_fill`` are stored on ``self``, so the
        paths that use the mask cannot drift apart.
        `_call_trendfill` / `_call_spline1d` で共通の前段。
        両方式とも背景の埋め方が分かれる前に同じ勾配ヒストグラム由来の
        ファイバーマスクを必要とする。中間配列 ``dif_x`` 〜
        ``tri_difx_fill``/``tri_dify_fill`` は ``self`` に保持するため、マスクを使う
        経路どうしが食い違うことはない。
        """
        self.dif_x, self.dif_y = self._difXY(original)
        # Fit histogram models to estimate background-difference distribution.
        self.histx, self.histy, self.outx, self.outy = self._bg_fit(self.dif_x, self.dif_y)
        self.tri_difx, self.tri_dify = self._dif_sep(self.dif_x, self.dif_y, self.outx, self.outy)
        # Fill likely fiber regions from ternary difference patterns.
        self.tri_difx_fill, self.tri_dify_fill = self._extract_fiber(self.tri_difx, self.tri_dify)

    def _call_trendfill(self, image: ProcessedImage) -> None:
        """
        Run the ridge-mask, trend-subtraction and nearest-fill pipeline.
        リッジマスク・トレンド減算・最近傍充填によるパイプラインを実行する。
        """
        self._detect_fiber_mask(image.original_image)
        self.bg_only, self.bg_sm = self._bg_generate(image.original_image, self.tri_difx_fill, self.tri_dify_fill)
        # Clear intermediates from the other paths so callers can tell
        # which path ran.
        # 他方式の中間配列は走っていないことを明示するため None を設定。
        self.bg_open = None
        self.bg_spline1d = None
        calibrated_image = self._bg_calibrate(image.original_image, self.bg_sm)

        if self.apply_median:
            # Optionally suppress impulse-like residual noise.
            calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)

        image.calibrated_image = calibrated_image

    def _call_tophat(self, image: ProcessedImage) -> None:
        """
        Run the morphological top-hat pipeline.
        形態学的トップハット方式のパイプラインを実行する。

        Notes
        -----
        Output shape matches the `_bg_calibrate` convention
        (`original.shape - (1, 1)`) so that downstream stages (Segmenter
        etc.) see the same array shape regardless of `bg_method`.
        Ridge-detection intermediates (``dif_x`` etc.) are set to ``None``
        because they are not computed by this method.
        出力形状は `_bg_calibrate` と同じく ``original.shape - (1, 1)``
        になるよう揃え、下流ステージ (Segmenter 等) が ``bg_method`` の
        違いを意識せず同じ配列形状を受け取れるようにする。リッジ検出系
        中間配列 (``dif_x`` 等) は計算しないため ``None`` を設定する。

        Because the opening is a lower-envelope estimator (it is <= the
        original everywhere), the subtracted image is finally re-centered by
        its median so the substrate level sits at 0 nm; without this step the
        background would carry a positive, noise-dependent offset and the
        calibrated heights would not be comparable with the other methods.
        opening は下側包絡線の推定量（常に元画像以下）であるため、減算後の
        画像は最後に中央値で再センタリングして基板レベルを 0 nm に揃える。
        この処理が無いと背景にノイズ依存の正のオフセットが残り、補正後の
        高さが他方式と比較できなくなる。
        """
        original = image.original_image
        # Mark intermediates from the other paths as unused so accidental
        # reads fail loudly instead of returning stale values from a
        # previous run.
        # 他方式の中間配列は使わないことを明示。古い実行結果が残って
        # 静かに参照される事故を防ぐため、明示的に None を入れる。
        self.dif_x = self.dif_y = None
        self.histx = self.histy = None
        self.outx = self.outy = None
        self.tri_difx = self.tri_dify = None
        self.tri_difx_fill = self.tri_dify_fill = None
        self.bg_only = None
        self.bg_spline1d = None

        # Morphological opening with a disk-shaped structuring element of
        # diameter `tophat_se_size`. The opening removes bright structures
        # narrower than the disk; the residual `original - opening` is the
        # classic white top-hat transform. Here we keep the opening itself
        # as the background estimate. cv2 requires float32.
        # 直径 `tophat_se_size` の円盤型構造要素で opening する。opening は
        # 円盤より細い明るい構造を除去するので、残差 `original - opening`
        # が典型的な white top-hat 変換。本実装では opening を背景推定値
        # として保持する。cv2 は float32 を要求する。
        se = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.tophat_se_size, self.tophat_se_size),
        )
        # Open a detrended copy, then restore the trend, for the same reason
        # the trendfill path detrends: a raw scan carries a large sample tilt.
        # Opening reproduces a plane in the image interior, but not within one
        # structuring-element radius of the border, because erosion there takes
        # its minimum from a clipped neighborhood that dilation cannot restore,
        # so on a tilted scan a band is left along the uphill edge
        # (docs/validation.md §1.4). Detrending first removes the slope the
        # border effect feeds on.
        # トレンドを除いた写しに opening をかけ、後でトレンドを戻す。理由は
        # trendfill 経路と同じで、生の走査は大きな試料傾斜を伴うためである。
        # opening は画像内部では平面を再現するが、構造要素の半径以内の境界域
        # では再現しない。そこでは収縮が切り詰められた近傍から最小値を取り、
        # 膨張が復元できないからである。そのため傾いた走査では上り側の縁に帯が
        # 残る（docs/validation.ja.md §1.4）。先にデトレンドすることで、この
        # 境界効果が餌にする傾斜そのものを取り除く。
        # The trend is fitted over every pixel because this method computes no
        # fiber mask. Fibers bias the surface upward, but only their spatial
        # variation survives: a uniform offset passes unchanged through both
        # the opening and the smoothing and is removed by the median
        # re-centering below.
        # 本方式は繊維マスクを作らないため、トレンドは全画素でフィットする。
        # 繊維は曲面を上方へ偏らせるが、残るのはその空間変化だけである。
        # 一様なオフセットは opening にも平滑化にもそのまま通り、後段の中央値
        # 再センタリングで除かれる。
        bg_trend = self._fit_trend_surface(
            original, np.ones(original.shape, dtype=bool),
        )
        opened_detrended = cv2.morphologyEx(
            (original - bg_trend).astype(np.float32), cv2.MORPH_OPEN, se,
        ).astype(np.float64)
        self.bg_open = opened_detrended + bg_trend

        # Apply the same Savitzky-Golay smoothing as the trendfill path so
        # that downstream noise characteristics are comparable between the
        # two methods. Smoothing runs on the detrended opening and the trend is
        # restored afterwards: the filter is a moving average along X at
        # `savgol_polyorder <= 1`, which does not reproduce a quadratic, so
        # smoothing the trend-restored surface would fold the trend's curvature
        # into the background estimate. Then crop by [1:, 1:] to match the
        # output shape produced by `_bg_calibrate`.
        # trendfill パスと同じ Savitzky-Golay 平滑化をかけ、両方式の下流の
        # ノイズ特性をそろえる。平滑化はデトレンド後の opening に対して行い、
        # トレンドは後から戻す。`savgol_polyorder <= 1` のときこのフィルタは
        # X 方向の単純移動平均であり 2 次曲面を再現しないため、トレンドを戻した
        # 曲面を平滑化するとトレンドの曲率が背景推定へ混入してしまう。最終的に
        # `_bg_calibrate` と同じ出力形状に合わせるため `[1:, 1:]` で切り出す。
        self.bg_sm = signal.savgol_filter(
            opened_detrended, self.savgol_window, self.savgol_polyorder,
        ) + bg_trend
        calibrated_image = original[1:, 1:] - self.bg_sm[1:, 1:]

        # Morphological opening is a lower-envelope estimator: over a noisy
        # substrate it tracks the local noise minima, so after subtraction the
        # substrate level floats above zero by roughly the noise-envelope
        # depth instead of centering at 0 nm. Re-center with the image median
        # (robust while fibers cover less than about half the image) so the
        # absolute nm thresholds downstream (global_threshold, low_threshold,
        # bp_height) keep the same meaning as with the interpolating
        # background methods, which pass through the middle of the noise.
        # 形態学的 opening は下側包絡線の推定量であり、ノイズのある基板では
        # 局所極小に張り付く。そのため減算後の基板レベルは 0 nm ではなく
        # ノイズ包絡の深さ分だけ正側に浮く。画像中央値（繊維被覆率が約半分
        # 未満なら頑健）で再センタリングし、下流の nm 絶対しきい値
        # (global_threshold, low_threshold, bp_height) が、ノイズの中央を通る
        # 補間系の背景方式と同じ意味を持つようにする。
        calibrated_image -= np.median(calibrated_image)

        if self.apply_median:
            calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)

        image.calibrated_image = calibrated_image

    def _call_spline1d(self, image: ProcessedImage) -> None:
        """
        Run the per-line 1D spline background interpolation.
        行/列ごとの 1D スプライン背景補間を実行する。

        Notes
        -----
        The fiber mask is the one `_call_trendfill` uses, including
        ``mask_dilation`` and ``min_mask_component_area``, so fiber-edge
        shoulders are excluded from the background pool exactly as in
        ``'trendfill'``. The image is detrended before the fill and the trend
        restored afterwards, as in ``'trendfill'``, so no filler has to
        reproduce the sample tilt.

        No shape is extrapolated past the line ends. Beyond the first/last
        valid sample of a line - a fiber touching the image edge along the
        interpolation axis - there is background data on one side only, so
        any shape a 1D method puts there is fitted to that single line, its
        error grows with the run length, and it is uncorrelated with the
        neighboring lines: holding the last sample constant streaks the image
        edge, and the fitted spline's own extrapolation paints smooth bands.
        These runs instead hold the mean of the line's nearest
        ``savgol_window`` background samples (`_spline1d_fill`): on a
        detrended image the per-line residual is essentially the scan-line
        offset, which is constant along the line, and averaging keeps pixel
        noise out of that level. Only a line with fewer than two valid samples
        is left unfilled there, and its pixels are filled from the nearest
        background pixel in 2D.

        The interpolation axis is ``spline1d_axis``: ``'x'`` (default)
        fills each row from its own values, so on the usual geometry (image
        rows are scan lines) each scan line's offset stays in the background
        and *horizontal* stripes are subtracted with it; ``'y'`` fills each
        column instead, which fills a hole from the rows above and below and
        does not remove horizontal stripes there.

        Like every background method, the estimated background is
        subtracted *in full*. The interpolated background is Savitzky-Golay
        smoothed first, because the per-line interpolation is not smooth by
        construction. Its effect on scan-line offsets, against ``'trendfill'``,
        is in docs/validation.md section 1.6.

        ファイバーマスクは `_call_trendfill` と同じもので、``mask_dilation`` と
        ``min_mask_component_area`` も含む。これにより ``'trendfill'`` と同様、
        ファイバー端の肩部が背景プールから除外される。``'trendfill'`` と同様、
        充填の前にデトレンドし後でトレンドを戻すため、どの充填器も試料傾斜を
        再現する必要がない。

        ライン端より外側へ形を外挿しない。各ラインの最初/最後の有効サンプルより
        外側 (補間軸の端にファイバーがかかる場合) は片側にしか背景データが無い
        ため、1 次元手法がそこへ置く形はそのライン単独の当てはめになり、誤差は
        区間長とともに増え、隣接ラインと無相関になる。最終サンプルの値を一定に
        保てば画像端に細いスジが出て、フィットしたスプライン自身の外挿では
        滑らかな帯が出る。そこでこの区間には、そのライン自身の最近傍
        ``savgol_window`` 個の背景サンプルの平均を保持する (`_spline1d_fill`)。
        デトレンド後にライン固有として残る量は実質的に走査ラインのオフセットで
        あり、ライン方向に一定であるうえ、平均を取ることでその水準に画素ノイズが
        入らない。この区間を埋めずに残すのは有効サンプルが 2 点未満のラインだけで、
        その画素は 2 次元の最近傍背景画素から埋める。

        補間の向きは ``spline1d_axis`` で決まる。``'x'`` (デフォルト) は各行を
        その行自身の値から埋めるので、一般的な撮り方 (画像の行が走査ライン)
        では各走査ラインのずれが背景に残り、*横縞* も一緒に引かれる。``'y'``
        は各列を埋めるので、穴は上下の行の値から埋まり、横縞はそこでは
        消えない。

        他の背景方式と同様、推定した背景は *そのまま全面* 減算する。行/列ごとの
        補間は構成上滑らかにはならないため、補間した背景を先に Savitzky-Golay
        平滑化する。走査ラインのオフセットへの効果を ``'trendfill'`` と比べた
        結果は docs/validation.ja.md の 1.6 節にある。
        """
        original = image.original_image

        # Reuse the trendfill-style ridge detection and fiber mask. We only
        # need ``bg_only`` (image with NaN at masked positions, shape
        # (H-1, W-1)); the smoothed bg returned by `_bg_generate` is
        # discarded because we re-fill with the 1D spline.
        # trendfill のリッジ検出とファイバーマスクを流用する。必要なのは
        # ``bg_only`` (マスク位置 NaN、(H-1, W-1) 形状)
        # のみで、`_bg_generate` が返す平滑化 bg は 1D スプラインで埋め直す
        # ため破棄する。
        self._detect_fiber_mask(original)
        self.bg_only, _ = self._bg_generate(original, self.tri_difx_fill, self.tri_dify_fill)

        # Mark intermediates from the other paths as unused.
        # 他方式の中間配列は使わないことを明示。
        self.bg_open = None

        crop = original[1:, 1:]
        valid_mask = ~np.isnan(self.bg_only)

        # Detrend before filling and restore the trend afterwards, exactly as
        # `_bg_generate` does, so that neither filler has to reproduce the
        # sample tilt.
        # `_bg_generate` と同じく、充填の前にデトレンドし後でトレンドを戻す。
        # どちらの充填器も試料傾斜を再現しなくてよくなる。
        if not valid_mask.any():
            # Pathological input: every pixel was classified as fiber. Fall
            # back to a flat zero background, as the other paths do.
            # 病的な入力: 全画素が繊維と判定された。他方式と同様、平坦な
            # ゼロ背景へフォールバックする。
            bg_trend = np.zeros_like(crop, dtype=np.float64)
            bg_int = np.zeros_like(crop, dtype=np.float64)
        else:
            bg_trend = self._fit_trend_surface(crop, valid_mask)
            detrended = np.where(valid_mask, crop - bg_trend, float('nan'))

            # Interpolate the masked positions along one axis. Inside a
            # line's valid span the spline interpolates; beyond the first/last
            # valid sample it holds the level of that line's nearest
            # `savgol_window` background samples.
            # マスク位置を 1 軸方向に補間する。各ラインの有効範囲内はスプライン
            # で補間し、最初/最後の有効サンプルより外側は、そのライン自身の
            # 最近傍 `savgol_window` 個の背景サンプルの水準を保持する。
            bg_int = self._spline1d_fill(
                detrended, axis=self.spline1d_axis, order=self.spline1d_degree,
                end_window=self.savgol_window,
            )

            # Only fully masked lines can still be unfilled; they carry no
            # information of their own, so take the nearest background pixel
            # in 2D.
            # ここで未充填として残るのは全域がマスクされたラインだけである。
            # 自前の情報を持たないため、2 次元の最近傍背景画素を使う。
            unfilled = np.isnan(bg_int)
            if unfilled.any():
                nearest_idx = distance_transform_edt(
                    ~valid_mask, return_distances=False, return_indices=True,
                )
                nearest = np.where(valid_mask, crop - bg_trend, 0.0)[tuple(nearest_idx)]
                bg_int = np.where(unfilled, nearest, bg_int)

            bg_int = bg_int + bg_trend

        self.bg_spline1d = bg_int

        # Savitzky-Golay smoothing then full-frame subtraction (no exact
        # restore of background-candidate pixels).
        # Savitzky-Golay 平滑化のあと全面減算する。背景候補画素の厳密復元は
        # 行わない。
        self.bg_sm = signal.savgol_filter(bg_int, self.savgol_window, self.savgol_polyorder)
        calibrated_image = original[1:, 1:] - self.bg_sm

        if self.apply_median:
            calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)

        image.calibrated_image = calibrated_image

    @staticmethod
    def _spline1d_fill(bg_only: np.ndarray, axis: str = 'x', order: int = 2,
                       end_window: int = 31) -> np.ndarray:
        """
        Fill each line's masked positions: interpolate inside, hold a level outside.
        各ラインのマスク位置を埋める。有効範囲内は補間し、範囲外は水準を保持する。

        Parameters
        ----------
        bg_only
            2D array with NaN at masked (fiber) positions. Pass a detrended
            image: the per-line fit then models only the residual.
            マスク (ファイバー) 位置が NaN の 2D 配列。デトレンド済み画像を
            渡すこと。行/列ごとのフィットが残差だけをモデル化すればよくなる。
        axis : {'y', 'x'}
            ``'y'`` interpolates each column along rows (axis 0);
            ``'x'`` interpolates each row along columns (axis 1).
            ``'y'`` は各列を行方向 (axis 0) に、``'x'`` は各行を列方向
            (axis 1) に補間する。
        order
            Spline order passed to ``pandas.Series.interpolate``.
            ``pandas.Series.interpolate`` に渡すスプライン order。
        end_window
            Number of a line's nearest valid samples averaged to set the level
            held across its end runs.
            ライン端の区間に保持する水準を決めるために平均する、そのラインの
            最近傍有効サンプルの数。

        Returns
        -------
        np.ndarray
            ``bg_only`` with its NaNs filled (float64). Positions beyond the
            first/last valid sample of their line hold the mean of that
            line's nearest ``end_window`` valid samples. A line with fewer
            than two valid samples is returned unchanged, so its NaNs remain.
            NaN を埋めた ``bg_only`` (float64)。各ラインの最初/最後の有効
            サンプルより外側の位置には、そのラインの最近傍 ``end_window`` 個の
            有効サンプルの平均が入る。有効サンプルが 2 点未満のラインはそのまま
            返すため、その NaN は残る。

        Notes
        -----
        Per line, NaNs are filled by the pandas spline of the given order,
        falling back to linear when there are too few valid points, and that
        result is kept only between the first and the last valid sample.
        Outside that span a line carries background data on one side only,
        so any shape a 1D method puts there is an extrapolation fitted to
        that one line: its error grows with the run length and is
        uncorrelated between neighboring lines, so each line would paint its
        own band. Those runs instead hold the mean of the line's nearest
        ``end_window`` valid samples. On a detrended image the per-line
        residual is essentially the scan-line offset, which is constant along
        the line, so holding a level estimates it without extrapolating a
        slope, and averaging keeps pixel noise out of that level; see
        `_call_spline1d`.
        各ラインの NaN は指定 order の pandas スプライン (有効点が少ない場合は
        線形へフォールバック) で埋め、その結果は最初と最後の有効サンプルの間
        だけ採用する。この範囲の外側はラインの片側にしか背景データが無いため、
        1 次元手法が置く形はそのライン単独で当てた外挿であり、誤差は区間長と
        ともに増え、隣接ラインと無相関になる。結果として各ラインが自前の帯を
        描いてしまう。そこでこの区間には、そのラインの最近傍 ``end_window``
        個の有効サンプルの平均を保持する。デトレンド後にライン固有として残る
        量は実質的に走査ラインのオフセットであり、ライン方向に一定なので、
        水準を保持すれば傾きを外挿せずにこれを推定でき、平均を取ることでその
        水準に画素ノイズが入らない (`_call_spline1d` 参照)。

        A line with fewer than two valid samples is returned unchanged.
        有効サンプルが 2 点未満のラインはそのまま返す。

        """
        import pandas as pd

        # Work column-wise internally; transpose for the 'x' case so the same
        # code path handles both axes. Each column of ``work`` is one line.
        # 内部的に列方向で処理する。'x' の場合は転置して同じコードパスで両軸を
        # 扱う。``work`` の各列が 1 本のラインに対応する。
        arr = np.asarray(bg_only, dtype=np.float64)
        work = arr if axis == 'y' else arr.T
        n = work.shape[0]
        idx = np.arange(n, dtype=np.float64)
        out = work.copy()

        for c in range(work.shape[1]):
            line = work[:, c]
            valid = ~np.isnan(line)
            n_valid = int(valid.sum())
            if n_valid < 2:
                # Nothing to interpolate along this line. Its valid sample, if
                # any, is left in place and the rest stays NaN for the caller.
                # このラインには補間の材料が無い。有効サンプルがあればそのまま
                # 残し、残りは NaN のまま呼び出し側に委ねる。
                continue

            # Choose a method that the available number of points can support:
            # a spline of order k needs at least k+1 points; otherwise degrade
            # gracefully.
            # 点数が order を満たさない場合は緩やかに劣化させる
            # (order k のスプラインには最低 k+1 点必要)。
            s = pd.Series(line)
            if n_valid >= order + 1 and order >= 2:
                filled = s.interpolate(method='spline', order=order,
                                       limit_direction='both')
            else:
                # Not enough points for the requested spline; linear is the
                # robust fallback (pandas 'index'/'linear' on a default
                # RangeIndex are equivalent here).
                # 要求スプラインには点数不足。線形を頑健なフォールバックに使う。
                filled = s.interpolate(method='linear', limit_direction='both')
            # ``copy=True`` guarantees a writable array; some pandas versions
            # return a read-only view from ``to_numpy()``.
            # 一部の pandas では ``to_numpy()`` が読み取り専用ビューを返すため
            # ``copy=True`` で書き込み可能配列を保証する。
            filled = filled.to_numpy(copy=True)

            # Replace whatever pandas produced outside the valid span. Both
            # branches extrapolate a *shape* there - the spline branch its own
            # fit (scipy ``ext=0``), the linear branch a constant at the last
            # sample - fitted to one line, so the error grows with the run
            # length and is uncorrelated between neighboring lines: each line
            # paints its own band. Hold the mean of that line's nearest
            # ``end_window`` background samples instead. On a detrended image
            # the remaining per-line quantity is essentially the scan-line
            # offset, which is constant along the line, so holding a level
            # estimates it without extrapolating a slope, and averaging
            # ``end_window`` samples keeps the pixel noise out of that level.
            # 有効範囲の外側に pandas が置いた値は差し替える。両分岐ともそこへ
            # *形* を外挿しており (スプライン分岐は自身のフィット、scipy
            # ``ext=0``。線形分岐は最終サンプルでの定数)、1 ライン単独の当てはめ
            # なので誤差は区間長とともに増え、隣接ラインとは無相関になる。結果
            # として各ラインが自前の帯を描く。代わりに、そのライン自身の最近傍
            # ``end_window`` 個の背景サンプルの平均を保持する。デトレンド後に
            # ライン固有として残る量は実質的に走査ラインのオフセットであり、
            # ライン方向に一定なので、水準を保持すれば傾きを外挿せずにこれを
            # 推定できる。``end_window`` 個を平均するのは、その水準に画素ノイズ
            # を持ち込まないためである。
            valid_pos = np.flatnonzero(valid)
            first, last = valid_pos[0], valid_pos[-1]
            k = max(1, min(end_window, n_valid))
            filled[:first] = np.mean(line[valid_pos[:k]])
            filled[last + 1:] = np.mean(line[valid_pos[-k:]])

            # Guard against any residual NaN inside the span (e.g. pathological
            # pandas output).
            # 有効範囲内に NaN が残った場合の保険 (pandas の病的出力など)。
            span = slice(first, last + 1)
            if np.isnan(filled[span]).any():
                still = np.flatnonzero(np.isnan(filled[span])) + first
                filled[still] = np.interp(idx[still], idx[valid_pos], line[valid_pos])

            out[:, c] = filled

        return out if axis == 'y' else out.T

    @staticmethod
    def _difXY(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute first-order differences along X and Y directions.
        X・Y 方向の1次差分を計算する。

        Parameters
        ----------
        image
            Input AFM height image.
            入力となる AFM 高さ画像。

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            (dif_x, dif_y) where each value is a nearest-neighbor difference.
            最近傍差分である (dif_x, dif_y) を返す。

        Notes
        -----
        Large absolute differences often correspond to edges or fiber boundaries.
        絶対値の大きな差分は、エッジや繊維境界に対応することが多い。
        """
        dif_x = image[:, 1:] - image[:, 0:-1]
        dif_y = image[1:, :] - image[0:-1, :]
        return dif_x, dif_y

    @staticmethod
    def _bg_fit(dif_x: np.ndarray, dif_y: np.ndarray, bin_n: int = 150) -> tuple:
        """
        Fit histogram distributions of differences with Gaussian + linear baseline.
        差分ヒストグラムをガウス + 線形ベースラインでフィットする。

        Parameters
        ----------
        dif_x
            Horizontal difference image.
            水平方向の差分画像。
        dif_y
            Vertical difference image.
            垂直方向の差分画像。
        bin_n
            Number of histogram bins used for fitting.
            フィットに使うヒストグラムのビン数。

        Returns
        -------
        tuple
            (histx, histy, outx, outy) for X/Y histograms and fit results.
            X/Y ヒストグラムとフィット結果の (histx, histy, outx, outy)。

        Notes
        -----
        The Gaussian center/sigma are later used as robust thresholds in `_dif_sep`.
        ここで得たガウス中心値とシグマは、後段 `_dif_sep` のしきい値に使われる。
        """
        # Local import: lmfit takes ~3 s to import and is used only by this
        # histogram fit, so loading it here keeps GUI and CLI startup fast.
        # lmfit は import に約 3 秒かかり、このヒストグラムフィットでしか
        # 使わないため、ここで読み込んで GUI / CLI の起動を速く保つ。
        from lmfit.models import GaussianModel, PolynomialModel

        histx = np.histogram(np.ravel(dif_x), bins=bin_n)
        histy = np.histogram(np.ravel(dif_y), bins=bin_n)
        h_arrayx = (histx[1][1:] + histx[1][:-1]) / 2
        h_arrayy = (histy[1][1:] + histy[1][:-1]) / 2

        bg = PolynomialModel(prefix='bg_', degree=1)
        pV1 = GaussianModel(prefix='pv1_')
        model = pV1 + bg
    
        # --- X direction ---
        # --- X方向 ---
        pars_x = model.make_params()
        pars_x['bg_c0'].set(0)
        pars_x['bg_c1'].set(0)
        pars_x['pv1_amplitude'].set(dif_x.size / 10)
        pars_x['pv1_center'].set(np.median(dif_x))
        pars_x['pv1_sigma'].set((np.percentile(dif_x, 75) - np.percentile(dif_x, 25)) / 1.349)
        outx = model.fit(histx[0], pars_x, x=h_arrayx)
    
        # --- Y direction, fitted independently from X because the AFM slow-scan
        #     axis often has broader sigma due to different noise characteristics. ---
        # --- Y方向(Xと独立。AFMの低速走査軸は高速走査軸と
        #         ノイズ特性が異なり、σが広がりやすいため) ---
        pars_y = model.make_params()
        pars_y['bg_c0'].set(0)
        pars_y['bg_c1'].set(0)
        pars_y['pv1_amplitude'].set(dif_y.size / 10)
        pars_y['pv1_center'].set(np.median(dif_y))
        pars_y['pv1_sigma'].set((np.percentile(dif_y, 75) - np.percentile(dif_y, 25)) / 1.349)
        outy = model.fit(histy[0], pars_y, x=h_arrayy)
    
        return histx, histy, outx, outy

    def _dif_sep(
        self,
        dif_x: np.ndarray,
        dif_y: np.ndarray,
        outx: "ModelResult",
        outy: "ModelResult",
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Separate differences into ternary categories using fitted thresholds.
        フィット結果のしきい値で差分を3値に分類する。

        Parameters
        ----------
        dif_x
            Horizontal difference image.
            水平方向の差分画像。
        dif_y
            Vertical difference image.
            垂直方向の差分画像。
        outx
            Fit result for `dif_x` histogram.
            `dif_x` ヒストグラムのフィット結果。
        outy
            Fit result for `dif_y` histogram.
            `dif_y` ヒストグラムのフィット結果。

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Ternary maps where -1/0/1 mean low/normal/high differences.
            -1/0/1 が低/通常/高差分を示す3値マップ。

        Notes
        -----
        Values near the fitted Gaussian center are treated as background (0).
        ガウス中心付近の値は背景らしい差分として 0 に分類される。
        Positive/negative outliers are preserved as +1/-1 for edge pattern search.
        正負の外れ値は +1/-1 として保持され、後段のエッジパターン探索に使われる。
        """
        outx_min = outx.best_values['pv1_center'] - self.threshold_factor * outx.best_values['pv1_sigma']
        outx_max = outx.best_values['pv1_center'] + self.threshold_factor * outx.best_values['pv1_sigma']
        outy_min = outy.best_values['pv1_center'] - self.threshold_factor * outy.best_values['pv1_sigma']
        outy_max = outy.best_values['pv1_center'] + self.threshold_factor * outy.best_values['pv1_sigma']
        tri_difx = np.where(dif_x < outx_min, -1, 0) + np.where(dif_x > outx_max, 1, 0)
        tri_dify = np.where(dif_y < outy_min, -1, 0) + np.where(dif_y > outy_max, 1, 0)
        return tri_difx, tri_dify

    def _extract_fiber(
        self,
        tri_difx: np.ndarray,
        tri_dify: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Detect and fill likely fiber spans from ternary edge patterns.
        3値のエッジパターンから繊維らしい区間を検出して塗りつぶす。

        Parameters
        ----------
        tri_difx
            Ternary difference map along row direction.
            行方向の3値差分マップ。
        tri_dify
            Ternary difference map along column direction.
            列方向の3値差分マップ。

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Filled masks for X and Y detections.
            X/Y 検出に対する塗りつぶし済みマスク。

        Notes
        -----
        Run-length encoding is used to evaluate local sign-transition patterns.
        ランレングス符号化を用いて局所的な符号遷移パターンを評価する。
        The method scans rows and columns independently, then combines results
        in the next stage to identify pixels likely belonging to fibers.
        行方向と列方向を独立に走査し、次段で両結果を組み合わせて
        繊維に属する可能性が高い画素を同定する。
        """
        # Process X-direction ridge patterns row by row.
        # X方向のリッジパターンを行ごとに処理する。
        tri_difx_fill = np.zeros(tri_difx.shape)
        for j in range(tri_difx.shape[0]):
            row = tri_difx[j, :]
            # Run-length encoding exposes gradient sign transitions used for ridge detection.
            # ランレングス符号化により、リッジ検出に使う勾配符号の遷移を取り出す。
            change_pos = np.where(np.diff(row) != 0)[0]
            l_arr = np.empty(len(change_pos) + 1, dtype=row.dtype)
            l_arr[0] = row[0]
            l_arr[1:] = row[change_pos + 1]
            arg_arr = np.empty(len(change_pos) + 1, dtype=np.intp)
            arg_arr[0] = 0
            arg_arr[1:] = change_pos + 1

            n = len(l_arr)
            if n < 4:
                continue

            # Pattern 1: [1, 0, -1] with small inner gap.
            # パターン1: [1, 0, -1] かつ内側ギャップが小さい場合。
            # This pattern approximates one ridge bounded by opposite gradients.
            # この並びは正負勾配で挟まれた1本のリッジ形状を近似する。
            mask1 = (l_arr[:-3] == 1) & (l_arr[1:-2] == 0) & (l_arr[2:-1] == -1)
            gap1_ok = (arg_arr[2:-1] - arg_arr[1:-2]) < self.fiber_detect_factor
            for vi in np.where(mask1 & gap1_ok)[0]:
                tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 3] - 1] = 1

            # Pattern 2: [1, -1] with enough span to avoid tiny noise.
            # パターン2: [1, -1] かつ微小ノイズを除くため十分なスパン。
            # This catches sharp ridge-like spans without an explicit zero plateau.
            # 0 区間を伴わない急峻なリッジ候補もこの条件で補足する。
            mask2 = (l_arr[:-3] == 1) & (l_arr[1:-2] == -1)
            gap2_ok = (arg_arr[2:-1] - arg_arr[:-3]) > self.noise_detect_factor
            for vi in np.where(mask2 & gap2_ok)[0]:
                tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 2] - 1] = 1

        # Process Y-direction ridge patterns column by column.
        # Y方向のリッジパターンを列ごとに処理する。
        tri_dify_fill = np.zeros(tri_dify.shape)
        for j in range(tri_dify.shape[1]):
            col = tri_dify[:, j]
            # Apply the same sign-transition logic symmetrically in Y-direction.
            # X方向と同じ符号遷移判定を Y方向へ対称的に適用する。
            change_pos = np.where(np.diff(col) != 0)[0]
            l_arr = np.empty(len(change_pos) + 1, dtype=col.dtype)
            l_arr[0] = col[0]
            l_arr[1:] = col[change_pos + 1]
            arg_arr = np.empty(len(change_pos) + 1, dtype=np.intp)
            arg_arr[0] = 0
            arg_arr[1:] = change_pos + 1

            n = len(l_arr)
            if n < 4:
                continue

            # Pattern 1: [1, 0, -1] with small inner gap.
            # パターン1: [1, 0, -1] かつ内側ギャップが小さい場合。
            mask1 = (l_arr[:-3] == 1) & (l_arr[1:-2] == 0) & (l_arr[2:-1] == -1)
            gap1_ok = (arg_arr[2:-1] - arg_arr[1:-2]) < self.fiber_detect_factor
            for vi in np.where(mask1 & gap1_ok)[0]:
                tri_dify_fill[arg_arr[vi]:arg_arr[vi + 3] - 1, j] = 1

            # Pattern 2: [1, -1] with enough span to avoid tiny noise.
            # パターン2: [1, -1] かつ微小ノイズを除くため十分なスパン。
            mask2 = (l_arr[:-3] == 1) & (l_arr[1:-2] == -1)
            gap2_ok = (arg_arr[2:-1] - arg_arr[:-3]) > self.noise_detect_factor
            for vi in np.where(mask2 & gap2_ok)[0]:
                tri_dify_fill[arg_arr[vi]:arg_arr[vi + 2] - 1, j] = 1

        return tri_difx_fill, tri_dify_fill

    def _bg_generate(
        self,
        original: np.ndarray,
        tri_difx_fill: np.ndarray,
        tri_dify_fill: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Build a smooth background from pixels not marked as fiber candidates.
        繊維候補としてマークされていない画素から平滑背景を構築する。

        Parameters
        ----------
        original
            Original AFM image.
            元の AFM 画像。
        tri_difx_fill
            Filled mask obtained from X-direction pattern detection.
            X方向パターン検出で得られた塗りつぶしマスク。
        tri_dify_fill
            Filled mask obtained from Y-direction pattern detection.
            Y方向パターン検出で得られた塗りつぶしマスク。

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            `bg_only` with NaN at excluded regions and smoothed `bg_sm`.
            除外領域を NaN とした `bg_only` と平滑化後の `bg_sm`。

        Notes
        -----
        The `[1:, 1:]` crop aligns dimensions with difference-derived masks.
        `[1:, 1:]` の切り出しは差分由来マスクと配列サイズを一致させるため。

        When `mask_dilation > 0`, the raw fiber mask is dilated before being
        applied so that fiber-edge pixels escaping `_extract_fiber` are also
        excluded from the background pool. This prevents over-subtraction
        around fibers caused by biased interpolation near fiber boundaries.
        `mask_dilation > 0` の場合、生のファイバーマスクを膨張させてから
        適用することで、`_extract_fiber` で取り切れないファイバー端画素も
        背景プールから除外する。これにより、ファイバー境界付近で背景推定が
        過大になり周辺が過剰減算される現象を防ぐ。

        Before dilation, 8-connected components smaller than
        `min_mask_component_area` are dropped from the raw mask to avoid
        amplifying spurious tiny detections from the `[1, -1]` ridge pattern
        in `_extract_fiber`. Without this step, each false positive is
        expanded by dilation into a `(2 * mask_dilation + 1)^2` hole,
        producing salt-and-pepper noise across the reconstructed background.
        dilation の前段で、生マスクから 8 連結成分の面積が
        `min_mask_component_area` 未満のものを除去する。
        これは `_extract_fiber` の `[1, -1]` リッジパターンが拾う微小な
        偽検出が dilation で `(2 * mask_dilation + 1)^2` ピクセルの穴に
        増幅され、再構成背景にゴマ塩状ノイズを生むのを防ぐためである。

        The holes are filled on a *detrended* copy of the image: a second-order
        surface is least-squares fitted to the background-candidate pixels and
        subtracted, the holes are filled by nearest-valid propagation, the
        result is Savitzky-Golay smoothed, and the surface is added back. The
        detrending step is what makes the fill accurate, and it matters because
        raw AFM scans can carry a sample tilt large enough that the background
        falls by a sizeable fraction of a fiber's height across one dilated
        fiber hole (docs/validation.md section 1.1). Any fill that cannot
        reproduce that ramp leaves an error of that size in the background.
        穴の充填は画像を *デトレンド* した写しの上で行う。背景候補画素に 2 次
        曲面を最小二乗フィットして減算し、最近傍の有効画素を伝播させて穴を
        埋め、Savitzky-Golay で平滑化してから曲面を足し戻す。精度の鍵はこの
        デトレンドにある。生の AFM 走査は、膨張後の繊維 1 本分の穴を横切る間に
        背景が繊維の高さのかなりの割合だけ落ちるほどの試料傾斜を伴うことがある
        （docs/validation.ja.md の 1.1 節）。この傾斜を再現できない充填法は、
        その大きさの誤差を背景に残すことになる。

        Nearest-valid propagation is enough once the image is detrended: with
        the trend removed the height difference across a hole is close to
        zero, so the choice of filler barely matters (docs/validation.md
        section 1.2).
        Nearest-valid propagation also preserves the background-candidate
        pixels exactly, so no explicit restore step is needed.
        デトレンド後であれば最近傍伝播で十分である。トレンドを除くと穴を跨ぐ
        高さ差がほぼゼロになるため、充填法の選択はほとんど効かない
        （docs/validation.ja.md の 1.2 節）。また最近傍伝播は背景候補画素をそのまま保存するので、
        明示的な復元処理を必要としない。

        The smoothed background is then obtained by Savitzky-Golay filtering.
        その後 Savitzky-Golay フィルタで平滑背景を得る。
        """
        raw_mask = (np.abs(tri_difx_fill[1:, :]) + np.abs(tri_dify_fill[:, 1:])) > 0

        # Rationale: `_extract_fiber`'s Pattern 2 (`[1, -1]`) catches 2- to
        # 10-pixel false positives that scatter densely across noisy / wide-
        # field images. Without this filter, dilation expands each one into
        # a `(2 * mask_dilation + 1)^2` hole, producing a salt-and-pepper
        # field across `bg_only` that destabilises the background fill
        # (visible as a tiled / cellular artefact at mask_dilation >= 3).
        # Real fibers form much larger 8-connected components and survive.
        # The filter runs only together with the dilation it guards against.
        # 理由: `_extract_fiber` の Pattern 2 (`[1, -1]`) は 2〜10 px 程度の
        # 偽検出を拾い、ノイズの多い画像や広視野画像では画面全体に密に
        # 散らばる。フィルタなしで dilation すると 1 つの偽検出が
        # `(2 * mask_dilation + 1)^2` ピクセルの穴に膨張し、bg_only に
        # ゴマ塩状の欠損を作って背景の充填を不安定化させる
        # （mask_dilation >= 3 でタイル状・細胞状パターンとして見える）。
        # 本物のファイバーは十分大きな 8 連結成分を形成するため残る。
        # このフィルタは、それが防ごうとする膨張と一緒にだけ実行する。
        if self.mask_dilation > 0 and self.min_mask_component_area > 1:
            n_cc, cc_labels, cc_stats, _cc_centroids = cv2.connectedComponentsWithStats(
                raw_mask.astype(np.uint8), connectivity=8,
            )
            # Background label 0 is never kept as a fiber component.
            keep = np.zeros(n_cc, dtype=bool)
            if n_cc > 1:
                keep[1:] = cc_stats[1:, cv2.CC_STAT_AREA] >= self.min_mask_component_area
            raw_mask = keep[cc_labels]

        # Dilate the mask to absorb fiber-edge pixels missed by _extract_fiber.
        # _extract_fiber が取りこぼすファイバー端画素を吸収するため膨張する。
        # Rationale: shoulder pixels that retain residual fiber height can bias
        # the interpolated background upward, producing overshoot (dark halo)
        # on both sides of fibers after subtraction.
        # 理由: 残留ファイバー高を含む肩部画素が背景推定を底上げし、
        # 減算後にファイバー両脇で過剰減算（暗いハロー）を生む。
        if self.mask_dilation > 0:
            kernel = np.ones(
                (self.mask_dilation * 2 + 1, self.mask_dilation * 2 + 1),
                dtype=np.uint8,
            )
            fiber_mask = cv2.dilate(raw_mask.astype(np.uint8), kernel).astype(bool)
        else:
            fiber_mask = raw_mask

        crop = original[1:, 1:]
        bg_only = np.where(~fiber_mask, crop, float('nan'))
        valid_mask = ~fiber_mask

        if not valid_mask.any():
            # Pathological input: every pixel was classified as fiber, so there
            # is no background information to fit or to propagate. Fall back to
            # a flat zero background.
            # 病的な入力: 全画素が繊維と判定され、フィットにも伝播にも使える
            # 背景情報が無い。平坦なゼロ背景へフォールバックする。
            return bg_only, np.zeros_like(crop, dtype=np.float64)

        # Remove the sample tilt/bowl before filling, then add it back after
        # smoothing (see Notes for why this dominates the fill accuracy).
        # 充填の前に試料の傾き・うねりを除去し、平滑化後に足し戻す
        # （充填精度を支配する理由は Notes 参照）。
        bg_trend = self._fit_trend_surface(crop, valid_mask)
        detrended = crop - bg_trend

        # Fill each masked pixel from its nearest background-candidate pixel.
        # `distance_transform_edt` measures distance to the nearest zero of its
        # input, so passing `fiber_mask` yields, for every pixel, the index of
        # the nearest non-fiber pixel; background pixels index themselves and
        # are therefore preserved exactly.
        # マスク画素を最近傍の背景候補画素の値で埋める。
        # `distance_transform_edt` は入力の 0 要素までの距離を測るため、
        # `fiber_mask` を渡すと各画素について最近傍の非繊維画素の添字が得られる。
        # 背景画素は自分自身を指すので、値はそのまま保存される。
        nearest_idx = distance_transform_edt(
            fiber_mask, return_distances=False, return_indices=True,
        )
        bg_int = detrended[tuple(nearest_idx)]

        bg_sm = signal.savgol_filter(
            bg_int, self.savgol_window, self.savgol_polyorder,
        ) + bg_trend
        return bg_only, bg_sm

    @staticmethod
    def _fit_trend_surface(image: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
        """
        Least-squares fit a second-order surface to background-candidate pixels.
        背景候補画素に 2 次曲面を最小二乗フィットする。

        Parameters
        ----------
        image
            Cropped height image the surface is fitted to.
            曲面をフィットする対象の、切り出し済み高さ画像。
        valid_mask
            True where the pixel is a background candidate, i.e. not fiber.
            背景候補（非繊維）画素で True となるマスク。

        Returns
        -------
        np.ndarray
            The fitted surface evaluated on the full grid, shaped like `image`.
            全格子上で評価したフィット曲面。`image` と同じ形状。

        Notes
        -----
        Second order rather than a plane because real scans can be bowl-shaped
        as well as tilted (docs/validation.md section 1.1).
        平面ではなく 2 次にするのは、実際の走査が傾いているだけでなく皿状に
        歪んでいることがあるためである（docs/validation.ja.md の 1.1 節）。

        Coordinates are normalised to [-1, 1] before the quadratic terms are
        formed. On a 1024-px axis the raw-pixel design matrix has a condition
        number of about 3.4e6 over the full grid against about 4 after
        normalisation; float64 SVD
        solves either, but the normalised form keeps headroom for larger scans.
        2 次項を作る前に座標を [-1, 1] へ正規化する。1024 px 軸では生ピクセル
        座標の設計行列の条件数が全格子で約 3.4e6、正規化後は約 4 になる。float64 の
        SVD はどちらでも解けるが、正規化しておく方が大きな走査に対して余裕がある。

        The fit degrades gracefully when the background pixels are degenerate,
        for example when they all lie on one row and leave the surface
        unconstrained along the other axis. `numpy.linalg.lstsq` returns a
        rank-deficient solution silently, so the rank is checked explicitly and
        the fit falls back from the quadratic to a plane and then to the mean
        background level.
        背景画素の配置が退化している場合（例: 全点が 1 行に載り、他軸方向で
        曲面が拘束されない場合）は段階的に劣化させる。`numpy.linalg.lstsq` は
        ランク落ちでも黙って解を返すため、ランクを明示的に検査し、2 次 → 平面
        → 背景の平均レベル、の順にフォールバックする。
        """
        h, w = image.shape
        y_grid, x_grid = np.mgrid[0:h, 0:w]
        # Normalise so that the x^2, y^2 and x*y columns stay O(1); see Notes.
        x_n = x_grid / max(w - 1, 1) * 2.0 - 1.0
        y_n = y_grid / max(h - 1, 1) * 2.0 - 1.0
        ones = np.ones_like(x_n)

        z = image[valid_mask]
        for terms in (
            (x_n * x_n, y_n * y_n, x_n * y_n, x_n, y_n, ones),
            (x_n, y_n, ones),
        ):
            design = np.column_stack([t[valid_mask] for t in terms])
            coef, _residuals, rank, _singular = np.linalg.lstsq(design, z, rcond=None)
            if rank == design.shape[1]:
                return sum(c * t for c, t in zip(coef, terms))
        return np.full(image.shape, float(np.mean(z)), dtype=np.float64)

    @staticmethod
    def _bg_calibrate(original: np.ndarray, bg_sm: np.ndarray) -> np.ndarray:
        """
        Subtract the smooth background surface from the original image.
        平滑背景面を元画像から減算する。

        Parameters
        ----------
        original
            Original AFM image.
            元の AFM 画像。
        bg_sm
            Smoothed background estimated by `_bg_generate`.
            `_bg_generate` で推定した平滑背景。

        Returns
        -------
        np.ndarray
            Background-calibrated height image.
            背景補正後の高さ画像。

        Notes
        -----
        The output shape is smaller than input by one pixel in each axis
        because it is aligned with the intermediate background map shape.
        出力形状が各軸で1ピクセル小さくなるのは、
        中間背景マップの形状に合わせているためである。
        """
        height_bgcalib = original[1:, 1:] - bg_sm
        return height_bgcalib
