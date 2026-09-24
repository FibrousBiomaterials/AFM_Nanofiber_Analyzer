#!/usr/bin/env python3
"""Check that re-analysis with this version reproduces an earlier one's bundles.
この版で再解析すると、以前の版のバンドルが再現されるかを確かめる。

Before a release, the default analysis of this code must give the same results
as the last release on the lab's own data, and the lab's saved work (older
bundles, exclusions, connections) must still apply. This compares, for every
bundle present in both folders:

1. **Arrays**, bit for bit: every key of either bundle (``calibrated``,
   ``skeletonized``, ``kp``, ``ka``, ``ke``, ``up``, ...), including shape and
   dtype.
2. **Parameters** recorded in each bundle's vlmeta: a field that differs means
   the two runs were not like for like, and the comparison says so rather than
   blaming the code.
3. **Measurements** the current code computes from each bundle, with the old
   folder's saved exclusions and connection plan applied to both: every
   ``FiberStats`` field of every fiber. This also shows that the current code
   still reads the old bundle and its sidecars.

Usage:
    # compare two folders of bundles
    python scripts/compare_bundles.py OLD_DIR NEW_DIR
    # re-analyze the inputs of OLD_DIR's bundles into NEW_DIR first, with the
    # parameters, scan size, scan-line range and input format each old bundle
    # recorded, then compare
    python scripts/compare_bundles.py OLD_DIR NEW_DIR --reanalyze RAW_DIR

``RAW_DIR`` is searched recursively for each bundle's ``input_file``; an input
whose SHA-256 differs from the recorded ``input_sha256`` is not used.

Exit codes: 0 = every bundle identical, 1 = a difference or an error in some
bundle, 2 = usage error.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

from lib import measure  # noqa: E402
from lib.afm_io import FORMAT_KINDS  # noqa: E402
from lib.blosc2_io import BUNDLE_EXT, load_bundle, load_bundle_meta  # noqa: E402
from lib.bundle_schema import (  # noqa: E402
    PARAMS_KEY,
    SOURCE_REGION_KEY,
    SPATIAL_CALIBRATION_KEY,
)
from lib.pipeline import ProcParams, _sha256_of_file, merge_params_dict, process_file  # noqa: E402


# ----------------------------------------------------------------------------
# Comparisons (pure), unit-tested in tests/test_compare_bundles.py
# ----------------------------------------------------------------------------

def compare_arrays(old: Dict[str, np.ndarray], new: Dict[str, np.ndarray]) -> List[str]:
    """Return one line per key whose array differs in presence, shape, dtype or value.
    存在・形状・dtype・値のいずれかが異なるキーごとに 1 行を返す。
    """
    out = []
    for key in sorted(set(old) | set(new)):
        if key not in new:
            out.append(f"{key}: only in the old bundle")
            continue
        if key not in old:
            out.append(f"{key}: only in the new bundle")
            continue
        a, b = np.asarray(old[key]), np.asarray(new[key])
        if a.shape != b.shape:
            out.append(f"{key}: shape {a.shape} -> {b.shape}")
        elif a.dtype != b.dtype:
            out.append(f"{key}: dtype {a.dtype} -> {b.dtype}")
        elif not np.array_equal(a, b, equal_nan=a.dtype.kind == "f"):
            n = int(np.count_nonzero(~((a == b) | (np.isnan(a) & np.isnan(b))))
                    if a.dtype.kind == "f" else np.count_nonzero(a != b))
            out.append(f"{key}: {n} of {a.size} values differ")
    return out


def compare_params(old: Optional[dict], new: Optional[dict]) -> List[str]:
    """Return the recorded parameters both runs have but set differently.
    両方の実行が持ち、値が異なる記録パラメータを返す。

    A field only the newer run records is a parameter added since. The older
    run behaved as its default does, so it is a difference only when the newer
    run set it to something else.
    新しい実行だけが記録するフィールドは後から追加されたパラメータである。古い
    実行はその既定値と同じ挙動なので、新しい実行が既定以外にした場合だけ差異とする。
    """
    old, new = old or {}, new or {}
    defaults = dataclasses.asdict(ProcParams())
    out = [f"{k}: {old[k]!r} -> {new[k]!r}"
           for k in sorted(set(old) & set(new)) if old[k] != new[k]]
    out += [f"{k}: not recorded (default {defaults[k]!r}) -> {new[k]!r}"
            for k in sorted(set(new) - set(old))
            if k in defaults and new[k] != defaults[k]]
    return out


def _same(a, b) -> bool:
    """Equality that treats NaN as equal to NaN, element-wise for arrays."""
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    if isinstance(a, (list, tuple, np.ndarray)) or isinstance(b, (list, tuple, np.ndarray)):
        x, y = np.asarray(a), np.asarray(b)
        if x.shape != y.shape:
            return False
        if x.dtype.kind == "f" or y.dtype.kind == "f":
            return bool(np.array_equal(x.astype(float), y.astype(float), equal_nan=True))
        return bool(np.array_equal(x, y))
    return a == b


def compare_stats(old: Sequence, new: Sequence) -> List[str]:
    """Return one line per fiber field that differs (dataclass records).
    異なる繊維のフィールドごとに 1 行を返す（dataclass のレコード）。
    """
    if len(old) != len(new):
        return [f"fiber count {len(old)} -> {len(new)}"]
    out = []
    for i, (a, b) in enumerate(zip(old, new)):
        for field in dataclasses.fields(a):
            va, vb = getattr(a, field.name), getattr(b, field.name, None)
            if not _same(va, vb):
                out.append(f"fiber {i} {field.name}: {va!r} -> {vb!r}")
    return out


# ----------------------------------------------------------------------------
# Re-analysis with the recorded settings
# ----------------------------------------------------------------------------

def _find_input(raw_dir: str, name: str, sha256: Optional[str]) -> Tuple[Optional[str], str]:
    """Locate an input by file name under `raw_dir`, verifying its digest."""
    candidates = [os.path.join(root, name)
                  for root, _dirs, files in os.walk(raw_dir) if name in files]
    if not candidates:
        return None, f"input {name} not found under {raw_dir}"
    for path in candidates:
        if sha256 is None or _sha256_of_file(path) == sha256:
            return path, ""
    return None, f"input {name} found, but its SHA-256 differs from the recorded one"


def reanalyze(old_path: str, raw_dir: str, out_dir: str) -> Tuple[Optional[str], str]:
    """Re-run the analysis that produced `old_path`; return the new bundle path.
    `old_path` を作った解析を再実行し、新しいバンドルのパスを返す。

    Uses the parameters, scan size, scan-line range and input format the old
    bundle recorded. Parameters added since take their defaults, which is what
    keeps an older analysis's behaviour.
    旧バンドルが記録したパラメータ・走査範囲・走査線範囲・入力形式を使う。
    その後に追加されたパラメータは既定値となり、それが旧解析の挙動を保つ。
    """
    meta = load_bundle_meta(old_path)
    src, why = _find_input(raw_dir, meta.get("input_file", ""), meta.get("input_sha256"))
    if src is None:
        return None, why
    params, _missing, _obsolete = merge_params_dict(meta.get(PARAMS_KEY) or {})
    kwargs = {"output_dir": out_dir,
              "save_original": "original" in load_bundle(old_path)}
    cal = meta.get(SPATIAL_CALIBRATION_KEY)
    # A header scan size is read from the input again; any other source is
    # passed on with its label so the new bundle records the same provenance.
    # ヘッダ由来の走査範囲は入力から読み直す。それ以外は出所の名前ごと渡し、
    # 新しいバンドルが同じ来歴を記録するようにする。
    if cal and cal.get("source") != "input_header":
        kwargs["scan_size_um"] = (cal["scan_size_x_um"], cal["scan_size_y_um"])
        kwargs["scan_size_source"] = cal["source"]
    region = meta.get(SOURCE_REGION_KEY)
    if region:
        kwargs["row_range"] = (int(region["row_start"]), int(region["row_stop"]))
    fmt = (meta.get("input_format") or {})
    if fmt.get("kind") == "gwy":
        kwargs["gwy_channel"] = fmt.get("channel_id")
    elif fmt.get("kind") in FORMAT_KINDS:
        kwargs["input_format"] = fmt["kind"]
    result = process_file(src, params, **kwargs)
    return result.bundle_path, ""


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------

# Scan size used for both bundles of a pair when neither records one. Heights,
# kinks and every pixel-space gate do not depend on it and lengths scale by the
# same factor on both sides, so an equality test is unaffected by the value.
# どちらのバンドルも走査範囲を記録していないときに両方へ使う走査範囲。高さ・
# キンク・画素空間の判定は依存せず、長さは両側で同じ倍率になるため、一致判定は
# この値に左右されない。
PLACEHOLDER_SCAN_UM = 1.0


def _measure(path: str, anchors, plan, scale_um: Optional[float] = None):
    return measure.measure_bundle(path, scale_um=scale_um,
                                  exclude_anchors=anchors, plan=plan).stats


def compare_pair(old_path: str, new_path: str) -> List[str]:
    """Compare one pair of bundles; return the differences found."""
    old_meta, new_meta = load_bundle_meta(old_path), load_bundle_meta(new_path)
    # Parameters first: a differing setting is the cause of the differences
    # listed after it, not a fault of the code.
    # パラメータを先に出す。設定の違いは後に続く差異の原因であり、コードの不具合
    # ではない。
    diffs = [f"param {d}" for d in compare_params(old_meta.get(PARAMS_KEY),
                                                    new_meta.get(PARAMS_KEY))]
    diffs += [f"array {d}" for d in compare_arrays(load_bundle(old_path), load_bundle(new_path))]
    scale = None
    if old_meta.get(SPATIAL_CALIBRATION_KEY) is None:
        if new_meta.get(SPATIAL_CALIBRATION_KEY) is not None:
            diffs.append("meta spatial_calibration: only the new bundle records a scan size")
        scale = PLACEHOLDER_SCAN_UM
        diffs.append(f"note: no recorded scan size, measured at a placeholder "
                     f"{PLACEHOLDER_SCAN_UM} um")
    # The old folder's curation is applied to both, so a sidecar that no longer
    # applies to the re-analyzed skeleton shows up as an error here.
    # 旧フォルダのキュレーションを両方に適用する。再解析した骨格に適用できなく
    # なったサイドカーはここでエラーとして現れる。
    anchors, plan = measure._curation_for(old_path, True, True)
    try:
        old_stats = _measure(old_path, anchors, plan, scale)
    except Exception as exc:  # the current code must still read the old bundle
        return diffs + [f"measure old bundle failed: {type(exc).__name__}: {exc}"]
    try:
        new_stats = _measure(new_path, anchors, plan, scale)
    except Exception as exc:
        return diffs + [f"measure new bundle failed: {type(exc).__name__}: {exc}"]
    diffs += [f"stats {d}" for d in compare_stats(old_stats, new_stats)]
    return diffs


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old_dir", help="folder of bundles made by the earlier version")
    parser.add_argument("new_dir", help="folder of bundles made by this version")
    parser.add_argument("--reanalyze", metavar="RAW_DIR",
                        help="first re-analyze the old bundles' inputs from RAW_DIR into NEW_DIR")
    parser.add_argument("--show", type=int, default=5,
                        help="differences listed per bundle (default 5)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    old_dir, new_dir = os.path.abspath(args.old_dir), os.path.abspath(args.new_dir)
    if old_dir == new_dir:
        print("compare: OLD_DIR and NEW_DIR must differ", file=sys.stderr)
        return 2
    olds = sorted(f for f in os.listdir(old_dir) if f.endswith(BUNDLE_EXT))
    if not olds:
        print(f"compare: no {BUNDLE_EXT} bundles in {old_dir}", file=sys.stderr)
        return 2

    pairs: List[Tuple[str, Optional[str], str]] = []
    if args.reanalyze:
        os.makedirs(new_dir, exist_ok=True)
        for name in olds:
            print(f"re-analyzing {name} ...", flush=True)
            try:
                new_path, why = reanalyze(os.path.join(old_dir, name), args.reanalyze, new_dir)
            except Exception as exc:
                new_path, why = None, f"re-analysis failed: {type(exc).__name__}: {exc}"
            pairs.append((name, new_path, why))
    else:
        for name in olds:
            path = os.path.join(new_dir, name)
            pairs.append((name, path if os.path.exists(path) else None,
                          "" if os.path.exists(path) else "no bundle of that name in NEW_DIR"))

    same = differ = skipped = 0
    for name, new_path, why in pairs:
        if new_path is None:
            skipped += 1
            print(f"SKIP  {name}: {why}")
            continue
        try:
            diffs = compare_pair(os.path.join(old_dir, name), new_path)
        except Exception as exc:
            diffs = [f"comparison failed: {type(exc).__name__}: {exc}"]
        real = [d for d in diffs if not d.startswith("note:")]
        notes = [d for d in diffs if d.startswith("note:")]
        if real:
            differ += 1
            print(f"DIFF  {name}: {len(real)} difference(s)")
            for d in real[:args.show]:
                print(f"        {d}")
            if len(real) > args.show:
                print(f"        ... {len(real) - args.show} more")
        else:
            same += 1
            print(f"SAME  {name}" + (f" ({notes[0][6:]})" if notes else ""))
    print(f"\n{same} identical, {differ} different, {skipped} skipped, of {len(pairs)} bundles.")
    return 0 if differ == 0 and skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
