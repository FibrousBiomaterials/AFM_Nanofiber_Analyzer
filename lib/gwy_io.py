# -*- coding: utf-8 -*-
"""
Load Gwyddion native ``.gwy`` files as NumPy height arrays.
Gwyddion ネイティブの ``.gwy`` ファイルを NumPy 高さ配列として読み込む。

This module is the binary counterpart to `afm_io`, which handles text/CSV
exports. Reading ``.gwy`` directly removes the manual "Export Text" step for
the many instruments Gwyddion already understands (Asylum, JPK, Park, Nanonis,
Olympus, …): the user opens the vendor file in this software just like a text
scan.
本モジュールはテキスト/CSV を扱う `afm_io` のバイナリ版にあたる。``.gwy`` を
直接読むことで、Gwyddion が既に解釈できる多数の機種（Asylum・JPK・Park・
Nanonis・Olympus 等）について手動の「Export Text」工程を省ける。利用者は
ベンダーファイルをテキストスキャンと同じ感覚で本ソフトに読み込める。

A ``.gwy`` container holds multiple channels (topography, phase, amplitude,
forward/backward passes, …), so a channel must be chosen. `select_default_channel`
auto-selects the topography/height channel, and callers may override it by
channel id or title (GUI dropdown, CLI ``--channel``).
``.gwy`` コンテナは複数チャンネル（地形・位相・振幅・往復スキャン等）を持つ
ため、チャンネルの選択が必要になる。`select_default_channel` が地形/高さ
チャンネルを自動選択し、呼び出し側はチャンネル id またはタイトルで上書き
できる（GUI のドロップダウン、CLI の ``--channel``）。

The dependency on the third-party ``gwyfile`` package is intentionally kept as
a function-local import: ``gwyfile`` is a pure-Python, NumPy-only reader, so it
adds no heavy transitive dependencies, but text-only workflows and plugin
startup never import it.
サードパーティ ``gwyfile`` への依存は意図的に関数ローカル import に留める。
``gwyfile`` は純 Python・NumPy のみ依存の軽量リーダだが、テキスト専用の
ワークフローやプラグイン起動時には読み込まれないようにするためである。
"""

# ===== Standard library =====
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
# Reuse the text loader's ScanSize so the pipeline and GUIs treat a scan size
# read from a .gwy and one read from a text header identically.
# テキストローダの ScanSize を再利用し、.gwy から読んだ走査範囲とテキスト
# ヘッダから読んだ走査範囲をパイプライン・GUI が同一に扱えるようにする。
from .afm_io import ScanSize

# Canonical extension for Gwyddion native files. `afm_io` dispatches on this.
# Gwyddion ネイティブファイルの正規拡張子。`afm_io` がこれで振り分ける。
GWY_EXT = ".gwy"

# Title substrings (case-insensitive) that mark a height/topography channel.
# Gwyddion's default English titles are "Topography"/"Height"; "ZSensor" and
# "Z" appear on closed-loop scanners. Localized titles are caught by the
# length-unit heuristic below instead.
# 高さ/地形チャンネルを示すタイトル部分文字列（大文字小文字無視）。Gwyddion の
# 既定英語タイトルは "Topography"/"Height"。クローズドループ機では "ZSensor"/
# "Z" も現れる。ローカライズされたタイトルは下の長さ単位ヒューリスティックで拾う。
_TOPO_TITLE_KEYWORDS = ("topograph", "height", "zsensor", "z sensor")

# Channel-id keys in a GwyContainer are "/<id>/data"; titles are
# "/<id>/data/title". Ids are not guaranteed contiguous (deleted channels
# leave gaps), so they are enumerated rather than assumed to be 0..N.
# GwyContainer のチャンネル id キーは "/<id>/data"、タイトルは
# "/<id>/data/title"。id は連番とは限らない（削除でき欠番が生じる）ため、
# 0..N と仮定せず列挙する。
_CHANNEL_DATA_KEY_RE = re.compile(r"^/(\d+)/data$")


@dataclass(frozen=True)
class GwyChannel:
    """
    Metadata describing one data channel inside a ``.gwy`` container.
    ``.gwy`` コンテナ内の 1 データチャンネルを表すメタデータ。

    Attributes
    ----------
    channel_id
        Numeric id from the ``/<id>/data`` container key.
        ``/<id>/data`` コンテナキー由来の数値 id。
    title
        Channel title (e.g. ``"Topography"``); empty string when untitled.
        チャンネルのタイトル（例 ``"Topography"``）。無題のときは空文字列。
    n_rows, n_cols
        Pixel dimensions of the channel's height matrix.
        チャンネル高さ行列の画素寸法。
    z_unit
        SI unit string of the value axis (``"m"`` for topography), or ``None``
        when the channel carries no unit. A length unit marks a height channel.
        値軸の SI 単位文字列（地形は ``"m"``）。単位が無ければ ``None``。長さ単位は
        高さチャンネルを示す。
    """

    channel_id: int
    title: str
    n_rows: int
    n_cols: int
    z_unit: Optional[str]

    @property
    def is_length_channel(self) -> bool:
        """
        Return whether the value axis is a length (a topography candidate).
        値軸が長さ（地形チャンネル候補）かどうかを返す。
        """
        return _is_length_unit(self.z_unit)

    @property
    def display_label(self) -> str:
        """
        Return a ``"[id] title"`` label for channel pickers and logs.
        チャンネル選択 UI やログ向けの ``"[id] title"`` ラベルを返す。
        """
        title = self.title or "(untitled)"
        return f"[{self.channel_id}] {title}"


@dataclass(frozen=True)
class GwyImage:
    """
    One channel loaded from a ``.gwy`` file as an analysis-ready height image.
    ``.gwy`` から読み込んだ 1 チャンネルを、解析可能な高さ画像として表す。

    Attributes
    ----------
    data
        2-D height array in nanometers.
        nm 単位の 2 次元高さ配列。
    scan_size
        Physical scan size in micrometers, or ``None`` when absent.
        µm 単位の物理走査範囲。無い場合は ``None``。
    channel
        Metadata of the channel that was loaded.
        読み込んだチャンネルのメタデータ。
    """

    data: np.ndarray
    scan_size: Optional[ScanSize]
    channel: GwyChannel


def _is_length_unit(unit: Optional[str]) -> bool:
    """
    Return whether an SI unit string denotes a length.
    SI 単位文字列が長さを表すかどうかを返す。
    """
    if not unit:
        return False
    # gwyfile reports base SI unit strings; topography is plain "m". Accept the
    # "µm"/"nm" spellings too in case a writer stored a prefixed unit string.
    # gwyfile は基底 SI 単位文字列を返し、地形は素の "m"。接頭辞付き単位を
    # 書き込むライタに備え "µm"/"nm" 等の表記も受け付ける。
    return unit.strip().lower() in {"m", "mm", "um", "µm", "μm", "nm", "pm"}


def _z_to_nm_factor(z_unit: Optional[str]) -> float:
    """
    Return the multiplier converting a channel's values to nanometers.
    チャンネル値を nm へ換算する係数を返す。

    Gwyddion stores topography in base SI meters, so ``"m"`` maps to ``1e9``.
    Non-length channels (phase ``rad``, current ``A`` …) are passed through
    unchanged; their values are not heights, so the caller is responsible for
    interpreting an overridden non-topography channel.
    Gwyddion は地形を基底 SI のメートルで保存するため ``"m"`` は ``1e9`` に対応
    する。長さ以外のチャンネル（位相 ``rad``・電流 ``A`` 等）はそのまま通す。
    これらは高さではないため、地形以外を上書き指定した場合の解釈は呼び出し側の
    責任となる。
    """
    factors = {
        "m": 1.0e9, "mm": 1.0e6, "um": 1.0e3, "µm": 1.0e3, "μm": 1.0e3,
        "nm": 1.0, "pm": 1.0e-3,
    }
    if not z_unit:
        return 1.0
    return factors.get(z_unit.strip().lower(), 1.0)


def _z_unit_of(datafield) -> Optional[str]:
    """
    Return a GwyDataField's value-axis unit string, or ``None`` when absent.
    GwyDataField の値軸単位文字列を返す。無ければ ``None``。
    """
    si = getattr(datafield, "si_unit_z", None)
    if si is None:
        return None
    unit = getattr(si, "unitstr", None)
    return unit or None


def _load_container(path: str):
    """
    Open a ``.gwy`` file and return its GwyContainer.
    ``.gwy`` ファイルを開き、その GwyContainer を返す。

    The ``gwyfile`` dependency is imported here, not at module top, so that
    importing this module (and therefore `afm_io`'s dispatch) never requires
    the package for text-only workflows.
    ``gwyfile`` 依存はモジュール冒頭ではなくここで import する。テキスト専用の
    ワークフローでは、本モジュール（および `afm_io` の振り分け）の import が
    このパッケージを必要としないようにするためである。

    Raises
    ------
    ImportError
        When the optional ``gwyfile`` package is not installed.
    """
    try:
        import gwyfile
    except ImportError as exc:  # pragma: no cover - exercised only without gwyfile
        raise ImportError(
            "Reading .gwy files requires the 'gwyfile' package. "
            "Install it with: pip install gwyfile"
        ) from exc
    return gwyfile.load(path)


def _channels_from_container(container) -> List[Tuple[GwyChannel, object]]:
    """
    Enumerate channels in container order, pairing metadata with its datafield.
    コンテナ内のチャンネルを id 順に列挙し、メタデータとデータフィールドを組にする。

    Returns
    -------
    list of tuple
        ``(GwyChannel, GwyDataField)`` pairs sorted by channel id.
        チャンネル id 昇順の ``(GwyChannel, GwyDataField)`` の組のリスト。
    """
    ids: List[int] = []
    for key in container.keys():
        match = _CHANNEL_DATA_KEY_RE.match(key)
        if match is not None:
            ids.append(int(match.group(1)))
    ids.sort()

    pairs: List[Tuple[GwyChannel, object]] = []
    for cid in ids:
        datafield = container[f"/{cid}/data"]
        title = container.get(f"/{cid}/data/title") or ""
        data = np.asarray(datafield.data)
        n_rows, n_cols = (data.shape + (0, 0))[:2] if data.ndim >= 2 else (data.shape[0], 1)
        channel = GwyChannel(
            channel_id=cid,
            title=str(title),
            n_rows=int(n_rows),
            n_cols=int(n_cols),
            z_unit=_z_unit_of(datafield),
        )
        pairs.append((channel, datafield))
    return pairs


def select_default_channel(channels: List[GwyChannel]) -> GwyChannel:
    """
    Auto-select the most likely topography/height channel.
    最も地形/高さらしいチャンネルを自動選択する。

    Selection order, stopping at the first match:
    判定順（最初に一致した時点で確定）:

    1. A length-unit channel whose title looks like topography/height.
       タイトルが地形/高さらしく、かつ長さ単位を持つチャンネル。
    2. Any length-unit channel (topography even when its title is localized).
       任意の長さ単位チャンネル（タイトルがローカライズされていても地形を拾う）。
    3. Any channel whose title looks like topography/height.
       タイトルが地形/高さらしい任意のチャンネル。
    4. The lowest-id channel (stable fallback).
       最小 id のチャンネル（安定なフォールバック）。

    Raises
    ------
    ValueError
        When `channels` is empty.
    """
    if not channels:
        raise ValueError("no data channels found in the .gwy file")

    def title_is_topo(channel: GwyChannel) -> bool:
        low = channel.title.lower()
        return any(keyword in low for keyword in _TOPO_TITLE_KEYWORDS)

    for channel in channels:
        if channel.is_length_channel and title_is_topo(channel):
            return channel
    for channel in channels:
        if channel.is_length_channel:
            return channel
    for channel in channels:
        if title_is_topo(channel):
            return channel
    return channels[0]


def _resolve_channel(
    channels: List[GwyChannel], selector: Optional[Union[int, str]],
) -> int:
    """
    Resolve a channel selector to an index into `channels`.
    チャンネル指定子を `channels` 内のインデックスへ解決する。

    `selector` may be ``None`` (auto-select), an integer channel id, or a
    title string (matched case-insensitively, exact first then substring). A
    digit-only string is treated as a channel id so a CLI ``--channel 2`` works.
    `selector` は ``None``（自動選択）、整数のチャンネル id、またはタイトル文字列
    （大文字小文字無視で完全一致を優先し、無ければ部分一致）を取りうる。数字のみの
    文字列はチャンネル id として扱い、CLI の ``--channel 2`` が動くようにする。

    Raises
    ------
    ValueError
        When the selector matches no channel.
    """
    if selector is None:
        default = select_default_channel(channels)
        return channels.index(default)

    # A digit-only string selects by id, mirroring an integer selector.
    # 数字のみの文字列は整数指定と同様に id で選ぶ。
    if isinstance(selector, str) and selector.strip().lstrip("+-").isdigit():
        selector = int(selector.strip())

    if isinstance(selector, (int, np.integer)) and not isinstance(selector, bool):
        for index, channel in enumerate(channels):
            if channel.channel_id == int(selector):
                return index
        available = ", ".join(str(c.channel_id) for c in channels)
        raise ValueError(
            f"no channel with id {int(selector)} (available ids: {available})"
        )

    target = str(selector).strip().lower()
    for index, channel in enumerate(channels):
        if channel.title.lower() == target:
            return index
    for index, channel in enumerate(channels):
        if target in channel.title.lower():
            return index
    available = ", ".join(repr(c.title) for c in channels)
    raise ValueError(
        f"no channel matching title {selector!r} (available titles: {available})"
    )


def _scan_size_from_datafield(datafield) -> Optional[ScanSize]:
    """
    Read a channel's physical scan size, converting meters to micrometers.
    チャンネルの物理走査範囲を読み取り、メートルを µm へ換算する。

    Gwyddion stores the fast-scan (X) extent in ``xreal`` and the slow-scan (Y)
    extent in ``yreal``, both in meters. A non-positive or missing extent yields
    ``None`` so the caller falls back to a measurement-time scan size.
    Gwyddion は高速走査軸 (X) の範囲を ``xreal``、低速走査軸 (Y) の範囲を
    ``yreal`` に、いずれもメートルで保存する。範囲が非正または欠損のときは
    ``None`` を返し、呼び出し側が計測時の走査範囲へフォールバックできるようにする。
    """
    xreal = getattr(datafield, "xreal", None)
    yreal = getattr(datafield, "yreal", None)
    if xreal is None or yreal is None:
        return None
    x_um = float(xreal) * 1.0e6
    y_um = float(yreal) * 1.0e6
    if not (x_um > 0 and y_um > 0):
        return None
    return ScanSize(x_um=x_um, y_um=y_um)


def list_gwy_channels(path: str) -> List[GwyChannel]:
    """
    List the data channels in a ``.gwy`` file in container order.
    ``.gwy`` ファイルのデータチャンネルを id 順に列挙する。

    Parameters
    ----------
    path
        Path to the ``.gwy`` file.
        ``.gwy`` ファイルのパス。

    Returns
    -------
    list of GwyChannel
        One entry per channel, suitable for populating a selection UI.
        チャンネルごとに 1 件。選択 UI の生成に使える。

    Raises
    ------
    ImportError
        When the optional ``gwyfile`` package is not installed.
    ValueError
        When the file contains no data channel.
    """
    pairs = _channels_from_container(_load_container(path))
    if not pairs:
        raise ValueError(f"no data channels found in {path}")
    return [channel for channel, _df in pairs]


def load_gwy_image(
    path: str, channel: Optional[Union[int, str]] = None,
) -> GwyImage:
    """
    Load one channel of a ``.gwy`` file as a height image in nanometers.
    ``.gwy`` ファイルの 1 チャンネルを nm 単位の高さ画像として読み込む。

    Parameters
    ----------
    path
        Path to the ``.gwy`` file.
        ``.gwy`` ファイルのパス。
    channel
        ``None`` auto-selects the topography/height channel; an integer selects
        by channel id; a string selects by title (or by id when digit-only).
        ``None`` は地形/高さチャンネルを自動選択。整数はチャンネル id で、文字列は
        タイトル（数字のみのときは id）で選択する。

    Returns
    -------
    GwyImage
        Height array (nm), scan size (µm or ``None``), and channel metadata.
        高さ配列 (nm)、走査範囲 (µm または ``None``)、チャンネルメタデータ。

    Raises
    ------
    ImportError
        When the optional ``gwyfile`` package is not installed.
    ValueError
        When the file has no channel, the selector matches none, or the loaded
        channel contains non-finite values.
    """
    pairs = _channels_from_container(_load_container(path))
    if not pairs:
        raise ValueError(f"no data channels found in {path}")
    channels = [channel_meta for channel_meta, _df in pairs]
    index = _resolve_channel(channels, channel)
    selected_meta, datafield = pairs[index]

    data = np.asarray(datafield.data, dtype=float)
    if data.ndim != 2:
        raise ValueError(
            f"channel {selected_meta.display_label} in {path} is not a 2-D "
            f"image (shape={data.shape})"
        )

    # Convert to nanometers when the channel is a length (topography);
    # non-length channels pass through unchanged.
    # 長さ（地形）チャンネルは nm へ換算し、長さ以外はそのまま通す。
    factor = _z_to_nm_factor(selected_meta.z_unit)
    if factor != 1.0:
        data = data * factor

    # Reject NaN/Inf at the source, matching load_afm_text, so downstream
    # statistics are never silently poisoned.
    # load_afm_text と同様、NaN/Inf を読み込み時点で拒否し、下流の統計が黙って
    # 汚染されないようにする。
    if not np.isfinite(data).all():
        n_bad = int((~np.isfinite(data)).sum())
        raise ValueError(
            f"non-finite values (NaN/Inf) in channel "
            f"{selected_meta.display_label} of {path}: {n_bad} element(s)"
        )

    scan_size = _scan_size_from_datafield(datafield)
    return GwyImage(data=data, scan_size=scan_size, channel=selected_meta)


def read_gwy_scan_size(path: str) -> Optional[ScanSize]:
    """
    Read the physical scan size from a ``.gwy`` file's default channel.
    ``.gwy`` ファイルの既定チャンネルから物理走査範囲を読み取る。

    The scan size is a property of the image, shared by every channel, so the
    auto-selected (topography) channel is used. This mirrors
    `afm_io.read_scan_size` and lets the pipeline and GUIs default the scale
    from a ``.gwy`` header just as they do from a text header.
    走査範囲は画像の属性で全チャンネル共通のため、自動選択（地形）チャンネルを
    用いる。`afm_io.read_scan_size` と同形であり、パイプライン・GUI が
    テキストヘッダと同様に ``.gwy`` ヘッダからスケールを既定化できる。

    Returns
    -------
    ScanSize or None
        Scan size in micrometers, or ``None`` when it cannot be read.
        µm 単位の走査範囲。読めない場合は ``None``。
    """
    pairs = _channels_from_container(_load_container(path))
    if not pairs:
        return None
    channels = [channel_meta for channel_meta, _df in pairs]
    index = _resolve_channel(channels, None)
    _meta, datafield = pairs[index]
    return _scan_size_from_datafield(datafield)


def is_gwy_path(path: str) -> bool:
    """
    Return whether a path names a Gwyddion ``.gwy`` file by extension.
    パスが拡張子で Gwyddion ``.gwy`` ファイルを指すかどうかを返す。
    """
    return os.path.splitext(path)[1].lower() == GWY_EXT
