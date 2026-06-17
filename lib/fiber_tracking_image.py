"""
Fiber tracking container and worker helpers for the GUI04 fiber view.
GUI04 のファイバー表示・追跡用コンテナとワーカー補助関数。

This module loads arrays saved by GUI01_Image_Processer_Shimadzu and builds
Fiber objects for display, profile extraction, and speed-oriented processing.
GUI01_Image_Processer_Shimadzu が保存した配列を読み込み、表示・プロファイル抽出・
高速化処理に使う Fiber オブジェクトを構築する。

Notes
-----
`processed_image.py` owns the GUI01 analysis and save pipeline. This module
is only for GUI04 loading, display, and fiber tracking; it does not run BG
correction, binarization, or skeletonization.
`processed_image.py` は GUI01 の解析・保存パイプラインを担当する。本モジュールは
GUI04 の読み込み・表示・ファイバー追跡専用であり、BG 補正・二値化・細線化は行わない。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Union

import cv2
import numpy as np

from . import imp_tools
from .fiber import Fiber


def _build_fiber(
    label_image: np.ndarray,
    label: int,
    data_row,
    cal: np.ndarray,
    size_per_pixel: float,
    kink_set: set,
    dp_set: set,
    ep_set: set,
    kink_angle_map: dict,
    y_size_per_pixel: Optional[float] = None,
) -> Fiber:
    """
    Build one Fiber from a labeled skeleton component and feature lookups.
    ラベル付き骨格成分と特徴点テーブルから Fiber を 1 本構築する。

    Single implementation shared by the sequential and parallel paths
    (`_generate_fiber_instances` and `fibers_in_image_parallel`), so the two
    paths cannot drift apart and always produce identical fibers.
    逐次経路と並列経路（`_generate_fiber_instances` と
    `fibers_in_image_parallel`）が共有する唯一の実装。両経路の結果が
    乖離せず、常に同一の Fiber を生成する。

    Parameters
    ----------
    label_image
        Connected-component label image of the cleaned skeleton.
        整理済み骨格の連結成分ラベル画像。
    label
        Component label of the fiber to build.
        構築対象ファイバーの成分ラベル。
    data_row
        OpenCV component stats row ``(x, y, width, height, area)``.
        OpenCV 連結成分統計の行 ``(x, y, width, height, area)``。
    cal
        Calibrated height image sampled along the track.
        トラックに沿って高さを取得する補正済み画像。
    size_per_pixel
        Physical X (column) pixel size in nm/px used for path-length conversion.
        経路長変換に使う X（列）軸の物理ピクセルサイズ (nm/px)。
    kink_set
        ``(x, y)`` coordinate set of kink points.
        キンク点の ``(x, y)`` 座標集合。
    dp_set
        ``(x, y)`` coordinate set of decomposition points.
        分解点の ``(x, y)`` 座標集合。
    ep_set
        ``(x, y)`` coordinate set of end points.
        端点の ``(x, y)`` 座標集合。
    kink_angle_map
        Mapping from ``(x, y)`` kink coordinates to angles in radians.
        キンク座標 ``(x, y)`` からラジアン角度値への対応辞書。
    y_size_per_pixel
        Physical Y (row) pixel size in nm/px. ``None`` reuses
        ``size_per_pixel`` for an isotropic (square-pixel) scale.
        Y（行）軸の物理ピクセルサイズ (nm/px)。``None`` のときは
        ``size_per_pixel`` を流用し等方（正方ピクセル）スケールとする。

    Returns
    -------
    Fiber
        Constructed fiber for the given label.
        指定ラベルに対して構築された Fiber。
    """
    # `data_row` is OpenCV component stats: (x, y, width, height, area).
    x, y, w, h, _size = data_row
    target_image = np.where(label_image == label, 1, 0).astype(np.uint8)
    # Track skeleton pixels in order so we can treat the fiber as a 1D sequence.
    # 骨格ピクセルを順序付きで追跡し、ファイバーを1次元列として扱えるようにする。
    xtrack_prcimg, ytrack_prcimg = imp_tools.tracking(target_image)
    xtrack = xtrack_prcimg - x
    ytrack = ytrack_prcimg - y
    horizon = imp_tools.convert_track_to_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = cal[ytrack_prcimg, xtrack_prcimg]
    fiber_image = cal[y: y + h, x: x + w].copy()

    # Linear scan keeps index alignment with the xtrack/ytrack arrays, so all
    # feature indices come out in track order for downstream consistency.
    # 線形走査により xtrack/ytrack 配列とのインデックス対応を保つ。特徴点の
    # インデックスは後段処理の一貫性のため追跡順になる。
    kink_indices, decomposed_point_indices, ep_indices = [], [], []
    for i, (px, py) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
        if (px, py) in kink_set:
            kink_indices.append(i)
        if (px, py) in dp_set:
            decomposed_point_indices.append(i)
        if (px, py) in ep_set:
            ep_indices.append(i)

    # Translate each kink index back into a coordinate key to read its angle.
    # 各 kink インデックスを座標キーに変換し、辞書から角度を取得する。
    kink_angles = np.array([
        kink_angle_map[(int(xtrack_prcimg[i]), int(ytrack_prcimg[i]))]
        for i in kink_indices
        if (int(xtrack_prcimg[i]), int(ytrack_prcimg[i])) in kink_angle_map
    ])

    return Fiber(
        fiber_image, tuple(data_row), xtrack, ytrack, horizon, height,
        np.array(kink_indices), np.array(ep_indices),
        kink_angles, np.array(decomposed_point_indices),
    )


class FiberTrackingImage:
    """
    Store image data and tracking results for GUI04 fiber view.
    GUI04 のファイバー表示・追跡用データを保持するコンテナ。

    The GUI04 loader assigns arrays saved by GUI01 directly to this class. It
    does not execute BG correction, binarization, or skeletonization.
    GUI04 の読み込み処理が GUI01 で保存された配列をこのクラスへ直接代入する。
    BG 補正・二値化・細線化は行わない。

    Attributes
    ----------
    name
        Image identifier.
        画像識別名。
    original_image
        Original AFM image array.
        元の AFM 画像配列。
    size_per_pixel
        Physical size represented by one pixel along the X (column) axis
        (nm/px); None when the scan scale is unknown.
        1ピクセルが表す X（列）軸方向の実空間サイズ (nm/px)。スキャンスケール
        未知の場合は None。
    y_size_per_pixel
        Physical Y (row) pixel size (nm/px); None reuses ``size_per_pixel``
        for an isotropic (square-pixel) scale.
        Y（行）軸の物理ピクセルサイズ (nm/px)。None のときは
        ``size_per_pixel`` を流用し等方（正方ピクセル）スケールとする。
    calibrated_image
        Calibrated AFM image loaded from GUI01 output.
        GUI01 出力から読み込む補正済み AFM 画像。
    skeleton_image
        Skeletonized binary image loaded from GUI01 output.
        GUI01 出力から読み込む骨格化2値画像。
    bp
        Branch-point mask array.
        分岐点マスク配列。
    ep
        End-point mask array.
        端点マスク配列。
    all_kink_coordinates
        Global kink coordinates as x-array and y-array tuple.
        グローバルな kink 座標を x 配列・y 配列で保持するタプル。
    decomposed_point_coordinates
        Coordinates of decomposition points.
        分解点の座標配列。
    all_kink_angles
        Angle values corresponding to kink points.
        kink 点に対応する角度配列。
    skipped_fiber_labels
        Labels skipped during the most recent tracing call with their reasons.
        直近の追跡呼び出しでスキップされたラベルと理由。
    """

    def __init__(
        self,
        original_AFM: np.ndarray,
        name: str,
        size_per_pixel: Optional[float] = None,
        y_size_per_pixel: Optional[float] = None,
    ) -> None:
        """
        Initialize container fields for GUI04 tracking workflow.
        GUI04 の追跡ワークフロー用フィールドを初期化する。

        Parameters
        ----------
        original_AFM
            Original AFM image array.
            元の AFM 画像配列。
        name
            Name or identifier of this image.
            画像名または識別子。
        size_per_pixel
            Physical X (column) pixel size (nm/px). None means the scan scale
            is unknown; fiber-length computation then fails loudly instead of
            silently assuming a default scan size, so callers that trace fibers
            must always pass an explicit value.
            X（列）軸の物理ピクセルサイズ (nm/px)。None はスキャンスケール未知を
            意味し、ファイバー長計算は既定スキャンサイズを黙って仮定せず明示的に
            失敗する。ファイバー追跡を行う呼び出し側は必ず明示値を渡すこと。
        y_size_per_pixel
            Physical Y (row) pixel size (nm/px). None reuses ``size_per_pixel``
            so a single value keeps the historical isotropic behavior; pass a
            distinct value for rectangular scans or non-square pixel grids.
            Y（行）軸の物理ピクセルサイズ (nm/px)。None のときは
            ``size_per_pixel`` を流用し、単一値で従来の等方挙動を保つ。矩形
            スキャンや非正方ピクセル格子では別の値を渡す。
        """
        self.name: str = name
        self.original_image: np.ndarray = original_AFM
        self.size_per_pixel: Optional[float] = size_per_pixel
        self.y_size_per_pixel: Optional[float] = y_size_per_pixel

        # GUI04 populates these arrays from GUI01 output files.
        # GUI04 が GUI01 出力ファイルからこれらの配列を設定する。
        self.calibrated_image: Optional[np.ndarray] = None
        self.binarized_image: Optional[np.ndarray] = None
        self.skeleton_image: Optional[np.ndarray] = None

        # Connected-component metadata for the skeleton image.
        self.nLabels: Optional[int] = None
        self.data: Optional[tuple] = None
        self.label_image: Optional[np.ndarray] = None

        # Binary masks of branch points and end points.
        self.bp = None
        self.ep = None

        # Kink/decomposition results computed by KinkDetector or loaded from files.
        self.all_kink_coordinates: Optional[
            tuple[np.ndarray, np.ndarray]] = None
        self.all_kink_angles: Optional[np.ndarray] = None
        self.decomposed_point_coordinates: Optional[np.ndarray] = None
        self.skipped_fiber_labels: tuple[tuple[int, str], ...] = ()

    def fibers_in_image_parallel(
        self,
        max_workers: Optional[int] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Fiber]:
        """
        Process fibers in parallel with ThreadPoolExecutor.
        ThreadPoolExecutor でファイバーを並列処理して返す。
        If provided, `progress_cb(done, total)` is called on each completion.
        progress_cb(done, total) が指定されていれば1本完了するごとに呼ぶ。

        Parameters
        ----------
        max_workers
            Maximum number of worker threads.
            ワーカースレッドの最大数。
        progress_cb
            Progress callback receiving `(done, total)`.
            `(done, total)` を受け取る進捗コールバック。

        Returns
        -------
        Fiber list extracted in parallel.
        並列処理で抽出された Fiber のリスト。
        """
        return self._generate_fiber_instances(
            self.skeleton_image, parallel=True,
            max_workers=max_workers, progress_cb=progress_cb,
        )

    def specific_height_fibers(
        self,
        lower_height: Union[int, float],
        upper_height: Union[int, float],
        include_lower_limit: bool = True,
        include_upper_limit: bool = True,
    ) -> list[Fiber]:
        """
        Extract fibers whose heights are within a selected range.
        指定した高さ範囲に含まれるファイバーを抽出する。

        The height test is applied per skeleton pixel: only skeleton pixels
        whose calibrated height satisfies the range are kept, and fibers are
        rebuilt from those surviving pixels. A single input fiber can therefore
        be split into shorter sub-segments or partially removed, so this
        extracts the portions at a specific height (e.g. dents), not whole
        fibers selected by a summary statistic.
        高さ判定はスケルトン画素ごとに行う。補正高さが範囲を満たす画素のみを
        残し、残った画素からファイバーを再構築する。そのため 1 本の入力
        ファイバーが短いサブセグメントに分割されたり一部が除去されたりする。
        要約統計でファイバーを丸ごと選ぶのではなく、特定の高さを持つ箇所
        （凹みなど）を抜き出す操作である。

        Parameters
        ----------
        lower_height
            Lower bound of target height range.
            抽出対象高さ範囲の下限。
        upper_height
            Upper bound of target height range.
            抽出対象高さ範囲の上限。
        include_lower_limit
            Whether lower bound is inclusive.
            下限値を含むかどうか。
        include_upper_limit
            Whether upper bound is inclusive.
            上限値を含むかどうか。

        Returns
        -------
        Fiber list that satisfies the height condition.
        高さ条件を満たす Fiber のリスト。
        """
        lower_cond = (self.calibrated_image >= lower_height) if include_lower_limit else (self.calibrated_image > lower_height)
        upper_cond = (self.calibrated_image <= upper_height) if include_upper_limit else (self.calibrated_image < upper_height)
        # Keep only skeleton pixels whose calibrated heights satisfy both conditions.
        skeleton_image = np.where(lower_cond & upper_cond & self.skeleton_image, 1, 0).astype(np.uint8)
        # Build in parallel: same fibers as the sequential path, just faster.
        # 並列で構築する。逐次と同一の Fiber を、より高速に得るだけ。
        return self._generate_fiber_instances(skeleton_image, parallel=True)

    def _generate_fiber_instances(
        self,
        skeleton_image: np.ndarray,
        *,
        parallel: bool = False,
        max_workers: Optional[int] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Fiber]:
        """
        Generate Fiber instances from a skeleton image.
        骨格画像から Fiber インスタンス群を生成する。

        Shared builder behind `fibers_in_image_parallel` and
        `specific_height_fibers`. The two only differ in which skeleton they
        pass in, so keeping one builder means both always produce fibers the
        same way.
        `fibers_in_image_parallel` と `specific_height_fibers` の共通ビルダー。
        両者は渡すスケルトンが違うだけなので、ビルダーを 1 つに保てば両者は
        常に同じ手順で Fiber を生成する。

        Parameters
        ----------
        skeleton_image
            Binary skeleton image used for component extraction.
            連結成分抽出に使う2値骨格画像。
        parallel
            When True, build fibers with a `ThreadPoolExecutor`. `_build_fiber`
            is a pure function of its arguments and the lookup tables are
            read-only after construction, so the threaded result is identical
            to the sequential one (output stays in label order). Most of the
            per-fiber cost is `imp_tools.tracking`'s hit-or-miss matching in
            native code that releases the GIL, so threading gives a real
            speedup.
            True のとき `ThreadPoolExecutor` でファイバーを構築する。
            `_build_fiber` は引数のみに依存する純関数で、参照テーブルは構築後
            読み取り専用のため、並列結果は逐次と同一になる（出力はラベル順）。
            ファイバーごとの処理時間の大半は GIL を解放するネイティブコード
            （`imp_tools.tracking` の hit-or-miss 照合）が占めるため、並列化が
            実際に効く。
        max_workers
            Maximum number of worker threads when `parallel` is True.
            `parallel` が True のときのワーカースレッド最大数。
        progress_cb
            Progress callback receiving `(done, total)`.
            `(done, total)` を受け取る進捗コールバック。

        Returns
        -------
        Constructed fibers for each connected component, in label order.
        各連結成分に対して構築された Fiber のリスト（ラベル順）。
        """
        nLabels, label_image, data = self._labeled_components(skeleton_image)
        kink_set, dp_set, ep_set, kink_angle_map = self._feature_lookups()
        total = nLabels - 1
        skipped: list[tuple[int, str]] = []

        # Bind the shared, read-only inputs once so both paths and every worker
        # use the same references.
        # 共有の読み取り専用入力を一度束ねておき、両経路・全ワーカーで同じ参照を使う。
        cal = self.calibrated_image
        spp = self.size_per_pixel
        # Y pixel size falls back to the X value, keeping isotropic behavior
        # when only one scale is known.
        # Y のピクセルサイズは X 値へフォールバックし、スケールが 1 つしか
        # 分からない場合は等方挙動を保つ。
        spp_y = self.y_size_per_pixel if self.y_size_per_pixel is not None else spp

        def build(label: int) -> Fiber:
            return _build_fiber(
                label_image, label, data[label], cal, spp,
                kink_set, dp_set, ep_set, kink_angle_map, spp_y,
            )

        if not parallel:
            fiber_instances = []
            for done, label in enumerate(range(1, nLabels), start=1):
                try:
                    fiber_instances.append(build(label))
                except ValueError as exc:
                    if "tracking requires exactly 2 endpoints" not in str(exc):
                        raise
                    skipped.append((label, str(exc)))
                if progress_cb is not None:
                    progress_cb(done, total)
            self.skipped_fiber_labels = tuple(skipped)
            return fiber_instances

        # Store each result at its label index to keep the sequential order.
        # 結果をラベルのインデックス位置へ格納し、逐次と同じ順序を保つ。
        results: list[Optional[Fiber]] = [None] * total
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(build, label): i
                for i, label in enumerate(range(1, nLabels))
            }
            done = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except ValueError as exc:
                    if "tracking requires exactly 2 endpoints" not in str(exc):
                        raise
                    skipped.append((idx + 1, str(exc)))
                done += 1
                if progress_cb is not None:
                    progress_cb(done, total)
        self.skipped_fiber_labels = tuple(sorted(skipped))
        return [f for f in results if f is not None]

    def _labeled_components(
        self,
        skeleton_image: np.ndarray,
    ) -> tuple[int, np.ndarray, np.ndarray]:
        """
        Label line-like skeleton components after branch cleanup.
        分岐除去後の線状骨格成分をラベリングする。

        Remove branch points and L-corners first so each connected component
        becomes a line-like shape that `imp_tools.tracking` can follow as a
        single path. Shared by the sequential and parallel tracing paths.
        分岐点とL字角を先に除去し、各連結成分を `imp_tools.tracking` が単一の
        経路として追跡できる線状の形へ単純化する。逐次・並列の両経路で共有する。

        Returns
        -------
        tuple
            ``(nLabels, label_image, data)`` from
            ``cv2.connectedComponentsWithStats``.
            ``cv2.connectedComponentsWithStats`` の
            ``(nLabels, label_image, data)``。
        """
        no_bp_skel = imp_tools.remove_bp(skeleton_image)
        no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
        nLabels, label_image, data, _center = \
            cv2.connectedComponentsWithStats(no_Lcorner_skel)
        return nLabels, label_image, data

    def _feature_lookups(self) -> tuple[set, set, set, dict]:
        """
        Build coordinate lookup tables for kink, decomposition, and end points.
        キンク・分解点・端点の座標検索テーブルを構築する。

        Sets and the angle dict give O(1) membership checks during track
        scanning. They are built once per tracing call and only read
        afterwards, so parallel workers can share them safely.
        集合と角度辞書によりトラック走査中の照合を O(1) にする。追跡呼び出し
        ごとに一度だけ構築し、その後は読み取り専用のため並列ワーカー間で
        安全に共有できる。

        Returns
        -------
        tuple
            ``(kink_set, dp_set, ep_set, kink_angle_map)`` consumed by
            `_build_fiber`.
            `_build_fiber` が使用する
            ``(kink_set, dp_set, ep_set, kink_angle_map)``。
        """
        all_kink_x, all_kink_y = self.all_kink_coordinates
        kink_set: set[tuple] = set(zip(all_kink_x.tolist(), all_kink_y.tolist()))
        kink_angle_map: dict[tuple, float] = {
            (int(kx), int(ky)): float(ka)
            for kx, ky, ka in zip(all_kink_x, all_kink_y, self.all_kink_angles)
        }
        dp_set: set[tuple] = set(zip(
            self.decomposed_point_coordinates[0].tolist(),
            self.decomposed_point_coordinates[1].tolist(),
        ))
        ep_y, ep_x = np.where(self.ep)
        ep_set: set[tuple] = set(zip(ep_x.tolist(), ep_y.tolist()))
        return kink_set, dp_set, ep_set, kink_angle_map
