# -*- coding: utf-8 -*-
"""
Load raw AFM text/CSV files exported by AFM instruments as NumPy arrays.
AFM 装置から出力されたテキスト/CSV ファイルを NumPy 配列として読み込む。

This module centralizes the text-based AFM file loader used by multiple GUIs
so that header layouts, encodings, and per-instrument quirks are handled in
one place. It is intentionally separated from `blosc2_io`, which deals with
the project's internal blosc2 storage format.
本モジュールは複数 GUI から共用する AFM テキストローダを一元化する。
ヘッダ構成・エンコーディング・装置固有の挙動を一か所で扱うことを目的とする。
プロジェクト内部の blosc2 保存形式を扱う `blosc2_io` とは責務を分離している。

Supported formats / 対応フォーマット
------------------------------------
[Multi-column]  Shimadzu SPM-9600 (comma-separated) and Gwyddion "Export Text"
                matrices (whitespace/tab-separated): many columns per row.
                e.g. ``1.23,4.56,7.89,...`` or ``1.23 4.56 7.89 ...``
                (one row = one scan line). The delimiter is auto-detected.
[多列形式]      島津 SPM-9600（カンマ区切り）と Gwyddion「Export Text」の行列
                （空白/タブ区切り）：1 行に多数列。
                例）1.23,4.56,7.89,... または 1.23 4.56 7.89 ...
                （1 行 = 1 スキャンライン）。区切り文字は自動判定する。

[Single-column] Bruker NanoScope etc.: one value per line, preceded by
                a few text-only header rows.
                e.g. a ``Height(nm)`` header row followed by ``image_size**2``
                values such as ``1.267e+001``.
[1 列形式]      Bruker NanoScope 等：1 行に 1 値が縦に並び、ヘッダは先頭数行のテキスト行のみ。
                例）Height(nm) というヘッダ行の後、1.267e+001 が image_size² 行続く。

Instruments without a layout above (Asylum, JPK, Park, Nanonis, Olympus, …)
are supported by converting their files to text with Gwyddion (File > Save As,
choose "Export Text"). Gwyddion writes the height matrix in SI units (meters)
with a small localized comment header recording the scan size and value unit,
both of which this loader reads and normalizes (heights to nm, sizes to µm).
上記レイアウトに該当しない機種（Asylum・JPK・Park・Nanonis・Olympus 等）は、
Gwyddion でテキストに変換（File > Save As の「Export Text」）すれば対応できる。
Gwyddion は高さ行列を SI 単位（メートル）で、走査サイズと値の単位を記録した
小さなローカライズ済みコメントヘッダ付きで出力する。本ローダーはその両方を
読み取り正規化する（高さを nm、サイズを µm へ）。

Gwyddion native ``.gwy`` files can also be read directly, without the manual
"Export Text" step, through `lib.gwy_io`. Because ``.gwy`` is a binary,
multi-channel container, that path lives in its own module; `load_afm_image`
and `read_scan_size` here dispatch ``.gwy`` paths to it, keeping the optional
``gwyfile`` dependency out of text-only workflows.
Gwyddion ネイティブの ``.gwy`` ファイルは、手動の「Export Text」工程を経ずに
`lib.gwy_io` 経由で直接読み込むこともできる。``.gwy`` はバイナリの複数チャンネル
コンテナのため、その処理は専用モジュールに置き、本モジュールの `load_afm_image`
と `read_scan_size` が ``.gwy`` パスをそこへ振り分ける。これによりオプション依存の
``gwyfile`` をテキスト専用ワークフローから排除する。

The header length, column count, and encoding are auto-detected by default,
so callers do not need to specify them. Because auto-detection of scientific
data must never mis-parse silently, two safeguards exist:
ヘッダ行数・列数・エンコーディングは既定で自動判定するため、呼び出し側は
何も指定する必要がない。ただし科学データの自動判定が黙って誤読することは
許されないため、2 つの安全装置を設けている:

- `detect_afm_format` / the ``fmt`` argument let callers force a specific
  layout when auto-detection picks the wrong region (e.g. a numeric
  calibration table inside the header).
  自動判定が誤った領域（ヘッダ内の数値較正テーブル等）に固定された場合、
  `detect_afm_format` と ``fmt`` 引数でレイアウトを明示指定できる。
- After detection, every data row is verified to have the detected column
  count, and loaded values are verified to be finite, so layout mismatches
  become loud errors instead of silently truncated or poisoned data.
  判定後は全データ行の列数を検証し、読み込み値が有限であることも確認する。
  レイアウト不一致は黙った切り捨てや汚染データではなく明示エラーになる。
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import numpy as np

# Format kinds accepted by `detect_afm_format` and `load_afm_text`.
# "auto" tries multi-column first, then single-column (the historical order).
# `detect_afm_format` と `load_afm_text` が受け付ける形式種別。
# "auto" は多列形式 → 1 列形式の順に試す（従来どおりの順序）。
FORMAT_KINDS = ("auto", "multi-column", "single-column")


@dataclass(frozen=True)
class AfmTextFormat:
    """
    Detected (or explicitly chosen) layout of an AFM text file.
    検出された（または明示指定された）AFM テキストファイルのレイアウト。

    Attributes
    ----------
    kind
        Layout kind: ``"multi-column"`` or ``"single-column"``.
        レイアウト種別。``"multi-column"`` または ``"single-column"``。
    skiprows
        Number of header rows preceding the numeric data.
        数値データの前にあるヘッダ行数。
    n_cols
        Number of data columns (1 for single-column layouts).
        データ列数（1 列形式では 1）。
    encoding
        Codec that successfully decoded the file.
        ファイルのデコードに成功したコーデック名。

    Notes
    -----
    `lib.pipeline.process_file` records this information in the bundle
    provenance metadata (vlmeta ``input_format``) so a suspected mis-parse
    can be audited after the fact.
    `lib.pipeline.process_file` はこの情報をバンドルの来歴メタデータ
    （vlmeta ``input_format``）へ記録し、誤判定が疑われた際に事後監査
    できるようにする。
    """

    kind: str
    skiprows: int
    n_cols: int
    encoding: str


@dataclass(frozen=True)
class ScanSize:
    """
    Physical scan size parsed from an instrument file header, in micrometers.
    装置ファイルのヘッダから読み取った物理走査範囲 (µm)。

    Attributes
    ----------
    x_um
        Fast-scan (X) physical size in micrometers.
        高速走査軸 (X) の物理サイズ (µm)。
    y_um
        Slow-scan (Y) physical size in micrometers.
        低速走査軸 (Y) の物理サイズ (µm)。

    Notes
    -----
    X and Y are kept separate because AFM scans are not always square; the
    measurement layer can use the per-axis size for non-square pixel grids.
    AFM 走査は常に正方形とは限らないため X と Y を分けて保持する。非正方形の
    画素グリッドでも計測層が軸別サイズを利用できる。
    """

    x_um: float
    y_um: float


# Shimadzu SPM file headers record the scan range under [SCANNING PARAMS] as
# e.g. ``SizeX: 2.0000um`` / ``SizeY: 2.0000um``. The unit is typically um or nm.
# 島津 SPM のヘッダは [SCANNING PARAMS] 配下に走査範囲を ``SizeX: 2.0000um`` /
# ``SizeY: 2.0000um`` の形で記録する。単位は通常 um または nm。
_SHIMADZU_SIZE_RE = re.compile(
    r"^\s*Size([XY])\s*:\s*([0-9.eE+\-]+)\s*(mm|nm|pm|um|[µμ]m|m)\b",
    re.IGNORECASE,
)

# Gwyddion "Export Text" writes a localized comment header before the data
# matrix, e.g. (Japanese-locale Gwyddion):
#   # チャネル： Topography
#   # 幅: 5 µm           (Width  -> X)
#   # 高さ： 5 µm         (Height -> Y)
#   # 値の単位: m         (unit of the height values)
# The key words are translated to the Gwyddion UI language and the colon may be
# ASCII ":" or full-width "：", so the parser keys off the *value structure*
# rather than the (untranslatable) key text:
#   - a size entry's value is "<number> <length-unit>"  (1st = X, 2nd = Y)
#   - the value-unit entry's value is a "<length-unit>" alone
# The leading "#" distinguishes Gwyddion comments from the Shimadzu "SizeX:"
# keys, which carry no "#".
# Gwyddion「Export Text」はデータ行列の前に、UI 言語へ翻訳されたコメントヘッダを
# 出力する（上は日本語ロケールの例）。コロンは半角 ":" と全角 "：" が混在し、
# キー語は翻訳されるため、キー語ではなく「値の構造」で判定する:
#   - サイズ項目の値は "<数値> <長さ単位>"（1 つ目=X、2 つ目=Y）
#   - 値の単位項目の値は "<長さ単位>" 単独
# 先頭の "#" により、"#" を持たない島津の "SizeX:" キーと区別する。
_GWY_COMMENT_RE = re.compile(r"^\s*#\s*[^:：]+[:：]\s*(\S.*?)\s*$")
_GWY_SIZE_VALUE_RE = re.compile(
    r"^([0-9.eE+\-]+)\s*(mm|nm|pm|um|[µμ]m|m)$", re.IGNORECASE
)
_GWY_UNIT_ONLY_RE = re.compile(r"^(mm|nm|pm|um|[µμ]m|m)$", re.IGNORECASE)

# Length-unit conversion factors. "µm" (U+00B5) and "μm" (U+03BC, Greek mu) are
# both micrometers; instruments emit either codepoint.
# 長さ単位の換算係数。"µm"(U+00B5) と "μm"(U+03BC, ギリシャ文字ミュー) はいずれも
# マイクロメートルで、装置によってどちらのコードポイントも出力されうる。
_LENGTH_UNIT_TO_UM = {
    "m": 1.0e6, "mm": 1.0e3, "um": 1.0, "µm": 1.0, "μm": 1.0,
    "nm": 1.0e-3, "pm": 1.0e-6,
}
_LENGTH_UNIT_TO_NM = {
    "m": 1.0e9, "mm": 1.0e6, "um": 1.0e3, "µm": 1.0e3, "μm": 1.0e3,
    "nm": 1.0, "pm": 1.0e-3,
}

# Maximum header lines scanned for scan-size keys. The scan range sits in the
# small text header, so reading the whole multi-megabyte data body is wasteful.
# 走査範囲キーを探すヘッダ行数の上限。走査範囲は小さなテキストヘッダ内にあり、
# 数 MB のデータ本体まで走査するのは無駄なため。
_SCAN_SIZE_HEADER_SCAN_LIMIT = 200


def _read_text_lines(path: str) -> Tuple[List[str], str]:
    """
    Read all lines of the file, auto-detecting the text encoding.
    テキストエンコーディングを自動判定しながらファイル全行を読み込む。

    Returns
    -------
    tuple
        ``(lines, encoding)`` where `encoding` is the codec that succeeded.
        ``(行リスト, 成功したエンコーディング名)``。
    """
    # Try UTF-8 with BOM first; this codec also handles UTF-8 without BOM.
    # UTF-8 BOM 付きを最優先で試す（BOM なしの UTF-8 でもこのコーデックで読める）。
    # Then try cp932, with latin-1 only as a last-resort byte-preserving fallback.
    # cp932 はその次。latin-1 は最後の保険（任意のバイト列を必ず通すため）。
    _ENCODINGS = ("utf-8-sig", "cp932", "utf-8", "latin-1")

    lines: list = []
    used_enc: str = ""
    for enc in _ENCODINGS:
        try:
            # Do not use errors="replace": it can make a wrong codec look valid.
            # errors="replace" は使わない。これを入れると cp932 で読めない UTF-8 ファイルでも
            # Invalid bytes would be replaced with "?", then np.loadtxt would fail
            # later when it reopens the file in strict mode.
            # 不正バイトが ? に置換されて「成功」を装い、間違ったエンコーディングが選ばれる。
            # その後 np.loadtxt が strict モードで再読み込みする際に UnicodeDecodeError で落ちる。
            with open(path, encoding=enc) as f:
                lines = f.readlines()
            used_enc = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError:
            continue

    if not lines:
        raise ValueError(f"ファイルを読み込めませんでした: {path}")
    return lines, used_enc


def _split_data_fields(line: str) -> List[str]:
    """
    Split a numeric data row into fields, accepting comma or whitespace.
    数値データ行をフィールドに分割する（カンマまたは空白区切りを受け付ける）。

    Comma-separated rows come from Shimadzu SPM-9600 exports; whitespace- or
    tab-separated matrices are produced by Gwyddion's "Export Text" (the
    recommended route for instruments without a native reader) and many other
    tools. Choosing the delimiter per line reads both without a manual switch.
    カンマ区切りは島津 SPM-9600 の出力、空白/タブ区切りの行列は Gwyddion の
    「Export Text」（ネイティブ対応の無い機種向けの推奨経路）や他の多くの
    ツールが出力する。行ごとに区切りを選ぶことで、手動切替なしに両方を読む。
    """
    s = line.strip()
    parts = s.split(",") if "," in s else s.split()
    return [p.strip() for p in parts if p.strip() != ""]


def _find_multi_column_start(lines: List[str]) -> Optional[Tuple[int, int]]:
    """
    Find the start of comma- or whitespace-separated multi-column data.
    カンマまたは空白区切りの多列数値データの先頭を探す。

    Detection rule: a line whose fields (split on comma or whitespace) are all
    floats and number more than ``_MIN_COLS`` counts as a numeric row; two
    consecutive numeric rows with the same column count fix the data start.
    判定規則: 全フィールド（カンマまたは空白で分割）が float かつ列数が
    ``_MIN_COLS`` を超える行を「数値行」とみなし、同じ列数の数値行が 2 行
    連続した時点でデータ先頭と確定する。

    Returns
    -------
    tuple or None
        ``(skiprows, n_cols)``, or ``None`` when no such region exists.
        ``(先頭スキップ行数, 列数)``。見つからなければ ``None``。
    """
    _MIN_COLS = 10

    prev_ncols: int = -1
    prev_index: int = -1
    for i, line in enumerate(lines):
        stripped = _split_data_fields(line)
        try:
            ncols = len(stripped)
            if ncols <= _MIN_COLS:
                raise ValueError  # 列数不足はメタデータ行とみなす
            _ = [float(v) for v in stripped]   # 全フィールドが数値か検証
        except ValueError:
            prev_ncols = -1
            prev_index = -1
            continue

        if ncols == prev_ncols:
            return prev_index, ncols

        prev_ncols = ncols
        prev_index = i
    return None


def _find_single_column_start(lines: List[str]) -> Optional[int]:
    """
    Find the start of one-value-per-line numeric data.
    1 行 1 値の数値データの先頭を探す。

    Detection rule: the first position where two consecutive lines each parse
    as a single float fixes the data start.
    判定規則: float に変換できる行が 2 行連続した最初の位置をデータ先頭と
    確定する。

    Returns
    -------
    int or None
        ``skiprows``, or ``None`` when no such region exists.
        先頭スキップ行数。見つからなければ ``None``。
    """
    prev_index = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            prev_index = -1
            continue
        try:
            float(stripped)
        except ValueError:
            prev_index = -1
            continue

        if prev_index >= 0:
            return prev_index

        prev_index = i
    return None


def _verify_multi_column_consistency(
    lines: List[str], skiprows: int, n_cols: int, path: str,
) -> None:
    """
    Ensure every data row has exactly the detected column count.
    全データ行の列数が検出列数と一致することを確認する。

    ``np.loadtxt`` with ``usecols`` silently truncates rows that have *more*
    columns than requested, so a detection that locked onto a narrow numeric
    metadata block would otherwise corrupt the data without any error. This
    check turns such layout mismatches into an explicit failure.
    ``np.loadtxt`` は ``usecols`` 指定時、要求より列数の*多い*行を黙って
    切り捨てる。そのため判定が列数の少ない数値メタデータブロックに固定
    されると、エラーなしにデータが破損してしまう。この検証でレイアウト
    不一致を明示的な失敗に変える。

    Raises
    ------
    ValueError
        If any non-blank row after the data start has a different column
        count, with guidance to pass an explicit format.
    """
    for i in range(skiprows, len(lines)):
        stripped = _split_data_fields(lines[i])
        if not stripped:
            # Blank (e.g. trailing) lines are skipped by np.loadtxt as well.
            # 空行（末尾の空行など）は np.loadtxt 側でも読み飛ばされる。
            continue
        if len(stripped) != n_cols:
            raise ValueError(
                f"inconsistent column count in {path}: line {i + 1} has "
                f"{len(stripped)} column(s), expected {n_cols}. Header "
                f"detection may have locked onto a metadata block; pass an "
                f"explicit format (fmt='multi-column' or 'single-column') "
                f"or inspect the input file."
            )


def detect_afm_format(path: str, fmt: str = "auto") -> AfmTextFormat:
    """
    Detect (or apply the requested) text layout of an AFM file.
    AFM ファイルのテキストレイアウトを判定（または指定形式を適用）する。

    Parameters
    ----------
    path
        Path to the AFM text/CSV file.
        AFM テキスト/CSV ファイルのパス。
    fmt
        ``"auto"`` tries multi-column first, then single-column.
        ``"multi-column"`` / ``"single-column"`` restrict detection to one
        layout — the escape hatch when auto-detection picks the wrong region.
        ``"auto"`` は多列形式 → 1 列形式の順に試す。``"multi-column"`` /
        ``"single-column"`` は判定を一方のレイアウトに限定する。自動判定が
        誤った領域を選んだときの回避手段。

    Returns
    -------
    AfmTextFormat
        Layout to be passed to `load_afm_text`, also suitable for recording
        in provenance metadata.
        `load_afm_text` へ渡すレイアウト。来歴メタデータへの記録にも使える。

    Raises
    ------
    ValueError
        If `fmt` is unknown, or no numeric data region matching the
        requested layout can be found, or the multi-column region has an
        inconsistent column count.
    """
    if fmt not in FORMAT_KINDS:
        raise ValueError(
            f"unknown fmt {fmt!r}; expected one of {', '.join(FORMAT_KINDS)}"
        )

    lines, encoding = _read_text_lines(path)

    if fmt in ("auto", "multi-column"):
        found = _find_multi_column_start(lines)
        if found is not None:
            skiprows, n_cols = found
            _verify_multi_column_consistency(lines, skiprows, n_cols, path)
            return AfmTextFormat("multi-column", skiprows, n_cols, encoding)
        if fmt == "multi-column":
            raise ValueError(
                f"no multi-column numeric data region found in {path}"
            )

    skiprows = _find_single_column_start(lines)
    if skiprows is None:
        raise ValueError(f"数値データ領域を検出できませんでした: {path}")
    return AfmTextFormat("single-column", skiprows, 1, encoding)


def _read_header_lines(path: str, encoding: str, limit: int) -> List[str]:
    """
    Read up to `limit` leading lines using a known encoding.
    既知のエンコーディングで先頭 `limit` 行までを読み込む。

    Used to recover the delimiter and the height value unit without re-reading
    a multi-megabyte data body.
    数 MB のデータ本体を読み直さずに区切りと高さの値単位を得るために使う。
    """
    out: List[str] = []
    with open(path, encoding=encoding) as f:
        for _ in range(limit):
            ln = f.readline()
            if not ln:
                break
            out.append(ln)
    return out


def _shimadzu_scan_size(
    header_lines: List[str],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse Shimadzu ``SizeX`` / ``SizeY`` keys into micrometers.
    島津の ``SizeX`` / ``SizeY`` キーを µm として読み取る。

    Returns
    -------
    tuple
        ``(x_um, y_um)``; either element is ``None`` when its axis is absent.
        ``(x_um, y_um)``。軸が無い要素は ``None``。
    """
    x_um: Optional[float] = None
    y_um: Optional[float] = None
    for line in header_lines:
        m = _SHIMADZU_SIZE_RE.match(line)
        if m is None:
            continue
        value_um = float(m.group(2)) * _LENGTH_UNIT_TO_UM.get(m.group(3).lower(), 1.0)
        if m.group(1).upper() == "X":
            x_um = value_um
        else:
            y_um = value_um
        if x_um is not None and y_um is not None:
            break
    return x_um, y_um


def _gwyddion_scan_size(
    header_lines: List[str],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse Gwyddion size comments into micrometers (1st = X, 2nd = Y).
    Gwyddion のサイズコメントを µm として読み取る（1 つ目=X、2 つ目=Y）。

    Reads the first two ``# <key>: <number> <length-unit>`` comment entries,
    independent of the (localized) key words, so a Japanese- or English-locale
    export is handled identically. Width precedes Height in Gwyddion's output.
    最初の 2 つの ``# <キー>: <数値> <長さ単位>`` コメントを、（ローカライズ
    された）キー語に依存せず読み取る。日本語・英語どちらのロケール出力も同様に
    扱える。Gwyddion の出力では Width が Height より先に並ぶ。
    """
    sizes: List[float] = []
    for line in header_lines:
        m = _GWY_COMMENT_RE.match(line)
        if m is None:
            continue
        sm = _GWY_SIZE_VALUE_RE.match(m.group(1))
        if sm is None:
            continue
        sizes.append(float(sm.group(1)) * _LENGTH_UNIT_TO_UM.get(sm.group(2).lower(), 1.0))
        if len(sizes) >= 2:
            return sizes[0], sizes[1]
    return None, None


def _gwyddion_height_unit_to_nm(header_lines: List[str]) -> float:
    """
    Return the nm-per-unit factor from a Gwyddion value-unit comment.
    Gwyddion の値単位コメントから nm 換算係数を返す。

    Gwyddion exports height in SI units (its matrix is typically in meters),
    recorded as a unit-only comment such as ``# Value units: m``. When no such
    comment is present (Shimadzu/Bruker exports), ``1.0`` is returned so the
    data is treated as already being in nanometers.
    Gwyddion は高さを SI 単位（行列は通常メートル）で出力し、``# Value units: m``
    のような単位のみのコメントで記録する。そのコメントが無い場合（島津/Bruker の
    出力）は ``1.0`` を返し、データを既に nm とみなす。
    """
    for line in header_lines:
        m = _GWY_COMMENT_RE.match(line)
        if m is None:
            continue
        um = _GWY_UNIT_ONLY_RE.match(m.group(1))
        if um is not None:
            return _LENGTH_UNIT_TO_NM.get(um.group(1).lower(), 1.0)
    return 1.0


def read_scan_size(path: str) -> Optional[ScanSize]:
    """
    Read the physical scan size from an AFM file header, if present.
    AFM ファイルのヘッダから物理走査範囲を読み取る（記録があれば）。

    This recognizes the Shimadzu SPM ``SizeX`` / ``SizeY`` keys under
    ``[SCANNING PARAMS]`` and the Gwyddion "Export Text" size comments
    (first ``# <key>: <n> <unit>`` = X/Width, second = Y/Height). Exports that
    strip the header (e.g. the bare ``Height(nm)`` single-column text from
    Bruker NanoScope, or a Gwyddion export written without the informational
    header) carry no scan size, so the caller must obtain it elsewhere.
    ``[SCANNING PARAMS]`` 配下の島津 SPM の ``SizeX`` / ``SizeY`` キーと、
    Gwyddion「Export Text」のサイズコメント（1 つ目の ``# <キー>: <数値> <単位>``
    が X/Width、2 つ目が Y/Height）を認識する。ヘッダを落としたエクスポート
    （Bruker NanoScope の ``Height(nm)`` だけの 1 列テキストや、情報ヘッダ無しで
    書き出した Gwyddion エクスポート等）は走査範囲を持たないため、呼び出し側が
    別途取得する。

    Parameters
    ----------
    path
        Path to the AFM text/CSV file.
        AFM テキスト/CSV ファイルのパス。

    Returns
    -------
    ScanSize or None
        Parsed scan size in micrometers, or ``None`` when the header does not
        record it.
        µm 単位の走査範囲。ヘッダに記録が無ければ ``None``。

    Notes
    -----
    A header that records only one of the two axes is treated as missing,
    because a single-axis scan size cannot calibrate length in both
    directions and is more likely a malformed header than a real scan.
    片方の軸しか記録されていないヘッダは「無し」として扱う。片軸だけの走査範囲
    では両方向の長さを較正できず、実走査よりもヘッダ不整合である可能性が高い。

    For a Gwyddion native ``.gwy`` file the size is read from the channel's
    ``xreal`` / ``yreal`` extents instead of a text header (see `lib.gwy_io`).
    Gwyddion ネイティブの ``.gwy`` ファイルではテキストヘッダではなくチャンネルの
    ``xreal`` / ``yreal`` 範囲から読み取る（`lib.gwy_io` を参照）。
    """
    # Dispatch binary .gwy to the Gwyddion reader; the gwyfile dependency is
    # imported only inside lib.gwy_io, so text-only callers never need it.
    # バイナリの .gwy は Gwyddion リーダへ振り分ける。gwyfile 依存は lib.gwy_io
    # 内でのみ import するため、テキスト専用の呼び出し側には不要。
    if os.path.splitext(path)[1].lower() == ".gwy":
        from . import gwy_io
        return gwy_io.read_gwy_scan_size(path)

    lines, _encoding = _read_text_lines(path)
    header = lines[:_SCAN_SIZE_HEADER_SCAN_LIMIT]

    # Shimadzu's explicit SizeX/SizeY wins; fall back to Gwyddion size comments.
    # 島津の明示的な SizeX/SizeY を優先し、無ければ Gwyddion のサイズコメントを使う。
    x_um, y_um = _shimadzu_scan_size(header)
    if x_um is None or y_um is None:
        x_um, y_um = _gwyddion_scan_size(header)

    if x_um is None or y_um is None:
        return None
    if not (x_um > 0 and y_um > 0):
        return None
    return ScanSize(x_um=x_um, y_um=y_um)


def load_afm_text(
    path: str, fmt: Union[str, AfmTextFormat] = "auto",
) -> np.ndarray:
    """
    Load an AFM text/CSV file as a 2D NumPy array.
    AFM のテキスト/CSV ファイルを 2 次元 NumPy 配列として読み込む。

    By default the header length, delimiter, column count, and encoding are
    all detected from the file itself, so callers do not need to know the
    instrument origin. Pass `fmt` to override the detection when needed.
    既定ではヘッダ行数・区切り文字・列数・エンコーディングをファイル自身から
    自動判定するため、呼び出し側は装置種別を意識する必要がない。必要に応じて
    `fmt` で判定を上書きできる。

    Multi-column files (Shimadzu SPM-9600 commas, Gwyddion "Export Text"
    whitespace/tab matrices) are read with the detected delimiter and column
    count, which supports non-square scans. Single-column files (Bruker
    NanoScope etc.) are read as a flat array and reshaped into a square
    ``(s, s)`` array only when the element count is a perfect square.
    多列形式（島津 SPM-9600 のカンマ、Gwyddion「Export Text」の空白/タブ行列）は
    検出した区切りと列数をそのまま使うため、非正方形スキャンも読める。1 列形式
    （Bruker NanoScope 等）は 1 次元として読み込んだ後、要素数の平方根が整数の
    ときに限り正方形 ``(s, s)`` に reshape する。

    Height values are returned in nanometers. Shimadzu/Bruker exports are
    already in nm and pass through unchanged; a Gwyddion export that declares a
    different unit in its header (e.g. ``# Value units: m``) is converted to nm.
    高さ値は nm 単位で返す。島津/Bruker の出力は既に nm でそのまま通す。
    Gwyddion 出力がヘッダで別単位（例: ``# Value units: m``）を宣言している場合は
    nm へ換算する。

    Parameters
    ----------
    path
        Path to the AFM text/CSV file.
        AFM テキスト/CSV ファイルのパス。
    fmt
        ``"auto"`` (default), ``"multi-column"``, ``"single-column"``, or an
        `AfmTextFormat` from a previous `detect_afm_format` call (avoids
        re-scanning the file).
        ``"auto"``（既定）、``"multi-column"``、``"single-column"``、または
        事前の `detect_afm_format` の結果である `AfmTextFormat`（ファイルの
        再走査を省ける）。

    Returns
    -------
    np.ndarray
        2-D height array.
        2 次元の高さ配列。

    Raises
    ------
    ValueError
        If the numeric data region cannot be detected, if the multi-column
        region has an inconsistent column count, if a single-column file
        does not contain a perfect-square number of values, or if the loaded
        data contains non-finite values.
        数値データ領域を検出できない場合、多列領域の列数が一致しない場合、
        1 列形式の要素数が平方数にならない場合、または読み込んだデータに
        非有限値が含まれる場合。
    """
    info = fmt if isinstance(fmt, AfmTextFormat) else detect_afm_format(path, fmt)

    # Read the small text header once to recover the delimiter (Gwyddion uses
    # whitespace/tabs, Shimadzu commas) and the height value unit (Gwyddion
    # exports in meters; Shimadzu/Bruker are already nanometers).
    # 小さなテキストヘッダを 1 度読み、区切り（Gwyddion は空白/タブ、島津は
    # カンマ）と高さの値単位（Gwyddion はメートル出力、島津/Bruker は既に nm）を
    # 取得する。
    header = _read_header_lines(path, info.encoding, info.skiprows + 1)
    unit_to_nm = _gwyddion_height_unit_to_nm(header[:info.skiprows])

    if info.n_cols > 1:
        # Multi-column: detect the delimiter from the first data row, then use
        # the detected column count directly so non-square scans (e.g.
        # 1024x512) are read without manual configuration.
        # 多列形式：最初のデータ行から区切りを判定し、検出列数をそのまま使う
        # （手入力不要、非正方形でも対応）。
        first_data_line = header[info.skiprows] if len(header) > info.skiprows else ""
        delimiter = "," if "," in first_data_line else None
        data = np.loadtxt(path, delimiter=delimiter, dtype="float",
                          usecols=range(info.n_cols), skiprows=info.skiprows,
                          encoding=info.encoding)
    else:
        # Single-column: reshape into a square only when sqrt(N) is integer.
        # 1 列形式：平方根が整数なら正方形として reshape。
        flat = np.loadtxt(path, dtype="float", skiprows=info.skiprows,
                          encoding=info.encoding)
        sqrt_size = int(round(flat.size ** 0.5))
        if sqrt_size * sqrt_size != flat.size:
            raise ValueError(
                f"1列形式のデータ要素数 ({flat.size}) が正方形の2乗になりません。"
                f" 非正方形データは未対応です: {path}"
            )
        data = flat.reshape(sqrt_size, sqrt_size)

    # Convert to nanometers when the header declares another unit (Gwyddion
    # "Value units: m"); a factor of 1.0 leaves Shimadzu/Bruker data unchanged.
    # ヘッダが別単位を宣言している場合（Gwyddion の "Value units: m"）は nm へ
    # 換算する。係数 1.0 のときは島津/Bruker のデータをそのまま通す。
    if unit_to_nm != 1.0:
        data = data * unit_to_nm

    # NaN/Inf would silently poison every downstream statistic (background
    # estimation, thresholds, fiber heights), so reject them at the source.
    # NaN/Inf は下流の全統計（背景推定・しきい値・繊維高さ）を黙って汚染する
    # ため、読み込みの時点で拒否する。
    if not np.isfinite(data).all():
        n_bad = int((~np.isfinite(data)).sum())
        raise ValueError(
            f"non-finite values (NaN/Inf) in {path}: {n_bad} element(s)"
        )
    return data


def load_afm_image(
    path: str,
    fmt: Union[str, AfmTextFormat] = "auto",
    channel: Optional[Union[int, str]] = None,
) -> np.ndarray:
    """
    Load any supported AFM input (text/CSV or Gwyddion ``.gwy``) as a 2D array.
    対応する任意の AFM 入力（テキスト/CSV または Gwyddion ``.gwy``）を 2 次元
    配列として読み込む。

    This is the format-agnostic entry point for callers that only need the
    height image and do not care whether the source is a text export or a
    native ``.gwy`` file (e.g. GUI image previews). Text inputs delegate to
    `load_afm_text`; ``.gwy`` inputs delegate to `lib.gwy_io.load_gwy_image`,
    whose selected channel's height matrix is returned. Both return heights in
    nanometers.
    高さ画像だけが必要で、入力がテキストエクスポートかネイティブ ``.gwy`` かを
    問わない呼び出し側（GUI の画像プレビュー等）のための形式非依存の入口。
    テキスト入力は `load_afm_text` に、``.gwy`` 入力は `lib.gwy_io.load_gwy_image`
    に委譲し、選択チャンネルの高さ行列を返す。いずれも nm 単位で返す。

    Parameters
    ----------
    path
        Path to the AFM text/CSV or ``.gwy`` file.
        AFM テキスト/CSV または ``.gwy`` ファイルのパス。
    fmt
        Text-layout selector forwarded to `load_afm_text`; ignored for ``.gwy``.
        `load_afm_text` へ渡すテキストレイアウト指定。``.gwy`` では無視される。
    channel
        Channel selector forwarded to `lib.gwy_io.load_gwy_image` for ``.gwy``
        inputs (``None`` auto-selects topography); ignored for text inputs.
        ``.gwy`` 入力で `lib.gwy_io.load_gwy_image` へ渡すチャンネル指定
        （``None`` は地形を自動選択）。テキスト入力では無視される。

    Returns
    -------
    np.ndarray
        2-D height array in nanometers.
        nm 単位の 2 次元高さ配列。
    """
    if os.path.splitext(path)[1].lower() == ".gwy":
        from . import gwy_io
        return gwy_io.load_gwy_image(path, channel=channel).data
    return load_afm_text(path, fmt=fmt)
