# Docstring Templates

Worked examples for the tiered bilingual docstring policy defined in
`AGENTS.md` §3. These templates illustrate the policy; the rules themselves
live in `AGENTS.md` and take precedence if the two ever disagree.

## Function docstring

```python
def detect_kinks(skeleton: np.ndarray, angle_threshold_deg: float) -> list[tuple[int, int]]:
    """
    Detect kink points along a skeletonized fiber trace.
    細線化された繊維トレース上のキンク点を検出する。

    Parameters
    ----------
    skeleton
        Binary skeleton image of the fiber. Nonzero pixels mark the centerline.
        繊維の二値化スケルトン画像。非ゼロ画素が繊維中心線を表す。
    angle_threshold_deg
        Interior-angle threshold (degrees). A three-point bend with an interior
        angle below this value is flagged as a kink.
        3 点折れ線の内角がこの値 (度) 未満のとき、その点をキンクとして検出する。

    Returns
    -------
    list of tuple
        Detected kink coordinates as ``(row, col)`` pairs.
        検出されたキンク点の (行, 列) 座標のリスト。

    Raises
    ------
    ValueError
        If `skeleton` is not a 2D array.

    Notes
    -----
    The interior angle is computed from a windowed three-point sampling along
    the skeleton, not from global curvature fitting.
    内角はスケルトンに沿ったウィンドウ 3 点サンプリングから計算され、
    大域的な曲率フィッティングは行わない。
    """
```

## Class docstring

```python
class FiberTracker:
    """
    Trace individual nanofibers from an AFM height image.
    AFM 高さ画像から個々のナノファイバーをトレースするクラス。

    Attributes
    ----------
    min_length_px
        Minimum trace length in pixels required to retain a fiber candidate.
        候補繊維として保持する最小トレース長 (px)。
    branch_length
        Maximum branch length in pixels explored during skeleton walking.
        スケルトン追跡時に探索する最大分岐長 (px)。
    """
```

## Module-level docstring

```python
"""
Background calibration for Shimadzu SPM-9600 AFM images.
島津 SPM-9600 AFM 画像のバックグラウンド補正モジュール。

Removes line-by-line baseline drift introduced by the scanner while preserving
nanofiber features above the noise floor.
スキャナ由来の行ごとのベースラインドリフトを除去しつつ、
ノイズフロアより上のナノファイバー構造を保持する。
"""
```

## Private function docstring — short helper

Summary only, bilingual:

```python
def _interior_angle_deg(p0: tuple, p1: tuple, p2: tuple) -> float:
    """
    Return the interior angle (degrees) at p1 formed by p0–p1–p2.
    p0–p1–p2 で構成される折れ線の p1 における内角 (度) を返す。

    Used by `detect_kinks` for the windowed three-point bend test.
    """
```

## Private function docstring — with algorithm rationale

Bilingual on the summary and on the explanatory body; routine parameter notes
English only:

```python
def _remove_line_drift(image: np.ndarray, order: int = 1) -> np.ndarray:
    """
    Subtract a per-row polynomial baseline from an AFM height image.
    AFM 高さ画像から、行ごとの多項式ベースラインを差し引く。

    Shimadzu SPM-9600 scans introduce a slow drift along the fast-scan axis
    that is uncorrelated between rows. Fitting and subtracting a low-order
    polynomial per row removes this drift without flattening nanofiber
    features, because fibers are narrow compared to the row length.
    島津 SPM-9600 のスキャンでは高速走査軸方向に行間で無相関な緩やかなドリフトが
    生じる。行ごとに低次多項式をフィットして差し引くことで、行長に比べて細い
    ナノファイバー構造を潰さずにドリフトのみを除去できる。

    Parameters
    ----------
    image
        2D height map in nanometers.
    order
        Polynomial order for the per-row fit. Order 1 is the default and is
        usually sufficient; higher orders risk fitting the fiber itself.
        行ごとの多項式の次数。通常は 1 で十分。高次にすると繊維本体まで
        フィットしてしまう恐れがある。
    """
```
