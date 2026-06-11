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

The header length, column count, and encoding are all auto-detected from
the file itself so callers do not need to specify them.
ヘッダ行数・列数・エンコーディングはファイル自身から自動判定するため、
呼び出し側は何も指定する必要がない。
"""

import numpy as np


def _detect_data_start(path: str) -> tuple:
    """
    Auto-detect the numeric data start row, column count, and encoding.
    数値データが始まる行番号・列数・エンコーディングを自動検出する。

    対応フォーマット:
      [多列形式] 島津 SPM-9600 等：カンマ区切りで多数列が並ぶ
                 例）1.23,4.56,7.89,...（1行 = 1スキャンライン）
      [1列形式]  Bruker NanoScope 等：1行に1値が縦に並び、ヘッダは先頭数行のテキスト行のみ
                 例）Height(nm) というヘッダ行の後、1.267e+001 が image_size² 行続く

    検出アルゴリズム:
      ・cp932 → utf-8 → latin-1 の順でデコードを試みる。
      ・各行をカンマで分割し、全フィールドが float に変換できる行を「数値行」とみなす。
      ・[多列形式] 列数が _MIN_COLS(=10) 超の数値行が 2 行連続 → その開始行をデータ先頭と確定。
      ・[1列形式] 上記で多列が見つからなかった場合、ファイル先頭から走査し、
        float に変換できる行が 2 行連続した最初の行をデータ先頭と確定。

    Returns
    -------
    tuple
        ``(skiprows, n_cols, encoding)``.
        ``skiprows`` is the number of header rows to pass to ``np.loadtxt``.
        ``n_cols`` is the detected number of data columns (1 for single-column
        layouts, otherwise the actual column count).
        ``encoding`` is the codec that successfully decoded the file.
        ``np.loadtxt`` に渡す先頭スキップ行数、データ列数（1 列形式は 1、
        多列形式は実列数）、読み込みに成功したエンコーディング名。

    Raises
    ------
    ValueError
        If no numeric data region can be detected.
        数値データ領域を検出できなかった場合。
    """
    # Try UTF-8 with BOM first; this codec also handles UTF-8 without BOM.
    # UTF-8 BOM 付きを最優先で試す（BOM なしの UTF-8 でもこのコーデックで読める）。
    # Then try cp932, with latin-1 only as a last-resort byte-preserving fallback.
    # cp932 はその次。latin-1 は最後の保険（任意のバイト列を必ず通すため）。
    _ENCODINGS = ("utf-8-sig", "cp932", "utf-8", "latin-1")
    _MIN_COLS   = 10

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

    # --- Pass 1: find comma-separated multi-column data (columns > _MIN_COLS). ---
    # --- パス1: 多列形式（カンマ区切り、列数 > _MIN_COLS）を探す ---
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
            return prev_index, ncols, used_enc

        prev_ncols = ncols
        prev_index = i

    # --- Pass 2: find single-column data (one numeric value per line). ---
    # --- パス2: 1列形式（1値/行）を探す ---
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
            return prev_index, 1, used_enc

        prev_index = i

    raise ValueError(f"数値データ領域を検出できませんでした: {path}")


def load_afm_text(path: str) -> np.ndarray:
    """
    Load an AFM text/CSV file as a 2D NumPy array.
    AFM のテキスト/CSV ファイルを 2 次元 NumPy 配列として読み込む。

    The header length, delimiter, column count, and encoding are all detected
    from the file itself, so callers do not need to know the instrument origin.
    ヘッダ行数・区切り文字・列数・エンコーディングはファイル自身から自動判定するため、
    呼び出し側は装置種別を意識する必要がない。

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

    Returns
    -------
    np.ndarray
        2-D height array.
        2 次元の高さ配列。

    Raises
    ------
    ValueError
        If the numeric data region cannot be detected, or if a single-column
        file does not contain a perfect-square number of values.
        数値データ領域を検出できなかった場合、または 1 列形式の要素数が
        正方形（平方数）にならない場合。
    """
    skiprows, n_cols, encoding = _detect_data_start(path)

    if n_cols > 1:
        # Multi-column: use the detected column count directly so non-square
        # scans (e.g. 1024x512) are read without manual configuration.
        # 多列形式：検出列数をそのまま使う（手入力不要、非正方形でも対応）。
        return np.loadtxt(path, delimiter=",", dtype="float",
                          usecols=range(n_cols), skiprows=skiprows, encoding=encoding)

    # Single-column: reshape into a square only when sqrt(N) is integer.
    # 1 列形式：平方根が整数なら正方形として reshape。
    flat = np.loadtxt(path, dtype="float", skiprows=skiprows, encoding=encoding)
    sqrt_size = int(round(flat.size ** 0.5))
    if sqrt_size * sqrt_size != flat.size:
        raise ValueError(
            f"1列形式のデータ要素数 ({flat.size}) が正方形の2乗になりません。"
            f" 非正方形データは未対応です: {path}"
        )
    return flat.reshape(sqrt_size, sqrt_size)
