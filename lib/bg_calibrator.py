"""
Background calibration utilities for line-scan AFM height images.
ラインスキャン AFM 高さ画像に対する背景補正ユーティリティ。

This module estimates line-to-line height differences, separates candidate
fiber regions from background, reconstructs a smooth background surface, and
subtracts it from the original image.
このモジュールは、ライン間の高さ差を推定し、繊維候補領域を背景から分離し、
平滑な背景面を再構成して元画像から減算する処理を提供する。

The methods were developed on Shimadzu SPM-9600 scans, and the module was
historically named ``bg_calibrator_shimadzu``. The algorithms are general
line-scan AFM background corrections and are also used on data from other
instruments (e.g. Bruker NanoScope text exports), so the module and class
were renamed to instrument-neutral names. The historical import path and
class name remain available through the ``bg_calibrator_shimadzu`` shim.
本手法は島津 SPM-9600 のスキャンを対象に開発され、モジュール名も歴史的に
``bg_calibrator_shimadzu`` だった。アルゴリズム自体はラインスキャン AFM
一般の背景補正であり、他装置（例: Bruker NanoScope のテキストエクスポート）
のデータにも使用されるため、モジュール名・クラス名を装置非依存の名称へ
改めた。従来の import パスとクラス名は ``bg_calibrator_shimadzu`` シム
経由で引き続き利用できる。
"""

import numpy as np
import cv2
from scipy import interpolate, signal
from scipy.ndimage import distance_transform_edt

from .processed_image import ProcessedImage

# Background-estimation methods, in the spelling written to `_param.json`.
# 背景推定方式の一覧。`_param.json` へ書き出される綴りで保持する。
BG_METHOD_NAMES = ("trendfill", "tophat", "spline1d", "spline2d")

# Retired spellings mapped to their current name. Parameter files written
# before the rename record ``"inpaint"``, and re-running an old analysis must
# keep working, so the value is translated on load rather than rejected. The
# method was renamed because it no longer inpaints: the mask is filled by a
# second-order trend subtraction plus nearest-background propagation.
# 廃止された綴りから現行名への対応表。改名前に書かれたパラメータファイルは
# ``"inpaint"`` を記録しており、過去の解析を再実行できる必要があるため、値は
# 拒否せず読み込み時に変換する。改名の理由は、この方式がもはや inpaint を
# 行わないためである（実体は 2 次トレンド減算＋最近傍背景の伝播）。
BG_METHOD_ALIASES = {"inpaint": "trendfill"}


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
    """

    def __init__(self, threshold_factor=3, fiber_detect_factor=10, noise_detect_factor=2,
                 savgol_window=51, savgol_polyorder=2, apply_median=True,
                 mask_dilation=3,
                 min_mask_component_area=10, bg_method='trendfill', tophat_se_size=25,
                 spline2d_degree=2, spline2d_subsample=4, spline2d_smoothing=None,
                 spline1d_axis='y', spline1d_degree=2) -> None:
        """
        Initialize background calibration parameters.
        背景補正の各種パラメータを初期化する。

        Parameters
        ----------
        threshold_factor : float, optional
            Sigma multiplier used when separating background-like differences.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline2d'``.
            背景らしい差分を分離する際に使うシグマ倍率。
            ``bg_method`` が ``'trendfill'`` または ``'spline2d'`` のときに
            使用される。
        fiber_detect_factor : int, optional
            Maximum inner-gap length for the [1, 0, -1] fiber pattern.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline2d'``.
            [1, 0, -1] の繊維パターンで許容する内側ギャップ長の最大値。
            ``bg_method`` が ``'trendfill'`` または ``'spline2d'`` のときに
            使用される。
        noise_detect_factor : int, optional
            Minimum span for the [1, -1] pattern to avoid tiny noise segments.
            Used when ``bg_method`` is ``'trendfill'`` or ``'spline2d'``.
            微小ノイズを避けるための [1, -1] パターン最小スパン。
            ``bg_method`` が ``'trendfill'`` または ``'spline2d'`` のときに
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
            background pool. Default is 3. Set to 0 to disable dilation
            (reproduces the original behavior). Used when ``bg_method``
            is ``'trendfill'`` or ``'spline2d'``.
            ファイバーマスクを膨張させるピクセル数。
            `_extract_fiber` で検出しきれないファイバー端ピクセルが背景推定に
            混入すると、補間・平滑化でファイバー周辺の背景推定値が過大になり、
            減算後に過剰減算（ファイバー両脇のえぐれ）が生じる。
            値を大きくするほど周辺の背景点も除外される。
            デフォルトは 3。0 を指定するとdilationなし（元の動作）。
            ``bg_method`` が ``'trendfill'`` または ``'spline2d'`` のときに
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
            to disable filtering (reproduces the previous behavior).
            Applied when `mask_dilation > 0` and ``bg_method`` is
            ``'trendfill'`` or ``'spline2d'``.
            Default is 10.
            dilation 前の生ファイバーマスクから残す 8 連結成分の最小面積
            （ピクセル単位）。`_extract_fiber` の `[1, -1]` リッジパターンが
            拾う 2〜10 px 程度の偽検出が、ノイズの多い画像や広視野画像で
            画面全体に散らばる。フィルタを掛けないと、これらは dilation で
            `(2 * mask_dilation + 1)^2` ピクセルに膨張し、bg_only にゴマ塩状の
            穴を作って背景補間を不安定化させる（`mask_dilation >= 3` で補正
            画像にタイル状・細胞状パターンとして現れる）。本物のファイバーは
            十分大きな連結成分を形成するため残る。1 を指定するとフィルタなし
            （従来動作と一致）。`mask_dilation > 0` かつ ``bg_method`` が
            ``'trendfill'`` または ``'spline2d'`` のときに適用される。
            デフォルトは 10。
        bg_method : {'trendfill', 'tophat', 'spline1d', 'spline2d'}, optional
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
            background upward). The name is historical: the mask used to be
            filled by OpenCV Navier-Stokes inpainting, which could not
            reproduce the background slope across a hole (see
            ``_bg_generate``). It is kept because ``bg_method`` values are
            serialized verbatim into ``<input_stem>_param.json``.

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
            etc.) are ignored. Empirically faster and produces more uniform
            background subtraction than ``'trendfill'`` for fiber-on-substrate
            AFM images.

            ``'spline2d'``: tensor-product bivariate B-spline fitted to
            background-candidate pixels via
            ``scipy.interpolate.SmoothBivariateSpline``. Conceptually the
            2D extension of the legacy ``pandas`` 1D spline interpolation
            (same polynomial degree by default), but solved as a 2D
            problem rather than row-by-row. Unlike ``'trendfill'``, the
            global formulation makes the fit insensitive to local
            mask-boundary biases, so fiber shoulders that escape detection
            do not propagate into the background estimate as strongly.
            Configurable via ``spline2d_degree``, ``spline2d_subsample``
            and ``spline2d_smoothing``. Requires the trendfill-style fiber
            mask (computed via ``threshold_factor`` etc.) to identify
            background-candidate pixels.

            ``'spline1d'``: per-line 1D spline interpolation of the
            background-candidate pixels along a single axis, the direct
            revival of the legacy ``pandas`` row/column spline. The
            ``spline1d_axis`` option selects which way the stripe noise
            runs. With ``spline1d_axis='y'`` (default) each column is
            interpolated independently down the image; combined with the
            Savitzky-Golay step this evens out *horizontal* stripes, i.e.
            line-to-line offsets where each scan line is shifted up or down
            (the common AFM geometry when the fast-scan axis lies along the
            image rows). ``spline1d_axis='x'`` interpolates each row across
            the image instead and targets *vertical* stripes. For such
            stripe/line noise this per-line approach is often more effective
            than the globally-coupled ``'spline2d'`` fit. Uses the same
            trendfill-style fiber mask (with ``mask_dilation`` and
            ``min_mask_component_area``) to choose background-candidate
            pixels, and the same ``pandas`` spline of order
            ``spline1d_degree``, applied to a detrended copy. Beyond the
            first/last background pixel of a line there is nothing to
            interpolate between, so those runs are filled from the nearest
            background pixel in 2D rather than extrapolated line by line;
            a single-line extrapolation there stripes the image edge,
            whether it degenerates to the constant padding that originally
            motivated replacing this method with ``'trendfill'`` or follows
            the fitted spline.
            The background is then Savitzky-Golay smoothed and subtracted in
            full (no exact restore of background-candidate pixels),
            reproducing the legacy behavior that performs well on
            line-noise-dominated scans. Configurable via ``spline1d_axis``
            and ``spline1d_degree``.

            背景推定方式の選択。

            ``'trendfill'`` (デフォルト): 2段構えの方式。勾配ヒストグラムの
            閾値とパターンマッチでファイバー状リッジを検出してマスクし、
            2 次のトレンド曲面をフィットして減算し、マスク領域を最近傍の
            背景画素の値で埋め、平滑化してからトレンドを復元する。
            ``threshold_factor``, ``fiber_detect_factor``,
            ``noise_detect_factor``, ``mask_dilation``,
            ``min_mask_component_area`` で挙動を制御する。リッジ検出の
            取りこぼし（ファイバーの肩がマスクを抜けて境界画素として残る現象）
            に弱く、背景推定値が上方にバイアスする傾向がある。名称は歴史的な
            もので、以前はマスク領域を OpenCV の Navier-Stokes 法 inpaint で
            埋めていたが、この方式は穴を跨ぐ背景の傾斜を再現できなかった
            (``_bg_generate`` 参照)。``bg_method`` の値は
            ``<input_stem>_param.json`` へそのまま保存されるため名称は維持する。

            ``'tophat'``: 直径 ``tophat_se_size`` の円形構造要素を用いる
            形態学的 opening。背景は opening 後の画像（収縮→膨張）そのもの。
            ``tophat_se_size`` より細い明るい構造は除去されて前景扱いに、
            それより太い構造は背景モデルに残る。opening は下側包絡線の
            推定量であるため、減算後の画像は中央値で再センタリングして
            基板レベルを 0 nm に揃え、補正後の高さが補間系方式と比較可能に
            なるようにする。ファイバーマスクを一切
            使わないため、リッジ検出系パラメータ (``threshold_factor`` 等)
            は無視される。ファイバー/基板型の AFM 画像では ``'trendfill'``
            より高速かつ背景補正の一様性が高い、というのが本リポジトリの
            実証ベンチマーク結果である。

            ``'spline2d'``: ``scipy.interpolate.SmoothBivariateSpline`` で
            背景候補画素にフィットするテンソル積二変数 B-スプライン。概念的
            には従来 ``pandas`` の 1D スプライン補間の 2D 拡張 (デフォルト
            次数も同じ) だが、行毎ではなく 2D 問題として解く。``'trendfill'``
            と違い、大局的なフィットなのでマスク境界の局所バイアスに鈍感で、
            ファイバーの肩がマスクをすり抜けても背景推定への影響は小さい。
            ``spline2d_degree``, ``spline2d_subsample``,
            ``spline2d_smoothing`` で挙動を制御する。背景候補画素を識別する
            ために trendfill と同じファイバーマスク (``threshold_factor`` 等
            で計算) を必要とする。

            ``'spline1d'``: 背景候補画素を1軸に沿って行/列ごとに 1D スプライン
            補間する方式で、従来 ``pandas`` の行/列スプラインの正統な復活版。
            ``spline1d_axis`` で除去対象の縞の向きを選ぶ。``'y'`` (デフォルト)
            は各列を画像の縦方向に独立補間し、後段の Savitzky-Golay と併せて
            *横縞* (各走査ラインが上下にずれるライン間オフセット。画像の行方向
            が高速走査軸のときに生じる一般的な AFM 形状) を均す。``'x'`` は
            代わりに各行を横方向に補間し *縦縞* を対象とする。こうした縞/ライン
            ノイズに対しては、本方式は大局結合する ``'spline2d'`` より有効な
            ことが多い。背景候補画素の選択には trendfill と同じファイバーマスク
            (``mask_dilation``, ``min_mask_component_area`` 込み) を使い、
            補間にはデトレンドした写しへ order ``spline1d_degree`` の
            ``pandas`` スプラインを適用する。各ラインの最初/最後の背景画素
            より外側は補間する材料が無いため、ライン単位で外挿するのではなく
            2 次元の最近傍背景画素から埋める。ここでライン単独の外挿を行うと
            画像端に縞が出る。本方式が当初 ``'trendfill'`` へ置き換えられた
            理由である定数埋めに縮退した場合でも、フィットしたスプラインに
            従った場合でも同様である。その後 Savitzky-Golay で
            平滑化し、背景候補画素を厳密復元せずそのまま全面減算する (従来
            挙動の再現)。ラインノイズ主体のスキャンで良好な結果を出す。
            ``spline1d_axis`` と ``spline1d_degree`` で挙動を制御する。

        tophat_se_size : int, optional
            Diameter (in pixels) of the circular structuring element used
            when ``bg_method='tophat'``. Should be larger than the widest
            fiber in the image (rule of thumb: 2-3x the typical fiber
            width). Too small leaves fibers in the background; too large
            also flattens the broader substrate features the background
            should preserve. Must be odd; even values are silently
            incremented by 1. Default is 25.
            ``bg_method='tophat'`` のときに使う円形構造要素の直径 (px)。
            画像中の最も太いファイバーより大きく取る (目安: 典型ファイバー幅の
            2〜3 倍)。小さすぎるとファイバーが背景に残り、大きすぎると本来
            背景として残すべき基板の局所構造も削られる。奇数のみ有効で、
            偶数を渡した場合は黙って +1 される。デフォルトは 25。
        spline2d_degree : int, optional
            Polynomial degree of the tensor-product B-spline used when
            ``bg_method='spline2d'``. Same degree is used along both axes
            (``kx = ky = spline2d_degree``). The legacy 1D ``pandas``
            spline used order 2, so 2 is the default here for the closest
            match. Common practical range is 1 (bilinear) to 3 (bicubic);
            values >= 4 are accepted by SciPy but rarely useful for AFM
            backgrounds. Must be in [1, 5].
            ``bg_method='spline2d'`` のときのテンソル積 B-スプラインの多項式
            次数。両軸で同じ次数を使う (``kx = ky = spline2d_degree``)。
            従来の 1D ``pandas`` スプラインが次数 2 を使っていたため、最も
            近い挙動になるよう本実装でも 2 をデフォルトとする。実用範囲は
            1 (双線形) 〜 3 (双立方)。SciPy 側は 4, 5 も受け付けるが AFM 背景
            では恩恵が少ない。[1, 5] の範囲必須。
        spline2d_subsample : int, optional
            Pixel subsampling factor used when fitting in
            ``bg_method='spline2d'``. The fit uses every
            ``spline2d_subsample``-th pixel along each axis. The spline is
            intrinsically smooth so subsampling has negligible quality
            impact; default 4 is a good speed-quality trade-off. Set to 1
            to use every pixel (slower, no quality gain). Must be a
            positive integer.
            ``bg_method='spline2d'`` のフィット時に用いる画素サブサンプリン
            グ係数。各軸 ``spline2d_subsample`` 画素おきに使う。スプライン
            自体が滑らかなため結果品質への影響はほぼなく、デフォルト 4 で
            速度と品質のバランスが良い。1 で全画素使用 (遅く、品質向上なし)。
            正の整数のみ。
        spline2d_smoothing : float or None, optional
            Smoothing factor ``s`` passed to
            ``scipy.interpolate.SmoothBivariateSpline`` when
            ``bg_method='spline2d'``. Controls the trade-off between
            following the background-candidate points (small ``s``) and a
            smoother surface (large ``s``). The default ``None`` uses
            SciPy's own default (``s = m``, the number of fit points). The
            fitted surface is subtracted in full (see ``_call_spline2d``),
            so ``s`` governs the smoothness of the whole background
            estimate, at fiber and substrate positions alike; the SciPy
            default gives a smooth, well-conditioned surface. Do not set
            this to ``0`` for full-resolution AFM scans:
            interpolating tens of thousands of scattered points is
            ill-conditioned and extremely slow. Pass a positive number only
            to deliberately smooth the under-fiber surface more (or less)
            than the default. Must be ``None`` or a non-negative number.
            ``bg_method='spline2d'`` のとき
            ``scipy.interpolate.SmoothBivariateSpline`` に渡す平滑化係数
            ``s``。背景候補点への追従 (``s`` 小) と曲面の滑らかさ (``s`` 大)
            のトレードオフを決める。デフォルト ``None`` は SciPy 既定
            (``s = m``、フィット点数) を使う。フィット済み曲面は全面減算
            されるため (``_call_spline2d`` 参照)、``s`` は繊維位置・基板位置を
            問わず背景推定全体の滑らかさを左右する。既定値でも滑らかで
            良条件の曲面が得られる。
            全解像度の AFM 画像では ``0`` を指定してはいけない。数万の散布点を
            補間するのは悪条件で極端に遅い。既定より強く (または弱く) 平滑化
            したい場合のみ正の数を渡す。``None`` または非負の数値のみ。
        spline1d_axis : {'y', 'x'}, optional
            Stripe orientation to remove when ``bg_method='spline1d'``,
            expressed as the interpolation axis. ``'y'`` (default)
            interpolates each column down the image and, with the
            subsequent Savitzky-Golay step, evens out *horizontal* stripes
            -- line-to-line offsets where each scan line is shifted up or
            down (the usual AFM geometry when the image rows are the
            fast-scan axis). ``'x'`` interpolates each row across the image
            instead and targets *vertical* stripes. Default ``'y'``.
            ``bg_method='spline1d'`` のとき除去する縞の向き (補間軸で表現)。
            ``'y'`` (デフォルト) は各列を画像の縦方向に補間し、後段の
            Savitzky-Golay と併せて *横縞* (各走査ラインが上下にずれる
            ライン間オフセット。画像の行方向が高速走査軸のときの一般的な AFM
            形状) を均す。``'x'`` は代わりに各行を横方向に補間し *縦縞* を
            対象とする。デフォルトは ``'y'``。
        spline1d_degree : int, optional
            Polynomial order of the per-line ``pandas`` spline used when
            ``bg_method='spline1d'``. Matches the legacy implementation's
            ``order=2`` by default. Practical range is 1-3; must be a
            positive integer. Lines with fewer valid points than the spline
            order fall back to linear (or nearest) interpolation
            automatically. Default is 2.
            ``bg_method='spline1d'`` のときの行/列ごと ``pandas`` スプライン
            の多項式 order。デフォルトは従来実装の ``order=2`` に一致。実用
            範囲は 1〜3 で正の整数のみ。スプライン order に満たない有効点数
            のラインは自動的に線形 (または最近傍) 補間にフォールバックする。
            デフォルトは 2。

        Raises
        ------
        ValueError
            If ``bg_method`` is not one of {'trendfill', 'tophat',
            'spline2d', 'spline1d'} nor the retired alias ``'inpaint'``, if
            ``tophat_se_size`` is not a positive
            integer, if ``spline2d_degree`` is not an integer in [1, 5], if
            ``spline2d_subsample`` is not a positive integer, if
            ``spline2d_smoothing`` is not ``None`` or a non-negative number,
            if ``spline1d_axis`` is not ``'y'`` or ``'x'``, or if
            ``spline1d_degree`` is not a positive integer.
            ``bg_method`` が {'trendfill', 'tophat', 'spline2d', 'spline1d'}
            でも廃止済みエイリアス ``'inpaint'`` でもない、
            ``tophat_se_size`` が正の整数でない、``spline2d_degree`` が
            [1, 5] の整数でない、``spline2d_subsample`` が正の整数でない、
            ``spline2d_smoothing`` が ``None`` でも非負の数値でもない、
            ``spline1d_axis`` が ``'y'`` でも ``'x'`` でもない、または
            ``spline1d_degree`` が正の整数でない場合。

        Notes
        -----
        Only parameters are stored here. Actual calibration runs in __call__.
        ここではパラメータのみ保持し、実際の補正処理は __call__ で実行する。
        """
        # Accept the retired spelling so a pre-rename `_param.json` still runs.
        # 改名前の `_param.json` がそのまま動くよう、旧綴りも受け付ける。
        bg_method = canonical_bg_method(bg_method)
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
        # SciPy SmoothBivariateSpline accepts only 1..5 for kx and ky.
        # SciPy の SmoothBivariateSpline は kx, ky を 1..5 の範囲でしか受け付けない
        if not isinstance(spline2d_degree, (int, np.integer)) \
                or spline2d_degree < 1 or spline2d_degree > 5:
            raise ValueError(
                f"spline2d_degree must be an int in [1, 5], got {spline2d_degree!r}"
            )
        if not isinstance(spline2d_subsample, (int, np.integer)) or spline2d_subsample < 1:
            raise ValueError(
                f"spline2d_subsample must be a positive int, got {spline2d_subsample!r}"
            )
        if spline2d_smoothing is not None and (
                not isinstance(spline2d_smoothing, (int, float, np.integer, np.floating))
                or isinstance(spline2d_smoothing, bool) or spline2d_smoothing < 0):
            # Reject bool explicitly because it satisfies isinstance(int).
            # bool は isinstance(int) を満たすが意味が変わるので個別に弾く
            raise ValueError(
                f"spline2d_smoothing must be None or a non-negative number, "
                f"got {spline2d_smoothing!r}"
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

        self.spline2d_degree = int(spline2d_degree)
        self.spline2d_subsample = int(spline2d_subsample)
        self.spline2d_smoothing = (
            None if spline2d_smoothing is None else float(spline2d_smoothing)
        )

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
        - ``'spline2d'``: the trendfill-style ridge-detection intermediates
          (``dif_x`` ... ``bg_only``) are computed since the spline needs
          the fiber mask to identify background-candidate pixels, plus
          ``bg_spline2d`` (raw 2D spline surface) and ``bg_sm`` (after
          Savitzky-Golay). ``bg_open`` is set to ``None``.
        - ``'spline1d'``: like ``'spline2d'``, the trendfill-style
          ridge-detection intermediates (``dif_x`` ... ``bg_only``) are
          computed for the fiber mask, plus ``bg_spline1d`` (the assembled
          background surface before smoothing: per-line interpolation, 2D
          nearest fill at the line ends, trend restored) and ``bg_sm``
          (after Savitzky-Golay). ``bg_open`` and ``bg_spline2d`` are set to
          ``None``.

        このメソッドは中間配列を段階的に保持する設計になっており、
        デバッグ時やパラメータ調整時に各段階を確認しやすい。``self`` に
        残る中間配列の集合は ``bg_method`` に依存する:

        - ``'trendfill'``: ``dif_x``, ``dif_y``, ``histx``, ``histy``,
          ``outx``, ``outy``, ``tri_difx``, ``tri_dify``,
          ``tri_difx_fill``, ``tri_dify_fill``, ``bg_only``, ``bg_sm``。
        - ``'tophat'``: ``bg_open`` (生の opening 結果) と ``bg_sm``
          (Savitzky-Golay 後) のみ。リッジ検出系の中間配列は計算しないため
          ``None`` を設定する。
        - ``'spline2d'``: スプラインが背景候補画素を識別するためにファイバー
          マスクを必要とするので trendfill と同じリッジ検出系中間配列
          (``dif_x`` 〜 ``bg_only``) を計算し、加えて ``bg_spline2d``
          (生の 2D スプライン曲面) と ``bg_sm`` (Savitzky-Golay 後) を保持。
          ``bg_open`` は ``None``。
        - ``'spline1d'``: ``'spline2d'`` と同様、ファイバーマスクのため
          trendfill と同じリッジ検出系中間配列 (``dif_x`` 〜 ``bg_only``) を
          計算し、加えて ``bg_spline1d`` (平滑化前の背景曲面。行/列補間 +
          ライン端の 2 次元最近傍充填 + トレンド復元まで済んだもの) と
          ``bg_sm`` (Savitzky-Golay 後) を保持。``bg_open`` と
          ``bg_spline2d`` は ``None``。
        """
        # Fail loudly at the stage boundary instead of deep inside the method.
        if image.original_image is None:
            raise ValueError(
                "BGCalibrator requires image.original_image; "
                "construct ProcessedImage with the raw AFM height array."
            )

        if self.bg_method == 'tophat':
            self._call_tophat(image)
        elif self.bg_method == 'spline2d':
            self._call_spline2d(image)
        elif self.bg_method == 'spline1d':
            self._call_spline1d(image)
        else:
            self._call_trendfill(image)

    def _detect_fiber_mask(self, original: np.ndarray) -> None:
        """
        Run trendfill-style ridge detection up to the fiber mask intermediates.
        trendfill 系のリッジ検出をファイバーマスク中間配列まで実行する。

        Shared prelude of `_call_trendfill`, `_call_spline2d`, and
        `_call_spline1d`: all three need the same gradient-histogram fiber
        mask before they diverge on how they fill the background. The
        intermediates ``dif_x`` ... ``tri_difx_fill``/``tri_dify_fill`` are
        stored on ``self`` exactly as before, so the three paths cannot drift
        apart and every consumed ``bg_only`` is identical to the legacy code.
        `_call_trendfill` / `_call_spline2d` / `_call_spline1d` で共通の前段。
        3 方式とも背景の埋め方が分かれる前に同じ勾配ヒストグラム由来の
        ファイバーマスクを必要とする。中間配列 ``dif_x`` 〜
        ``tri_difx_fill``/``tri_dify_fill`` は従来どおり ``self`` に保持する。
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
        self.bg_spline2d = None
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
        Output shape matches the legacy `_bg_calibrate` convention
        (`original.shape - (1, 1)`) so that downstream stages (Segmenter
        etc.) see the same array shape regardless of `bg_method`.
        Ridge-detection intermediates (``dif_x`` etc.) are set to ``None``
        because they are not computed by this method.
        出力形状はレガシー `_bg_calibrate` と同じく ``original.shape - (1, 1)``
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
        self.bg_spline2d = None
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
        # its minimum from a clipped neighborhood that dilation cannot restore.
        # On a 0.34 nm/px ramp with a 25-px element that leaves a band about
        # 4 nm high down the uphill edge - far above the 0.3 nm binarization
        # threshold, so the scan border was segmented as a fiber. Detrending
        # first removes the slope the border effect feeds on.
        # トレンドを除いた写しに opening をかけ、後でトレンドを戻す。理由は
        # trendfill 経路と同じで、生の走査は大きな試料傾斜を伴うためである。
        # opening は画像内部では平面を再現するが、構造要素の半径以内の境界域
        # では再現しない。そこでは収縮が切り詰められた近傍から最小値を取り、
        # 膨張が復元できないからである。0.34 nm/px の傾斜と直径 25 px の要素
        # では、上り側の端に高さ約 4 nm の帯が残る。二値化しきい値 0.3 nm を
        # 大きく超えるため、走査端が繊維として抽出されていた。先にデトレンド
        # することで、この境界効果が餌にする傾斜そのものを取り除く。
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
        # legacy output shape produced by `_bg_calibrate`.
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

    def _call_spline2d(self, image: ProcessedImage) -> None:
        """
        Run the 2D tensor-product B-spline background fit.
        テンソル積二変数 B-スプラインによる背景フィットを実行する。

        Notes
        -----
        This is the conceptual 2D extension of the legacy ``pandas`` 1D
        spline interpolation. The legacy pipeline computed a fiber mask
        from gradient histograms (the trendfill pipeline's
        ``_difXY`` ... ``_extract_fiber`` ... ``_bg_generate`` chain),
        marked fiber pixels as NaN, and called pandas' 1D spline
        interpolation row-by-row. Here we use the same fiber mask but
        fit a 2D B-spline globally to the background-candidate pixels
        with ``scipy.interpolate.SmoothBivariateSpline``.

        Compared to ``'trendfill'``: same mask, different filler.

        Implementation details:

        * ``SmoothBivariateSpline`` refuses duplicate (y, x) coordinates,
          so we work on a regular ``spline2d_subsample`` grid which is
          guaranteed unique.
        * The spline is fit on the subsampled background-candidate points
          and then evaluated densely on the full grid via the
          ``(y_full, x_full)`` rectangular-grid form
          ``spl(np.arange(H), np.arange(W))``, which uses the fast tensor
          form internally. ``spline2d_smoothing`` sets the spline ``s``.
        * The fitted surface is subtracted in full, at fiber and substrate
          positions alike, exactly like the other background methods. The
          calibrated substrate therefore retains its measurement noise, as
          it must: an earlier revision restored background-candidate pixels
          exactly from the original image, which forced the substrate to
          exactly zero, erased the noise from the data, and clipped the
          shoulders of fibers the mask misclassified as background.
        * No Savitzky-Golay smoothing is applied: the spline surface is
          already smooth by construction, so the row-wise smoothing pass
          used by the other methods would add nothing. Output is cropped
          to ``(H-1, W-1)`` to match the other pipelines.

        これは従来の ``pandas`` 1D スプライン補間の概念的な 2D 拡張。従来
        パイプラインは勾配ヒストグラムからファイバーマスクを計算し
        (trendfill と同じ ``_difXY`` 〜 ``_extract_fiber`` 〜 ``_bg_generate``
        の流れ)、ファイバー画素を NaN にして pandas の 1D スプライン補間を
        行毎に呼んでいた。本メソッドは同じファイバーマスクを使うが、補間は
        ``scipy.interpolate.SmoothBivariateSpline`` で背景候補画素に対して
        2D B-スプラインを大局的にフィットする。

        ``'trendfill'`` との比較: 同じマスク、別の埋め方。

        実装上の注意:

        * ``SmoothBivariateSpline`` は重複する (y, x) 座標を受け付けない
          ので、``spline2d_subsample`` 間隔の規則格子で作業する (重複なし
          が保証される)。
        * サブサンプル後の背景候補点でスプラインをフィットし、評価は
          ``spl(np.arange(H), np.arange(W))`` の矩形格子形式で全グリッド
          上に行う (内部的に高速テンソル形式が使われる)。
          ``spline2d_smoothing`` がスプラインの ``s`` を決める。
        * フィット済み曲面は、他の背景方式と同様に繊維位置・基板位置を
          問わず全面で減算する。したがって補正後の基板には測定ノイズが
          そのまま残る（残るべきものである）。旧版は背景候補画素を原画像値で
          厳密復元していたが、それは基板を厳密にゼロへ固定してデータから
          ノイズを消去し、マスクが背景と誤分類した繊維の肩を切り落として
          いた。
        * Savitzky-Golay 平滑化はかけない。スプライン曲面は構成上すでに
          滑らかで、他方式の行方向平滑化を重ねても意味がないためである。
          出力は他パイプラインと揃えて ``(H-1, W-1)`` にクロップする。
        """
        original = image.original_image

        # Reuse the trendfill-style ridge detection and fiber mask. This is
        # the same code path as `_call_trendfill` up through `_bg_generate`,
        # because spline2d is conceptually "trendfill mask + different
        # interpolator". We need ``bg_only`` (image with NaN at masked
        # positions) and the implied background-candidate mask.
        # trendfill と同じリッジ検出とファイバーマスク計算を流用する。
        # spline2d は概念的に「trendfill と同じマスク + 別の埋め方」なので、
        # `_bg_generate` までは `_call_trendfill` と同じ処理が必要になる。
        # ``bg_only`` (マスク位置が NaN になった画像) と背景候補マスクを得る。
        self._detect_fiber_mask(original)
        # `_bg_generate` returns ``bg_only`` (NaN at fiber, shape (H-1, W-1))
        # and a savgol-smoothed bg as the second value. We use only
        # ``bg_only`` here; the background surface is built from the spline
        # fit below instead.
        # `_bg_generate` は (H-1, W-1) 形状の ``bg_only`` (ファイバー位置 NaN)
        # と平滑化済み bg を返す。ここでは ``bg_only`` だけ使い、背景曲面は
        # 下のスプライン fit から構築する。
        self.bg_only, _ = self._bg_generate(original, self.tri_difx_fill, self.tri_dify_fill)
        # ``bg_only`` has shape (H-1, W-1). Build the working grid on
        # that shape for shape consistency with the legacy code path.
        # ``bg_only`` は (H-1, W-1) 形状。レガシーパスとの形状整合性のため
        # 作業用グリッドもその形状で構築する。
        Hm, Wm = self.bg_only.shape
        fiber_mask_dense = np.isnan(self.bg_only)

        # Mark intermediates from the other path as unused.
        # 他方式の中間配列は使わないことを明示。
        self.bg_open = None
        self.bg_spline1d = None

        # Build the regular-grid subsampling of background-candidate
        # pixels. ``SmoothBivariateSpline`` requires unique coordinates,
        # which is guaranteed when we sample every ``s``-th pixel on a
        # regular grid.
        # 背景候補画素の規則格子サブサンプリングを構築する。
        # ``SmoothBivariateSpline`` は一意座標を要求するが、規則格子上で
        # ``s`` 画素おきに取れば自動的に保証される。
        step = self.spline2d_subsample
        deg = self.spline2d_degree
        ys_sub = np.arange(0, Hm, step)
        xs_sub = np.arange(0, Wm, step)
        Yg, Xg = np.meshgrid(ys_sub, xs_sub, indexing='ij')
        # Keep only sub-grid points that fall on background-candidate pixels.
        # 背景候補画素に当たるサブ格子点のみ残す。
        valid_sub = ~fiber_mask_dense[Yg, Xg]
        y_fit = Yg[valid_sub].astype(np.float64)
        x_fit = Xg[valid_sub].astype(np.float64)
        v_fit = original[1:, 1:][Yg[valid_sub], Xg[valid_sub]].astype(np.float64)

        # SmoothBivariateSpline needs at least (kx+1) * (ky+1) points to
        # fit a degree-(kx, ky) spline. Guard against pathological inputs.
        # SmoothBivariateSpline は次数 (kx, ky) のスプラインに最低
        # (kx+1) * (ky+1) 点を要求する。病的な入力に備える。
        min_pts = (deg + 1) * (deg + 1)
        if len(v_fit) < min_pts:
            raise RuntimeError(
                f"spline2d: only {len(v_fit)} background pixels available "
                f"after subsampling, need at least {min_pts}. "
                f"Try reducing spline2d_subsample or spline2d_degree."
            )

        # Fit the tensor-product B-spline. ``kx``, ``ky`` are the polynomial
        # degrees along the row and column axes; we use the same value
        # along both to match the legacy 1D spline's behavior. ``s`` is the
        # smoothing factor from ``spline2d_smoothing``; ``None`` lets SciPy
        # use its default (``s`` = number of points). The surface is
        # subtracted in full below, so ``s`` governs the smoothness of the
        # whole background estimate, at fiber and substrate positions alike.
        # Do not force ``s=0`` on full-resolution scans: interpolating tens
        # of thousands of scattered points is ill-conditioned and extremely
        # slow.
        # テンソル積 B-スプラインをフィットする。``kx``, ``ky`` は行/列方向の
        # 多項式次数。レガシー 1D スプラインの挙動と揃えるため両軸同じ次数。
        # ``s`` は ``spline2d_smoothing`` の平滑化係数。``None`` なら SciPy 既定
        # (``s`` = 点数) を使う。下で曲面を全面減算するため、``s`` は繊維位置・
        # 基板位置を問わず背景推定全体の滑らかさを左右する。全解像度の画像で
        # ``s=0`` を強制してはいけない。数万散布点の補間は悪条件で極端に遅い。
        if self.spline2d_smoothing is None:
            spl = interpolate.SmoothBivariateSpline(y_fit, x_fit, v_fit, kx=deg, ky=deg)
        else:
            spl = interpolate.SmoothBivariateSpline(
                y_fit, x_fit, v_fit, kx=deg, ky=deg, s=self.spline2d_smoothing
            )

        # Evaluate the spline on the dense grid. The rectangular-grid call
        # ``spl(ys, xs)`` is much faster than the scattered-point call
        # ``spl.ev(yr, xr)`` because it uses tensor-product separation.
        # スプラインを密グリッド上で評価する。矩形格子形式 ``spl(ys, xs)``
        # はテンソル積分離が効くため、散布点形式 ``spl.ev(yr, xr)`` より
        # ずっと速い。
        bg_spline = spl(np.arange(Hm), np.arange(Wm))
        # The spline surface is subtracted in full, at fiber and background
        # positions alike. The background model must stay a *model*: replacing
        # it with the original values at background-candidate pixels (as an
        # earlier revision did) forces the substrate to exactly zero, which
        # deletes the measurement noise from the data, makes downstream
        # statistics on background pixels meaningless, and clips the shoulders
        # of any fiber the mask misclassified as background.
        # スプライン曲面は、繊維位置・背景位置を問わず全面で減算する。背景
        # モデルはあくまで「モデル」に留めるべきで、背景候補画素を原画像値で
        # 置き換える方式（旧版の挙動）は基板を厳密にゼロへ固定してしまい、
        # データから測定ノイズを消去し、背景画素に対する下流統計を無意味に
        # し、マスクが背景と誤分類した繊維の肩を切り落とす。
        self.bg_spline2d = bg_spline

        # No Savitzky-Golay smoothing here (see Notes): the fitted spline
        # surface is already smooth by construction, so the row-wise
        # Savitzky-Golay pass used by the other methods would add nothing.
        # ``bg_spline`` already has the (H-1, W-1) shape used by the other
        # pipelines.
        # ここでは Savitzky-Golay 平滑化をかけない (Notes 参照)。フィット済み
        # スプライン曲面は構成上すでに滑らかで、他方式の行方向 Savitzky-Golay
        # を重ねても意味がない。``bg_spline`` は既に他パイプラインと同じ
        # (H-1, W-1) 形状を持つ。
        self.bg_sm = bg_spline
        calibrated_image = original[1:, 1:] - self.bg_sm

        if self.apply_median:
            calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)

        image.calibrated_image = calibrated_image

    def _call_spline1d(self, image: ProcessedImage) -> None:
        """
        Run the per-line 1D spline background interpolation.
        行/列ごとの 1D スプライン背景補間を実行する。

        Notes
        -----
        This is the direct revival of the legacy ``pandas`` row/column
        spline background (see ``BG_Calibrator_shimadzuOld``), modernised
        in two ways:

        * The fiber mask reuses the trendfill pipeline's ridge detection
          *together with* ``mask_dilation`` and ``min_mask_component_area``
          (the legacy version had neither), so fiber-edge shoulders are
          excluded from the background pool exactly as in ``'trendfill'`` and
          ``'spline2d'``.
        * The image is detrended before the fill and the trend restored
          afterwards, as in ``'trendfill'``, so no filler has to reproduce
          the sample tilt.
        * The line ends are not extrapolated at all. Beyond the first/last
          valid sample of a line - a fiber touching the image edge along the
          interpolation axis - there is background data on one side only, so
          any 1D model of that run is fitted to that single line and its
          error is uncorrelated with the neighboring lines. The legacy
          ``pandas`` behavior there (constant padding, the documented reason
          the method was dropped in favour of ``'trendfill'``) is only one
          instance of the problem: the fitted spline's own extrapolation
          fails the same way, in smooth bands instead of thin streaks.
          These runs are therefore filled from the nearest background pixel
          in 2D, which draws on the neighboring lines.

        The stripe orientation is controlled by ``spline1d_axis``:
        ``'y'`` (default) interpolates each column down the image and, with
        the Savitzky-Golay step, evens out *horizontal* stripes (line-to-
        line up/down offsets); ``'x'`` interpolates each row across the
        image and targets *vertical* stripes instead.

        Like every background method, the estimated background is
        subtracted *in full*. Unlike ``'spline2d'``, this path follows the
        legacy behavior of Savitzky-Golay smoothing the interpolated
        background first (the per-line interpolation is not smooth by
        construction the way the 2D spline surface is). On
        line-noise-dominated scans this per-line approach is empirically
        the better-behaved choice; see the class docstring.

        これは従来 ``pandas`` の行/列スプライン背景
        (``BG_Calibrator_shimadzuOld`` 参照) の正統な復活版で、2 点を
        現代化している:

        * ファイバーマスクは trendfill のリッジ検出に加えて ``mask_dilation``
          と ``min_mask_component_area`` を併用する (旧版は両方なし)。
          これにより ``'trendfill'`` / ``'spline2d'`` と同様、ファイバー端の
          肩部が背景プールから除外される。
        * ``'trendfill'`` と同様、充填の前にデトレンドし後でトレンドを戻す。
          どの充填器も試料傾斜を再現する必要がなくなる。
        * ライン端は一切外挿しない。各ラインの最初/最後の有効サンプルより
          外側 (補間軸の端にファイバーがかかる場合) は片側にしか背景データが
          無いため、その区間を 1 次元でモデル化するとそのライン単独のフィット
          になり、誤差は隣接ラインと無相関になる。旧 ``pandas`` の挙動である
          定数埋め (本方式が ``'trendfill'`` へ置き換えられた既知の理由) は
          この問題の一例にすぎず、フィットしたスプライン自身の外挿も同じ形で
          破綻する。細いスジではなく滑らかな帯になるだけである。よってこの
          区間は 2 次元の最近傍背景画素から埋め、隣接ラインを参照させる。

        除去する縞の向きは ``spline1d_axis`` で制御する。``'y'`` (デフォルト)
        は各列を画像の縦方向に補間し、Savitzky-Golay と併せて *横縞* (各走査
        ラインが上下にずれるオフセット) を均す。``'x'`` は代わりに各行を横方向
        に補間し *縦縞* を対象とする。

        他の背景方式と同様、推定した背景は *そのまま全面* 減算する。
        ``'spline2d'`` と異なるのは、旧来挙動に従って補間背景を先に
        Savitzky-Golay 平滑化する点である（行/列ごとの補間は 2D スプライン
        曲面のように構成上滑らかにはならないため）。ラインノイズ主体の
        スキャンでは経験的にこの行/列方式の方が振る舞いが良い
        (クラス docstring 参照)。
        """
        original = image.original_image

        # Reuse the trendfill-style ridge detection and fiber mask, exactly as
        # `_call_spline2d` does. We only need ``bg_only`` (image with NaN at
        # masked positions, shape (H-1, W-1)); the smoothed bg returned by
        # `_bg_generate` is discarded because we re-fill with the 1D spline.
        # `_call_spline2d` と同じく trendfill のリッジ検出とファイバーマスクを
        # 流用する。必要なのは ``bg_only`` (マスク位置 NaN、(H-1, W-1) 形状)
        # のみで、`_bg_generate` が返す平滑化 bg は 1D スプラインで埋め直す
        # ため破棄する。
        self._detect_fiber_mask(original)
        self.bg_only, _ = self._bg_generate(original, self.tri_difx_fill, self.tri_dify_fill)

        # Mark intermediates from the other paths as unused.
        # 他方式の中間配列は使わないことを明示。
        self.bg_open = None
        self.bg_spline2d = None

        crop = original[1:, 1:]
        valid_mask = ~np.isnan(self.bg_only)

        # Detrend before filling and restore the trend afterwards, exactly as
        # `_bg_generate` does, so that neither filler has to reproduce the
        # sample tilt (0.23-0.34 nm/px on the bundled scans).
        # `_bg_generate` と同じく、充填の前にデトレンドし後でトレンドを戻す。
        # どちらの充填器も試料傾斜（同梱スキャンで 0.23〜0.34 nm/px）を
        # 再現しなくてよくなる。
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

        # Savitzky-Golay smoothing then full-frame subtraction, matching the
        # legacy pipeline (no exact restore of background-candidate pixels).
        # Savitzky-Golay 平滑化のあと全面減算する。旧パイプラインと同じく
        # 背景候補画素の厳密復元は行わない。
        self.bg_sm = signal.savgol_filter(bg_int, self.savgol_window, self.savgol_polyorder)
        calibrated_image = original[1:, 1:] - self.bg_sm

        if self.apply_median:
            calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)

        image.calibrated_image = calibrated_image

    @staticmethod
    def _spline1d_fill(bg_only: np.ndarray, axis: str = 'y', order: int = 2,
                       end_window: int = 31) -> np.ndarray:
        """
        Interpolate the masked positions inside each line's valid span.
        各ラインの有効範囲内にあるマスク位置を補間する。

        Parameters
        ----------
        bg_only : np.ndarray
            2D array with NaN at masked (fiber) positions. Pass a detrended
            image: the per-line fit then models only the residual.
            マスク (ファイバー) 位置が NaN の 2D 配列。デトレンド済み画像を
            渡すこと。行/列ごとのフィットが残差だけをモデル化すればよくなる。
        axis : {'y', 'x'}
            ``'y'`` interpolates each column along rows (axis 0);
            ``'x'`` interpolates each row along columns (axis 1).
            ``'y'`` は各列を行方向 (axis 0) に、``'x'`` は各行を列方向
            (axis 1) に補間する。
        order : int
            Spline order passed to ``pandas.Series.interpolate``.
            ``pandas.Series.interpolate`` に渡すスプライン order。
        end_window : int
            Number of a line's nearest valid samples averaged to set the level
            held across its end runs.
            ライン端の区間に保持する水準を決めるために平均する、そのラインの
            最近傍有効サンプルの数。

        Returns
        -------
        np.ndarray
            ``bg_only`` with the interior NaNs filled (float64). Positions
            beyond the first/last valid sample of their line stay NaN.
            内側の NaN を埋めた ``bg_only`` (float64)。各ラインの最初/最後の
            有効サンプルより外側の位置は NaN のまま残る。

        Notes
        -----
        Per line, NaNs are filled by the pandas spline of the given order,
        falling back to linear when there are too few valid points, and the
        result is then restricted to the span between the first and the last
        valid sample. Outside that span a line carries background data on one
        side only, so anything a 1D method puts there is an extrapolation
        fitted to that one line, and its error is uncorrelated between
        neighboring lines. Returning NaN lets the caller fill those runs from
        the neighboring lines instead, which is what keeps the estimate free
        of per-line stripes; see `_call_spline1d`.
        各ラインの NaN は指定 order の pandas スプライン (有効点が少ない場合は
        線形へフォールバック) で埋め、その結果を最初と最後の有効サンプルの間に
        限定する。この範囲の外側はラインの片側にしか背景データが無いため、
        1 次元手法が入れる値はそのライン単独で当てた外挿であり、誤差は隣接
        ラインと無相関になる。NaN を返すことで、その区間を隣接ラインから
        埋める判断を呼び出し側に委ねる。これが推定値をライン単位の縞から
        守っている (`_call_spline1d` 参照)。

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
        dif_x : np.ndarray
            Horizontal difference image.
            水平方向の差分画像。
        dif_y : np.ndarray
            Vertical difference image.
            垂直方向の差分画像。
        bin_n : int, optional
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
        outx: float,
        outy: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Separate differences into ternary categories using fitted thresholds.
        フィット結果のしきい値で差分を3値に分類する。

        Parameters
        ----------
        dif_x : np.ndarray
            Horizontal difference image.
            水平方向の差分画像。
        dif_y : np.ndarray
            Vertical difference image.
            垂直方向の差分画像。
        outx : lmfit.model.ModelResult
            Fit result for `dif_x` histogram.
            `dif_x` ヒストグラムのフィット結果。
        outy : lmfit.model.ModelResult
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
        tri_difx : np.ndarray
            Ternary difference map along row direction.
            行方向の3値差分マップ。
        tri_dify : np.ndarray
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
        for j in range(tri_difx.shape[0] - 1):
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
        for j in range(tri_dify.shape[1] - 1):
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
        original : np.ndarray
            Original AFM image.
            元の AFM 画像。
        tri_difx_fill : np.ndarray
            Filled mask obtained from X-direction pattern detection.
            X方向パターン検出で得られた塗りつぶしマスク。
        tri_dify_fill : np.ndarray
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
        raw AFM scans routinely carry a large sample tilt: on the bundled scans
        the least-squares plane drops 0.23-0.34 nm per pixel, so the background
        falls 7-9 nm across a single fiber hole while the fiber itself is only
        about 10 nm tall. Any fill that cannot reproduce that ramp leaves an
        error comparable to the signal.
        穴の充填は画像を *デトレンド* した写しの上で行う。背景候補画素に 2 次
        曲面を最小二乗フィットして減算し、最近傍の有効画素を伝播させて穴を
        埋め、Savitzky-Golay で平滑化してから曲面を足し戻す。精度の鍵はこの
        デトレンドにある。生の AFM 走査は大きな試料傾斜を伴うのが普通で、
        同梱スキャンでは最小二乗平面が 1 画素あたり 0.23〜0.34 nm 下がる。
        つまり繊維 1 本分の穴を横切る間に背景が 7〜9 nm 落ちる一方、繊維自身の
        高さは約 10 nm しかない。この傾斜を再現できない充填法は、信号と同程度
        の誤差を残すことになる。

        This replaces the previous OpenCV Navier-Stokes inpainting. That
        scheme is a boundary-propagation method intended for thin scratches:
        with `inpaintRadius=3` it extended each side of a hole inward as a
        flat plateau and met in a step discontinuity at the middle, measured
        at up to +/-4 nm across a 21-px hole. Because `savgol_polyorder <= 1`
        makes the Savitzky-Golay pass a plain moving average along X, that
        step was then averaged into the background estimate of every genuine
        background pixel within half a window of the hole, producing an
        antisymmetric halo (a trough on the uphill side, a ridge on the
        downhill side) that reached +0.76 nm - above the default
        `Segmenter.global_threshold` of 0.3 nm, so it binarized as a second
        fiber running parallel to the real one.
        これは従来の OpenCV Navier-Stokes inpainting を置き換えるものである。
        あの方式は細い傷の修復を想定した境界伝播法で、`inpaintRadius=3` では
        穴の左右それぞれの境界値を平坦に内側へ伸ばし、中央で段差になっていた
        （幅 21 px の穴で実測 ±4 nm）。`savgol_polyorder <= 1` のとき
        Savitzky-Golay は X 方向の単純移動平均そのものになるため、この段差が
        穴から窓半分以内にある本物の背景画素の推定値へ平均化されて漏れ出し、
        反対称のハロー（上り側に溝、下り側に尾根）を生んでいた。尾根は
        +0.76 nm に達し、`Segmenter.global_threshold` の既定値 0.3 nm を
        超えるため、実際の繊維に並走する 2 本目の繊維として二値化されていた。

        Nearest-valid propagation is enough once the image is detrended: with
        the trend removed the height difference across a hole is close to
        zero, so the choice of filler barely matters (measured maximum
        deviation from the chord across a 21-px hole: 0.24 nm for nearest
        versus 0.20 nm for inpainting, against 3.93 nm before detrending).
        Nearest-valid propagation also preserves the background-candidate
        pixels exactly, so no explicit restore step is needed.
        デトレンド後であれば最近傍伝播で十分である。トレンドを除くと穴を跨ぐ
        高さ差がほぼゼロになるため、充填法の選択はほとんど効かない（幅 21 px
        の穴で弦からの最大偏差は最近傍 0.24 nm、inpainting 0.20 nm。デトレンド
        前は 3.93 nm）。また最近傍伝播は背景候補画素をそのまま保存するので、
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
        # Skipped when `mask_dilation == 0` so the original behavior is
        # preserved bit-identically.
        # 理由: `_extract_fiber` の Pattern 2 (`[1, -1]`) は 2〜10 px 程度の
        # 偽検出を拾い、ノイズの多い画像や広視野画像では画面全体に密に
        # 散らばる。フィルタなしで dilation すると 1 つの偽検出が
        # `(2 * mask_dilation + 1)^2` ピクセルの穴に膨張し、bg_only に
        # ゴマ塩状の欠損を作って背景の充填を不安定化させる
        # （mask_dilation >= 3 でタイル状・細胞状パターンとして見える）。
        # 本物のファイバーは十分大きな 8 連結成分を形成するため残る。
        # `mask_dilation == 0` の場合は従来動作と完全一致させるためスキップ。
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
            # a flat zero background, which is what the previous inpainting path
            # also produced for a fully masked image.
            # 病的な入力: 全画素が繊維と判定され、フィットにも伝播にも使える
            # 背景情報が無い。平坦なゼロ背景へフォールバックする。従来の
            # inpainting 経路も全面マスク時は同じ結果を返していた。
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
        Second order rather than a plane because real scans are bowl-shaped as
        well as tilted: on the bundled Bruker scan 32 nm of curvature remains
        after the best-fit plane is removed. Fitting the quadratic reduced the
        residual fill error across a fiber hole from 0.68 nm (plane) to 0.24 nm.
        平面ではなく 2 次にするのは、実際の走査が傾いているだけでなく皿状に
        歪んでいるためである。同梱の Bruker 走査では最適平面を除去した後も
        32 nm のうねりが残る。2 次でフィットすると、繊維の穴を跨ぐ充填残差が
        0.68 nm（平面）から 0.24 nm へ減少した。

        Coordinates are normalised to [-1, 1] before the quadratic terms are
        formed. On a 1024-px axis the raw-pixel design matrix has a condition
        number near 3.6e6 against about 4 after normalisation; float64 SVD
        solves either (the two fitted surfaces agreed to 1.8e-10 nm), but the
        normalised form keeps headroom for larger scans.
        2 次項を作る前に座標を [-1, 1] へ正規化する。1024 px 軸では生ピクセル
        座標の設計行列の条件数が約 3.6e6、正規化後は約 4 になる。float64 の
        SVD はどちらでも解ける（両者のフィット曲面の差は 1.8e-10 nm）が、
        正規化しておく方が大きな走査に対して余裕がある。

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
        original : np.ndarray
            Original AFM image.
            元の AFM 画像。
        bg_sm : np.ndarray
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
