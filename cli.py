# -*- coding: utf-8 -*-
"""
Command-line interface for the AFM nanofiber preprocessing pipeline.
AFM ナノファイバー前処理パイプラインのコマンドラインインターフェース。

Runs the same pipeline as the GUI01 Image Preprocessor (background
calibration, segmentation, skeletonization, kink detection) through
`lib.pipeline.process_file`, so CLI and GUI outputs are identical for the
same input and parameters. This enables scripted batch processing and
reproducible analysis without the GUI.
GUI01 Image Preprocessor と同じパイプライン（背景補正・二値化・細線化・
キンク検出）を `lib.pipeline.process_file` 経由で実行するため、同じ入力と
パラメータに対して CLI と GUI の出力は一致する。GUI なしでのバッチ処理と
再現可能な解析を可能にする。

Usage examples
--------------
    python cli.py process data/*.txt
    python cli.py process scan.txt --params my_param.json --output-dir out/
    python cli.py show-params > default_param.json

Output messages are fixed English strings; this interface is intended for
scripting and JOSS-reviewer use, so it does not load gettext catalogs.
出力メッセージは固定の英語文字列とする。本インターフェースはスクリプト用
および JOSS レビュー用であり、gettext カタログは読み込まない。
"""

# ===== Standard library =====
import argparse
import glob
import json
import os
import sys

# Register the project root before importing local packages, mirroring
# Main.py, so `python cli.py` works regardless of the caller's directory.
# Main.py と同様、ローカルパッケージの import 前にプロジェクトルートを登録し、
# どのディレクトリから `python cli.py` を呼んでも動作するようにする。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ===== Project libraries =====
from lib.blosc2_io import load_bundle, load_bundle_meta
from lib.pipeline import (
    ProcParams,
    build_stages,
    existing_min_set,
    merge_params_dict,
    process_file,
    validate_params,
)


def _expand_inputs(patterns: list) -> list:
    """
    Expand glob patterns and deduplicate input paths in stable order.
    glob パターンを展開し、入力パスを順序を保って重複排除する。

    Windows shells do not expand wildcards, so the CLI expands them itself.
    Windows のシェルはワイルドカードを展開しないため、CLI 側で展開する。
    """
    seen = {}
    for pattern in patterns:
        matches = glob.glob(pattern)
        for m in (matches if matches else [pattern]):
            seen[os.path.abspath(m)] = None
    return list(seen)


def _load_params(path: str) -> ProcParams:
    """
    Load analysis parameters from a JSON file, reporting reconciled keys.
    JSON ファイルから解析パラメータを読み込み、整合処理したキーを報告する。

    Missing keys are filled from `ProcParams` defaults and unknown keys are
    ignored, matching the GUI startup-settings behavior.
    欠損キーは `ProcParams` の既定値で補完し、未知キーは無視する。GUI の
    起動時設定と同じ挙動である。
    """
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    params, missing, obsolete = merge_params_dict(d)
    if missing:
        print(f"[params] missing keys filled from defaults: {', '.join(missing)}")
    if obsolete:
        print(f"[params] unknown keys ignored: {', '.join(obsolete)}")
    return params


def _output_stem(txt_path: str, output_dir: str) -> str:
    """
    Return the extensionless output path for one input file.
    1 入力ファイルに対応する拡張子なしの出力パスを返す。
    """
    name = os.path.splitext(os.path.basename(txt_path))[0]
    if output_dir:
        return os.path.join(output_dir, name)
    return os.path.splitext(txt_path)[0]


def cmd_process(args: argparse.Namespace) -> int:
    """
    Run the preprocessing pipeline over all requested input files.
    要求された全入力ファイルに対して前処理パイプラインを実行する。

    Returns
    -------
    int
        0 when every file succeeded, 1 when any file failed, 2 when no
        usable input file was found or the parameters are invalid.
        全ファイル成功で 0、いずれか失敗で 1、有効な入力が無いか
        パラメータが不正なら 2。
    """
    inputs = _expand_inputs(args.inputs)
    inputs = [p for p in inputs if os.path.isfile(p)]
    if not inputs:
        print("error: no input files found", file=sys.stderr)
        return 2

    params = _load_params(args.params) if args.params else ProcParams()

    # Validate once before the batch so every problem is reported together,
    # instead of the same failure repeating per input file.
    # バッチ開始前に一括検証し、同じ失敗が入力ファイルごとに繰り返される
    # 代わりに全問題をまとめて報告する。
    problems = validate_params(params)
    if problems:
        print("error: invalid analysis parameters:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    # Build the stage objects once and reuse them, as the GUI batch loop does.
    # GUI のバッチループと同様、ステージは一度だけ構築して再利用する。
    stages = build_stages(params)

    n_done = 0
    n_skipped = 0
    failures = []
    for i, txt_path in enumerate(inputs, 1):
        name = os.path.basename(txt_path)
        stem = _output_stem(txt_path, args.output_dir)

        ok, _missing = existing_min_set(stem)
        if ok and not args.overwrite:
            print(f"[{i}/{len(inputs)}] {name}: skipped (outputs exist; use --overwrite)")
            n_skipped += 1
            continue

        print(f"[{i}/{len(inputs)}] {name}: ", end="", flush=True)
        try:
            result = process_file(
                txt_path,
                params,
                stages=stages,
                output_dir=args.output_dir or None,
                save_original=args.save_original,
                on_stage=lambda s: print(s, end=" ", flush=True),
            )
        except Exception as e:
            print("FAILED")
            print(f"    {type(e).__name__}: {e}", file=sys.stderr)
            failures.append(name)
            continue
        print(f"done ({result.elapsed_s:.2f}s) -> {result.bundle_path}")
        n_done += 1

    print(
        f"finished: {n_done} processed, {n_skipped} skipped, "
        f"{len(failures)} failed (of {len(inputs)} inputs)"
    )
    if failures:
        print("failed files: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def cmd_show_params(args: argparse.Namespace) -> int:
    """
    Print the default analysis parameters as JSON.
    既定の解析パラメータを JSON で出力する。

    The output can be redirected to a file, edited, and passed back through
    `process --params`.
    出力をファイルへリダイレクトして編集し、`process --params` に渡せる。
    """
    from dataclasses import asdict
    print(json.dumps(asdict(ProcParams()), ensure_ascii=False, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """
    Export `.b2z` bundles to standard formats readable outside this project.
    `.b2z` バンドルを本プロジェクト外でも読める標準形式へエクスポートする。

    `npz` writes one compressed NumPy archive per bundle; `csv` writes one
    text file per array key. Bundle metadata (analysis parameters and
    provenance) is always written as a `<stem>_meta.json` sidecar.
    `npz` はバンドルごとに 1 つの圧縮 NumPy アーカイブを、`csv` は配列キー
    ごとに 1 つのテキストファイルを書き出す。バンドルのメタデータ（解析
    パラメータと来歴）は常に `<stem>_meta.json` として併記出力される。

    Returns
    -------
    int
        0 when every bundle exported, 1 when any failed, 2 when no usable
        input bundle was found.
        全バンドル成功で 0、いずれか失敗で 1、有効な入力が無ければ 2。
    """
    # Local import: NumPy is needed only by this subcommand's writers.
    import numpy as np

    inputs = _expand_inputs(args.inputs)
    inputs = [p for p in inputs if os.path.isfile(p)]
    if not inputs:
        print("error: no input bundle files found", file=sys.stderr)
        return 2

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    failures = []
    for i, bundle_path in enumerate(inputs, 1):
        name = os.path.basename(bundle_path)
        stem = _output_stem(bundle_path, args.output_dir)
        print(f"[{i}/{len(inputs)}] {name}: ", end="", flush=True)
        try:
            arrays = load_bundle(bundle_path)
            meta = load_bundle_meta(bundle_path)

            if args.format == "npz":
                out_path = stem + ".npz"
                np.savez_compressed(out_path, **arrays)
                written = os.path.basename(out_path)
            else:
                # One CSV per key; 1D arrays are written as a single row.
                # キーごとに 1 つの CSV。1 次元配列は 1 行として書き出す。
                for key, arr in arrays.items():
                    np.savetxt(
                        f"{stem}_{key}.csv", np.atleast_2d(arr),
                        delimiter=",", fmt="%.10g",
                    )
                written = f"{os.path.basename(stem)}_<key>.csv"

            meta_path = stem + "_meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                # default=str keeps export usable even if a future bundle
                # carries metadata values JSON cannot represent natively.
                json.dump(meta, f, ensure_ascii=False, indent=2, default=str)

            print(f"done -> {written} + {os.path.basename(meta_path)}")
        except Exception as e:
            print("FAILED")
            print(f"    {type(e).__name__}: {e}", file=sys.stderr)
            failures.append(name)

    if failures:
        print("failed bundles: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for the CLI entry point.
    CLI エントリポイント用の引数パーサーを構築する。
    """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description=(
            "Batch-run the AFM nanofiber preprocessing pipeline "
            "(same outputs as the GUI01 Image Preprocessor)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_proc = sub.add_parser(
        "process",
        help="process raw AFM text/CSV files into .b2z bundles",
    )
    p_proc.add_argument(
        "inputs", nargs="+",
        help="input AFM text/CSV files (glob patterns are expanded)",
    )
    p_proc.add_argument(
        "--params", metavar="JSON",
        help="analysis-parameter JSON file (default: built-in defaults; "
             "see 'show-params')",
    )
    p_proc.add_argument(
        "--output-dir", metavar="DIR",
        help="directory for .b2z and _param.json outputs "
             "(default: next to each input file)",
    )
    p_proc.add_argument(
        "--overwrite", action="store_true",
        help="re-process inputs whose outputs already exist",
    )
    p_proc.add_argument(
        "--save-original", action="store_true",
        help="also store the raw height image in the bundle ('original' key)",
    )
    p_proc.set_defaults(func=cmd_process)

    p_show = sub.add_parser(
        "show-params",
        help="print default analysis parameters as JSON",
    )
    p_show.set_defaults(func=cmd_show_params)

    p_export = sub.add_parser(
        "export",
        help="export .b2z bundles to standard formats (NumPy .npz or CSV)",
    )
    p_export.add_argument(
        "inputs", nargs="+",
        help="input .b2z bundle files (glob patterns are expanded)",
    )
    p_export.add_argument(
        "--format", choices=("npz", "csv"), default="npz",
        help="output format: one .npz archive per bundle (default), "
             "or one CSV file per array key",
    )
    p_export.add_argument(
        "--output-dir", metavar="DIR",
        help="directory for exported files (default: next to each bundle)",
    )
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list = None) -> int:
    """
    Parse arguments and dispatch to the selected subcommand.
    引数を解析し、選択されたサブコマンドへ振り分ける。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
