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
and `read_scan_size` here dispatch ``.gwy`` paths to it, keeping the
feature-specific ``gwyfile`` dependency out of text-only workflows.
Gwyddion ネイティブの ``.gwy`` ファイルは、手動の「Export Text」工程を経ずに
`lib.gwy_io` 経由で直接読み込むこともできる。``.gwy`` はバイナリの複数チャンネル
コンテナのため、その処理は専用モジュールに置き、本モジュールの `load_afm_image`
と `read_scan_size` が ``.gwy`` パスをそこへ振り分ける。これにより `.gwy` 用の
``gwyfile`` 依存をテキスト専用ワークフローから排除する。

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
# "auto" tries multi-column first, then single-column.
# `detect_afm_format` と `load_afm_text` が受け付ける形式種別。
# "auto" は多列形式 → 1 列形式の順に試す。
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


# A decimal number with an optional exponent. Written out instead of a run of
# digits, dots and "eE+-" so that an "e" or "E" is read as an exponent only when
# digits follow it, and otherwise is left to the unit.
# 指数部を持ちうる 10 進数。数字・点・"eE+-" の並びとして書かないのは、"e" や
# "E" を、後に数字が続くときだけ指数と読み、そうでなければ単位に残すため。
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"

# Shimadzu SPM file headers record the scan range under [SCANNING PARAMS] as
# e.g. ``SizeX: 2.0000um`` / ``SizeY: 2.0000um``. The unit is typically um or nm;
# it is read by `_length_unit_nm`.
# 島津 SPM のヘッダは [SCANNING PARAMS] 配下に走査範囲を ``SizeX: 2.0000um`` /
# ``SizeY: 2.0000um`` の形で記録する。単位は通常 um または nm で、
# `_length_unit_nm` で読む。
_SHIMADZU_SIZE_RE = re.compile(
    r"^\s*Size([XY])\s*:\s*(" + _NUMBER + r")\s*(\S+)\s*$",
    re.IGNORECASE,
)

# Shimadzu SPM text exports state the unit of the height values on the line
# just before the data, e.g. ``[DATA Unit(nm)]``.
# 島津 SPM のテキスト出力は、データ直前の行に高さの値の単位を
# ``[DATA Unit(nm)]`` の形で書く。
_SHIMADZU_DATA_UNIT_RE = re.compile(
    r"^\s*\[\s*DATA\s+Unit\s*\(\s*([^()]*?)\s*\)\s*\]\s*$", re.IGNORECASE,
)

# A single-column export (Bruker NanoScope) names its values on the line just
# before the data, with their unit in parentheses, e.g. ``Height(nm)``.
# 1 列形式の出力（Bruker NanoScope）は、データ直前の行で値の名前を書き、単位を
# 括弧に入れる（例 ``Height(nm)``）。
_COLUMN_LABEL_UNIT_RE = re.compile(r"^\s*[^()#:\[\]]*\(\s*([^()]*?)\s*\)\s*$")

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
#   - the value-unit entry is the comment that follows the two size entries
#     (Gwyddion writes Channel, Width, Height, Value units in that order)
# The leading "#" distinguishes Gwyddion comments from the Shimadzu "SizeX:"
# keys, which carry no "#". `_GWY_ENTRY_RE` also matches an entry whose value is
# empty, which Gwyddion writes for a dimensionless channel.
# Gwyddion「Export Text」はデータ行列の前に、UI 言語へ翻訳されたコメントヘッダを
# 出力する（上は日本語ロケールの例）。コロンは半角 ":" と全角 "：" が混在し、
# キー語は翻訳されるため、キー語ではなく「値の構造」で判定する:
#   - サイズ項目の値は "<数値> <長さ単位>"（1 つ目=X、2 つ目=Y）
#   - 値の単位項目は 2 つのサイズ項目の次のコメント（Gwyddion は Channel、
#     Width、Height、Value units の順に書く）
# 先頭の "#" により、"#" を持たない島津の "SizeX:" キーと区別する。
# `_GWY_ENTRY_RE` は値が空の項目にも一致する。Gwyddion は無次元のチャンネルで
# 値を空にして書く。
_GWY_COMMENT_RE = re.compile(r"^\s*#\s*[^:：]+[:：]\s*(\S.*?)\s*$")
_GWY_ENTRY_RE = re.compile(r"^\s*#\s*[^:：]+[:：][ \t]*(.*?)\s*$")
_GWY_SIZE_VALUE_RE = re.compile(r"^(" + _NUMBER + r")\s*(\S+)$")

# Length units an AFM file can state, in nanometres, keyed by their casefolded
# spelling: metres with the prefixes AFM data use (milli, micro, nano, pico) as
# symbols and spelled out, "micron", and the angstrom as U+00C5, U+212B,
# Gwyddion's ASCII spellings and spelled out. They are matched without regard to
# case because no other prefix is accepted: "MM" or "Mm" can only be a
# millimetre and "PM" a picometre, never a megametre or a petametre, which no
# scan reaches. Casefolding also maps the micro sign U+00B5 onto the Greek mu
# U+03BC and U+212B onto U+00C5. "u" and "~" stand for micro as Gwyddion
# accepts them, and the Cyrillic "м" is Gwyddion's metre. A bare "A" is not an
# angstrom: it is the ampere.
# AFM のファイルが書きうる長さ単位（nm 換算）。綴りを casefold した文字列を
# キーにする。AFM のデータが使う接頭辞（ミリ・マイクロ・ナノ・ピコ）を付けた
# メートルの記号と綴り、"micron"、オングストロームの U+00C5・U+212B・Gwyddion の
# ASCII 表記・綴り。ほかの接頭辞は受け付けないので、大文字と小文字を区別せずに
# 照合する。"MM" や "Mm" はミリメートル、"PM" はピコメートルとしか読めず、
# どの走査も届かないメガメートルやペタメートルにはならない。casefold により
# マイクロ記号 U+00B5 はギリシャ文字ミュー U+03BC に、U+212B は U+00C5 に
# そろう。"u" と "~" は Gwyddion が受け付けるマイクロの代用で、キリル文字の
# "м" は Gwyddion のメートル。単独の "A" はオングストロームではなくアンペアである。
_PREFIX_NM = {"": 1.0e9, "milli": 1.0e6, "micro": 1.0e3, "nano": 1.0, "pico": 1.0e-3}
_LENGTH_UNITS_NM = {
    "m": 1.0e9, "mm": 1.0e6, "μm": 1.0e3, "um": 1.0e3, "~m": 1.0e3,
    "nm": 1.0, "pm": 1.0e-3, "м": 1.0e9,
    "micron": 1.0e3, "microns": 1.0e3, "mum": 1.0e3,
    "å": 0.1, "aa": 0.1, "ang": 0.1,
    **{f"{a}ngstr{o}m{s}": 0.1
       for a in ("a", "å") for o in ("o", "ö") for s in ("", "s")},
    **{f"{prefix}{base}": nm
       for prefix, nm in _PREFIX_NM.items()
       for base in ("meter", "meters", "metre", "metres")},
}


def _length_unit_nm(unit: Optional[str]) -> Optional[float]:
    """
    Nanometres per unit of a length-unit string, or None for anything else.
    長さ単位の文字列 1 単位あたりの nm。長さでなければ None。

    Parameters
    ----------
    unit
        Unit as written in a file header or a Gwyddion SI unit; the spellings
        read are the keys of `_LENGTH_UNITS_NM`, in any case.
        ファイルのヘッダや Gwyddion の SI 単位に書かれた単位。読む綴りは
        `_LENGTH_UNITS_NM` のキーで、大文字と小文字は問わない。

    Returns
    -------
    float or None
        The factor that converts a value in `unit` into nanometres; ``None``
        when `unit` is empty, ``None``, or not a length.
        `unit` の値を nm に換算する係数。`unit` が空・``None``・長さでなければ
        ``None``。

    Examples
    --------
    >>> from lib.afm_io import _length_unit_nm
    >>> _length_unit_nm("m"), _length_unit_nm("µm"), _length_unit_nm("UM")
    (1000000000.0, 1000.0, 1000.0)
    >>> _length_unit_nm("Å"), _length_unit_nm("Nanometers"), _length_unit_nm("MM")
    (0.1, 1.0, 1000000.0)
    >>> _length_unit_nm("deg") is None, _length_unit_nm("km") is None
    (True, True)
    """
    if unit is None:
        return None
    return _LENGTH_UNITS_NM.get(unit.strip().casefold())

# Maximum header lines scanned for scan-size keys. The scan range sits in the
# small text header, so reading the whole multi-megabyte data body is wasteful.
# 走査範囲キーを探すヘッダ行数の上限。走査範囲は小さなテキストヘッダ内にあり、
# 数 MB のデータ本体まで走査するのは無駄なため。
_SCAN_SIZE_HEADER_SCAN_LIMIT = 200

# Maximum input file size accepted by the loaders, in bytes. Parsing
# materializes the whole file in memory (the line list, then the float array),
# so an oversized or wrongly selected input (e.g. a multi-gigabyte log file)
# would exhaust memory long before any layout error surfaces. The cap sits far
# above real AFM exports — an 8192x8192 multi-column text matrix is about
# 1 GiB — and `lib.gwy_io` applies the same cap to `.gwy` files. Set to None
# to disable the check.
# ローダが受け付ける入力ファイルサイズの上限（バイト）。解析時にはファイル
# 全体（行リスト、続いて float 配列）をメモリへ実体化するため、巨大な入力や
# 誤選択された入力（数 GB のログファイル等）はレイアウトエラーより先に
# メモリを枯渇させる。上限は実際の AFM 出力（8192x8192 の多列テキスト行列で
# 約 1 GiB）より十分大きく、`lib.gwy_io` も同じ上限を `.gwy` に適用する。
# None で検査を無効化できる。
MAX_INPUT_FILE_BYTES = 2 * 1024**3  # 2 GiB


def check_input_file_size(path: str) -> None:
    """
    Reject an input file larger than `MAX_INPUT_FILE_BYTES` before reading it.
    `MAX_INPUT_FILE_BYTES` を超える入力ファイルを読み込み前に拒否する。

    Shared by the text loaders in this module and the ``.gwy`` loader in
    `lib.gwy_io`, so every input format applies the same file-size policy.
    The limit is read at call time; callers with legitimately larger files can
    raise `MAX_INPUT_FILE_BYTES` on this module or set it to ``None``.
    本モジュールのテキストローダと `lib.gwy_io` の ``.gwy`` ローダが共用し、
    全入力形式に同じファイルサイズ方針を適用する。上限は呼び出し時に参照する
    ため、正当に大きなファイルを扱う場合は本モジュールの
    `MAX_INPUT_FILE_BYTES` を引き上げるか ``None`` にできる。

    Parameters
    ----------
    path
        Input file to check. A file whose size cannot be read passes, so the
        read itself reports it as missing or unreadable.
        検査する入力ファイル。サイズを読めないファイルは通過させ、欠損・読込不能は
        実際の読み込み側が報告する。

    Raises
    ------
    ValueError
        If the file exists and exceeds the limit.
    """
    limit = MAX_INPUT_FILE_BYTES
    if limit is None:
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        # Let the actual read report missing/unreadable files.
        # 欠損・読込不能ファイルは実際の読み込み側に報告させる。
        return
    if size > limit:
        raise ValueError(
            f"input file is {size} bytes, exceeding the {limit}-byte limit "
            f"(raise lib.afm_io.MAX_INPUT_FILE_BYTES to load larger files): "
            f"{path}"
        )


def _read_text_lines(path: str) -> Tuple[List[str], str]:
    """
    Read all lines of the file, auto-detecting the text encoding.
    テキストエンコーディングを自動判定しながらファイル全行を読み込む。

    Parameters
    ----------
    path
        Text file to read.
        読み込むテキストファイル。

    Returns
    -------
    tuple
        ``(lines, encoding)`` where `encoding` is the codec that succeeded.
        ``(行リスト, 成功したエンコーディング名)``。
    """
    # Enforce the input size cap before the whole file is read into memory.
    # ファイル全体をメモリへ読み込む前に入力サイズ上限を適用する。
    check_input_file_size(path)

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

    Parameters
    ----------
    line
        One line of the file. It is split on commas when it contains one,
        otherwise on whitespace.
        ファイルの 1 行。カンマを含めばカンマで、含まなければ空白で分割する。

    Returns
    -------
    list of str
        The non-empty fields, stripped.
        前後の空白を除いた、空でないフィールド。
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

    Parameters
    ----------
    lines
        Lines of the file, as `_read_text_lines` returns them.
        `_read_text_lines` が返すファイルの行。

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
                raise ValueError  # too few columns: a metadata row / 列数不足はメタデータ行とみなす
            _ = [float(v) for v in stripped]   # every field must be numeric / 全フィールドが数値か検証
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

    Parameters
    ----------
    lines
        Lines of the file, as `_read_text_lines` returns them.
        `_read_text_lines` が返すファイルの行。

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

    Parameters
    ----------
    lines
        Lines of the file.
        ファイルの行。
    skiprows
        Index of the first data row.
        最初のデータ行の位置。
    n_cols
        Column count detected for the data.
        データについて検出した列数。
    path
        The file, named in the error message.
        エラーメッセージに示すファイル。

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
        If `fmt` is unknown, the file exceeds `MAX_INPUT_FILE_BYTES`, no
        numeric data region matching the requested layout can be found, or
        the multi-column region has an inconsistent column count.

    Examples
    --------
    The synthetic scan is a header-less grid of 256 columns; the Bruker
    export is one column of values after one header line. The paths are
    relative to the repository root:

    >>> from lib.afm_io import detect_afm_format
    >>> detect_afm_format("testdata_artificial/sample_isotropic.txt")
    AfmTextFormat(kind='multi-column', skiprows=0, n_cols=256, encoding='utf-8-sig')
    >>> detect_afm_format("testdata_Bruker_txt/NDTOC250306.000.txt")
    AfmTextFormat(kind='single-column', skiprows=1, n_cols=1, encoding='utf-8-sig')
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

    Parameters
    ----------
    path
        Text file to read.
        読み込むテキストファイル。
    encoding
        Codec that already decoded the file (`_read_text_lines`).
        既にこのファイルを読めたコーデック（`_read_text_lines`）。
    limit
        Largest number of lines to read.
        読み込む行数の上限。

    Returns
    -------
    list of str
        The first lines of the file, at most `limit` of them.
        ファイル先頭の行（最大 `limit` 行）。
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

    Parameters
    ----------
    header_lines
        Leading lines of the file (`_read_header_lines`).
        ファイル先頭の行（`_read_header_lines`）。

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
        # A size whose unit is not a length is not a scan size; the axis then
        # stays missing rather than taking a guessed unit.
        # 単位が長さでないサイズは走査範囲ではない。単位を推測せず、その軸は
        # 欠けたままにする。
        unit_nm = _length_unit_nm(m.group(3))
        if unit_nm is None:
            continue
        value_um = float(m.group(2)) * (unit_nm / 1000.0)
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

    Parameters
    ----------
    header_lines
        Leading lines of the file (`_read_header_lines`).
        ファイル先頭の行（`_read_header_lines`）。

    Returns
    -------
    tuple
        ``(x_um, y_um)``, or ``(None, None)`` unless two size entries were
        found.
        ``(x_um, y_um)``。サイズの記載が 2 つ見つからなければ ``(None, None)``。
    """
    sizes: List[float] = []
    for line in header_lines:
        m = _GWY_COMMENT_RE.match(line)
        if m is None:
            continue
        value_um = _gwyddion_size_um(m.group(1))
        if value_um is None:
            continue
        sizes.append(value_um)
        if len(sizes) >= 2:
            return sizes[0], sizes[1]
    return None, None


def _gwyddion_size_um(value: str) -> Optional[float]:
    """
    Read a Gwyddion size entry ``<number> <length-unit>`` in micrometres.
    Gwyddion のサイズ項目 ``<数値> <長さ単位>`` を µm として読む。

    Parameters
    ----------
    value
        The value part of a header comment, after its key.
        ヘッダのコメントのうち、キーの後ろの値の部分。

    Returns
    -------
    float or None
        The size in micrometres; ``None`` unless `value` is a number followed by
        a length unit.
        µm 単位の大きさ。`value` が数値と長さ単位の組でなければ ``None``。
    """
    sm = _GWY_SIZE_VALUE_RE.match(value)
    if sm is None:
        return None
    unit_nm = _length_unit_nm(sm.group(2))
    if unit_nm is None:
        return None
    return float(sm.group(1)) * (unit_nm / 1000.0)


def _not_a_height(unit: str, where: str, path: str) -> ValueError:
    """
    The error raised for a file whose values are declared in a unit that is not a length.
    値が長さでない単位で宣言されたファイルに対して送出する例外。

    Parameters
    ----------
    unit
        The declared unit.
        宣言された単位。
    where
        Which header line declared it, for the message.
        どのヘッダ行が宣言したか（メッセージ用）。
    path
        The input file.
        入力ファイル。

    Returns
    -------
    ValueError
        The error to raise.
        送出する例外。
    """
    return ValueError(
        f"the values of {path} are declared in {unit!r} ({where}), which is not "
        f"a length; this loader returns heights in nm, so a non-height channel "
        f"is refused rather than read as nanometres"
    )


def _gwyddion_height_unit_to_nm(header_lines: List[str], path: str = "") -> Optional[float]:
    """
    Return the nm-per-unit factor a Gwyddion header declares for the values.
    Gwyddion のヘッダが値について宣言する nm 換算係数を返す。

    Gwyddion's "Export Text" writes its comment header as Channel, Width,
    Height and Value units, in that order, with the key words translated. The
    value unit is therefore read as the comment that follows the two size
    entries (each a number and a unit, in any unit), whatever language the keys
    are in. It is the channel's base unit (``m`` for heights, ``deg`` for a
    phase, empty for a dimensionless channel).
    Gwyddion「Export Text」はコメントヘッダを Channel、Width、Height、
    Value units の順に、キー語を翻訳して書く。そのため値の単位は、キーが何語でも、
    2 つのサイズ項目（それぞれ数値と単位の組。単位は問わない）の次のコメントとして
    読む。これはチャンネルの基本単位（高さなら ``m``、位相なら ``deg``、無次元なら
    空）である。

    Parameters
    ----------
    header_lines
        Leading lines of the file (`_read_header_lines`).
        ファイル先頭の行（`_read_header_lines`）。
    path
        The input file, named in the error message.
        入力ファイル。例外のメッセージに載せる。

    Returns
    -------
    float or None
        Nanometres per unit of the stored heights; ``None`` when the header
        declares no value unit. Without the Gwyddion layout, the first comment
        whose whole value is a length unit is taken as the declaration.
        保存された高さ 1 単位あたりの nm。ヘッダが値の単位を宣言していなければ
        ``None``。Gwyddion の並びが無いときは、値全体が長さ単位である最初の
        コメントを宣言とみなす。

    Raises
    ------
    ValueError
        If the Gwyddion layout is present and its value unit is not a length.
    """
    values = [m.group(1) for m in map(_GWY_ENTRY_RE.match, header_lines) if m]
    for i in range(len(values) - 2):
        # The layout is recognized by its shape alone: two sizes, each a number
        # and a unit, then a bare unit or nothing. The sizes need not be in a
        # length unit; an export in pixels still declares its value unit, and a
        # phase channel exported in pixels must be refused like any other.
        # 並びは形だけで見分ける。数値と単位の組であるサイズが 2 つ続き、その次が
        # 単位 1 語か空。サイズが長さの単位である必要はない。画素単位で書き出しても
        # 値の単位は宣言されており、画素単位で書き出した位相のチャンネルもほかと
        # 同じく拒否しなければならない。
        if (_GWY_SIZE_VALUE_RE.match(values[i])
                and _GWY_SIZE_VALUE_RE.match(values[i + 1])
                and len(values[i + 2].split()) <= 1):
            unit = values[i + 2]
            factor = _length_unit_nm(unit)
            if factor is None:
                raise _not_a_height(unit, "Gwyddion value-unit comment", path)
            return factor
    for line in header_lines:
        m = _GWY_COMMENT_RE.match(line)
        if m is None:
            continue
        factor = _length_unit_nm(m.group(1))
        if factor is not None:
            return factor
    return None


def _shimadzu_height_unit_to_nm(header_lines: List[str], path: str = "") -> Optional[float]:
    """
    Return the nm-per-unit factor of a Shimadzu ``[DATA Unit(...)]`` line.
    島津の ``[DATA Unit(...)]`` 行の nm 換算係数を返す。

    Parameters
    ----------
    header_lines
        Header lines before the data (`_read_header_lines`).
        データより前のヘッダ行（`_read_header_lines`）。
    path
        The input file, named in the error message.
        入力ファイル。例外のメッセージに載せる。

    Returns
    -------
    float or None
        Nanometres per unit of the stored heights; ``None`` when the header has
        no ``[DATA Unit(...)]`` line.
        保存された高さ 1 単位あたりの nm。ヘッダに ``[DATA Unit(...)]`` 行が
        無ければ ``None``。

    Raises
    ------
    ValueError
        If the declared unit is not a length.
    """
    for line in header_lines:
        m = _SHIMADZU_DATA_UNIT_RE.match(line)
        if m is None:
            continue
        factor = _length_unit_nm(m.group(1))
        if factor is None:
            raise _not_a_height(m.group(1), "[DATA Unit(...)] line", path)
        return factor
    return None


def _column_label_height_unit_to_nm(header_lines: List[str], path: str = "") -> Optional[float]:
    """
    Return the nm-per-unit factor of a single-column label such as ``Height(nm)``.
    ``Height(nm)`` のような 1 列形式の見出しの nm 換算係数を返す。

    Only the last non-blank line before the data is read, which is where Bruker
    NanoScope single-column exports name their values; blank lines between the
    label and the data are skipped so that they cannot hide a declared unit.
    データより前の、空行でない最後の行だけを読む。Bruker NanoScope の 1 列形式の
    出力が値の名前を書くのはその行である。見出しとデータの間の空行は飛ばし、
    宣言された単位を空行が隠さないようにする。

    Parameters
    ----------
    header_lines
        Header lines before the data (`_read_header_lines`).
        データより前のヘッダ行（`_read_header_lines`）。
    path
        The input file, named in the error message.
        入力ファイル。例外のメッセージに載せる。

    Returns
    -------
    float or None
        Nanometres per unit of the stored values; ``None`` when that line does
        not end in a unit in parentheses.
        保存された値 1 単位あたりの nm。その行が括弧に入った単位で終わらなければ
        ``None``。

    Raises
    ------
    ValueError
        If the unit in parentheses is not a length.
    """
    filled = [line for line in header_lines if line.strip()]
    if not filled:
        return None
    m = _COLUMN_LABEL_UNIT_RE.match(filled[-1])
    if m is None:
        return None
    factor = _length_unit_nm(m.group(1))
    if factor is None:
        raise _not_a_height(m.group(1), f"column label {filled[-1].strip()!r}", path)
    return factor


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
        Path to an AFM text/CSV or Gwyddion ``.gwy`` file.
        AFM テキスト/CSV または Gwyddion ``.gwy`` ファイルのパス。

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

    Examples
    --------
    A Gwyddion text export records its size; the Bruker single-column export
    does not. The paths are relative to the repository root:

    >>> from lib.afm_io import read_scan_size
    >>> read_scan_size("testdata_Gwyddion_txt/_20250318-164122_T.ssp.txt")
    ScanSize(x_um=2.0, y_um=2.0)
    >>> read_scan_size("testdata_Bruker_txt/NDTOC250306.000.txt") is None
    True
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

    Height values are returned in nanometers. The unit the header declares --
    Shimadzu's ``[DATA Unit(nm)]``, Gwyddion's ``# Value units: m``, or a
    single-column label such as Bruker's ``Height(nm)`` -- is converted to nm
    (`_length_unit_nm`); a file whose header declares no unit is taken to be in
    nm already.
    高さ値は nm 単位で返す。ヘッダが宣言する単位（島津の ``[DATA Unit(nm)]``、
    Gwyddion の ``# Value units: m``、Bruker の ``Height(nm)`` のような 1 列形式の
    見出し）を nm へ換算する（`_length_unit_nm`）。単位を宣言しないヘッダの
    ファイルは、既に nm とみなす。

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
        If the file exceeds `MAX_INPUT_FILE_BYTES`, if the numeric data
        region cannot be detected, if the multi-column region has an
        inconsistent column count, if a single-column file does not contain
        a perfect-square number of values, if the header declares a value unit
        that is not a length (for example a phase channel in ``deg``), or if
        the loaded data contains non-finite values.
        ファイルが `MAX_INPUT_FILE_BYTES` を超える場合、数値データ領域を
        検出できない場合、多列領域の列数が一致しない場合、1 列形式の要素数が
        平方数にならない場合、ヘッダが長さでない値の単位を宣言している場合
        （例: ``deg`` の位相チャンネル）、または読み込んだデータに非有限値が
        含まれる場合。

    Examples
    --------
    The path is relative to the repository root, where the test scans are
    stored:

    >>> from lib.afm_io import load_afm_text
    >>> image = load_afm_text("testdata_artificial/sample_isotropic.txt")
    >>> image.shape, image.dtype
    ((256, 256), dtype('float64'))
    """
    # Check here as well as in _read_text_lines: a pre-detected AfmTextFormat
    # skips detection, and np.loadtxt below reads the whole file regardless.
    # _read_text_lines に加えてここでも検査する。事前検出済みの AfmTextFormat
    # を渡すと検出が省かれ、下の np.loadtxt はいずれにせよ全体を読むため。
    check_input_file_size(path)

    info = fmt if isinstance(fmt, AfmTextFormat) else detect_afm_format(path, fmt)

    # Read the small text header once to recover the delimiter (Gwyddion uses
    # whitespace/tabs, Shimadzu commas) and the height value unit (Gwyddion
    # exports in meters; Shimadzu/Bruker are already nanometers).
    # 小さなテキストヘッダを 1 度読み、区切り（Gwyddion は空白/タブ、島津は
    # カンマ）と高さの値単位（Gwyddion はメートル出力、島津/Bruker は既に nm）を
    # 取得する。
    header = _read_header_lines(path, info.encoding, info.skiprows + 1)
    # The value unit is taken from whichever declaration the header carries:
    # Shimadzu's [DATA Unit(...)], Gwyddion's value-unit comment, or a
    # single-column label such as Bruker's "Height(nm)". A header that declares
    # none is read as nanometres; one that declares a unit other than a length
    # is refused, because the array is returned as heights in nm.
    # 値の単位はヘッダにある宣言から取る。島津の [DATA Unit(...)]、Gwyddion の
    # 値の単位のコメント、Bruker の "Height(nm)" のような 1 列形式の見出しである。
    # 宣言の無いヘッダは nm とみなし、長さ以外の単位を宣言するものは拒否する。
    # 配列を nm の高さとして返すためである。
    lead = header[:info.skiprows]
    unit_to_nm = _shimadzu_height_unit_to_nm(lead, path)
    if unit_to_nm is None:
        unit_to_nm = _gwyddion_height_unit_to_nm(lead, path)
    if unit_to_nm is None and info.n_cols == 1:
        unit_to_nm = _column_label_height_unit_to_nm(lead, path)
    if unit_to_nm is None:
        unit_to_nm = 1.0

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
    # "Value units: m"); a factor of 1.0 leaves nm data unchanged.
    # ヘッダが別単位を宣言している場合（Gwyddion の "Value units: m"）は nm へ
    # 換算する。係数 1.0 のときは nm のデータをそのまま通す。
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

    Examples
    --------
    A Gwyddion text export and a native ``.gwy`` file; the paths are relative
    to the repository root, where the test scans are stored:

    >>> from lib.afm_io import load_afm_image
    >>> load_afm_image("testdata_Gwyddion_txt/_20250318-164122_T.ssp.txt").shape
    (1024, 1024)
    >>> load_afm_image("testdata_Gwyddion_gwy/_20250318-164122_T.ssp.gwy").shape
    (1024, 1024)
    """
    if os.path.splitext(path)[1].lower() == ".gwy":
        from . import gwy_io
        return gwy_io.load_gwy_image(path, channel=channel).data
    return load_afm_text(path, fmt=fmt)
