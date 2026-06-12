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
[Multi-column]  Shimadzu SPM-9600 etc.: comma-separated rows of many columns.
                e.g. ``1.23,4.56,7.89,...`` (one row = one scan line)
[多列形式]      島津 SPM-9600 等：カンマ区切りで多数列が並ぶ。
                例）1.23,4.56,7.89,...（1 行 = 1 スキャンライン）

[Single-column] Bruker NanoScope etc.: one value per line, preceded by
                a few text-only header rows.
                e.g. a ``Height(nm)`` header row followed by ``image_size**2``
                values such as ``1.267e+001``.
[1 列形式]      Bruker NanoScope 等：1 行に 1 値が縦に並び、ヘッダは先頭数行のテキスト行のみ。
                例）Height(nm) というヘッダ行の後、1.267e+001 が image_size² 行続く。

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


def _find_multi_column_start(lines: List[str]) -> Optional[Tuple[int, int]]:
    """
    Find the start of comma-separated multi-column numeric data.
    カンマ区切りの多列数値データの先頭を探す。

    Detection rule: a line whose comma-separated fields are all floats and
    number more than ``_MIN_COLS`` counts as a numeric row; two consecutive
    numeric rows with the same column count fix the data start.
    判定規則: カンマ区切りの全フィールドが float かつ列数が ``_MIN_COLS`` を
    超える行を「数値行」とみなし、同じ列数の数値行が 2 行連続した時点で
    データ先頭と確定する。

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
        parts = line.strip().split(",")
        stripped = [p.strip() for p in parts if p.strip() != ""]
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
        stripped = [p.strip() for p in lines[i].strip().split(",") if p.strip() != ""]
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

    Multi-column files (Shimadzu SPM-9600 etc.) are read with the detected
    column count, which supports non-square scans. Single-column files
    (Bruker NanoScope etc.) are read as a flat array and reshaped into a
    square ``(s, s)`` array only when the element count is a perfect square.
    多列形式（島津 SPM-9600 等）は検出した列数をそのまま使うため、非正方形スキャンも
    そのまま読める。1 列形式（Bruker NanoScope 等）は 1 次元として読み込んだ後、
    要素数の平方根が整数のときに限り正方形 ``(s, s)`` に reshape する。

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

    if info.n_cols > 1:
        # Multi-column: use the detected column count directly so non-square
        # scans (e.g. 1024x512) are read without manual configuration.
        # 多列形式：検出列数をそのまま使う（手入力不要、非正方形でも対応）。
        data = np.loadtxt(path, delimiter=",", dtype="float",
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
