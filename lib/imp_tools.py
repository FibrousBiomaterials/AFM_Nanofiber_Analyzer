"""
Skeleton morphology and fiber measurement helpers for AFM nanofiber images.
AFM ナノファイバー画像のスケルトン形態処理と繊維計測用ヘルパー。

Provides branch/end-point detection, skeleton tracing, path-distance
conversion, and aggregate fiber height utilities used by the GUI tools.
GUI ツールで使う分岐点・端点検出、スケルトン追跡、経路距離変換、
および繊維高さの集計ユーティリティを提供する。
"""

import math
import time
from functools import wraps
from typing import Union

import cv2
import mahotas as mh
import numpy as np
from numpy.typing import NDArray


def branchedPoints(skel: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """
    Detect branch points in a skeleton image by hit-or-miss templates.
    hit-or-miss テンプレートによりスケルトン画像内の分岐点を検出する。

    Parameters
    ----------
    skel
        Binary skeleton image. Nonzero pixels are treated as skeleton pixels.
        二値スケルトン画像。非ゼロ画素をスケルトン画素として扱う。

    Returns
    -------
    ndarray
        Binary image whose nonzero pixels mark detected branch points.
        検出された分岐点を非ゼロ画素で示す二値画像。

    Notes
    -----
    The templates use ``2`` as the mahotas hit-or-miss wildcard value.
    テンプレート内の ``2`` は mahotas の hit-or-miss におけるワイルドカード値。
    """

    vh_xbranch = np.array([[0, 1, 0],
                           [1, 1, 1],
                           [0, 1, 0]])

    diagonal_xbranch = np.array([[1, 0, 1],
                                 [0, 1, 0],
                                 [1, 0, 1]])

    vh_ybranch = np.array([[1, 0, 1],
                           [0, 1, 0],
                           [2, 1, 2]])

    # TODO(review): diagonal_ybranch may cover too many patterns; confirm before changing detection behavior.
    # TODO(review): diagonal_ybranchは多くのパターンをカバーしすぎでは?
    diagonal_ybranch = np.array([[0, 1, 2],
                                 [1, 1, 2],
                                 [2, 2, 1]])

    vh_tbranch = np.array([[0, 0, 0],
                           [1, 1, 1],
                           [0, 1, 0]])

    diagonal_tbranch = np.array([[1, 0, 1],
                                 [0, 1, 0],
                                 [1, 0, 0]])

    square_branch =  np.array([[2, 2, 2],
                               [1, 1, 2],
                               [1, 1, 2]])


    branch_patterns = []
    for rot_time in range(4):
        for branch_pattern in [vh_ybranch, diagonal_ybranch, vh_tbranch, diagonal_tbranch]:
            branch_patterns.append(np.rot90(branch_pattern, k=rot_time))
    branch_patterns.append(vh_xbranch)
    branch_patterns.append(diagonal_xbranch)

    branch_patterns.append(square_branch)

    padded_skel = np.pad(skel, pad_width=1, mode='constant', constant_values=0)
    hits = np.zeros_like(padded_skel, dtype=np.uint8)
    for branch_pattern in branch_patterns:
        hits |= mh.morph.hitmiss(padded_skel, branch_pattern)
    # Pixels with multiple pattern hits are also corrected to 1.
    return hits[1:-1, 1:-1].copy()


def endPoints(skel: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """
    Detect end points in a skeleton image by hit-or-miss templates.
    hit-or-miss テンプレートによりスケルトン画像内の端点を検出する。

    Parameters
    ----------
    skel
        Binary skeleton image. Nonzero pixels are treated as skeleton pixels.
        二値スケルトン画像。非ゼロ画素をスケルトン画素として扱う。

    Returns
    -------
    ndarray
        Binary image whose nonzero pixels mark detected end points.
        検出された端点を非ゼロ画素で示す二値画像。
    """
    endpoint1 = np.array([[0, 0, 0],
                          [0, 1, 0],
                          [2, 1, 2]])

    endpoint2 = np.array([[0, 0, 0],
                          [0, 1, 0],
                          [0, 0, 1]])
    end_patterns = []
    for rot_time in range(4):
        for end_pattern in [endpoint1, endpoint2]:
            end_patterns.append(np.rot90(end_pattern, k=rot_time))

    endpoint_single = np.array([[0, 0, 0],
                                [0, 1, 0],
                                [0, 0, 0]])
    end_patterns.append(endpoint_single)

    padded_skel = np.pad(skel, pad_width=1, mode='constant', constant_values=0)
    hits = np.zeros_like(padded_skel, dtype=np.uint8)
    for end_pattern in end_patterns:
        hits |= mh.morph.hitmiss(padded_skel, end_pattern).astype(np.uint8)
        # Pixels with multiple pattern hits are also corrected to 1.

    return hits[1:-1, 1:-1].copy()


def remove_bp(
    img: NDArray[np.uint8],
    remove_size: int = 1,
    min_area: int = 10,
) -> NDArray[np.uint8]:
    """
    Remove branch-point neighborhoods and optionally discard small components.
    分岐点周辺を除去し、必要に応じて小さな連結成分を捨てる。

    Parameters
    ----------
    img
        Binary skeleton image from which branch neighborhoods are removed.
        分岐点周辺を除去する対象の二値スケルトン画像。
    remove_size
        Half-width of the square neighborhood removed around each branch point.
        各分岐点の周囲から除去する正方形近傍の半幅。
    min_area
        Minimum connected-component area retained after branch removal. Set to
        ``0`` to skip area filtering.
        分岐点除去後に保持する連結成分の最小面積。``0`` の場合は面積フィルタを行わない。

    Returns
    -------
    ndarray
        Skeleton image after branch-neighborhood and small-component removal.
        分岐点周辺と小成分を除去した後のスケルトン画像。
    """
    imgcopy = img.copy()
    bp = branchedPoints(imgcopy)
    bp_coor = np.where(bp)
    for bp_x, bp_y in zip(bp_coor[0], bp_coor[1]):
        imgcopy[
        bp_x - remove_size: bp_x + remove_size + 1,
        bp_y - remove_size: bp_y + remove_size + 1,
        ] = 0

    if min_area != 0:
        tmp_nlabels, tmp_label_image = cv2.connectedComponents(np.uint8(imgcopy))
        sizes = np.bincount(tmp_label_image.ravel())
        small_mask = sizes < min_area
        small_mask[0] = False  # Do not remove the background label.
        imgcopy[small_mask[tmp_label_image]] = 0
    return imgcopy


def remove_Lcorner(skeleton_image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """
    Remove two-pixel L-corner artifacts from a skeleton image.
    スケルトン画像から 2 画素の L 字コーナーアーティファクトを除去する。

    Parameters
    ----------
    skeleton_image
        Binary skeleton image to clean.
        クリーニング対象の二値スケルトン画像。

    Returns
    -------
    ndarray
        Skeleton image with detected L-corner pixels removed.
        検出された L 字コーナー画素を除去したスケルトン画像。
    """
    imgcopy = skeleton_image.copy()
    imgcopy = np.pad(imgcopy, pad_width=1, mode='constant', constant_values=0)

    # Hit-or-miss patterns identify small L-shaped corner artifacts.
    corner = np.array([[0, 1, 0],
                       [1, 1, 0],
                       [0, 0, 0]])
    corner2 = np.array([[0, 1, 0],
                        [0, 1, 1],
                        [0, 0, 0]])
    corner3 = np.array([[0, 0, 0],
                        [1, 1, 0],
                        [0, 1, 0]])
    corner4 = np.array([[0, 0, 0],
                        [0, 1, 1],
                        [0, 1, 0]])

    hits = np.zeros_like(imgcopy, dtype=np.uint8)
    for corner_pattern in [corner, corner2, corner3, corner4]:
        hits += mh.morph.hitmiss(imgcopy, corner_pattern)

    Lremoved_img = imgcopy - hits
    return Lremoved_img[1:-1, 1:-1].copy()




def tracking(skeleton_image: NDArray[np.uint8]) -> tuple[NDArray, NDArray]:
    """
    Trace a single skeleton line from one end point to the other.
    1 本のスケルトン線を一方の端点からもう一方の端点まで追跡する。

    Parameters
    ----------
    skeleton_image
        Binary skeleton image containing one traceable fiber segment.
        追跡可能な 1 本の繊維セグメントを含む二値スケルトン画像。

    Returns
    -------
    tuple of ndarray
        ``(xtrack, ytrack)`` coordinate arrays in tracing order.
        追跡順の ``(xtrack, ytrack)`` 座標配列。

    Notes
    -----
    If multiple next pixels are available, the first candidate returned by
    ``np.where`` is used. This function assumes branch points were removed
    before tracing.
    複数の次候補画素がある場合は ``np.where`` が返す最初の候補を使う。
    この関数は追跡前に分岐点が除去されていることを前提とする。
    """
    if np.array_equal(skeleton_image, np.array([[1]])):
        return (np.array([0]), np.array([0]))
    imgcopy = skeleton_image.copy()
    imgcopy = np.pad(imgcopy, pad_width=1, mode='constant', constant_values=0)

    ep = endPoints(imgcopy)
    (ep_y_start, ep_y_end), (ep_x_start, ep_x_end) = np.where(ep)

    ytrack = [ep_y_start]
    xtrack = [ep_x_start]

    y = ep_y_start
    x = ep_x_start
    for i in range(np.sum(imgcopy)):
        imgcopy[y, x] = 0
        window = imgcopy[y - 1: y + 2, x - 1: x + 2]
        direction_y, direction_x = np.where(window != 0)
        if len(direction_y) == 0:
            # Stop defensively if no next pixel exists, although this is not expected.
            break
        dy = int(direction_y[0]) - 1
        dx = int(direction_x[0]) - 1
        y += dy
        x += dx
        xtrack.append(x)
        ytrack.append(y)
        if x == ep_x_end and y == ep_y_end:
            break

    xtrack = np.asarray(xtrack) - 1  # subtract 1 to compensate for the padding
    ytrack = np.asarray(ytrack) - 1
    return xtrack, ytrack



def convert_track_to_distance(xtrack: np.ndarray,
                              ytrack: np.ndarray,
                              pixel_step_size: Union[int, float]) -> np.ndarray:
    """
    Convert traced pixel coordinates to cumulative path distance.
    追跡された画素座標を累積経路距離に変換する。

    Parameters
    ----------
    xtrack
        X-coordinate array in tracing order.
        追跡順の X 座標配列。
    ytrack
        Y-coordinate array in tracing order.
        追跡順の Y 座標配列。
    pixel_step_size
        Physical pixel size used for horizontal/vertical steps.
        上下左右方向の 1 画素ステップに用いる物理ピクセルサイズ。

    Returns
    -------
    ndarray
        Cumulative path distance from the first traced pixel.
        追跡開始画素からの累積経路距離。

    Notes
    -----
    Diagonal neighbor steps are counted as ``sqrt(2) * pixel_step_size``.
    斜め隣接画素へのステップは ``sqrt(2) * pixel_step_size`` として数える。
    """
    xmove = xtrack - np.roll(xtrack, 1)
    ymove = ytrack - np.roll(ytrack, 1)
    xmove = np.delete(xmove, 0)
    ymove = np.delete(ymove, 0)
    a = xmove != 0
    b = ymove != 0
    c = np.vstack((a, b))
    d = np.all(c, axis=0)
    steps = np.where(d, pixel_step_size * math.sqrt(2), pixel_step_size)
    horizon = np.empty(len(steps) + 1)
    horizon[0] = 0.0
    horizon[1:] = np.cumsum(steps)
    return horizon
