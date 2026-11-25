# -*- coding: utf-8 -*-
"""
Open a ``.b2z`` bundle for editing by hand, change its kinks, and save the edit.
``.b2z`` バンドルを手で編集するために開き、キンクを変更し、その編集を保存する。

GUI06 (the bundle editor) shows what one analysis stored and what its
background stage started from. A bundle holds the first; the second it holds
only when the analysis was run with ``save_original``. This module finds the
raw height image either way, repeats the background stage with the settings
the bundle records, and returns everything as one `EditSession`.
GUI06（バンドル編集ツール）は、1 回の解析が保存したものと、その背景補正が出発点に
したものを表示する。バンドルが必ず持つのは前者で、後者は ``save_original`` を付けて
解析したときだけ持つ。本モジュールは、どちらの場合も生の高さ画像を探し、バンドルが
記録する設定で背景補正をやり直し、すべてを 1 つの `EditSession` として返す。

The background stage is repeated for two results it does not store: the fiber
mask its fill excluded (the "ridge mask" of the editor), and whether the
analysis can still be reproduced. The mask is not a bundle key, so running the
stage again is the only way to see it, and it is the mask the analysis used
only if the heights it yields equal the stored ``calibrated``. That comparison
is therefore made here, and a session reports it (`BackgroundRebuild.reproduces`).
背景補正をやり直すのは、保存されない 2 つの結果のためである。穴埋めから除外した
繊維マスク（編集ツールでいう「リッジマスク」）と、解析を今も再現できるかどうか。
マスクはバンドルのキーではないため、見るには補正をやり直すしかない。そしてそれが
解析時のマスクだと言えるのは、得られた高さが保存済みの ``calibrated`` と等しい
ときだけである。そのためこの比較をここで行い、セッションが結果を伝える
（`BackgroundRebuild.reproduces`）。

Kinks are changed through `KinkEditor` and written with `save_edited_bundle`,
which marks the saved bundle as edited by hand and never replaces the bundle
the analysis wrote.
キンクは `KinkEditor` で変更し、`save_edited_bundle` で書き出す。後者は、保存した
バンドルに手で編集したという印を付け、解析が書いたバンドルを置き換えることはない。

This module runs an analysis stage, so it belongs with the code that produces
bundles, not with the readers that measure a stored record.
本モジュールは解析の段を実行するため、保存された記録を計測する読み取り側ではなく、
バンドルを作る側のコードに属する。
"""

# ===== Standard library =====
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from . import __version__
from .afm_io import AfmTextFormat, load_afm_text
from .blosc2_io import BUNDLE_EXT, load_bundle, load_bundle_meta, save_bundle
from . import imp_tools
from .bundle_schema import (
    BUNDLE_FORMAT_VERSION, FIBER_MASK_KEY, KINK_ARMS_KEY, MANUAL_EDIT_KEY,
    PARAMS_KEY, REQUIRED_BUNDLE_KEYS, SOURCE_REGION_KEY,
    pixel_aspect_from_meta, pixel_size_nm, scan_size_um_from_meta,
    validate_bundle,
)
from .fiber import Fiber, skeleton_track
from .pipeline import (
    ProcParams, build_stages, merge_params_dict, param_path_for, validate_params,
)
from .processed_image import ProcessedImage

# Where a session's raw height image was read from. Fixed English keys, not
# user-visible text.
# セッションの生の高さ画像の読み込み元。固定の英語キーで、表示文字列ではない。
RAW_FROM_BUNDLE = "bundle"
RAW_FROM_INPUT_FILE = "input_file"

# Why a session has no raw height image. Fixed English keys, not user-visible
# text; the GUI turns each into a message.
# セッションに生の高さ画像が無い理由。固定の英語キーで、表示文字列ではない。GUI が
# それぞれをメッセージに変える。
RAW_MISSING_NOT_RECORDED = "not_recorded"
RAW_MISSING_NOT_FOUND = "not_found"
RAW_MISSING_CHANGED = "changed"
RAW_MISSING_UNREADABLE = "unreadable"
RAW_MISSING_SHAPE = "shape"

# Background methods whose fill excludes a fiber mask. `tophat` opens the image
# without one, so a bundle analyzed with it has no mask to show.
# 穴埋めから繊維マスクを除外する背景補正の方式。`tophat` はマスクを使わずに画像を
# オープニングするため、それで解析したバンドルには表示するマスクが無い。
MASK_BG_METHODS = ("trendfill", "spline1d")

# Steps `load_edit_session` reports through its callback, in order. Fixed
# English keys, not user-visible text.
# `load_edit_session` がコールバックへ順に通知する段階。固定の英語キーで、表示
# 文字列ではない。
LOAD_STEPS = ("read", "raw", "background", "centerline")

# Suffix of the bundle an edit is saved to, added to the stem of the bundle
# the edit started from.
# 編集の保存先バンドルの接尾辞。編集の元になったバンドルの stem に付ける。
EDITED_SUFFIX = "_edited"

# Results of the analysis an edit can change or a stage can compute again, in
# the order the analysis computes them. A saved bundle's `MANUAL_EDIT_KEY`
# entry names them. Fixed English keys, not user-visible text.
# 編集で変更でき、段を再実行して計算し直せる解析結果。解析が計算する順に並べる。
# 保存したバンドルの `MANUAL_EDIT_KEY` の記録がこの名前を使う。固定の英語キーで、
# 表示文字列ではない。
RESULT_FIBER_MASK = "fiber_mask"
RESULT_CALIBRATED = "calibrated"
RESULT_BINARIZED = "binarized"
RESULT_SKELETON = "skeletonized"
RESULT_KINKS = "kinks"
RESULTS = (RESULT_FIBER_MASK, RESULT_CALIBRATED, RESULT_BINARIZED,
           RESULT_SKELETON, RESULT_KINKS)

# The results computed from each result, directly or through others. Changing
# a result leaves these as they were computed from its earlier state.
# 各結果から、直接または他の結果を介して計算される結果。ある結果を変えると、
# これらは変える前の状態から計算されたままになる。
DOWNSTREAM = {
    name: RESULTS[position + 1:] for position, name in enumerate(RESULTS)
}

# Stages that can be run again and the result each computes. The names are
# those of `pipeline.STAGE_KEYS`, with `STAGE_MASK` for detecting the fiber
# mask, which the analysis does inside its background stage.
# 再実行できる段と、それぞれが計算する結果。名前は `pipeline.STAGE_KEYS` のもので、
# `STAGE_MASK` は繊維マスクの検出を指す。解析はこれを背景補正の段の中で行う。
STAGE_MASK = "mask"
STAGE_BACKGROUND = "bg"
STAGE_BINARIZE = "binarize"
STAGE_SKELETONIZE = "skeletonize"
STAGE_KINKS = "kink"
STAGE_RESULT = {
    STAGE_MASK: RESULT_FIBER_MASK,
    STAGE_BACKGROUND: RESULT_CALIBRATED,
    STAGE_BINARIZE: RESULT_BINARIZED,
    STAGE_SKELETONIZE: RESULT_SKELETON,
    STAGE_KINKS: RESULT_KINKS,
}

# Masks a person can paint, and whether pixels may be set as well as cleared.
# The skeleton can only be cleared: a line one pixel wide stays one pixel wide
# when pixels are taken away, and need not when they are added.
# 人が塗れるマスクと、画素を消すだけでなく立てることもできるかどうか。スケルトンは
# 消すことだけができる。太さ 1 画素の線は、画素を除いても太さ 1 画素のままだが、
# 足すとそうとは限らない。
PAINTABLE = {
    RESULT_FIBER_MASK: True,
    RESULT_BINARIZED: True,
    RESULT_SKELETON: False,
}

# The two kinds of mark on a fiber: a kink, and a bend the rule measured and
# did not judge. Fixed English keys, not user-visible text.
# 繊維の上の 2 種類の印。キンクと、規則が測ったが判定しなかった折れ。固定の英語
# キーで、表示文字列ではない。
MARK_KINK = "kink"
MARK_UNJUDGED = "unjudged"

# The two ends of a kink's arms: the one toward the start of the fiber's line
# and the one toward its end.
# キンクの腕の 2 つの端。繊維の線の始点側のものと、終点側のもの。
ARM_BEFORE = 0
ARM_AFTER = 1

# How far from a kink each of its arms starts, in apparent widths W along the
# fiber's line. An arm runs from that point to its end, so the stretch next to
# the kink, where the line turns, is left out of the arm's direction. Where an
# end lies nearer than twice this distance, the arm starts halfway to it.
# キンクの各腕が、キンクからどれだけ離れた位置で始まるか。繊維の線に沿った見かけ幅
# W の倍数。腕はその点から端までなので、キンクのすぐ隣の、線が曲がっている区間は
# 腕の向きに入らない。端がこの距離の 2 倍より近い場合、腕は端までの中間で始まる。
ARM_GAP_WIDTHS = 0.5

# How far from a kink its two arm ends are put when the kink is placed, in
# apparent widths W along the fiber's line. A person can move each end
# afterwards.
# キンクを置いたときに、腕の 2 つの端をキンクからどれだけ離して置くか。繊維の線に
# 沿った見かけ幅 W の倍数。置いたあと、人がそれぞれの端を動かせる。
DEFAULT_ARM_WIDTHS = 1.5

# Interior angles are stored strictly inside (0, pi), as the bundle contract
# requires of `ka`.
# 内角は、バンドルの契約が `ka` に求めるとおり、(0, pi) の内側に収めて保存する。
_MIN_INTERIOR_ANGLE = 1e-6

Pixel = Tuple[int, int]


@dataclass(frozen=True)
class RawHeight:
    """
    The raw height image of a bundle's analysis, or why there is none.
    バンドルの解析の生の高さ画像、またはそれが無い理由。

    Attributes
    ----------
    height
        Raw heights in nanometers as the background stage received them, with
        the analyzed scan lines already cut out; ``None`` when not available.
        背景補正が受け取ったままの生の高さ（nm）。解析した走査線は切り出し済み。
        得られなければ ``None``。
    source
        `RAW_FROM_BUNDLE` or `RAW_FROM_INPUT_FILE`; ``None`` with no image.
        `RAW_FROM_BUNDLE` または `RAW_FROM_INPUT_FILE`。画像が無ければ ``None``。
    problem
        One of the ``RAW_MISSING_*`` keys when `height` is ``None``.
        `height` が ``None`` のときの ``RAW_MISSING_*`` キー。
    detail
        The input file's name, followed by the error text when reading failed.
        入力ファイルの名前。読み込みに失敗した場合はエラーの文面が続く。
    """

    height: Optional[np.ndarray]
    source: Optional[str] = None
    problem: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class BackgroundRebuild:
    """
    What repeating a bundle's background stage on its raw image gives.
    バンドルの背景補正を生の画像でやり直して得られるもの。

    Attributes
    ----------
    calibrated
        Heights the repeated stage returns, in nanometers.
        やり直した補正が返す高さ（nm）。
    fiber_mask
        Pixels the fill excluded as fiber, after the small-component removal
        and the dilation, in the frame of the stored arrays; ``None`` for a
        method outside `MASK_BG_METHODS`.
        穴埋めが繊維として除外した画素。小領域の除去と膨張を済ませたもので、
        保存された配列と同じ座標系。`MASK_BG_METHODS` 以外の方式では ``None``。
    reproduces
        Whether `calibrated` equals the bundle's stored ``calibrated``. Only
        then is `fiber_mask` the mask the stored analysis used.
        `calibrated` がバンドルの保存済み ``calibrated`` と等しいか。等しいときに
        限り、`fiber_mask` は保存済みの解析が使ったマスクである。
    max_difference_nm
        Largest absolute height difference from the stored ``calibrated``;
        ``None`` when the two shapes differ.
        保存済み ``calibrated`` との高さの差の絶対値の最大。形状が違えば ``None``。
    """

    calibrated: np.ndarray
    fiber_mask: Optional[np.ndarray]
    reproduces: bool
    max_difference_nm: Optional[float]


@dataclass
class EditSession:
    """
    One bundle opened for editing.
    編集のために開いた 1 つのバンドル。

    Attributes
    ----------
    bundle_path
        Path of the bundle the session was read from.
        セッションを読み込んだバンドルのパス。
    arrays
        Every array the bundle stores, by key.
        バンドルが保存するすべての配列（キーごと）。
    meta
        The bundle's vlmeta.
        バンドルの vlmeta。
    params
        Analysis settings the bundle records; ``None`` when it records none
        this version can use.
        バンドルが記録する解析設定。このバージョンで使える設定が記録されて
        いなければ ``None``。
    params_problem
        Why `params` is ``None``; empty otherwise.
        `params` が ``None`` である理由。そうでなければ空。
    raw
        The raw height image, or why there is none.
        生の高さ画像、またはそれが無い理由。
    raw_aligned
        `raw` cut to the frame of the stored arrays; ``None`` without a raw
        image.
        `raw` を保存された配列の座標系へ切り出したもの。生の画像が無ければ
        ``None``。
    background
        The repeated background stage; ``None`` without a raw image or
        without usable settings.
        やり直した背景補正。生の画像または使える設定が無ければ ``None``。
    fibers
        The fibers `measure.load_tracking_image` builds from the bundle, one
        per traced skeleton component, before any connection.
        `measure.load_tracking_image` がバンドルから組み立てる繊維。追跡した
        スケルトン成分ごとに 1 本で、連結する前のもの。
    pixel_aspect
        Y pixel size over X pixel size of the stored arrays.
        保存された配列の、Y のサンプリング間隔を X のサンプリング間隔で割った値。
    """

    bundle_path: str
    arrays: Dict[str, np.ndarray]
    meta: Dict
    params: Optional[ProcParams]
    params_problem: str
    raw: RawHeight
    raw_aligned: Optional[np.ndarray]
    background: Optional[BackgroundRebuild]
    fibers: List[Fiber]
    pixel_aspect: float

    @property
    def fiber_mask(self) -> Optional[np.ndarray]:
        """
        Fiber mask of the background stage, or ``None``.
        背景補正の繊維マスク。無ければ ``None``。

        It is the mask of the repeated stage, or, when the stage could not be
        repeated, the mask an edited bundle stores.
        やり直した補正のマスクである。補正をやり直せなかった場合は、編集した
        バンドルが保存しているマスクである。
        """
        if self.background is not None:
            return self.background.fiber_mask
        stored = self.arrays.get(FIBER_MASK_KEY)
        return None if stored is None else np.asarray(stored).astype(bool)

    @property
    def centerlines(self) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        ``(x, y)`` of the line each fiber is measured along, in stored pixels.
        各繊維を計測する線の ``(x, y)``。保存された配列の画素座標。
        """
        return [fiber_line(fiber) for fiber in self.fibers]

    @property
    def format_version(self) -> Optional[str]:
        """
        Bundle format version the session's bundle records, or ``None``.
        セッションのバンドルが記録する形式バージョン。無ければ ``None``。
        """
        version = self.meta.get("version")
        return None if version is None else str(version)

    @property
    def editable(self) -> bool:
        """
        Whether the bundle can be edited and saved.
        このバンドルを編集して保存できるかどうか。

        Only a bundle of the current format can: an edit is saved in that
        format, and the values an older format stores were computed by other
        conventions, which an edit would then mix with the current ones.
        現在の形式のバンドルに限る。編集はその形式で保存するが、古い形式が保存する
        値は別の約束事で計算されており、編集するとそれが現在の値と混ざるためである。
        """
        return self.format_version == BUNDLE_FORMAT_VERSION


def _sha256_of_file(path: str) -> str:
    """
    Return the SHA-256 hex digest of a file.
    ファイルの SHA-256 を 16 進文字列で返す。
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _recorded_text_format(meta: Dict) -> object:
    """
    Return the text layout a bundle records, or ``"auto"`` without one.
    バンドルが記録するテキストのレイアウトを返す。記録が無ければ ``"auto"``。

    Reading with the recorded layout repeats what the analysis read even where
    the automatic detection of this version would decide differently.
    記録されたレイアウトで読むことで、このバージョンの自動判定が別の結論を出す
    場合でも、解析が読んだものをそのまま読み直す。
    """
    recorded = meta.get("input_format")
    if not isinstance(recorded, dict):
        return "auto"
    try:
        return AfmTextFormat(
            kind=str(recorded["kind"]),
            skiprows=int(recorded["skiprows"]),
            n_cols=int(recorded["n_cols"]),
            encoding=str(recorded["encoding"]),
        )
    except (KeyError, TypeError, ValueError):
        return "auto"


def load_input_height(path: str, meta: Dict) -> np.ndarray:
    """
    Read an analysis's input file the way the bundle records it was read.
    解析の入力ファイルを、バンドルが記録する読み方で読む。

    Parameters
    ----------
    path
        The input file: an AFM text/CSV export or a Gwyddion ``.gwy``.
        入力ファイル。AFM のテキスト/CSV エクスポート、または Gwyddion の ``.gwy``。
    meta
        The bundle's vlmeta. Its ``input_format`` names the text layout or
        the ``.gwy`` channel, and its ``source_region`` the analyzed scan
        lines.
        バンドルの vlmeta。``input_format`` がテキストのレイアウトまたは ``.gwy``
        のチャンネルを、``source_region`` が解析した走査線を示す。

    Returns
    -------
    numpy.ndarray
        Heights in nanometers, cut to the analyzed scan lines.
        高さ（nm）。解析した走査線へ切り出し済み。

    Raises
    ------
    ValueError
        If the recorded scan-line range does not fit the file.
    """
    if os.path.splitext(path)[1].lower() == ".gwy":
        # Local import keeps the feature-specific gwyfile dependency out of
        # text-only use.
        # ローカル import により、.gwy 用の gwyfile 依存をテキストだけの利用から外す。
        from .gwy_io import load_gwy_image
        recorded = meta.get("input_format")
        channel = recorded.get("channel_id") if isinstance(recorded, dict) else None
        height = load_gwy_image(path, channel=channel).data
    else:
        height = load_afm_text(path, fmt=_recorded_text_format(meta))

    region = meta.get(SOURCE_REGION_KEY)
    if isinstance(region, dict):
        start, stop = int(region["row_start"]), int(region["row_stop"])
        rows = int(np.asarray(height).shape[0])
        if not (0 <= start < stop <= rows) or int(region.get("row_total", rows)) != rows:
            raise ValueError(
                f"recorded scan lines {start}-{stop} of {region.get('row_total')} "
                f"do not fit the {rows} scan lines of {os.path.basename(path)}"
            )
        height = np.ascontiguousarray(height[start:stop])
    return height


def find_raw_height(
    bundle_path: str, meta: Dict, original: Optional[np.ndarray] = None,
) -> RawHeight:
    """
    Find the raw height image a bundle was analyzed from.
    バンドルの解析の元になった生の高さ画像を探す。

    Parameters
    ----------
    bundle_path
        Path of the bundle; the input file is looked for in its folder.
        バンドルのパス。入力ファイルはそのフォルダで探す。
    meta
        The bundle's vlmeta.
        バンドルの vlmeta。
    original
        The bundle's ``original`` array when it has one.
        バンドルが持つ場合の ``original`` 配列。

    Returns
    -------
    RawHeight
        The image and where it came from, or the reason there is none.
        画像とその読み込み元、または画像が無い理由。

    Notes
    -----
    The bundle's own ``original`` is used first. Otherwise the file named by
    ``input_file`` is taken from the bundle's folder, and only when its
    SHA-256 equals the recorded ``input_sha256``: a file of the same name with
    other contents would be drawn under an analysis it does not belong to. A
    bundle that records no digest cannot be checked this way; its file is
    read, and `rebuild_background` then tells whether it reproduces the
    stored heights.
    まずバンドル自身の ``original`` を使う。無ければ、``input_file`` の名前の
    ファイルをバンドルのフォルダから取る。ただし SHA-256 が記録された
    ``input_sha256`` と等しい場合に限る。同じ名前で中身の違うファイルは、それとは
    無関係な解析の下に描かれてしまうためである。ダイジェストを記録していない
    バンドルはこの方法で確かめられないので、ファイルを読み、保存済みの高さを
    再現するかどうかを `rebuild_background` が伝える。
    """
    if original is not None:
        return RawHeight(np.asarray(original), source=RAW_FROM_BUNDLE)

    name = meta.get("input_file")
    if not name:
        return RawHeight(None, problem=RAW_MISSING_NOT_RECORDED)
    name = os.path.basename(str(name))
    path = os.path.join(os.path.dirname(os.path.abspath(bundle_path)), name)
    if not os.path.isfile(path):
        return RawHeight(None, problem=RAW_MISSING_NOT_FOUND, detail=name)
    recorded = meta.get("input_sha256")
    try:
        if recorded and _sha256_of_file(path) != recorded:
            return RawHeight(None, problem=RAW_MISSING_CHANGED, detail=name)
        height = load_input_height(path, meta)
    except Exception as exc:  # noqa: BLE001 - any read failure leaves the session without a raw image
        return RawHeight(None, problem=RAW_MISSING_UNREADABLE,
                         detail=f"{name}: {type(exc).__name__}: {exc}")
    return RawHeight(np.asarray(height), source=RAW_FROM_INPUT_FILE, detail=name)


def align_raw(raw: np.ndarray, stored_shape: Tuple[int, int]) -> Optional[np.ndarray]:
    """
    Cut a raw height image to the frame of a bundle's stored arrays.
    生の高さ画像を、バンドルの保存された配列の座標系へ切り出す。

    Parameters
    ----------
    raw
        Raw heights as the background stage received them.
        背景補正が受け取ったままの生の高さ。
    stored_shape
        Shape of the bundle's ``calibrated``.
        バンドルの ``calibrated`` の形状。

    Returns
    -------
    numpy.ndarray or None
        ``raw[1:, 1:]``, or ``None`` when that is not `stored_shape`.
        ``raw[1:, 1:]``。それが `stored_shape` でなければ ``None``。

    Notes
    -----
    Every background method subtracts from ``original[1:, 1:]``, because the
    difference images the fiber mask is built from are one row and one column
    shorter than the scan. The stored arrays therefore start at raw pixel
    (1, 1).
    どの背景補正の方式も ``original[1:, 1:]`` から差し引く。繊維マスクの元になる
    差分画像が、走査より 1 行 1 列短いためである。したがって保存された配列は、
    生の画像の画素 (1, 1) から始まる。
    """
    raw = np.asarray(raw)
    if raw.ndim != 2:
        return None
    cut = raw[1:, 1:]
    return cut if cut.shape == tuple(stored_shape) else None


def rebuild_background(
    raw: np.ndarray, params: ProcParams, stored_calibrated: np.ndarray,
    given_mask: Optional[np.ndarray] = None,
) -> BackgroundRebuild:
    """
    Repeat a bundle's background stage and compare it with what was stored.
    バンドルの背景補正をやり直し、保存されたものと比べる。

    Parameters
    ----------
    raw
        Raw heights as the background stage received them.
        背景補正が受け取ったままの生の高さ。
    params
        Analysis settings the bundle records.
        バンドルが記録する解析設定。
    stored_calibrated
        The bundle's ``calibrated``.
        バンドルの ``calibrated``。
    given_mask
        The fiber mask an edited bundle stores (`bundle_schema.FIBER_MASK_KEY`).
        The stage is then repeated with that mask instead of detecting one,
        which is how the edited bundle's own heights were computed.
        編集したバンドルが保存する繊維マスク（`bundle_schema.FIBER_MASK_KEY`）。
        このときマスクを検出せず、そのマスクで補正をやり直す。編集したバンドル
        自身の高さは、そうして計算されたものだからである。

    Returns
    -------
    BackgroundRebuild
        The repeated heights, the fiber mask and the comparison.
        やり直した高さ、繊維マスク、比較の結果。

    Notes
    -----
    The calibrator keeps ``bg_only``, the raw image with the masked pixels
    blanked to NaN, so the mask its fill used is read from there instead of
    being recomputed beside it. A raw pixel that is itself NaN is blank
    whether or not the mask covered it, and is left out of the mask.
    補正器は ``bg_only``（マスクした画素を NaN にした生の画像）を保持するので、
    穴埋めが使ったマスクは、横で計算し直さずにそこから読む。生の画素そのものが
    NaN のものは、マスクが覆っていたかどうかによらず空になるため、マスクには
    含めない。
    """
    stages = build_stages(params)
    image = ProcessedImage(original_AFM=raw, name="")
    uses_mask = params.bg_method in MASK_BG_METHODS
    if uses_mask and given_mask is not None:
        fiber_mask = np.asarray(given_mask).astype(bool)
        stages.bg_calibrator.calibrate_with_mask(image, fiber_mask)
    else:
        stages.bg_calibrator(image)
        fiber_mask = None
        if uses_mask:
            bg_only = np.asarray(stages.bg_calibrator.bg_only)
            fiber_mask = np.isnan(bg_only) & ~np.isnan(np.asarray(raw)[1:, 1:])
    calibrated = np.asarray(image.calibrated_image)

    stored = np.asarray(stored_calibrated)
    if stored.shape != calibrated.shape:
        return BackgroundRebuild(calibrated, fiber_mask, False, None)
    reproduces = bool(np.array_equal(stored, calibrated, equal_nan=True))
    difference = np.abs(stored.astype(np.float64) - calibrated.astype(np.float64))
    finite = np.isfinite(difference)
    max_difference = float(difference[finite].max()) if finite.any() else 0.0
    return BackgroundRebuild(calibrated, fiber_mask, reproduces, max_difference)


def fiber_line(fiber: Fiber) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return the line a fiber is measured along, in pixels of the stored arrays.
    繊維を計測する線を、保存された配列の画素座標で返す。

    A fiber stores its line relative to the origin of its bounding box, which
    `Fiber.data` starts with.
    繊維は線を外接矩形の原点基準で保存する。その原点は `Fiber.data` の先頭にある。
    """
    return (np.asarray(fiber.xtrack, dtype=np.float64) + float(fiber.data[0]),
            np.asarray(fiber.ytrack, dtype=np.float64) + float(fiber.data[1]))


def fiber_pixels(fiber: Fiber) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return the skeleton pixels of a fiber, in pixels of the stored arrays.
    繊維のスケルトン画素を、保存された配列の画素座標で返す。

    One pixel per point of `fiber_line`, in the same order. Kinks are stored
    at these pixels.
    `fiber_line` の点ごとに 1 画素で、順番も同じ。キンクはこの画素に保存される。
    """
    track_x, track_y = skeleton_track(fiber)
    return (np.asarray(track_x, dtype=np.int64) + int(fiber.data[0]),
            np.asarray(track_y, dtype=np.int64) + int(fiber.data[1]))


def trace_fibers(
    bundle_path: str, meta: Dict, stored_shape: Tuple[int, int],
) -> List[Fiber]:
    """
    Build the fibers of a bundle as the measuring GUIs build them.
    バンドルの繊維を、計測する GUI と同じ方法で組み立てる。

    Parameters
    ----------
    bundle_path
        Path of the bundle.
        バンドルのパス。
    meta
        The bundle's vlmeta, for the recorded scan size.
        バンドルの vlmeta。記録された走査範囲を読む。
    stored_shape
        Shape of the bundle's ``calibrated``.
        バンドルの ``calibrated`` の形状。

    Returns
    -------
    list of Fiber
        One fiber per traced skeleton component, in label order.
        追跡したスケルトン成分ごとに 1 本の繊維。ラベル順。

    Notes
    -----
    The fibers are built by `measure.load_tracking_image`, which GUI03 and
    GUI04 measure through, so their lines are the lines those measure along
    for this bundle's format. Only pixel coordinates are read from them here,
    so a bundle without a recorded scan size is traced with a pixel size of 1.
    繊維は `measure.load_tracking_image` で組み立てる。GUI03 と GUI04 が計測に使う
    関数なので、その線は、このバンドルの形式についてそれらが計測する線と同じに
    なる。ここで読むのは画素座標だけなので、走査範囲を記録していないバンドルは
    サンプリング間隔を 1 として追跡する。
    """
    # Imported here: tracing loads the measurement stack, which a caller that
    # only needs the raw image or the mask does not use.
    # ここでインポートする。追跡は計測の一式を読み込むが、生の画像やマスクだけが
    # 要る呼び出し側はそれを使わないためである。
    from .measure import load_tracking_image

    scan_size = scan_size_um_from_meta(meta)
    if scan_size is not None and stored_shape[0] > 0 and stored_shape[1] > 0:
        x_nm = pixel_size_nm(scan_size[0], stored_shape[1])
        y_nm = pixel_size_nm(scan_size[1], stored_shape[0])
    else:
        x_nm = y_nm = 1.0
    tracking = load_tracking_image(bundle_path, x_nm, y_nm)
    return list(tracking.fibers_in_image_parallel())


def load_edit_session(
    bundle_path: str, on_step: Optional[Callable[[str], None]] = None,
) -> EditSession:
    """
    Open a bundle for editing.
    バンドルを編集のために開く。

    Parameters
    ----------
    bundle_path
        Path to a ``.b2z`` bundle written by `pipeline.process_file`.
        `pipeline.process_file` が書いた ``.b2z`` バンドルのパス。
    on_step
        Called with each key of `LOAD_STEPS` as that step starts.
        `LOAD_STEPS` の各キーを、その段階の開始時に受け取るコールバック。

    Returns
    -------
    EditSession
        The stored arrays with the raw image, the repeated background stage
        and the fibers, as far as each could be obtained.
        保存された配列と、得られた範囲での生の画像・やり直した背景補正・繊維。

    Raises
    ------
    ValueError
        If the bundle violates the ``.b2z`` contract
        (`bundle_schema.validate_bundle`).

    Notes
    -----
    A missing raw image or unusable settings do not fail the load: the stored
    arrays can still be shown, and the session says what is missing (`raw`,
    `params_problem`) so the caller can tell the user.
    生の画像が無い、または設定が使えない場合も、読み込みは失敗しない。保存された
    配列は表示でき、何が無いかをセッションが示す（`raw`・`params_problem`）ので、
    呼び出し側が利用者に伝えられる。
    """
    def step(key: str) -> None:
        if on_step is not None:
            on_step(key)

    step("read")
    arrays = load_bundle(bundle_path)
    meta = load_bundle_meta(bundle_path)
    problems = validate_bundle(arrays, meta=meta, require=REQUIRED_BUNDLE_KEYS)
    if problems:
        raise ValueError("; ".join(problems))
    stored_shape = tuple(np.asarray(arrays["calibrated"]).shape)

    step("raw")
    raw = find_raw_height(bundle_path, meta, arrays.get("original"))
    raw_aligned = None
    if raw.height is not None:
        raw_aligned = align_raw(raw.height, stored_shape)
        if raw_aligned is None:
            raw = RawHeight(None, problem=RAW_MISSING_SHAPE, detail=raw.detail)

    params: Optional[ProcParams] = None
    params_problem = ""
    recorded = meta.get(PARAMS_KEY)
    if isinstance(recorded, dict):
        try:
            params = merge_params_dict(recorded)[0]
        except Exception as exc:  # noqa: BLE001 - e.g. a removed bg_method; reported, not fatal
            params_problem = f"{type(exc).__name__}: {exc}"
    else:
        params_problem = "no analysis settings recorded"

    step("background")
    background = None
    if raw.height is not None and params is not None:
        background = rebuild_background(
            raw.height, params, arrays["calibrated"],
            given_mask=arrays.get(FIBER_MASK_KEY))

    step("centerline")
    fibers = trace_fibers(bundle_path, meta, stored_shape)

    return EditSession(
        bundle_path=bundle_path,
        arrays=arrays,
        meta=meta,
        params=params,
        params_problem=params_problem,
        raw=raw,
        raw_aligned=raw_aligned,
        background=background,
        fibers=fibers,
        pixel_aspect=float(pixel_aspect_from_meta(meta, stored_shape)),
    )


def arm_angle(
    first_start: Tuple[float, float], first_end: Tuple[float, float],
    second_start: Tuple[float, float], second_end: Tuple[float, float],
) -> float:
    """
    Return the angle between two arms, each given by its start and its end.
    始点と終点で与えた 2 本の腕のなす角を返す。

    Parameters
    ----------
    first_start, first_end
        ``(x, y)`` of the point the first arm starts at, beside the kink, and
        of its end.
        1 本目の腕がキンクのそばで始まる点と、その端の ``(x, y)``。
    second_start, second_end
        The same for the second arm.
        2 本目の腕についての同じもの。

    Returns
    -------
    float
        The angle between the two directions pointing away from the kink, in
        radians: pi for arms in line, 0 for arms folded onto each other. NaN
        when an arm has no length.
        キンクから遠ざかる 2 つの向きのなす角（ラジアン）。腕が一直線なら pi、
        折り重なっていれば 0。腕に長さが無い場合は NaN。
    """
    ax, ay = first_end[0] - first_start[0], first_end[1] - first_start[1]
    bx, by = second_end[0] - second_start[0], second_end[1] - second_start[1]
    if (ax == 0.0 and ay == 0.0) or (bx == 0.0 and by == 0.0):
        return float("nan")
    return float(np.arctan2(abs(ax * by - ay * bx), ax * bx + ay * by))


class KinkEditor:
    """
    The kinks of an opened bundle, changed by hand.
    開いたバンドルのキンクを、手で変更するためのもの。

    A kink is stored at a skeleton pixel of a fiber, and the editor keeps that
    contract: a kink can be put only on a pixel of a traced fiber.
    キンクは繊維のスケルトン画素に保存される。エディタはこの約束事を守り、キンクを
    置けるのは追跡した繊維の画素の上だけとする。

    The angle of a kink a person places is set by two points the person
    chooses, the ends of its arms, one on either side of the kink on the same
    fiber. Each arm runs to its end from the point `ARM_GAP_WIDTHS` apparent
    widths along the line from the kink, and the angle is the one between the
    two arms (`arm_angle`). The kink and the ends are skeleton pixels, where a
    person can point; the arms are read at the points of the fiber's line that
    belong to them, with Y scaled by the pixel aspect, because the pixels of a
    skeleton lie on a staircase that would enter the angle. The excess turning
    stored with such a kink is pi minus its angle, the turning between its
    arms.
    人が置くキンクの角度は、人が選ぶ 2 つの点、すなわち腕の端で決める。端は、同じ
    繊維の上で、キンクの両側に 1 つずつ置く。各腕は、キンクから線に沿って見かけ幅の
    `ARM_GAP_WIDTHS` 倍だけ離れた点から端までで、角度は 2 本の腕のなす角である
    （`arm_angle`）。キンクと端はスケルトン画素で、人はそこを指し示せる。腕は、
    それらに対応する繊維の線の点で、Y を画素の縦横比で拡大して読む。スケルトンの
    画素は階段状に並び、それが角度に入ってしまうためである。こうしたキンクとともに
    保存する超過回転は、pi から内角を引いたもの、すなわち腕の間の回転である。

    A kink the bundle stores keeps the angle and the excess turning the kink
    rule stored, until a person moves one of its arm ends. Nothing else
    changes it: adding, moving or removing another mark leaves it as stored.
    バンドルが保存するキンクは、人がその腕の端を動かすまで、キンク規則が保存した
    内角と超過回転を保つ。ほかの操作では変わらない。別の印を足す・動かす・除く
    ことは、それを保存されたままにする。

    Parameters
    ----------
    fibers
        The fibers of the bundle (`EditSession.fibers`).
        バンドルの繊維（`EditSession.fibers`）。
    arrays
        The bundle's arrays; ``kp``, ``ka`` and, when stored, ``ke`` and
        ``up`` are read.
        バンドルの配列。``kp``・``ka`` と、保存されていれば ``ke``・``up`` を読む。
    pixel_aspect
        Y pixel size over X pixel size, used to compare pointer distances.
        Y のサンプリング間隔を X のサンプリング間隔で割った値。ポインタからの距離を
        比べるのに使う。
    kink_arms
        The bundle's `bundle_schema.KINK_ARMS_KEY` entry: the kinks whose
        angle a person set, with their arm ends.
        バンドルの `bundle_schema.KINK_ARMS_KEY` の項目。人が角度を決めたキンクと、
        その腕の端。
    """

    def __init__(
        self, fibers: Sequence[Fiber], arrays: Dict[str, np.ndarray],
        pixel_aspect: float = 1.0,
        kink_arms: Optional[Iterable[Sequence[int]]] = None,
    ) -> None:
        self._aspect = float(pixel_aspect)
        self._kinks: Dict[Pixel, List] = {}
        self._unjudged: Set[Pixel] = set()
        self.set_fibers(fibers)
        self._read_marks(arrays)
        for entry in kink_arms or ():
            self._adopt_arms(entry)
        self._saved = self._snapshot()
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []

    def set_fibers(self, fibers: Sequence[Fiber]) -> None:
        """
        Take the fibers the marks lie on, as traced from the current skeleton.
        印が載る繊維を、現在のスケルトンから追跡したものとして受け取る。

        Parameters
        ----------
        fibers
            The fibers of the bundle as it stands now.
            現在の状態のバンドルの繊維。

        Notes
        -----
        The marks and their history are untouched: a kink is a pixel with its
        values, and its arm ends are pixels too, so they stay meaningful when
        the skeleton around them is edited and the fibers are traced again.
        A kink whose pixel is on no fiber afterwards is listed in `off_track`.
        印とその履歴は変えない。キンクは画素とその値であり、腕の端も画素なので、
        周りのスケルトンを編集して繊維を追跡し直しても意味を保つ。追跡し直したあと
        どの繊維の上にも無い画素のキンクは、`off_track` に挙がる。
        """
        self._fibers = list(fibers)
        self._tracks = [fiber_pixels(fiber) for fiber in self._fibers]
        # Each fiber's line with Y scaled by its pixel aspect, the geometry
        # angles and distances along the line are read in.
        # 各繊維の線。Y をその画素の縦横比で拡大してあり、角度と線に沿った距離は
        # この幾何で読む。
        self._lines = []
        self._arcs = []
        for fiber in self._fibers:
            line_x, line_y = fiber_line(fiber)
            line_y = line_y * float(fiber.pixel_aspect)
            self._lines.append((line_x, line_y))
            self._arcs.append(np.concatenate(
                [[0.0], np.cumsum(np.hypot(np.diff(line_x), np.diff(line_y)))]))
        # Where each skeleton pixel sits: (fiber, index along its line).
        # 各スケルトン画素の位置：（繊維、線に沿ったインデックス）。
        self._where: Dict[Pixel, Tuple[int, int]] = {}
        for number, (track_x, track_y) in enumerate(self._tracks):
            for index, pixel in enumerate(zip(track_x.tolist(), track_y.tolist())):
                self._where.setdefault(pixel, (number, index))
        if self._tracks:
            self._all_x = np.concatenate([track[0] for track in self._tracks])
            self._all_y = np.concatenate([track[1] for track in self._tracks])
        else:
            self._all_x = np.zeros(0, dtype=np.int64)
            self._all_y = np.zeros(0, dtype=np.int64)

    def _read_marks(self, arrays: Dict[str, np.ndarray]) -> None:
        """
        Set the marks from bundle arrays, every kink keeping the stored values.
        バンドルの配列から印を設定する。どのキンクも保存された値を保つ。
        """
        kinks = np.asarray(arrays["kp"])
        angles = np.asarray(arrays["ka"], dtype=np.float64)
        stored_excess = arrays.get("ke")
        excess = (np.asarray(stored_excess, dtype=np.float64)
                  if stored_excess is not None and len(stored_excess) == kinks.shape[1]
                  else np.zeros(kinks.shape[1], dtype=np.float64))
        # Pixel -> [angle, excess, arms]; arms is None for a kink that keeps
        # the stored values, or the pixels of its two arm ends.
        # 画素 -> [内角, 超過回転, 腕]。腕は、保存された値を保つキンクでは None、
        # そうでなければ 2 つの腕の端の画素。
        self._kinks = {
            (int(x), int(y)): [float(angle), float(value), None]
            for x, y, angle, value in zip(kinks[0], kinks[1], angles, excess)
        }
        unjudged = np.asarray(arrays.get("up", np.zeros((2, 0), dtype=np.int64)))
        self._unjudged = {(int(x), int(y)) for x, y in zip(unjudged[0], unjudged[1])}

    def replace_marks(self, arrays: Dict[str, np.ndarray]) -> None:
        """
        Replace every mark by those of bundle arrays, as one undoable change.
        すべての印を、バンドルの配列の印で置き換える。元に戻せる 1 回の変更とする。

        Parameters
        ----------
        arrays
            ``kp``, ``ka`` and, when present, ``ke`` and ``up``, as the kink
            stage writes them.
            キンク検出の段が書く ``kp``・``ka`` と、あれば ``ke``・``up``。
        """
        snapshot = self._snapshot()
        self._read_marks(arrays)
        self._commit(snapshot)

    @property
    def off_track(self) -> Tuple[Pixel, ...]:
        """
        Kinks that lie on no fiber's pixels.
        どの繊維の画素の上にも無いキンク。

        They are kept as stored and can only be removed.
        保存されたまま保ち、除くことだけができる。
        """
        return tuple(sorted(pixel for pixel in self._kinks if pixel not in self._where))

    def _arm_indices(self, pixel: Pixel) -> Optional[Tuple[int, int]]:
        """
        Line indices of a kink's arm ends, or ``None`` when it has none that fit.
        キンクの腕の端の線上のインデックス。合う端を持たなければ ``None``。

        Ends fit when both lie on the kink's fiber, one on either side of it.
        Ends that no longer do, after the skeleton was edited, are ignored:
        the kink then keeps its values and is treated like one without ends.
        端が合うとは、両方がキンクの繊維の上にあり、キンクの両側に 1 つずつある
        ことである。スケルトンの編集のあとで合わなくなった端は無視する。その
        キンクは値を保ち、端を持たないキンクと同じに扱う。
        """
        values = self._kinks.get(pixel)
        place = self._where.get(pixel)
        if values is None or values[2] is None or place is None:
            return None
        first = self._where.get(values[2][0])
        second = self._where.get(values[2][1])
        if first is None or second is None:
            return None
        number, index = place
        if first[0] != number or second[0] != number or not first[1] < index < second[1]:
            return None
        return first[1], second[1]

    def _adopt_arms(self, entry: Sequence[int]) -> None:
        """
        Take the recorded arm ends of one kink, if they fit the fibers.
        1 つのキンクについて記録された腕の端を、繊維に合う場合に取り込む。

        An entry that names no stored kink, or ends that are not on the kink's
        fiber on either side of it, is left out; the kink then keeps its
        stored values like one the rule placed.
        保存済みのキンクを指さない項目や、キンクの繊維の上で両側に無い端は取り込ま
        ない。そのキンクは、規則が置いたキンクと同じく、保存された値を保つ。
        """
        try:
            kink_x, kink_y, first_x, first_y, second_x, second_y = (int(v) for v in entry)
        except (TypeError, ValueError):
            return
        pixel = (kink_x, kink_y)
        values = self._kinks.get(pixel)
        place = self._where.get(pixel)
        first = self._where.get((first_x, first_y))
        second = self._where.get((second_x, second_y))
        if values is None or place is None or first is None or second is None:
            return
        number, index = place
        if first[0] != number or second[0] != number or not first[1] < index < second[1]:
            return
        values[2] = ((first_x, first_y), (second_x, second_y))

    # ----- State -----

    def _snapshot(self) -> tuple:
        """
        Copy the current marks.
        現在の印を複製する。
        """
        return ({pixel: list(values) for pixel, values in self._kinks.items()},
                set(self._unjudged))

    def _restore(self, snapshot: tuple) -> None:
        """
        Replace the current marks with a copy of a snapshot.
        現在の印を、スナップショットの複製で置き換える。
        """
        kinks, unjudged = snapshot
        self._kinks = {pixel: list(values) for pixel, values in kinks.items()}
        self._unjudged = set(unjudged)

    @property
    def modified(self) -> bool:
        """
        Whether the marks differ from those last loaded or saved.
        印が、最後に読み込んだ、または保存したものと違うかどうか。
        """
        return self._snapshot() != self._saved

    @property
    def can_undo(self) -> bool:
        """
        Whether a change can be undone.
        元に戻せる変更があるかどうか。
        """
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """
        Whether an undone change can be applied again.
        やり直せる変更があるかどうか。
        """
        return bool(self._redo)

    def undo(self) -> bool:
        """
        Take back the last change; ``False`` when there is none.
        直前の変更を取り消す。変更が無ければ ``False``。
        """
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        """
        Apply the last undone change again; ``False`` when there is none.
        直前に取り消した変更をやり直す。無ければ ``False``。
        """
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def mark_saved(self) -> None:
        """
        Take the current marks as the saved ones.
        現在の印を、保存済みのものとする。
        """
        self._saved = self._snapshot()

    def _commit(self, snapshot: tuple) -> None:
        """
        Record the state before a change that has been made.
        行った変更の前の状態を記録する。
        """
        self._undo.append(snapshot)
        self._redo.clear()

    # ----- Reading -----

    def kink_pixels(self) -> List[Pixel]:
        """
        Return the kinks' pixels, fiber by fiber along each line.
        キンクの画素を、繊維ごとに線に沿った順で返す。

        Kinks on no fiber's pixels (`off_track`) come last.
        どの繊維の画素の上にも無いキンク（`off_track`）は最後に来る。
        """
        on_track = sorted(
            (pixel for pixel in self._kinks if pixel in self._where),
            key=lambda pixel: self._where[pixel])
        return on_track + sorted(
            pixel for pixel in self._kinks if pixel not in self._where)

    def unjudged_pixels(self) -> List[Pixel]:
        """
        Return the pixels of the bends that were measured and not judged.
        測ったが判定しなかった折れの画素を返す。
        """
        return sorted(self._unjudged, key=lambda pixel: self._where.get(
            pixel, (len(self._tracks), 0)) + pixel)

    def kink_values(self, pixel: Pixel) -> Optional[Tuple[float, float]]:
        """
        Return ``(angle, excess)`` of the kink at a pixel, in radians.
        ある画素のキンクの ``(内角, 超過回転)`` をラジアンで返す。
        """
        values = self._kinks.get((int(pixel[0]), int(pixel[1])))
        return None if values is None else (values[0], values[1])

    def angle_is_set_by_hand(self, pixel: Pixel) -> bool:
        """
        Whether a kink's angle comes from arm ends a person placed.
        キンクの角度が、人が置いた腕の端から決まっているかどうか。
        """
        return self._arm_indices((int(pixel[0]), int(pixel[1]))) is not None

    def arrays(self) -> Dict[str, np.ndarray]:
        """
        Return the bundle arrays the current marks stand for.
        現在の印に対応するバンドルの配列を返す。

        Returns
        -------
        dict
            ``kp`` and ``up`` of shape ``(2, N)`` holding x then y, and ``ka``
            and ``ke`` in radians index-aligned with ``kp``.
            x・y の順に持つ形状 ``(2, N)`` の ``kp`` と ``up``、および ``kp`` と
            添字が揃うラジアンの ``ka`` と ``ke``。
        """
        kinks = self.kink_pixels()
        unjudged = self.unjudged_pixels()
        return {
            "kp": np.array(kinks, dtype=np.int64).reshape(-1, 2).T,
            "ka": np.array([self._kinks[pixel][0] for pixel in kinks], dtype=np.float64),
            "ke": np.array([self._kinks[pixel][1] for pixel in kinks], dtype=np.float64),
            "up": np.array(unjudged, dtype=np.int64).reshape(-1, 2).T,
        }

    def kink_arms(self) -> List[List[int]]:
        """
        Return the `bundle_schema.KINK_ARMS_KEY` entry for the current kinks.
        現在のキンクについての `bundle_schema.KINK_ARMS_KEY` の項目を返す。

        Returns
        -------
        list
            ``[kink_x, kink_y, first_x, first_y, second_x, second_y]`` for
            every kink whose angle a person set, in the order of `kink_pixels`.
            人が角度を決めたキンクごとの
            ``[kink_x, kink_y, first_x, first_y, second_x, second_y]``。
            `kink_pixels` の順。
        """
        table = []
        for pixel in self.kink_pixels():
            if self._arm_indices(pixel) is None:
                continue
            first, second = self._kinks[pixel][2]
            table.append([pixel[0], pixel[1], first[0], first[1], second[0], second[1]])
        return table

    # ----- Arms -----

    def _arm_pixels(self, pixel: Pixel, arms: Tuple[int, int]) -> Tuple[Pixel, Pixel]:
        """
        Skeleton pixels of a kink's two arm ends.
        キンクの 2 つの腕の端のスケルトン画素。
        """
        track_x, track_y = self._tracks[self._where[pixel][0]]
        return ((int(track_x[arms[0]]), int(track_y[arms[0]])),
                (int(track_x[arms[1]]), int(track_y[arms[1]])))

    def _arm_starts(self, number: int, index: int, arms: Tuple[int, int]) -> Tuple[int, int]:
        """
        Line indices of the points a kink's two arms start at.
        キンクの 2 本の腕が始まる点の、線上のインデックス。

        Each arm starts at the line point nearest `ARM_GAP_WIDTHS` × W along
        the line from the kink, toward its end. Where the end lies nearer than
        twice that distance, the arm starts at the point nearest halfway to
        the end, so an end beside the kink still leaves an arm, which then
        starts at the kink itself.
        各腕は、キンクからその端のほうへ、線に沿って `ARM_GAP_WIDTHS` × W に最も近い
        線の点で始まる。端がその距離の 2 倍より近い場合は、端までの中間に最も近い点で
        始まる。こうすると、キンクの隣に置いた端でも腕が残り、そのとき腕はキンク
        自身から始まる。
        """
        arc = self._arcs[number]
        width = float(self._fibers[number].width_px)
        gap = ARM_GAP_WIDTHS * width if np.isfinite(width) and width > 0 else 0.0
        first, second = arms
        before = arc[index] - min(gap, 0.5 * (arc[index] - arc[first]))
        after = arc[index] + min(gap, 0.5 * (arc[second] - arc[index]))
        first_start = first + 1 + int(np.argmin(np.abs(arc[first + 1:index + 1] - before)))
        second_start = index + int(np.argmin(np.abs(arc[index:second] - after)))
        return first_start, second_start

    def _angle(self, number: int, index: int, arms: Tuple[int, int]) -> float:
        """
        Angle between the two arms of a kink at a line point.
        線上の 1 点にあるキンクの、2 本の腕のなす角。
        """
        line_x, line_y = self._lines[number]
        first_start, second_start = self._arm_starts(number, index, arms)
        angle = arm_angle(
            (line_x[first_start], line_y[first_start]),
            (line_x[arms[0]], line_y[arms[0]]),
            (line_x[second_start], line_y[second_start]),
            (line_x[arms[1]], line_y[arms[1]]),
        )
        if not np.isfinite(angle):
            return angle
        return float(min(max(angle, _MIN_INTERIOR_ANGLE), np.pi - _MIN_INTERIOR_ANGLE))

    def default_arms(self, pixel: Pixel) -> Optional[Tuple[int, int]]:
        """
        Return the arm ends a kink at a fiber pixel is given when it is placed.
        繊維の画素に置いたキンクに、置いた時点で与える腕の端を返す。

        Parameters
        ----------
        pixel
            ``(x, y)`` of a pixel of a traced fiber.
            追跡した繊維の画素の ``(x, y)``。

        Returns
        -------
        tuple or None
            Line indices of the two ends, or ``None`` when the pixel is on no
            fiber or at an end of its line, where one side has no point.
            2 つの端の線上のインデックス。画素がどの繊維の上にも無いか、線の端に
            あって片側に点が無い場合は ``None``。

        Notes
        -----
        Each end lies `DEFAULT_ARM_WIDTHS` apparent widths along the line from
        the pixel, or nearer where the line ends or another mark comes first:
        an arm does not run through a neighbouring kink.
        各端は、画素から線に沿って見かけ幅の `DEFAULT_ARM_WIDTHS` 倍だけ離れた位置に
        置く。線の端や別の印がそれより手前にあれば、そこに置く。腕は隣のキンクを
        通り越さない。
        """
        place = self._where.get((int(pixel[0]), int(pixel[1])))
        if place is None:
            return None
        number, index = place
        arc = self._arcs[number]
        last = arc.size - 1
        if index <= 0 or index >= last:
            return None
        width = float(self._fibers[number].width_px)
        reach = DEFAULT_ARM_WIDTHS * width if np.isfinite(width) and width > 0 else 0.0
        first = int(np.argmin(np.abs(arc[:index] - (arc[index] - reach))))
        second = index + 1 + int(np.argmin(np.abs(arc[index + 1:] - (arc[index] + reach))))
        marks = [
            self._where[mark][1]
            for mark in list(self._kinks) + list(self._unjudged)
            if self._where.get(mark, (None, 0))[0] == number and mark != pixel
        ]
        before = [mark for mark in marks if mark < index]
        after = [mark for mark in marks if mark > index]
        if before:
            first = max(first, max(before))
        if after:
            second = min(second, min(after))
        return first, second

    def arm_ends(self, pixel: Pixel) -> Optional[Tuple[Pixel, Pixel, bool]]:
        """
        Return the two arm ends of a kink as skeleton pixels.
        キンクの 2 つの腕の端を、スケルトン画素で返す。

        Returns
        -------
        tuple or None
            ``(first, second, set_by_hand)``. For a kink that keeps the rule's
            values the ends are those it would be given if placed now, and
            `set_by_hand` is ``False``: they are where a drag would start
            from, not what its stored angle was read with. ``None`` for a
            pixel that holds no kink or allows no arms.
            ``(first, second, set_by_hand)``。規則の値を保つキンクでは、端は、いま
            置いたとすれば与えられるもので、`set_by_hand` は ``False`` になる。
            これはドラッグの出発点であり、保存された角度を読んだ位置ではない。
            キンクの無い画素や、腕を取れない画素では ``None``。
        """
        pixel = (int(pixel[0]), int(pixel[1]))
        if pixel not in self._kinks or pixel not in self._where:
            return None
        placed = self._arm_indices(pixel)
        arms = placed if placed is not None else self.default_arms(pixel)
        if arms is None:
            return None
        first, second = self._arm_pixels(pixel, arms)
        return first, second, placed is not None

    def measure_arms(
        self, pixel: Pixel, first: Pixel, second: Pixel,
    ) -> Optional[Tuple[float, List[Tuple[float, float]]]]:
        """
        Measure the angle a kink would have with two given arm ends.
        与えた 2 つの腕の端でキンクが持つことになる角度を測る。

        Parameters
        ----------
        pixel
            Pixel of the kink.
            キンクの画素。
        first, second
            Skeleton pixels of the two ends, on the kink's fiber on either
            side of it.
            2 つの端のスケルトン画素。キンクの繊維の上で、その両側にあるもの。

        Returns
        -------
        tuple or None
            ``(angle, points)``: the angle in radians, and the four points of
            the fiber's line the two arms run between -- first end, start of
            the first arm, start of the second arm, second end -- in pixels of
            the stored arrays, which is what to draw. ``None`` when the ends
            are not on the kink's fiber on either side of it.
            ``(angle, points)``。角度（ラジアン）と、2 本の腕が結ぶ繊維の線の 4 点
            （1 つ目の端、1 本目の腕の始点、2 本目の腕の始点、2 つ目の端）。点は
            保存された配列の画素座標で、描くのはこれである。端がキンクの繊維の上で
            両側に無ければ ``None``。
        """
        place = self._where.get((int(pixel[0]), int(pixel[1])))
        start = self._where.get((int(first[0]), int(first[1])))
        stop = self._where.get((int(second[0]), int(second[1])))
        if place is None or start is None or stop is None:
            return None
        number, index = place
        if start[0] != number or stop[0] != number or not start[1] < index < stop[1]:
            return None
        arms = (start[1], stop[1])
        angle = self._angle(number, index, arms)
        first_start, second_start = self._arm_starts(number, index, arms)
        line_x, line_y = fiber_line(self._fibers[number])
        points = [(float(line_x[i]), float(line_y[i]))
                  for i in (arms[0], first_start, second_start, arms[1])]
        return angle, points

    def nearest_arm_pixel(self, pixel: Pixel, side: int, x: float, y: float) -> Optional[Pixel]:
        """
        Return the pixel on one side of a kink nearest a position.
        キンクの片側の画素のうち、ある位置に最も近いものを返す。

        Parameters
        ----------
        pixel
            Pixel of the kink.
            キンクの画素。
        side
            `ARM_BEFORE` or `ARM_AFTER`.
            `ARM_BEFORE` または `ARM_AFTER`。
        x, y
            Position in image pixels.
            画像の画素単位の位置。

        Returns
        -------
        tuple or None
            A skeleton pixel of the kink's fiber on that side, or ``None``
            when the side has none.
            その側にある、キンクの繊維のスケルトン画素。その側に画素が無ければ
            ``None``。
        """
        place = self._where.get((int(pixel[0]), int(pixel[1])))
        if place is None:
            return None
        number, index = place
        track_x, track_y = self._tracks[number]
        if side == ARM_BEFORE:
            xs, ys, offset = track_x[:index], track_y[:index], 0
        else:
            xs, ys, offset = track_x[index + 1:], track_y[index + 1:], index + 1
        if xs.size == 0:
            return None
        nearest = offset + int(np.argmin(np.hypot(xs - x, (ys - y) * self._aspect)))
        return int(track_x[nearest]), int(track_y[nearest])

    def set_arm(self, pixel: Pixel, side: int, end: Pixel) -> bool:
        """
        Move one arm end of a kink, which sets its angle by its arm ends.
        キンクの腕の端の 1 つを動かす。これにより角度は腕の端で決まるようになる。

        Parameters
        ----------
        pixel
            Pixel of the kink.
            キンクの画素。
        side
            `ARM_BEFORE` or `ARM_AFTER`: which end to move.
            `ARM_BEFORE` または `ARM_AFTER`。どちらの端を動かすか。
        end
            Skeleton pixel of the kink's fiber, on that side of the kink.
            キンクの繊維のスケルトン画素。キンクのその側にあるもの。

        Returns
        -------
        bool
            ``False`` when the pixel holds no kink on a fiber, when the end is
            not on the kink's fiber on that side, or when it is where the end
            already is.
            画素に繊維の上のキンクが無い、端がキンクの繊維のその側に無い、または
            端がすでにその位置にある場合は ``False``。

        Notes
        -----
        For a kink that kept the rule's values this is the moment they are
        replaced: its angle becomes the one between the arms its ends give,
        and its excess turning pi minus that angle.
        規則の値を保っていたキンクでは、この時点で値が置き換わる。内角は、端で決まる
        2 本の腕のなす角に、超過回転は pi からそれを引いた値になる。
        """
        pixel = (int(pixel[0]), int(pixel[1]))
        values = self._kinks.get(pixel)
        place = self._where.get(pixel)
        target = self._where.get((int(end[0]), int(end[1])))
        if values is None or place is None or target is None:
            return False
        number, index = place
        placed = self._arm_indices(pixel)
        current = placed if placed is not None else self.default_arms(pixel)
        if current is None or target[0] != number:
            return False
        if side == ARM_BEFORE and target[1] < index:
            arms = (target[1], current[1])
        elif side == ARM_AFTER and target[1] > index:
            arms = (current[0], target[1])
        else:
            return False
        if placed is not None and arms == placed:
            return False
        angle = self._angle(number, index, arms)
        if not np.isfinite(angle):
            return False
        snapshot = self._snapshot()
        values[0], values[1] = angle, float(np.pi - angle)
        values[2] = self._arm_pixels(pixel, arms)
        self._commit(snapshot)
        return True

    # ----- Finding what is under the pointer -----

    def _nearest(self, xs: np.ndarray, ys: np.ndarray, x: float, y: float,
                 radius: float) -> Optional[int]:
        """
        Index of the point nearest a position within a radius, or ``None``.
        ある位置から半径以内で最も近い点の番号。無ければ ``None``。

        Distances are in X pixels, with Y scaled by the pixel aspect, so the
        radius is a circle on the specimen and on the screen.
        距離は X の画素単位で、Y は画素の縦横比で拡大する。こうすると半径は、
        試料の上でも画面の上でも円になる。
        """
        if xs.size == 0:
            return None
        distance = np.hypot(xs - x, (ys - y) * self._aspect)
        nearest = int(np.argmin(distance))
        return nearest if distance[nearest] <= radius else None

    def nearest_track_pixel(self, x: float, y: float, radius: float) -> Optional[Pixel]:
        """
        Return the fiber pixel nearest a position, within a radius.
        ある位置に最も近い繊維の画素を、半径以内で返す。
        """
        nearest = self._nearest(self._all_x, self._all_y, x, y, radius)
        if nearest is None:
            return None
        return int(self._all_x[nearest]), int(self._all_y[nearest])

    def nearest_mark(
        self, x: float, y: float, radius: float, kinks_only: bool = False,
    ) -> Optional[Tuple[str, Pixel]]:
        """
        Return the mark nearest a position, within a radius.
        ある位置に最も近い印を、半径以内で返す。

        Returns
        -------
        tuple or None
            ``(kind, pixel)`` with `MARK_KINK` or `MARK_UNJUDGED`.
            ``(種類, 画素)``。種類は `MARK_KINK` または `MARK_UNJUDGED`。
        """
        marks = [(MARK_KINK, pixel) for pixel in self._kinks]
        if not kinks_only:
            marks += [(MARK_UNJUDGED, pixel) for pixel in self._unjudged]
        if not marks:
            return None
        xs = np.array([pixel[0] for _kind, pixel in marks], dtype=np.float64)
        ys = np.array([pixel[1] for _kind, pixel in marks], dtype=np.float64)
        nearest = self._nearest(xs, ys, x, y, radius)
        return None if nearest is None else marks[nearest]

    # ----- Changing -----

    def _placed(self, pixel: Pixel) -> Optional[List]:
        """
        Values of a kink placed at a fiber pixel now, or ``None`` if it cannot be.
        いま繊維の画素に置いたキンクの値。置けなければ ``None``。
        """
        arms = self.default_arms(pixel)
        if arms is None:
            return None
        number, index = self._where[pixel]
        angle = self._angle(number, index, arms)
        if not np.isfinite(angle):
            return None
        return [angle, float(np.pi - angle), self._arm_pixels(pixel, arms)]

    def add_kink(self, pixel: Pixel) -> bool:
        """
        Put a kink on a fiber pixel.
        繊維の画素にキンクを置く。

        Parameters
        ----------
        pixel
            ``(x, y)`` of a pixel of a traced fiber.
            追跡した繊維の画素の ``(x, y)``。

        Returns
        -------
        bool
            ``False`` when the pixel is on no fiber, already holds a kink, or
            is an end of its fiber's line, where no angle can be read.
            画素がどの繊維の上にも無い、すでにキンクがある、または繊維の線の端で
            角度を読めない場合は ``False``。

        Notes
        -----
        The kink gets the arm ends of `default_arms` and the angle between
        the arms they give. A bend that was not judged at that pixel is
        replaced by the kink: a person has now judged it.
        キンクには `default_arms` の腕の端と、それで決まる 2 本の腕のなす角が与え
        られる。その画素に判定しなかった折れがあれば、キンクで置き換える。人が判定
        したことになるためである。
        """
        pixel = (int(pixel[0]), int(pixel[1]))
        if pixel not in self._where or pixel in self._kinks:
            return False
        values = self._placed(pixel)
        if values is None:
            return False
        snapshot = self._snapshot()
        self._unjudged.discard(pixel)
        self._kinks[pixel] = values
        self._commit(snapshot)
        return True

    def remove_mark(self, pixel: Pixel) -> bool:
        """
        Remove the kink, or the bend that was not judged, at a pixel.
        ある画素のキンク、または判定しなかった折れを除く。

        Returns
        -------
        bool
            ``False`` when the pixel holds neither.
            その画素にどちらも無ければ ``False``。
        """
        pixel = (int(pixel[0]), int(pixel[1]))
        if pixel not in self._kinks and pixel not in self._unjudged:
            return False
        snapshot = self._snapshot()
        self._kinks.pop(pixel, None)
        self._unjudged.discard(pixel)
        self._commit(snapshot)
        return True

    def move_kink(self, source: Pixel, target: Pixel) -> bool:
        """
        Move a kink to another fiber pixel.
        キンクを、別の繊維の画素へ動かす。

        Parameters
        ----------
        source
            Pixel of the kink.
            キンクの画素。
        target
            Fiber pixel to move it to; it may lie on another fiber.
            動かす先の繊維の画素。別の繊維の上でもよい。

        Returns
        -------
        bool
            ``False`` when `source` holds no kink, or `target` is on no fiber,
            holds a kink already, or is an end of its fiber's line.
            `source` にキンクが無い、または `target` がどの繊維の上にも無い、
            すでにキンクがある、繊維の線の端である、のいずれかの場合は ``False``。

        Notes
        -----
        The moved kink is a kink placed at `target`: it gets the arm ends of
        `default_arms` there and the angle between the arms they give, and
        carries nothing over from `source`.
        動かしたキンクは、`target` に置いたキンクである。そこでの `default_arms` の
        腕の端と、それで決まる 2 本の腕のなす角が与えられ、`source` からは何も
        持ち越さない。
        """
        source = (int(source[0]), int(source[1]))
        target = (int(target[0]), int(target[1]))
        if (source not in self._kinks or target not in self._where
                or target in self._kinks):
            return False
        snapshot = self._snapshot()
        del self._kinks[source]
        values = self._placed(target)
        if values is None:
            self._restore(snapshot)
            return False
        self._unjudged.discard(target)
        self._kinks[target] = values
        self._commit(snapshot)
        return True


@dataclass
class _Step:
    """
    One undoable change of a `BundleEditor`.
    `BundleEditor` の、元に戻せる 1 回の変更。

    Attributes
    ----------
    ident
        Number of the change, unique within the editor.
        変更の番号。エディタの中で一意。
    flags_before, flags_after
        ``(stale, edited, rerun)`` before and after the change.
        変更の前後の ``(stale, edited, rerun)``。
    kink_steps
        How many changes of the editor's `KinkEditor` belong to this one.
        エディタの `KinkEditor` の変更のうち、この変更に属するものの数。
    mask
        Name of the painted mask, for a stroke.
        ストロークの場合の、塗ったマスクの名前。
    indices
        Flat indices of the pixels the stroke changed.
        ストロークが変えた画素の、平坦化したインデックス。
    value
        Value the stroke gave them; before it they held the opposite.
        ストロークが与えた値。その前は逆の値だった。
    before, after
        Attributes a stage or a settings change replaced, by name.
        段の再実行や設定の変更が置き換えた属性（名前ごと）。
    retrace
        Whether the change alters the skeleton, so the fibers have to be
        traced again after it, after undoing it and after redoing it.
        変更がスケルトンを変えるかどうか。変えるなら、実行後・取り消し後・
        やり直し後に、繊維を追跡し直す必要がある。
    """

    ident: int
    flags_before: tuple
    flags_after: tuple = ()
    kink_steps: int = 0
    mask: str = ""
    indices: Optional[np.ndarray] = None
    value: bool = False
    before: Optional[Dict[str, object]] = None
    after: Optional[Dict[str, object]] = None
    retrace: bool = False


class BundleEditor:
    """
    Everything of an opened bundle a person can change, with one undo history.
    開いたバンドルのうち人が変更できるものすべて。元に戻す履歴は 1 本である。

    Three kinds of change are made through it. Masks are painted: the fiber
    mask of the background stage and the binarized image can have pixels set
    and cleared, the skeleton only cleared (`PAINTABLE`). Kinks are placed,
    removed, moved and given an angle (`KinkEditor`, as `kinks`). And a stage
    is run again on the results as they stand, with settings that can be
    changed first (`compute`, `apply`, `set_params`).
    変更は 3 種類ある。マスクを塗る。背景補正の繊維マスクと二値化画像は画素を立てる
    ことも消すこともでき、スケルトンは消すことだけができる（`PAINTABLE`）。キンクを
    置く・除く・動かす・角度を与える（`kinks` としての `KinkEditor`）。そして、現在の
    結果に対して段を再実行する。その前に設定を変えられる（`compute`・`apply`・
    `set_params`）。

    A result that was computed from another keeps its values when that other
    changes, so the editor records which results are in that state (`stale`):
    changing a result, by hand or by running its stage, marks every result
    computed from it, and running a stage clears the mark of its own result.
    Nothing is recomputed without being asked.
    ある結果から計算された結果は、元の結果が変わっても値を保つ。そこでエディタは、
    その状態にある結果を記録する（`stale`）。手で、または段の再実行で結果を変えると、
    そこから計算される結果すべてに印が付き、段を再実行するとその段自身の結果の印が
    消える。求められない限り、何も計算し直さない。

    Parameters
    ----------
    session
        The opened bundle, which has to be editable (`EditSession.editable`).
        開いたバンドル。編集できるものでなければならない
        （`EditSession.editable`）。

    Attributes
    ----------
    params
        Analysis settings as they stand; they are saved with the bundle.
        現在の解析設定。バンドルとともに保存される。
    calibrated
        Background-corrected heights.
        背景補正後の高さ。
    fiber_mask, binarized, skeleton
        The masks as boolean arrays; `fiber_mask` is ``None`` without one.
        真偽値の配列としてのマスク。`fiber_mask` は、無ければ ``None``。
    fibers
        The fibers traced from the skeleton as last traced.
        最後に追跡したときのスケルトンから追跡した繊維。
    kinks
        The kinks, changed through the methods of this class so that the
        history stays one.
        キンク。履歴が 1 本に保たれるよう、このクラスのメソッドを通して変更する。
    stale
        Results not computed again since something they are computed from
        changed.
        計算の元になるものが変わってから、計算し直していない結果。
    edited
        Results changed by hand since they were last computed.
        最後に計算されてから、手で変更された結果。
    rerun
        Stages run again in this session, in the order first run.
        このセッションで再実行した段。最初に実行した順。
    tracks_stale
        Whether the skeleton changed since `fibers` were traced.
        `fibers` を追跡してからスケルトンが変わったかどうか。
    skeleton_revision
        Counter raised at every change of the skeleton, so a tracing that
        took a while can tell whether its skeleton is still the current one.
        スケルトンが変わるたびに増えるカウンタ。時間のかかった追跡が、追跡した
        スケルトンがまだ現在のものかどうかを判定できる。

    Raises
    ------
    ValueError
        If the bundle is not of the current format.
    """

    def __init__(self, session: EditSession) -> None:
        if not session.editable:
            raise ValueError(
                f"bundle format {session.format_version} cannot be edited; "
                f"analyze the input again to get format {BUNDLE_FORMAT_VERSION}"
            )
        self.session = session
        self.params: ProcParams = session.params if session.params is not None else ProcParams()
        stored = session.arrays
        self.calibrated = np.asarray(stored["calibrated"])
        self.binarized = np.asarray(stored["binarized"]).astype(bool)
        self.skeleton = np.asarray(stored["skeletonized"]).astype(bool)
        mask = session.fiber_mask
        self.fiber_mask: Optional[np.ndarray] = (
            None if mask is None else np.array(mask, dtype=bool))
        self.fibers: List[Fiber] = list(session.fibers)
        self.kinks = KinkEditor(
            self.fibers, stored, session.pixel_aspect,
            kink_arms=session.meta.get(KINK_ARMS_KEY))
        # An edited bundle is opened in the state it was saved in: what was
        # stale or changed by hand then still is, because opening computes
        # nothing again.
        # 編集したバンドルは、保存したときの状態で開く。そのとき古かったもの、手で
        # 変更されていたものは、いまもそうである。開くだけでは何も計算し直さない
        # ためである。
        history = session.meta.get(MANUAL_EDIT_KEY) or []
        last = history[-1] if history else {}
        self.stale: Set[str] = {
            name for name in (last.get("stale_layers") or ()) if name in RESULTS}
        self.edited: Set[str] = {
            name for name in (last.get("edited_layers") or ()) if name in RESULTS}
        self.rerun: List[str] = []
        self.tracks_stale = False
        self.skeleton_revision = 0
        self._undo: List[_Step] = []
        self._redo: List[_Step] = []
        self._next_ident = 1
        self._saved_ident = 0
        self._stroke: Optional[Tuple[str, bool, List[np.ndarray]]] = None

    # ----- History -----

    def _flags(self) -> tuple:
        """
        Copy the marks a change can alter.
        変更によって変わりうる印を複製する。
        """
        return frozenset(self.stale), frozenset(self.edited), tuple(self.rerun)

    def _begin(self) -> _Step:
        """
        Start recording a change.
        変更の記録を始める。
        """
        step = _Step(ident=self._next_ident, flags_before=self._flags())
        self._next_ident += 1
        return step

    def _finish(self, step: _Step) -> None:
        """
        Record a change that has been made.
        行った変更を記録する。
        """
        step.flags_after = self._flags()
        self._undo.append(step)
        self._redo.clear()
        if step.retrace:
            self._skeleton_changed()

    def _skeleton_changed(self) -> None:
        """
        Note that the skeleton is no longer the one `fibers` were traced from.
        スケルトンが、`fibers` を追跡したときのものではなくなったことを記録する。
        """
        self.tracks_stale = True
        self.skeleton_revision += 1

    def _changed(self, result: str) -> None:
        """
        Mark a result as changed by hand, and what is computed from it as stale.
        ある結果を手で変更したものとし、そこから計算されるものを古いものとする。
        """
        self.edited.add(result)
        self.stale.update(DOWNSTREAM[result])

    def _play(self, step: _Step, forward: bool) -> None:
        """
        Apply a recorded change, or take it back.
        記録した変更を適用する、または取り消す。
        """
        for _ in range(step.kink_steps):
            if forward:
                self.kinks.redo()
            else:
                self.kinks.undo()
        if step.indices is not None:
            self._mask(step.mask).flat[step.indices] = step.value if forward else not step.value
        values = step.after if forward else step.before
        for name, value in (values or {}).items():
            setattr(self, name, value)
        stale, edited, rerun = step.flags_after if forward else step.flags_before
        self.stale, self.edited, self.rerun = set(stale), set(edited), list(rerun)
        if step.retrace:
            self._skeleton_changed()

    @property
    def can_undo(self) -> bool:
        """
        Whether a change can be undone.
        元に戻せる変更があるかどうか。
        """
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """
        Whether an undone change can be applied again.
        やり直せる変更があるかどうか。
        """
        return bool(self._redo)

    def undo(self) -> bool:
        """
        Take back the last change; ``False`` when there is none.
        直前の変更を取り消す。変更が無ければ ``False``。
        """
        if not self._undo:
            return False
        step = self._undo.pop()
        self._play(step, forward=False)
        self._redo.append(step)
        return True

    def redo(self) -> bool:
        """
        Apply the last undone change again; ``False`` when there is none.
        直前に取り消した変更をやり直す。無ければ ``False``。
        """
        if not self._redo:
            return False
        step = self._redo.pop()
        self._play(step, forward=True)
        self._undo.append(step)
        return True

    @property
    def modified(self) -> bool:
        """
        Whether anything differs from what was last loaded or saved.
        最後に読み込んだ、または保存したものと違いがあるかどうか。
        """
        return (self._undo[-1].ident if self._undo else 0) != self._saved_ident

    def mark_saved(self) -> None:
        """
        Take the current state as the saved one.
        現在の状態を、保存済みのものとする。
        """
        self._saved_ident = self._undo[-1].ident if self._undo else 0

    # ----- Painting masks -----

    def _mask(self, name: str) -> np.ndarray:
        """
        Return the mask with a name as it stands.
        ある名前のマスクの現在の配列を返す。
        """
        mask = {
            RESULT_FIBER_MASK: self.fiber_mask,
            RESULT_BINARIZED: self.binarized,
            RESULT_SKELETON: self.skeleton,
        }.get(name)
        if mask is None:
            raise ValueError(f"no mask named {name!r} to paint")
        return mask

    def begin_stroke(self, name: str, value: bool) -> None:
        """
        Start painting one mask with one value.
        1 つのマスクを 1 つの値で塗り始める。

        Parameters
        ----------
        name
            One of `PAINTABLE`.
            `PAINTABLE` のいずれか。
        value
            ``True`` to set pixels, ``False`` to clear them.
            画素を立てるなら ``True``、消すなら ``False``。

        Raises
        ------
        ValueError
            If the mask does not exist, or pixels of it cannot be set.
        """
        self._mask(name)
        if value and not PAINTABLE.get(name, False):
            raise ValueError(f"pixels of {name!r} can only be cleared")
        self._stroke = (name, bool(value), [])

    def paint(
        self, x0: float, y0: float, x1: float, y1: float, diameter: float,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Paint the stroke's value along a segment with a round brush.
        丸いブラシで、線分に沿ってストロークの値を塗る。

        Parameters
        ----------
        x0, y0, x1, y1
            Ends of the segment in image pixels; the same point twice paints
            one dab.
            線分の両端（画像の画素単位）。同じ点を 2 回渡すと、1 か所だけ塗る。
        diameter
            Brush diameter in pixels.
            ブラシの直径（画素）。

        Returns
        -------
        tuple or None
            ``(row_start, row_stop, column_start, column_stop)`` bounding the
            pixels whose value changed, or ``None`` when none did.
            値が変わった画素を囲む
            ``(row_start, row_stop, column_start, column_stop)``。変わった画素が
            無ければ ``None``。

        Notes
        -----
        A pixel is painted when its center lies within half the diameter of
        the segment. The pixels the two ends fall in are always painted, so a
        brush one pixel wide leaves no gap where the pointer crossed a pixel
        corner.
        画素は、その中心が線分から直径の半分以内にあるとき塗られる。両端が入る画素は
        必ず塗るので、太さ 1 画素のブラシでも、ポインタが画素の角を通った場所に
        すき間が残らない。
        """
        if self._stroke is None:
            return None
        name, value, changed = self._stroke
        mask = self._mask(name)
        rows, columns = mask.shape
        radius = max(float(diameter), 1.0) / 2.0
        row_start = max(int(np.floor(min(y0, y1) - radius)), 0)
        row_stop = min(int(np.ceil(max(y0, y1) + radius)) + 1, rows)
        column_start = max(int(np.floor(min(x0, x1) - radius)), 0)
        column_stop = min(int(np.ceil(max(x0, x1) + radius)) + 1, columns)
        if row_start >= row_stop or column_start >= column_stop:
            return None
        yy, xx = np.mgrid[row_start:row_stop, column_start:column_stop].astype(np.float64)
        dx, dy = x1 - x0, y1 - y0
        length_squared = dx * dx + dy * dy
        along = (
            np.clip(((xx - x0) * dx + (yy - y0) * dy) / length_squared, 0.0, 1.0)
            if length_squared > 0 else 0.0)
        hit = (xx - (x0 + along * dx)) ** 2 + (yy - (y0 + along * dy)) ** 2 <= radius ** 2
        for x, y in ((x0, y0), (x1, y1)):
            hit |= (xx == round(x)) & (yy == round(y))
        window = mask[row_start:row_stop, column_start:column_stop]
        change = hit & (window != value)
        if not change.any():
            return None
        window[change] = value
        hit_rows, hit_columns = np.nonzero(change)
        changed.append((hit_rows + row_start) * columns + hit_columns + column_start)
        return (row_start + int(hit_rows.min()), row_start + int(hit_rows.max()) + 1,
                column_start + int(hit_columns.min()), column_start + int(hit_columns.max()) + 1)

    def end_stroke(self) -> bool:
        """
        Finish the stroke and record it as one change.
        ストロークを終え、1 回の変更として記録する。

        Returns
        -------
        bool
            Whether the stroke changed any pixel.
            ストロークが画素を変えたかどうか。
        """
        if self._stroke is None:
            return False
        name, value, changed = self._stroke
        self._stroke = None
        if not changed:
            return False
        # The pixels are already painted; the marks before the stroke are
        # those that still stand, because painting does not touch them.
        # 画素はすでに塗られている。ストローク前の印は、いま立っているものである。
        # 塗ること自体は印に触れないためである。
        step = self._begin()
        step.mask, step.value = name, value
        step.indices = np.unique(np.concatenate(changed))
        step.retrace = name == RESULT_SKELETON
        self._changed(name)
        self._finish(step)
        return True

    # ----- Kinks -----

    def _kink_change(self, done: bool) -> bool:
        """
        Record a change the `KinkEditor` has just made.
        `KinkEditor` がいま行った変更を記録する。
        """
        if not done:
            return False
        step = self._begin()
        # The marks before the change are needed, but the change is made: the
        # kink editor never alters them, so they are the ones still standing.
        # 必要なのは変更前の印だが、変更はすでに行われている。キンクエディタは印を
        # 変えないので、いま立っているものが変更前の印である。
        step.kink_steps = 1
        self._changed(RESULT_KINKS)
        self._finish(step)
        return True

    def add_kink(self, pixel: Pixel) -> bool:
        """
        Put a kink on a fiber pixel (`KinkEditor.add_kink`).
        繊維の画素にキンクを置く（`KinkEditor.add_kink`）。
        """
        return self._kink_change(self.kinks.add_kink(pixel))

    def remove_mark(self, pixel: Pixel) -> bool:
        """
        Remove the kink or the unjudged bend at a pixel (`KinkEditor.remove_mark`).
        ある画素のキンク、または判定しなかった折れを除く
        （`KinkEditor.remove_mark`）。
        """
        return self._kink_change(self.kinks.remove_mark(pixel))

    def move_kink(self, source: Pixel, target: Pixel) -> bool:
        """
        Move a kink to another fiber pixel (`KinkEditor.move_kink`).
        キンクを、別の繊維の画素へ動かす（`KinkEditor.move_kink`）。
        """
        return self._kink_change(self.kinks.move_kink(source, target))

    def set_arm(self, pixel: Pixel, side: int, end: Pixel) -> bool:
        """
        Move one arm end of a kink (`KinkEditor.set_arm`).
        キンクの腕の端の 1 つを動かす（`KinkEditor.set_arm`）。
        """
        return self._kink_change(self.kinks.set_arm(pixel, side, end))

    # ----- Settings and stages -----

    def set_params(self, params: ProcParams, stage: str) -> None:
        """
        Change the analysis settings of one stage.
        1 つの段の解析設定を変更する。

        Parameters
        ----------
        params
            The settings to use from now on.
            これ以降に使う設定。
        stage
            The stage whose settings changed, one of `STAGE_RESULT`. Its
            result, and what is computed from it, become stale: they were
            computed with the earlier settings.
            設定を変えた段。`STAGE_RESULT` のいずれか。その結果と、そこから計算
            されるものは古いものになる。以前の設定で計算されたものだからである。

        Raises
        ------
        ValueError
            If `pipeline.validate_params` rejects the settings.
        """
        problems = validate_params(params)
        if problems:
            raise ValueError("; ".join(problems))
        if params == self.params:
            return
        step = self._begin()
        step.before, step.after = {"params": self.params}, {"params": params}
        self.params = params
        result = STAGE_RESULT[stage]
        self.stale.add(result)
        self.stale.update(DOWNSTREAM[result])
        self._finish(step)

    def _image(self) -> ProcessedImage:
        """
        Build the container the stages read, holding the results as they stand.
        段が読むコンテナを、現在の結果を持たせて作る。
        """
        raw = self.session.raw.height
        image = ProcessedImage(
            original_AFM=raw if raw is not None else self.calibrated, name="")
        stored = self.session.arrays
        # Stores the heights together with the image detection reads, which is
        # median filtered when `apply_median` is set, exactly as the
        # background stage leaves them.
        # 高さと、検出が読む画像を一緒に格納する。後者は `apply_median` が有効なら
        # メディアンフィルタをかけたもので、背景補正の段が残す状態とまったく同じに
        # なる。
        build_stages(self.params).bg_calibrator._store(image, self.calibrated)
        image.binarized_image = self.binarized.astype(stored["binarized"].dtype)
        image.skeleton_image = self.skeleton.astype(stored["skeletonized"].dtype)
        return image

    def can_run(self, stage: str) -> bool:
        """
        Whether a stage can be run on the session as it stands.
        現在のセッションで、ある段を実行できるかどうか。

        The background stage and the detection of its mask need the raw
        height image, and a mask is detected only by a method that uses one.
        背景補正の段とそのマスクの検出には、生の高さ画像が要る。マスクを検出する
        のは、マスクを使う方式だけである。
        """
        if stage == STAGE_BACKGROUND:
            return self.session.raw.height is not None
        if stage == STAGE_MASK:
            return (self.session.raw.height is not None
                    and self.params.bg_method in MASK_BG_METHODS)
        return stage in STAGE_RESULT

    def compute(self, stage: str) -> Dict[str, object]:
        """
        Run a stage on the results as they stand, changing nothing.
        現在の結果に対して段を実行する。何も変更しない。

        Parameters
        ----------
        stage
            One of `STAGE_RESULT`.
            `STAGE_RESULT` のいずれか。

        Returns
        -------
        dict
            What the stage computed, for `apply`.
            段が計算したもの。`apply` に渡す。

        Raises
        ------
        ValueError
            If the stage cannot be run (`can_run`).

        Notes
        -----
        It only reads the editor, so it can run in a worker thread while the
        window stays responsive, as long as nothing changes the editor
        meanwhile. The stage objects are those of `pipeline.build_stages`
        with the current settings, called as `pipeline.process_file` calls
        them.
        エディタを読むだけなので、その間に何もエディタを変更しなければ、ウィンドウを
        応答させたままワーカースレッドで実行できる。段のオブジェクトは、現在の設定で
        `pipeline.build_stages` が作るもので、`pipeline.process_file` と同じ呼び方を
        する。
        """
        if not self.can_run(stage):
            raise ValueError(f"stage {stage!r} cannot be run on this bundle")
        stages = build_stages(self.params)
        raw = self.session.raw.height
        uses_mask = self.params.bg_method in MASK_BG_METHODS
        if stage == STAGE_MASK:
            image = ProcessedImage(original_AFM=raw, name="")
            stages.bg_calibrator(image)
            bg_only = np.asarray(stages.bg_calibrator.bg_only)
            return {"fiber_mask": np.isnan(bg_only) & ~np.isnan(np.asarray(raw)[1:, 1:])}
        if stage == STAGE_BACKGROUND:
            image = ProcessedImage(original_AFM=raw, name="")
            mask = self.fiber_mask
            if uses_mask and mask is not None:
                stages.bg_calibrator.calibrate_with_mask(image, mask.copy())
            else:
                stages.bg_calibrator(image)
                mask = None
                if uses_mask:
                    bg_only = np.asarray(stages.bg_calibrator.bg_only)
                    mask = np.isnan(bg_only) & ~np.isnan(np.asarray(raw)[1:, 1:])
            return {"calibrated": np.asarray(image.calibrated_image), "fiber_mask": mask}

        image = self._image()
        meta = self.session.meta
        aspect = self.session.pixel_aspect
        if stage == STAGE_BINARIZE:
            scan_size = scan_size_um_from_meta(meta)
            columns = self.calibrated.shape[1]
            nm_per_px = (pixel_size_nm(scan_size[0], columns)
                         if scan_size is not None and columns > 0 else None)
            stages.segmenter(image, nm_per_px=nm_per_px, pixel_aspect=aspect)
            return {"binarized": np.asarray(image.binarized_image).astype(bool)}
        if stage == STAGE_SKELETONIZE:
            stages.skeletonizer(image)
            return {"skeleton": np.asarray(image.skeleton_image).astype(bool)}
        stages.kink_detector(image, pixel_aspect=aspect)
        kink_x, kink_y = image.all_kink_coordinates
        unjudged_x, unjudged_y = image.unjudged_point_coordinates
        kinks = {
            "kp": np.stack([kink_x, kink_y]).astype(np.int64),
            "ka": np.asarray(image.all_kink_angles, dtype=np.float64),
            "ke": np.asarray(image.all_kink_excess, dtype=np.float64),
            "up": np.stack([unjudged_x, unjudged_y]).astype(np.int64),
        }
        return {"kinks": kinks, "fibers": self._trace(self.current_arrays(kinks))}

    def apply(self, stage: str, computed: Dict[str, object]) -> None:
        """
        Take over what `compute` returned for a stage, as one undoable change.
        ある段について `compute` が返したものを取り込む。元に戻せる 1 回の変更とする。

        Parameters
        ----------
        stage
            The stage that was computed.
            計算した段。
        computed
            What `compute` returned for it.
            その段について `compute` が返したもの。

        Notes
        -----
        The stage's result is no longer stale and no longer edited by hand,
        and what is computed from it becomes stale. Hand edits of the result
        itself are replaced by what the stage computed.
        その段の結果は、古いものでも、手で変更したものでもなくなる。そこから計算
        されるものは古いものになる。その結果自体への手の変更は、段が計算したもので
        置き換わる。
        """
        result = STAGE_RESULT[stage]
        step = self._begin()
        if stage == STAGE_KINKS:
            self.set_fibers(computed["fibers"])
            self.kinks.replace_marks(computed["kinks"])
            step.kink_steps = 1
        else:
            names = [name for name in ("fiber_mask", "calibrated", "binarized", "skeleton")
                     if name in computed]
            step.before = {name: getattr(self, name) for name in names}
            step.after = {name: computed[name] for name in names}
            for name in names:
                setattr(self, name, computed[name])
            step.retrace = stage == STAGE_SKELETONIZE
        self.stale.discard(result)
        self.edited.discard(result)
        self.stale.update(DOWNSTREAM[result])
        if stage not in self.rerun:
            self.rerun.append(stage)
        self._finish(step)

    # ----- Fibers -----

    def current_arrays(self, kinks: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, np.ndarray]:
        """
        Return the bundle arrays the editor's state stands for.
        エディタの状態に対応するバンドルの配列を返す。

        Parameters
        ----------
        kinks
            Kink arrays to use instead of the editor's own.
            エディタ自身のものの代わりに使うキンクの配列。

        Returns
        -------
        dict
            Every array of the opened bundle, with the changed results in
            their place and in the stored dtypes. The branch points and end
            points are those of the skeleton as it stands.
            開いたバンドルのすべての配列。変更した結果は差し替えてあり、dtype は
            保存されていたものに合わせる。分岐点と端点は、現在のスケルトンのもの
            である。
        """
        stored = self.session.arrays
        arrays = dict(stored)
        arrays["calibrated"] = self.calibrated
        arrays["binarized"] = self.binarized.astype(stored["binarized"].dtype)
        arrays["skeletonized"] = self.skeleton.astype(stored["skeletonized"].dtype)
        if not np.array_equal(self.skeleton, np.asarray(stored["skeletonized"]).astype(bool)):
            # The same two functions the skeleton stage derives them with.
            # 細線化の段がこれらを求めるのと同じ 2 つの関数。
            skeleton = self.skeleton.astype(np.uint8)
            arrays["bp"] = imp_tools.branchedPoints(skeleton).astype(stored["bp"].dtype)
            arrays["ep"] = imp_tools.endPoints(skeleton).astype(stored["ep"].dtype)
        arrays.update(kinks if kinks is not None else self.kinks.arrays())
        return arrays

    def _trace(self, arrays: Dict[str, np.ndarray]) -> List[Fiber]:
        """
        Trace the fibers of bundle arrays.
        バンドルの配列の繊維を追跡する。

        The arrays are written to a bundle in a temporary folder and traced
        from there by `trace_fibers`, so the fibers are built by the same
        code, with the same settings read from the same metadata, as GUI03
        and GUI04 build them from the bundle once it is saved.
        配列を一時フォルダのバンドルに書き出し、そこから `trace_fibers` で追跡する。
        こうすると繊維は、保存後のバンドルから GUI03 と GUI04 が組み立てるのと同じ
        コードで、同じメタデータから読んだ同じ設定で組み立てられる。
        """
        arrays = {key: value for key, value in arrays.items() if key != FIBER_MASK_KEY}
        shape = np.asarray(arrays["calibrated"]).shape
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "trace" + BUNDLE_EXT)
            save_bundle(path, arrays, vlmeta=dict(self.session.meta))
            return trace_fibers(path, self.session.meta, shape)

    def compute_fibers(self, arrays: Optional[Dict[str, np.ndarray]] = None) -> List[Fiber]:
        """
        Trace the fibers of the skeleton, changing nothing.
        スケルトンの繊維を追跡する。何も変更しない。

        Parameters
        ----------
        arrays
            Arrays to trace, as `current_arrays` returned them earlier.
            Without them the editor's current ones are taken now.
            追跡する配列。先に `current_arrays` が返したもの。指定しなければ、
            エディタの現在の配列をいま取る。

        Notes
        -----
        `current_arrays` returns copies of everything a brush stroke can
        change, so with arrays taken in the main thread this can run in a
        worker thread while painting goes on; `set_fibers` takes the result
        over, and `skeleton_revision` tells whether it is still current.
        `current_arrays` は、ブラシのストロークが変えうるものをすべて複製して返す。
        そのため、メインスレッドで取った配列を渡せば、塗る操作を続けたままこれを
        ワーカースレッドで実行できる。結果は `set_fibers` で取り込み、それがまだ
        現在のものかどうかは `skeleton_revision` で分かる。
        """
        return self._trace(arrays if arrays is not None else self.current_arrays())

    def set_fibers(self, fibers: Sequence[Fiber]) -> None:
        """
        Take over fibers traced from the skeleton as it stands.
        現在のスケルトンから追跡した繊維を取り込む。

        Tracing is not a change of its own: the fibers follow from the
        skeleton, so they are not recorded in the history, and they are
        traced again whenever a change of the skeleton is made, undone or
        redone (`tracks_stale`).
        追跡はそれ自体が変更ではない。繊維はスケルトンから決まるので、履歴には記録
        しない。スケルトンの変更を行う・取り消す・やり直すたびに、追跡し直す
        （`tracks_stale`）。
        """
        self.fibers = list(fibers)
        self.kinks.set_fibers(self.fibers)
        self.tracks_stale = False

    # ----- Saving -----

    def _mask_to_store(self) -> Optional[np.ndarray]:
        """
        Return the fiber mask to save with the bundle, or ``None`` for none.
        バンドルとともに保存する繊維マスクを返す。保存しないなら ``None``。

        The mask is saved when it is known to belong to this bundle: it was
        painted, detected or used by the background stage in this session, the
        opened bundle stored it, or the repeated background stage reproduced
        the stored heights with it. A mask the session only recomputed, with
        heights that do not match, is not written as this bundle's mask.
        マスクは、このバンドルのものだと分かっているときに保存する。このセッションで
        塗った・検出した・背景補正の段が使った場合、開いたバンドルがそれを保存していた
        場合、やり直した背景補正がそのマスクで保存済みの高さを再現した場合である。
        セッションが再計算しただけで高さが合わないマスクは、このバンドルのマスク
        としては書かない。
        """
        if self.fiber_mask is None:
            return None
        background = self.session.background
        if (RESULT_FIBER_MASK in self.edited
                or STAGE_MASK in self.rerun or STAGE_BACKGROUND in self.rerun
                or FIBER_MASK_KEY in self.session.arrays
                or (background is not None and background.reproduces)):
            return self.fiber_mask
        return None

    def save(self, path: str, editor_name: str = "") -> str:
        """
        Save the editor's state as an edited bundle (`save_edited_bundle`).
        エディタの状態を、編集済みバンドルとして保存する（`save_edited_bundle`）。

        Parameters
        ----------
        path
            Where to write the edited bundle.
            編集済みバンドルの書き込み先。
        editor_name
            Name of the person who edited, or empty to record none.
            編集した人の名前。空なら記録しない。

        Returns
        -------
        str
            Path of the parameter file written beside the bundle.
            バンドルの隣に書いたパラメータファイルのパス。

        Notes
        -----
        The record states how the bundle stood when it was saved: which
        results hold changes made by hand (`edited`), which were stale
        (`stale`), and which stages were run again in this session (`rerun`).
        A reader of the file can then tell a result that follows from the
        ones before it from one that does not, and the editor that opens the
        bundle again starts from the same marks.
        記録には、保存時のバンドルの状態を書く。手で変更した内容を持つ結果
        （`edited`）、古かった結果（`stale`）、このセッションで再実行した段（`rerun`）
        である。これにより、ファイルを読む側は、前の結果から導かれた結果とそうでない
        結果を見分けられ、バンドルを開き直したエディタは同じ印から始められる。
        """
        arrays = self.current_arrays()
        mask = self._mask_to_store()
        if mask is not None:
            arrays[FIBER_MASK_KEY] = mask.astype(np.uint8)
        else:
            arrays.pop(FIBER_MASK_KEY, None)
        meta = {
            PARAMS_KEY: asdict(self.params),
            KINK_ARMS_KEY: self.kinks.kink_arms(),
        }
        record = {
            "edited_layers": [name for name in RESULTS if name in self.edited],
            "rerun_stages": list(self.rerun),
            "stale_layers": [name for name in RESULTS if name in self.stale],
        }
        param_path = save_edited_bundle(
            self.session, path, arrays, record, meta=meta, editor_name=editor_name)
        self.mark_saved()
        return param_path


def edited_path_for(bundle_path: str, meta: Optional[Dict] = None) -> str:
    """
    Return the path an edit of a bundle is saved to by default.
    バンドルの編集を保存する既定のパスを返す。

    Parameters
    ----------
    bundle_path
        Path of the bundle the edit started from.
        編集の元になったバンドルのパス。
    meta
        That bundle's vlmeta.
        そのバンドルの vlmeta。

    Returns
    -------
    str
        The bundle's stem followed by `EDITED_SUFFIX`, or `bundle_path`
        itself when the bundle is already an edited one.
        バンドルの stem に `EDITED_SUFFIX` を付けたパス。すでに編集済みの
        バンドルなら `bundle_path` そのもの。
    """
    if meta is not None and meta.get(MANUAL_EDIT_KEY):
        return bundle_path
    stem, extension = os.path.splitext(bundle_path)
    return stem + EDITED_SUFFIX + (extension or BUNDLE_EXT)


def save_edited_bundle(
    session: EditSession,
    path: str,
    arrays: Dict[str, np.ndarray],
    record: Dict[str, object],
    meta: Optional[Dict[str, object]] = None,
    editor_name: str = "",
) -> str:
    """
    Save an edited copy of a session's bundle, marked as edited by hand.
    セッションのバンドルの編集済みの写しを、手で編集したという印を付けて保存する。

    Parameters
    ----------
    session
        The opened bundle.
        開いたバンドル。
    path
        Where to write the edited bundle.
        編集済みバンドルの書き込み先。
    arrays
        Every array to store, by key (`BundleEditor.current_arrays`).
        保存するすべての配列（キーごと。`BundleEditor.current_arrays`）。
    record
        What this edit did, added to the bundle's `MANUAL_EDIT_KEY` list
        together with the source bundle, the time and the software version.
        この編集が行ったこと。元のバンドル・日時・ソフトのバージョンとともに、
        バンドルの `MANUAL_EDIT_KEY` の一覧に加える。
    meta
        vlmeta entries that replace the opened bundle's, by key.
        開いたバンドルの vlmeta を置き換える項目（キーごと）。
    editor_name
        Name of the person who edited, or empty to record none.
        編集した人の名前。空なら記録しない。

    Returns
    -------
    str
        Path of the parameter file written beside the bundle.
        バンドルの隣に書いたパラメータファイルのパス。

    Raises
    ------
    ValueError
        If the bundle is not of the current format, if `path` is the bundle
        the pipeline wrote, or if the edited arrays violate the ``.b2z``
        contract.

    Notes
    -----
    The bundle the pipeline wrote is never overwritten: it is the record of
    the analysis, and the edited bundle names it (`MANUAL_EDIT_KEY`) as what
    the edit started from. A bundle that is itself an edited one may be saved
    over; its earlier records are kept and a new one is added.
    パイプラインが書いたバンドルは上書きしない。それは解析の記録であり、編集済み
    バンドルは、編集の元になったものとしてそれを名指しする（`MANUAL_EDIT_KEY`）。
    すでに編集済みのバンドルには上書きでき、それまでの記録を残して新しい記録を足す。
    """
    if not session.editable:
        raise ValueError(
            f"bundle format {session.format_version} cannot be edited; "
            f"analyze the input again to get format {BUNDLE_FORMAT_VERSION}"
        )
    source = os.path.abspath(session.bundle_path)
    history = list(session.meta.get(MANUAL_EDIT_KEY) or [])
    if os.path.abspath(path) == source and not history:
        raise ValueError("an edit is not saved over the bundle the analysis wrote")

    record = dict(record)
    record.update({
        "source_bundle": os.path.basename(source),
        "source_sha256": _sha256_of_file(source),
        "edited_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "software_version": __version__,
    })
    if editor_name.strip():
        record["editor"] = editor_name.strip()
    meta = {**session.meta, **(meta or {})}
    meta[MANUAL_EDIT_KEY] = history + [record]

    problems = validate_bundle(arrays, meta=meta, require=REQUIRED_BUNDLE_KEYS)
    mask = arrays.get(FIBER_MASK_KEY)
    if mask is not None and np.asarray(mask).shape != np.asarray(arrays["calibrated"]).shape:
        problems.append(
            f"{FIBER_MASK_KEY}: shape {np.asarray(mask).shape} differs from "
            f"calibrated shape {np.asarray(arrays['calibrated']).shape}")
    if problems:
        raise ValueError("edited bundle violates the contract: " + "; ".join(problems))

    param_path = param_path_for(os.path.splitext(path)[0])
    directory = os.path.dirname(os.path.abspath(path))
    temporary = []
    try:
        # Written beside the target and moved into place, so a failed save
        # leaves no half-written bundle under the target's name.
        # 保存先の隣に書いてから置き換える。保存に失敗しても、保存先の名前で
        # 書きかけのバンドルが残らないようにするためである。
        for suffix in (".tmp" + BUNDLE_EXT, ".tmp"):
            handle, name = tempfile.mkstemp(suffix=suffix, dir=directory)
            os.close(handle)
            temporary.append(name)
        save_bundle(temporary[0], arrays, vlmeta=meta)
        with open(temporary[1], "w", encoding="utf-8") as f:
            json.dump(meta.get(PARAMS_KEY, {}), f, ensure_ascii=False, indent=2)
        os.replace(temporary[0], path)
        os.replace(temporary[1], param_path)
    except Exception:
        for name in temporary:
            try:
                os.remove(name)
            except OSError:
                pass
        raise
    return param_path
