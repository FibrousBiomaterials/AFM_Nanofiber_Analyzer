# -*- coding: utf-8 -*-
"""
Save and load NumPy arrays with blosc2 compression.
blosc2 圧縮を用いて NumPy 配列を保存・読み込みする。

This module centralizes the legacy single-array payload helpers
(`save_blosc2` / `load_blosc2`) and the current multi-array `.b2z` bundle API
used by the pipeline, CLI, measurement layer, and GUI plugins.
本モジュールは、従来の単一配列 payload ヘルパー
（`save_blosc2` / `load_blosc2`）と、パイプライン・CLI・計測層・GUI
プラグインが使う現行の複数配列 `.b2z` バンドル API を一元管理する。

Notes
-----
`blosc2.pack_array2` raises `ZeroDivisionError` for empty arrays (`size == 0`)
because chunk-size calculation is not supported for this edge case.
`blosc2.pack_array2` は要素数 0 の配列（`size == 0`）で
チャンクサイズ計算に失敗し、`ZeroDivisionError` を起こす。
Therefore, empty arrays are saved with NumPy standard format (`.npy`),
and load-time format detection is done using file magic bytes.
そのため size == 0 の配列は numpy 標準形式（`.npy`）にフォールバックして保存し、
読み込み時にファイル先頭のマジックバイトで自動判定する。
"""

import math
import os
import tempfile

import numpy as np
import blosc2

# Magic bytes at the head of NumPy `.npy` files.
_NPY_MAGIC = b'\x93NUMPY'

# Default cap on the decompressed size of a single array loaded by
# `load_blosc2`, in bytes. Both storage formats it reads declare their array
# size in a small header: a `.npy` header declares shape and dtype, and a
# blosc2 cframe declares its uncompressed byte count. In both cases the
# declared size is unrelated to the file size — a 128-byte `.npy` can declare
# a multi-terabyte array, and a compressed blosc2 payload of constant values
# stays tiny on disk — so the declared size is checked before the array is
# materialized. Matches `MAX_BUNDLE_DECOMPRESSED_BYTES`; set to None to
# disable the check.
# `load_blosc2` が読み込む単一配列の展開後サイズ上限（バイト）。読み込む 2 つの
# 保存形式はいずれも小さなヘッダで配列サイズを宣言する。`.npy` ヘッダは shape と
# dtype を、blosc2 cframe は非圧縮バイト数を宣言する。いずれも宣言サイズと
# ファイルサイズは無関係で、128 バイトの `.npy` がテラバイト級の配列を宣言でき、
# 定数値を圧縮した blosc2 payload はディスク上で極小に留まる。そのため配列を
# 実体化する前に宣言サイズを検査する。`MAX_BUNDLE_DECOMPRESSED_BYTES` と同値。
# None で検査を無効化できる。
MAX_ARRAY_DECOMPRESSED_BYTES = 4 * 1024**3  # 4 GiB


def save_blosc2(path: str, x: np.ndarray) -> None:
    """
    Save a NumPy array using blosc2 binary payload.
    NumPy 配列を blosc2 バイナリ形式で保存する。

    If the array is empty, save as `.npy` instead of blosc2 to avoid
    `ZeroDivisionError` in `blosc2.pack_array2`.
    配列が空の場合、`blosc2.pack_array2` の `ZeroDivisionError` を避けるため
    blosc2 ではなく `.npy` 形式で保存する。
    This fallback keeps the function safe for edge cases such as
    "no kink points" or "no branch points" outputs.
    このフォールバックにより「kink 点がない」「分岐点がない」などの
    端ケースでも安全に保存できる。

    Parameters
    ----------
    path
        Destination file path.
        保存先ファイルパス。
    x
        NumPy array to be saved.
        保存対象の NumPy 配列。

    Returns
    -------
    This function writes data to disk and returns nothing.
    この関数はディスクに書き込みを行い、戻り値は持たない。
    """
    # Empty arrays must bypass blosc2 packer due to known crash behavior.
    # 既知のクラッシュ挙動があるため、空配列は blosc2 圧縮を回避する。
    if x.size == 0:
        # Write through an open file handle: np.save(path, ...) appends ".npy"
        # when the path has another extension, which would desynchronize the
        # saved filename from the one load_blosc2 reads.
        # ファイルハンドル経由で書き込む。np.save(path, ...) はパスが別の拡張子
        # のとき ".npy" を自動付加するため、load_blosc2 が読むファイル名と
        # ずれてしまう。
        with open(path, "wb") as f:
            np.save(f, x)
        return
    with open(path, "wb") as f:
        f.write(blosc2.pack_array2(x))


def _check_size_limit(declared_bytes: int, limit: int | None, path: str) -> None:
    """
    Raise when an array's declared size exceeds `limit`.
    配列の宣言サイズが `limit` を超える場合に例外を送出する。
    """
    if limit is not None and declared_bytes > limit:
        raise ValueError(
            f"array declares {declared_bytes} decompressed bytes, exceeding "
            f"the {limit}-byte limit (raise "
            f"lib.blosc2_io.MAX_ARRAY_DECOMPRESSED_BYTES to load larger "
            f"arrays): {path}"
        )


def _npy_declared_bytes(path: str) -> int | None:
    """
    Read a `.npy` header's declared array size in bytes, without loading it.
    `.npy` ヘッダが宣言する配列サイズ（バイト）を、読み込まずに取得する。

    Returns
    -------
    Declared byte count, or None when the header format version is one this
    function cannot parse (the caller then lets `np.load` report the problem).
    宣言バイト数。ヘッダの形式バージョンを解釈できない場合は None（呼び出し側は
    `np.load` に問題を報告させる）。

    Notes
    -----
    `np.load` allocates the full array declared by the header before it reads
    the body, so a truncated file with a large declared shape raises only
    after the allocation is attempted. Reading the header first turns that
    into a cheap, explicit rejection.
    `np.load` はヘッダが宣言する配列全体を確保してから本体を読むため、宣言
    shape が巨大な切り詰めファイルは確保を試みた後にしか失敗しない。先に
    ヘッダを読むことで、安価かつ明示的な拒否に変えられる。
    """
    header_readers = {
        (1, 0): np.lib.format.read_array_header_1_0,
        (2, 0): np.lib.format.read_array_header_2_0,
    }
    with open(path, "rb") as f:
        version = np.lib.format.read_magic(f)
        reader = header_readers.get(version)
        if reader is None:
            return None
        shape, _fortran_order, dtype = reader(f)
    return math.prod(shape) * dtype.itemsize


def load_blosc2(
    path: str,
    *,
    max_decompressed_bytes: int | None = MAX_ARRAY_DECOMPRESSED_BYTES,
) -> np.ndarray:
    """
    Load an array saved in either blosc2 or NumPy `.npy` format.
    blosc2 形式または NumPy `.npy` 形式で保存された配列を読み込む。

    The function first inspects file header bytes to detect format.
    まずファイル先頭バイトを確認して保存形式を判定する。
    This allows transparent loading even when `save_blosc2` used `.npy`
    fallback for empty arrays.
    これにより `save_blosc2` が空配列で `.npy` フォールバック保存した場合でも
    呼び出し側は同じ API で透過的に読み込める。

    Parameters
    ----------
    path
        File path to read.
        読み込むファイルパス。
    max_decompressed_bytes
        Maximum array size (bytes) the file's header may declare. None
        disables the check.
        ファイルのヘッダが宣言できる配列サイズ（バイト）の上限。None で検査を
        無効化する。

    Returns
    -------
    Loaded NumPy array.
    読み込まれた NumPy 配列。

    Raises
    ------
    ValueError
        If the header declares an array larger than the limit. Raised before
        the array is allocated or decompressed, so a crafted (or corrupted)
        file cannot exhaust memory during load.
    """
    # Read only the header prefix needed for format detection.
    # 形式判定に必要な先頭部分だけを先に読み取る。
    with open(path, "rb") as f:
        header = f.read(len(_NPY_MAGIC))

    if header == _NPY_MAGIC:
        declared = _npy_declared_bytes(path)
        if declared is not None:
            _check_size_limit(declared, max_decompressed_bytes, path)
        # allow_pickle=False is the NumPy default, but stated explicitly:
        # this loader is reachable from user-selected files, which must never
        # execute a pickled object payload.
        # allow_pickle=False は NumPy の既定値だが明示する。本ローダーはユーザーが
        # 選択したファイルから到達しうるため、pickle 化されたオブジェクトを
        # 決して実行してはならない。
        return np.load(path, allow_pickle=False)

    with open(path, "rb") as f:
        payload = f.read()

    # A blosc2 cframe records its uncompressed size in the frame header, so the
    # SChunk view reports `nbytes` without decompressing any chunk. An
    # unparseable payload yields no size; `unpack_array2` then raises its own
    # error without allocating.
    # blosc2 の cframe は非圧縮サイズをフレームヘッダに記録するため、SChunk
    # ビューはチャンクを展開せずに `nbytes` を返す。解釈できない payload では
    # サイズが得られないが、その場合 `unpack_array2` が確保を伴わず自前の
    # エラーを送出する。
    try:
        declared = blosc2.schunk_from_cframe(payload, copy=False).nbytes
    except Exception:
        declared = None
    if declared is not None:
        _check_size_limit(declared, max_decompressed_bytes, path)

    return blosc2.unpack_array2(payload)


# =============================================================================
# Bundle API: pack multiple named arrays into a single .b2z file.
# Bundle API: 複数の名前付き配列を1つの .b2z ファイルにまとめる API。
#
# Backed by `blosc2.TreeStore`, which stores arrays under hierarchical keys
# (e.g. "/calibrated", "/binarized") and supports variable-length metadata.
# 内部的には `blosc2.TreeStore` を使い、階層キー（例: "/calibrated",
# "/binarized"）配下に配列を格納し、可変長メタデータ（vlmeta）も併せて保持する。
#
# Designed to replace per-array .npy files with one bundle per source input.
# 1 解析対象（テキスト/CSV または .gwy）ごとに .npy 群を出力していた旧仕様を、
# 1 ファイル（.b2z）へまとめる現行仕様に置き換えるために設計されている。
# =============================================================================

BUNDLE_EXT = ".b2z"

# Default guard limits for `load_bundle`. Blosc2 metadata declares each
# array's shape and dtype without decompressing it, and highly compressible
# data means a bundle of a few hundred bytes on disk can declare a
# decompressed size in the terabytes. Checking the declared sizes against
# these caps before materializing protects every `load_bundle` caller (GUI
# preview, CLI export/validate, measurement) from decompression-bomb bundles.
# The defaults sit far above any legitimate AFM bundle: a bundle holds about
# ten keys, and even an 8192x8192 float64 height image is only 0.5 GiB.
# blosc2 のメタデータは展開せずに各配列の shape/dtype を宣言できるため、
# 高圧縮データではディスク上数百バイトのバンドルがテラバイト級の展開後
# サイズを宣言し得る。実体化前に宣言サイズを上限と照合することで、全ての
# `load_bundle` 呼び出し元を展開爆弾から保護する。既定値は正当な AFM
# バンドル（約 10 キー、8192x8192 の float64 高さ画像でも 0.5 GiB）より
# 十分大きく取ってある。
MAX_BUNDLE_KEYS = 64
MAX_BUNDLE_DECOMPRESSED_BYTES = 4 * 1024**3  # 4 GiB


def save_bundle(path: str, arrays: dict, vlmeta: dict | None = None) -> None:
    """
    Save multiple named NumPy arrays into a single bundle file.
    複数の名前付き NumPy 配列を1つのバンドルファイルに保存する。

    Parameters
    ----------
    path
        Destination bundle file path (typically ending with `.b2z`).
        保存先バンドルファイルパス（通常は `.b2z` 拡張子）。
    arrays
        Mapping from key name (e.g. "calibrated") to NumPy array.
        Leading "/" is optional; it is normalized internally.
        キー名（例: "calibrated"）から NumPy 配列への辞書。
        先頭の "/" は任意で、内部で正規化される。
    vlmeta
        Optional metadata dictionary (msgpack-serializable values).
        Stored on the root of the TreeStore.
        任意のメタデータ辞書（msgpack でシリアライズ可能な値）。
        TreeStore のルートに保存される。

    Returns
    -------
    This function writes the bundle to disk and returns nothing.
    この関数はバンドルをディスクに書き込み、戻り値は持たない。
    """
    directory = os.path.dirname(os.path.abspath(path))
    basename = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{basename}.", suffix=".tmp.b2z", dir=directory,
    )
    os.close(fd)
    try:
        # Open TreeStore in write mode on a sibling temp file, then atomically
        # replace the final path only after the bundle has been closed cleanly.
        # 同じディレクトリの一時ファイルに書き、正常に close できてから
        # 最終パスを原子的に置き換える。
        with blosc2.TreeStore(tmp_path, mode="w") as ts:
            for key, arr in arrays.items():
                # Normalize key: ensure it starts with "/" as required by TreeStore.
                # TreeStore のキーは "/" で始まる必要があるため正規化する。
                k = key if key.startswith("/") else "/" + key
                ts[k] = np.asarray(arr)

            # Persist optional user metadata into the root vlmeta storage.
            # ユーザーメタデータをルートの vlmeta に書き込む。
            if vlmeta:
                for k, v in vlmeta.items():
                    ts.vlmeta[k] = v
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_bundle(
    path: str,
    keys: list[str] | None = None,
    *,
    max_keys: int | None = MAX_BUNDLE_KEYS,
    max_decompressed_bytes: int | None = MAX_BUNDLE_DECOMPRESSED_BYTES,
) -> dict:
    """
    Load arrays from a bundle file as a dictionary.
    バンドルファイルから配列を読み込み、辞書として返す。

    Parameters
    ----------
    path
        Bundle file path to read.
        読み込むバンドルファイルパス。
    keys
        Subset of keys to load. If None, load all leaf datasets.
        Leading "/" is optional.
        読み込むキーのサブセット。None の場合は全リーフデータセットを読み込む。
        先頭の "/" は任意。
    max_keys
        Maximum number of keys to load. None disables the check.
        読み込むキー数の上限。None で検査を無効化する。
    max_decompressed_bytes
        Maximum total decompressed size (bytes) the requested arrays may
        declare in their metadata. None disables the check.
        読み込む配列がメタデータで宣言できる展開後合計サイズ（バイト）の
        上限。None で検査を無効化する。

    Returns
    -------
    Mapping from key name (without leading "/") to loaded NumPy array.
    キー名（先頭の "/" は除去）から NumPy 配列への辞書。

    Raises
    ------
    ValueError
        If the bundle declares more keys or a larger decompressed size than
        the limits allow. Raised before any oversized array is materialized,
        so a crafted (or corrupted) bundle cannot exhaust memory during load.
    """
    out: dict = {}
    with blosc2.TreeStore(path, mode="r") as ts:
        if keys is None:
            target_keys = bundle_keys(path)
        else:
            target_keys = [k if k.startswith("/") else "/" + k for k in keys]

        if max_keys is not None and len(target_keys) > max_keys:
            raise ValueError(
                f"bundle declares {len(target_keys)} keys, exceeding the "
                f"limit of {max_keys}: {path}"
            )

        # Sum each array's declared decompressed size (shape x itemsize, read
        # from blosc2 metadata without decompressing) and refuse the load
        # before `[:]` would materialize anything past the cap.
        # 各配列の宣言展開サイズ（shape × itemsize、展開せずメタデータから
        # 取得）を積算し、`[:]` が上限超過分を実体化する前に読み込みを拒否する。
        total_bytes = 0
        for k in target_keys:
            node = ts[k]
            total_bytes += math.prod(node.shape) * node.dtype.itemsize
            if (max_decompressed_bytes is not None
                    and total_bytes > max_decompressed_bytes):
                raise ValueError(
                    f"bundle arrays declare more than "
                    f"{max_decompressed_bytes} decompressed bytes "
                    f"({k!r} raises the total to {total_bytes}): {path}"
                )
            # `[:]` materializes the (possibly compressed) NDArray as a NumPy array.
            out[k.lstrip("/")] = node[:]
    return out


def load_bundle_meta(path: str) -> dict:
    """
    Load the variable-length metadata (vlmeta) stored at bundle root.
    バンドルのルートに保存された可変長メタデータ（vlmeta）を読み込む。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルパス。

    Returns
    -------
    Decoded vlmeta dictionary. Empty dict if no metadata.
    デコード済み vlmeta 辞書。メタデータがなければ空辞書。

    Raises
    ------
    Exception
        Any blosc2 read or decode failure propagates unchanged. A bundle
        without metadata is not an error (blosc2 itself yields an empty
        dict), so an exception here means real corruption; swallowing it
        would let the format-version check be skipped silently.
        blosc2 の読み込み・デコード失敗はそのまま送出する。メタデータの無い
        バンドルはエラーではなく（blosc2 自体が空辞書を返す）、ここでの例外は
        本物の破損を意味する。握りつぶすと形式バージョン検査が黙って
        スキップされてしまう。
    """
    with blosc2.TreeStore(path, mode="r") as ts:
        # `vlmeta[:]` returns all metadata as a dict with string keys.
        return dict(ts.vlmeta[:])


def bundle_keys(path: str) -> list[str]:
    """
    List all leaf dataset keys in a bundle file.
    バンドル内の全リーフデータセットキーを列挙する。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルパス。

    Returns
    -------
    Leaf keys with leading "/" (e.g. ["/calibrated", "/binarized", ...]).
    先頭の "/" を含むリーフキー一覧（例: ["/calibrated", "/binarized", ...]）。
    """
    keys: list[str] = []
    with blosc2.TreeStore(path, mode="r") as ts:
        # `walk` yields (path, subgroups, leaves) tuples for each tree node.
        for parent, _subgroups, leaves in ts.walk("/"):
            base = parent.rstrip("/")
            for leaf in leaves:
                keys.append(f"{base}/{leaf}")
    return keys


def bundle_has_keys(path: str, required: list[str]) -> tuple[bool, list[str]]:
    """
    Check whether a bundle file contains all the required keys.
    バンドルファイルが必要キーをすべて含むかチェックする。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルパス。
    required
        Required key names. Leading "/" is optional.
        必要なキー名のリスト。先頭の "/" は任意。

    Returns
    -------
    Whether all keys are present and the missing keys normalized with a
    leading slash.
    全て存在するか、および存在しないキー一覧（先頭の "/" 付き）。
    """
    if not os.path.isfile(path):
        return False, [k if k.startswith("/") else "/" + k for k in required]

    try:
        existing = set(bundle_keys(path))
    except Exception:
        # Any read failure is conservatively treated as "all missing".
        # 読み込み失敗は安全側に倒し、全欠損として扱う。
        return False, [k if k.startswith("/") else "/" + k for k in required]

    missing: list[str] = []
    for k in required:
        nk = k if k.startswith("/") else "/" + k
        if nk not in existing:
            missing.append(nk)
    return (len(missing) == 0), missing
