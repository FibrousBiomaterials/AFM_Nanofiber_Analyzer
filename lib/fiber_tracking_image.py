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


def _process_single_fiber(args: tuple) -> "Fiber":
    """
    Process one fiber entry for parallel execution.
    並列実行用に1本分のファイバーを処理する。

    Parameters
    ----------
    args
        Packed arguments used by the thread worker.
        スレッドワーカーで使用する引数をまとめたタプル。
        (label_image, label, data_row, cal, size_per_pixel,
         all_kink_x, all_kink_y, all_kink_angles, dp_x, dp_y, ep_arr)

    Returns
    -------
    One constructed Fiber object for the given label.
    指定ラベルに対応する1つの Fiber オブジェクト。
    """
    (label_image, label, data_row, cal, size_per_pixel,
     all_kink_x, all_kink_y, all_kink_angles,
     dp_x, dp_y, ep_arr) = args

    # `data_row` is OpenCV component stats: (x, y, width, height, area).
    x, y, w, h, size = data_row
    target_image = np.where(label_image == label, 1, 0).astype(np.uint8)
    # Track skeleton pixels in order so we can treat the fiber as a 1D sequence.
    # 骨格ピクセルを順序付きで追跡し、ファイバーを1次元列として扱えるようにする。
    xtrack_prcimg, ytrack_prcimg = imp_tools.tracking(target_image)
    xtrack  = xtrack_prcimg - x
    ytrack  = ytrack_prcimg - y
    horizon = imp_tools.convert_track_to_distance(xtrack, ytrack, size_per_pixel)
    height  = cal[ytrack_prcimg, xtrack_prcimg]
    fiber_image = cal[y: y + h, x: x + w].copy()

    # Convert coordinate arrays to sets for O(1) membership checks.
    kink_set  = set(zip(all_kink_x.tolist(), all_kink_y.tolist()))
    dp_set    = set(zip(dp_x.tolist(), dp_y.tolist()))
    ep_y_arr, ep_x_arr = np.where(ep_arr)
    ep_set    = set(zip(ep_x_arr.tolist(), ep_y_arr.tolist()))
    # Build a coordinate->angle map to recover kink angles quickly.
    kink_angle_map = {
        (int(kx), int(ky)): float(ka)
        for kx, ky, ka in zip(all_kink_x, all_kink_y, all_kink_angles)
    }

    kink_indices, decomposed_point_indices, ep_indices = [], [], []
    for i, (px, py) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
        if (px, py) in kink_set:
            kink_indices.append(i)
        if (px, py) in dp_set:
            decomposed_point_indices.append(i)
        if (px, py) in ep_set:
            ep_indices.append(i)

    kink_indices_arr = np.array(kink_indices)
    kink_angles = np.array([
        kink_angle_map[(int(xtrack_prcimg[i]), int(ytrack_prcimg[i]))]
        for i in kink_indices_arr
        if (int(xtrack_prcimg[i]), int(ytrack_prcimg[i])) in kink_angle_map
    ])

    return Fiber(
        fiber_image, tuple(data_row), xtrack, ytrack, horizon, height,
        kink_indices_arr, np.array(ep_indices),
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
        Physical size represented by one pixel (nm/px); None when the scan
        scale is unknown.
        1ピクセルが表す実空間サイズ (nm/px)。スキャンスケール未知の場合は None。
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
    """

    def __init__(
        self,
        original_AFM: np.ndarray,
        name: str,
        size_per_pixel: Optional[float] = None,
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
            Physical length represented by one pixel (nm/px). None means the
            scan scale is unknown; fiber-length computation then fails loudly
            instead of silently assuming a default scan size, so callers that
            trace fibers must always pass an explicit value.
            1ピクセルあたりの実空間長 (nm/px)。None はスキャンスケール未知を
            意味し、ファイバー長計算は既定スキャンサイズを黙って仮定せず明示的に
            失敗する。ファイバー追跡を行う呼び出し側は必ず明示値を渡すこと。
        """
        self.name: str = name
        self.original_image: np.ndarray = original_AFM
        self.size_per_pixel: Optional[float] = size_per_pixel

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

    def fibers_in_image(
        self,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Fiber]:
        """
        Process all fibers sequentially and return them.
        全ファイバーを逐次処理して返す。
        If provided, `progress_cb(done, total)` is called after each fiber.
        progress_cb(done, total) が指定されていれば1本処理するごとに呼ぶ。

        Parameters
        ----------
        progress_cb
            Progress callback receiving `(done, total)`.
            `(done, total)` を受け取る進捗コールバック。

        Returns
        -------
        Fiber list extracted from the image.
        画像から抽出された Fiber のリスト。
        """
        return self._generate_fiber_instances(self.skeleton_image, progress_cb=progress_cb)

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
        # Remove branch points and L-corners to simplify each component into a line-like shape.
        # 分岐点とL字角を除去し、各成分を線状に近い形へ単純化する。
        no_bp_skel      = imp_tools.remove_bp(self.skeleton_image)
        no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
        nLabels, label_image, data, _ = cv2.connectedComponentsWithStats(no_Lcorner_skel)

        all_kink_x, all_kink_y = self.all_kink_coordinates
        dp_x = self.decomposed_point_coordinates[0]
        dp_y = self.decomposed_point_coordinates[1]

        # Pass only explicit arrays into the worker so the threaded path is independent of self state changes.
        args_list = [
            (
                label_image, label, data[label],
                self.calibrated_image, self.size_per_pixel,
                all_kink_x, all_kink_y, self.all_kink_angles,
                dp_x, dp_y, self.ep,
            )
            for label in range(1, nLabels)
        ]
        total = len(args_list)
        # Keep output order stable by storing each future result at its original index.
        results: list[Optional[Fiber]] = [None] * total

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_process_single_fiber, args): i
                for i, args in enumerate(args_list)
            }
            # Count completed tasks to report progress in real time.
            done = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()
                done += 1
                if progress_cb is not None:
                    progress_cb(done, total)

        return [f for f in results if f is not None]

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
        return self._generate_fiber_instances(skeleton_image)

    def _generate_fiber_instances(
        self,
        skeleton_image: np.ndarray,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Fiber]:
        """
        Generate Fiber instances from a skeleton image.
        骨格画像から Fiber インスタンス群を生成する。

        Parameters
        ----------
        skeleton_image
            Binary skeleton image used for component extraction.
            連結成分抽出に使う2値骨格画像。
        progress_cb
            Progress callback receiving `(done, total)`.
            `(done, total)` を受け取る進捗コールバック。

        Returns
        -------
        Constructed fibers for each connected component.
        各連結成分に対して構築された Fiber のリスト。
        """
        # Same preprocessing as parallel path: remove branching artifacts before labeling.
        # 並列経路と同じ前処理として、ラベリング前に分岐アーティファクトを除去する。
        no_bp_skel = imp_tools.remove_bp(skeleton_image)
        no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
        nLabels, label_image, data, center = cv2.connectedComponentsWithStats(no_Lcorner_skel)

        # Build lookup set/dict tables once before component loop.
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

        fiber_instances = []
        total = nLabels - 1
        for done, label in enumerate(range(1, nLabels), start=1):
            x, y, w, h, size = data[label]
            target_image = np.where(label_image == label, 1, 0).astype(np.uint8)
            xtrack_prcimg, ytrack_prcimg = imp_tools.tracking(target_image)
            xtrack = xtrack_prcimg - x
            ytrack = ytrack_prcimg - y
            horizon = imp_tools.convert_track_to_distance(xtrack, ytrack, self.size_per_pixel)
            height = self.calibrated_image[ytrack_prcimg, xtrack_prcimg]
            fiber_image = self.calibrated_image[y: y + h, x: x + w].copy()

            # Resolve feature indices from prebuilt lookup tables.
            kink_indices, decomposed_point_indices = \
                self._calc_kink_and_decomposed_point_indices(
                    xtrack_prcimg, ytrack_prcimg, kink_set, dp_set)
            ep_indices = self._calc_endpoint_indices(
                xtrack_prcimg, ytrack_prcimg, ep_set)
            kink_angles = self._get_kink_angles_in_fiber(
                xtrack_prcimg, ytrack_prcimg, kink_indices, kink_angle_map)

            fiber = Fiber(fiber_image, tuple(data[label]), xtrack, ytrack, horizon, height,
                          kink_indices, ep_indices, kink_angles, decomposed_point_indices)
            fiber_instances.append(fiber)
            if progress_cb is not None:
                progress_cb(done, total)
        return fiber_instances

    def _calc_kink_and_decomposed_point_indices(
        self,
        xtrack_prcimg: np.ndarray,
        ytrack_prcimg: np.ndarray,
        kink_set: set,
        dp_set: set,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Return kink and decomposition-point indices from tracked coordinates.
        トラック座標列からキンクと分解点のインデックスを返す。

        Parameters
        ----------
        xtrack_prcimg
            X coordinates on processed image track.
            処理画像上トラックの x 座標列。
        ytrack_prcimg
            Y coordinates on processed image track.
            処理画像上トラックの y 座標列。
        kink_set
            Coordinate set of kink points.
            kink 点座標の集合。
        dp_set
            Coordinate set of decomposition points.
            分解点座標の集合。

        Returns
        -------
        `(kink_indices, decomposed_point_indices)`.
        `(kink_indices, decomposed_point_indices)`。
        """
        # Linear scan keeps index alignment with xtrack/ytrack arrays.
        # 線形走査により xtrack/ytrack 配列とのインデックス対応を保つ。
        kink_indices = []
        decomposed_point_indices = []
        for i, (x, y) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
            if (x, y) in kink_set:
                kink_indices.append(i)
            if (x, y) in dp_set:
                decomposed_point_indices.append(i)
        return np.array(kink_indices), np.array(decomposed_point_indices)

    def _calc_endpoint_indices(
        self,
        xtrack_prcimg: np.ndarray,
        ytrack_prcimg: np.ndarray,
        ep_set: set,
    ) -> np.ndarray:
        """
        Return endpoint indices from tracked coordinates.
        トラック座標列から端点のインデックスを返す。

        Parameters
        ----------
        xtrack_prcimg
            X coordinates on processed image track.
            処理画像上トラックの x 座標列。
        ytrack_prcimg
            Y coordinates on processed image track.
            処理画像上トラックの y 座標列。
        ep_set
            Coordinate set of endpoint pixels.
            端点ピクセル座標の集合。

        Returns
        -------
        Endpoint index array. Empty if none exists.
        端点インデックス配列。該当がなければ空配列。
        """
        # Endpoint indices are returned in track order for consistent downstream usage.
        # 端点インデックスは後段処理の一貫性のため追跡順で返す。
        ep_indices = []
        for i, (x, y) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
            if (x, y) in ep_set:
                ep_indices.append(i)
        return np.array(ep_indices)

    def _get_kink_angles_in_fiber(
        self,
        xtrack_prcimg: np.ndarray,
        ytrack_prcimg: np.ndarray,
        kink_indices: np.ndarray,
        kink_angle_map: dict,
    ) -> np.ndarray:
        """
        Get kink angles for indices using coordinate-to-angle mapping.
        座標→角度マップを用いてキンクインデックスの角度を取得する。

        Parameters
        ----------
        xtrack_prcimg
            X coordinates on processed image track.
            処理画像上トラックの x 座標列。
        ytrack_prcimg
            Y coordinates on processed image track.
            処理画像上トラックの y 座標列。
        kink_indices
            Indices identified as kink points.
            kink 点として識別されたインデックス列。
        kink_angle_map
            Mapping from `(x, y)` coordinates to angle values.
            `(x, y)` 座標から角度値への対応辞書。

        Returns
        -------
        Angle array aligned with valid kink indices.
        有効な kink インデックスに対応する角度配列。
        """
        # Translate each kink index into a coordinate key, then read angle from dictionary.
        # 各 kink インデックスを座標キーに変換し、辞書から角度を取得する。
        kink_angles = []
        for i in kink_indices:
            key = (int(xtrack_prcimg[i]), int(ytrack_prcimg[i]))
            if key in kink_angle_map:
                kink_angles.append(kink_angle_map[key])
        return np.array(kink_angles)
