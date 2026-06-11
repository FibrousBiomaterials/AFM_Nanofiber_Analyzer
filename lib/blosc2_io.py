# -*- coding: utf-8 -*-
"""
Save and load NumPy arrays with blosc2 compression.
blosc2 圧縮を用いて NumPy 配列を保存・読み込みする。

This module centralizes lightweight I/O helpers used by multiple GUIs.
このモジュールは複数 GUI で使う軽量 I/O ヘルパーを一元管理する。
It provides `save_blosc2` and `load_blosc2` so callers do not need to care
about storage backend details.
呼び出し側が保存形式の詳細を意識しなくてよいように
`save_blosc2` と `load_blosc2` を提供する。

Used by GUI01_Image_Processer, GUI03_Histogram_maker, and GUI04_Tracking.
GUI01_Image_Processer / GUI03_Histogram_maker / GUI04_Tracking で
使用される save_blosc2 / load_blosc2 をここに一元化する。

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

import numpy as np
import blosc2

# Magic bytes at the head of NumPy `.npy` files.
_NPY_MAGIC = b'\x93NUMPY'


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


def load_blosc2(path: str) -> np.ndarray:
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

    Returns
    -------
    Loaded NumPy array.
    読み込まれた NumPy 配列。
    """
    # Read only the header prefix needed for format detection.
    # 形式判定に必要な先頭部分だけを先に読み取る。
    with open(path, "rb") as f:
        header = f.read(len(_NPY_MAGIC))

    if header == _NPY_MAGIC:
        return np.load(path)

    with open(path, "rb") as f:
        return blosc2.unpack_array2(f.read())


# =============================================================================
# Bundle API: pack multiple named arrays into a single .b2z file.
# Bundle API: 複数の名前付き配列を1つの .b2z ファイルにまとめる API。
#
# Backed by `blosc2.TreeStore`, which stores arrays under hierarchical keys
# (e.g. "/calibrated", "/binarized") and supports variable-length metadata.
# 内部的には `blosc2.TreeStore` を使い、階層キー（例: "/calibrated",
# "/binarized"）配下に配列を格納し、可変長メタデータ（vlmeta）も併せて保持する。
#
# Designed to replace per-array .npy files with one bundle file per source.
# 1解析対象（1つのtxt）あたり .npy 群を出力していた旧仕様を、
# 1ファイル（.b2z）にまとめる新仕様に置き換えるために設計されている。
# =============================================================================

BUNDLE_EXT = ".b2z"


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
    # Open TreeStore in write mode so an existing file is overwritten cleanly.
    # 既存ファイルがあっても確実に上書きされるよう書き込みモードで開く。
    with blosc2.TreeStore(path, mode="w") as ts:
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


def load_bundle(path: str, keys: list[str] | None = None) -> dict:
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

    Returns
    -------
    Mapping from key name (without leading "/") to loaded NumPy array.
    キー名（先頭の "/" は除去）から NumPy 配列への辞書。
    """
    out: dict = {}
    with blosc2.TreeStore(path, mode="r") as ts:
        if keys is None:
            target_keys = bundle_keys(path)
        else:
            target_keys = [k if k.startswith("/") else "/" + k for k in keys]

        for k in target_keys:
            # `[:]` materializes the (possibly compressed) NDArray as a NumPy array.
            out[k.lstrip("/")] = ts[k][:]
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
    """
    with blosc2.TreeStore(path, mode="r") as ts:
        # `vlmeta[:]` returns all metadata as a dict with string keys.
        try:
            return dict(ts.vlmeta[:])
        except Exception:
            return {}


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
    import os
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
