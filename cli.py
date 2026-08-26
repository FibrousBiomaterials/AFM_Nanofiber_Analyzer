# -*- coding: utf-8 -*-
"""
Command-line interface for the AFM nanofiber preprocessing pipeline.
AFM ナノファイバー前処理パイプラインのコマンドラインインターフェース。

Runs the same pipeline as the GUI01 Image Preprocessor (background
calibration, segmentation, skeletonization, kink detection) through
`lib.pipeline.process_file`, so CLI and GUI analysis arrays and parameter
sidecars match for the same input and settings. Run-specific provenance
metadata, such as timestamps, differs. This enables scripted batch processing
and reproducible analysis without the GUI.
GUI01 Image Preprocessor と同じパイプライン（背景補正・二値化・細線化・
キンク検出）を `lib.pipeline.process_file` 経由で実行するため、同じ入力と設定に
対して CLI と GUI の解析配列・パラメータサイドカーは一致する。タイムスタンプ
など実行固有の来歴情報は異なる。GUI なしでのバッチ処理と再現可能な解析を
可能にする。

Fiber measurement is also exposed through `lib.measure`: `measure` shares the
GUI04 analysis and CSV writer, while `heights` shares GUI03's skeleton-height
collection. A complete, unfiltered GUI04 CSV is byte-identical to `measure` for
the same bundle and scale; a filtered GUI04 export intentionally contains only
the retained fiber portions.
ファイバー計測も `lib.measure` 経由で提供する。`measure` は GUI04 の解析と CSV
writer を、`heights` は GUI03 のスケルトン高さ収集を共有する。GUI04 の全件・
フィルターなし CSV は同じバンドルとスケールに対する `measure` とバイト単位で
一致するが、フィルター後の GUI04 出力は残ったファイバー部分だけを含む。

Usage examples
--------------
    python cli.py process data/*.txt
    python cli.py process scan.txt --params my_param.json --output-dir out/
    python cli.py process scan.gwy --channel Topography
    python cli.py show-params > default_param.json
    python cli.py measure out/*.b2z --scale-um 2.0
    python cli.py heights out/ --output heights.csv
    python cli.py validate out/*.b2z

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
from lib.blosc2_io import BUNDLE_EXT, load_bundle, load_bundle_meta
from lib.bundle_schema import REQUIRED_BUNDLE_KEYS, validate_bundle
from lib.measure import (
    measure_bundle,
    skeleton_height_values,
    write_fiber_csv,
    write_heights_csv,
)
from lib.pipeline import (
    ProcParams,
    build_stages,
    existing_min_set,
    merge_params_dict,
    process_file,
    row_range_suffix,
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


def _load_params(path: str, strict: bool = False) -> ProcParams:
    """
    Load analysis parameters from a JSON file, reporting reconciled keys.
    JSON ファイルから解析パラメータを読み込み、整合処理したキーを報告する。

    Missing keys are filled from `ProcParams` defaults and unknown keys are
    ignored, matching the GUI startup-settings behavior. With `strict`,
    unknown keys raise instead, because a typoed key would otherwise silently
    fall back to the default value and change the analysis without notice.
    欠損キーは `ProcParams` の既定値で補完し、未知キーは無視する。GUI の
    起動時設定と同じ挙動である。`strict` 指定時は未知キーを例外にする。
    typo したキーが黙って既定値へフォールバックし、気づかないまま解析条件が
    変わることを防ぐためである。

    Raises
    ------
    ValueError
        If `strict` is true and the file contains keys unknown to
        `ProcParams`.
    """
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    params, missing, obsolete = merge_params_dict(d)
    if strict and obsolete:
        raise ValueError(
            "unknown parameter keys (use show-params for the valid set): "
            + ", ".join(obsolete)
        )
    if missing:
        print(f"[params] missing keys filled from defaults: {', '.join(missing)}")
    if obsolete:
        print(f"[params] unknown keys ignored: {', '.join(obsolete)}")
    return params


def _output_stem(txt_path: str, output_dir: str, row_range=None) -> str:
    """
    Return the extensionless output path for one input file.
    1 入力ファイルに対応する拡張子なしの出力パスを返す。

    `row_range` selects one analyzed scan-line range, whose suffix has to match
    what `process_file` writes, or the existing-output check would look at the
    wrong path and re-run work that is already done.
    `row_range` は解析する走査線範囲を指定する。その接尾辞は `process_file` が
    書き出すものと一致していなければならない。さもないと既存出力の確認が別の
    パスを見てしまい、済んでいる処理をやり直すことになる。
    """
    name = os.path.splitext(os.path.basename(txt_path))[0] + row_range_suffix(row_range)
    if output_dir:
        return os.path.join(output_dir, name)
    return os.path.splitext(txt_path)[0] + row_range_suffix(row_range)


def _parse_row_ranges(text):
    """
    Parse a ``--rows`` value into half-open scan-line ranges.
    ``--rows`` の値を半開区間の走査線範囲へ解析する。

    Parameters
    ----------
    text
        Comma-separated ``START-STOP`` ranges, or ``None`` for the whole image.
        カンマ区切りの ``START-STOP`` 範囲。画像全体なら ``None``。

    Returns
    -------
    list
        One entry per range, or ``[None]`` meaning "analyze the whole image",
        so callers can loop uniformly.
        範囲ごとに 1 要素。``[None]`` は「画像全体を解析」を意味し、呼び出し側が
        一様にループできるようにする。

    Raises
    ------
    ValueError
        If a range is malformed or not increasing. Bounds against the actual
        image are checked later by `process_file`, which is the only place that
        knows how many scan lines the input has.
    """
    if not text:
        return [None]
    ranges = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        start_text, sep, stop_text = chunk.partition("-")
        if not sep:
            raise ValueError(f"expected START-STOP, got {chunk!r}")
        try:
            start, stop = int(start_text), int(stop_text)
        except ValueError:
            raise ValueError(f"expected whole numbers in {chunk!r}") from None
        if start < 0 or stop <= start:
            raise ValueError(f"{chunk!r} is not a non-empty range")
        ranges.append((start, stop))
    if not ranges:
        raise ValueError("no scan-line range given")
    return ranges


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

    if args.scale_um is not None and not (args.scale_um > 0):
        print("error: --scale-um must be a positive number", file=sys.stderr)
        return 2
    if args.scale_y_um is not None and not (args.scale_y_um > 0):
        print("error: --scale-y-um must be a positive number", file=sys.stderr)
        return 2
    if args.scale_y_um is not None and args.scale_um is None:
        print(
            "error: --scale-y-um requires --scale-um (X size) as well",
            file=sys.stderr,
        )
        return 2

    try:
        row_ranges = _parse_row_ranges(getattr(args, "rows", None))
    except ValueError as e:
        print(f"error: --rows: {e}", file=sys.stderr)
        return 2

    try:
        params = _load_params(args.params, strict=args.strict) if args.params else ProcParams()
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

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
    # One job per (input file, scan-line range) pair: asking for several ranges
    # of one scan produces one bundle each, as the GUI's file table does.
    # (入力ファイル, 走査線範囲) の組ごとに 1 ジョブ。1 つの走査に複数範囲を
    # 指定すると、GUI のファイル表と同様それぞれ 1 バンドルを生成する。
    jobs = [(txt_path, rr) for txt_path in inputs for rr in row_ranges]
    for i, (txt_path, row_range) in enumerate(jobs, 1):
        # Label for progress output only. The suffix is appended as a
        # bracketed range rather than glued onto the file name, which would
        # otherwise read as text after the extension ("scan.txt_r200-456").
        # 進捗表示用のラベル。接尾辞はファイル名に直接繋げず角括弧の範囲として
        # 付す。繋げると拡張子の後ろに文字列が続く形（"scan.txt_r200-456"）に
        # 見えてしまうためである。
        name = os.path.basename(txt_path)
        if row_range is not None:
            name += " [{0}-{1}]".format(row_range[0], row_range[1])
        stem = _output_stem(txt_path, args.output_dir, row_range)

        ok, _missing = existing_min_set(stem)
        if ok and not args.overwrite:
            print(f"[{i}/{len(jobs)}] {name}: skipped (outputs exist; use --overwrite)")
            n_skipped += 1
            continue

        print(f"[{i}/{len(jobs)}] {name}: ", end="", flush=True)
        try:
            result = process_file(
                txt_path,
                params,
                stages=stages,
                output_dir=args.output_dir or None,
                save_original=args.save_original,
                on_stage=lambda s: print(s, end=" ", flush=True),
                input_format=args.format,
                scan_size_um=(
                    (args.scale_um, args.scale_y_um or args.scale_um)
                    if args.scale_um is not None else None
                ),
                scan_size_source="manual",
                gwy_channel=args.channel,
                row_range=row_range,
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
        f"{len(failures)} failed (of {len(jobs)} jobs)"
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


def _expand_bundle_inputs(patterns: list) -> list:
    """
    Expand globs and directories into a deduplicated `.b2z` path list.
    glob とディレクトリを展開し、重複排除した `.b2z` パスのリストを返す。

    A directory argument is replaced by every bundle file directly inside it,
    so a GUI01 output folder can be passed as-is.
    ディレクトリ引数は直下の全バンドルファイルへ置き換えるため、GUI01 の
    出力フォルダをそのまま渡せる。
    """
    paths = []
    for p in _expand_inputs(patterns):
        if os.path.isdir(p):
            paths.extend(
                os.path.join(p, fn)
                for fn in sorted(os.listdir(p))
                if fn.endswith(BUNDLE_EXT)
            )
        else:
            paths.append(p)
    return [p for p in dict.fromkeys(paths) if os.path.isfile(p)]


def cmd_measure(args: argparse.Namespace) -> int:
    """
    Trace fibers in `.b2z` bundles and write per-fiber statistics CSV files.
    `.b2z` バンドル内のファイバーを追跡し、ファイバー統計 CSV を書き出す。

    Each bundle produces one `<stem>_fibers.csv` through
    `lib.measure.write_fiber_csv`, the same writer used by the GUI04 export.
    各バンドルにつき `<stem>_fibers.csv` を 1 つ、GUI04 のエクスポートと同じ
    `lib.measure.write_fiber_csv` 経由で出力する。

    Returns
    -------
    int
        0 when every bundle succeeded, 1 when any failed, 2 when no usable
        input bundle was found or the scale is invalid.
        全バンドル成功で 0、いずれか失敗で 1、有効な入力が無いか
        スケールが不正なら 2。
    """
    inputs = _expand_bundle_inputs(args.inputs)
    if not inputs:
        print("error: no input bundle files found", file=sys.stderr)
        return 2
    # When given, the scale must be positive; when omitted (None), each bundle
    # falls back to its own recorded scan size inside measure_bundle.
    # 指定時はスケールが正であること。省略時 (None) は各バンドルが
    # measure_bundle 内で自身の記録走査範囲にフォールバックする。
    if args.scale_um is not None and not (args.scale_um > 0):
        print("error: --scale-um must be a positive number", file=sys.stderr)
        return 2
    if args.scale_y_um is not None and not (args.scale_y_um > 0):
        print("error: --scale-y-um must be a positive number", file=sys.stderr)
        return 2
    if args.scale_y_um is not None and args.scale_um is None:
        print(
            "error: --scale-y-um requires --scale-um (X size) as well",
            file=sys.stderr,
        )
        return 2

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    failures = []
    for i, bundle_path in enumerate(inputs, 1):
        name = os.path.basename(bundle_path)
        stem = _output_stem(bundle_path, args.output_dir)
        print(f"[{i}/{len(inputs)}] {name}: ", end="", flush=True)
        try:
            result = measure_bundle(
                bundle_path, scale_um=args.scale_um, scale_y_um=args.scale_y_um,
            )
            csv_path = stem + "_fibers.csv"
            write_fiber_csv(csv_path, result.stats)
        except Exception as e:
            print("FAILED")
            print(f"    {type(e).__name__}: {e}", file=sys.stderr)
            failures.append(name)
            continue
        print(f"{len(result.stats)} fibers -> {os.path.basename(csv_path)}")

    if failures:
        print("failed bundles: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def cmd_heights(args: argparse.Namespace) -> int:
    """
    Collect skeleton-pixel heights from bundles and summarize or export them.
    バンドルからスケルトン画素の高さを収集し、要約表示または CSV 出力する。

    This is the data source of the GUI03 height histogram. The optional
    long-format CSV lets external tools regroup and re-bin the values freely.
    GUI03 の高さヒストグラムの元データに相当する。任意出力の縦持ち CSV に
    より、外部ツールで自由に再グループ化・再ビニングできる。

    Returns
    -------
    int
        0 when every bundle was read, 1 when any failed, 2 when no usable
        input bundle was found.
        全バンドル読込成功で 0、いずれか失敗で 1、有効な入力が無ければ 2。
    """
    # Local import: NumPy is needed only by this subcommand's summary lines.
    # ローカル import: NumPy はこのサブコマンドの要約表示でのみ必要。
    import numpy as np

    inputs = _expand_bundle_inputs(args.inputs)
    if not inputs:
        print("error: no input bundle files found", file=sys.stderr)
        return 2

    per_bundle = []
    failures = []
    for i, bundle_path in enumerate(inputs, 1):
        name = os.path.basename(bundle_path)
        heights, errors = skeleton_height_values([bundle_path])
        if errors:
            print(f"[{i}/{len(inputs)}] {name}: FAILED")
            for _path, msg in errors:
                print(f"    {msg}", file=sys.stderr)
            failures.append(name)
            continue
        stem = os.path.splitext(name)[0]
        per_bundle.append((stem, heights))
        print(
            f"[{i}/{len(inputs)}] {name}: {heights.size} skeleton px, "
            f"mean {np.mean(heights):.3f} nm, std {np.std(heights):.3f} nm"
        )

    if args.output and per_bundle:
        write_heights_csv(args.output, per_bundle)
        total = sum(h.size for _n, h in per_bundle)
        print(f"wrote {total} height values -> {args.output}")

    if failures:
        print("failed bundles: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """
    Check `.b2z` bundles against the bundle contract and report problems.
    `.b2z` バンドルを契約と照合し、問題を報告する。

    Verifies required keys, array shapes, mask values, kink-angle units, and
    the recorded format version through `lib.bundle_schema.validate_bundle`.
    Provenance metadata presence is reported as information, not as a
    failure, because bundles from old releases legitimately lack it.
    必須キー、配列形状、マスク値、キンク角の単位、記録された形式バージョンを
    `lib.bundle_schema.validate_bundle` で検証する。来歴メタデータの有無は
    情報として表示するだけで失敗にはしない。旧リリースのバンドルには来歴が
    無いのが正常なためである。

    Returns
    -------
    int
        0 when every bundle conforms, 1 when any violates the contract or
        cannot be read, 2 when no usable input bundle was found.
        全バンドル適合で 0、違反または読込不能があれば 1、有効な入力が
        無ければ 2。
    """
    inputs = _expand_bundle_inputs(args.inputs)
    if not inputs:
        print("error: no input bundle files found", file=sys.stderr)
        return 2

    n_invalid = 0
    for i, bundle_path in enumerate(inputs, 1):
        name = os.path.basename(bundle_path)
        try:
            arrays = load_bundle(bundle_path)
            meta = load_bundle_meta(bundle_path)
        except Exception as e:
            print(f"[{i}/{len(inputs)}] {name}: UNREADABLE")
            print(f"    {type(e).__name__}: {e}", file=sys.stderr)
            n_invalid += 1
            continue

        problems = validate_bundle(arrays, meta=meta, require=REQUIRED_BUNDLE_KEYS)
        if problems:
            print(f"[{i}/{len(inputs)}] {name}: INVALID")
            for problem in problems:
                print(f"    - {problem}", file=sys.stderr)
            n_invalid += 1
            continue

        # Provenance keys are optional (old bundles lack them); report only.
        # 来歴キーは任意（旧バンドルには無い）。報告のみ行う。
        has_provenance = all(
            k in meta for k in ("software_version", "input_file", "input_sha256")
        )
        n_kinks = arrays["ka"].shape[0]
        version = meta.get("version", "unrecorded")
        print(
            f"[{i}/{len(inputs)}] {name}: OK "
            f"(format {version}, image {arrays['calibrated'].shape[0]}x"
            f"{arrays['calibrated'].shape[1]}, {n_kinks} kinks, "
            f"provenance {'present' if has_provenance else 'absent'})"
        )

    print(f"finished: {len(inputs) - n_invalid} valid, {n_invalid} invalid")
    return 1 if n_invalid else 0


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for the CLI entry point.
    CLI エントリポイント用の引数パーサーを構築する。
    """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description=(
            "Batch-run the AFM nanofiber preprocessing pipeline "
            "(same analysis arrays and parameters as GUI01)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_proc = sub.add_parser(
        "process",
        help="process raw AFM text/CSV or Gwyddion .gwy files into .b2z bundles",
    )
    p_proc.add_argument(
        "inputs", nargs="+",
        help="input AFM text/CSV or Gwyddion .gwy files "
             "(glob patterns are expanded)",
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
    p_proc.add_argument(
        "--format", choices=("auto", "multi-column", "single-column"),
        default="auto",
        help="input text layout (default: auto-detect). Use an explicit "
             "layout when auto-detection locks onto a numeric header block; "
             "the resolved layout is recorded in the bundle metadata. Ignored "
             "for .gwy inputs",
    )
    p_proc.add_argument(
        "--channel", metavar="ID_OR_NAME", default=None,
        help="for Gwyddion .gwy inputs, the channel to analyze, by id (e.g. 1) "
             "or title (e.g. Topography). Default: auto-select the "
             "topography/height channel. Non-length channels keep native "
             "values and are unsuitable for this height-in-nm pipeline. "
             "Ignored for text/CSV inputs",
    )
    p_proc.add_argument(
        "--scale-um", type=float, default=None, metavar="UM",
        help="physical scan size (X / width) in micrometers to record in the "
             "bundle. Applied to both axes unless --scale-y-um is given. "
             "Overrides the value read from the instrument header; when "
             "omitted, the header value is used if present, otherwise no scan "
             "size is stored.",
    )
    p_proc.add_argument(
        "--scale-y-um", type=float, default=None, metavar="UM",
        help="physical scan size (Y / height) in micrometers for rectangular "
             "scans; requires --scale-um. When omitted, the Y size equals "
             "--scale-um (square scan).",
    )
    p_proc.add_argument(
        "--rows", metavar="START-STOP[,...]", default=None,
        help="analyze only these scan lines, as half-open ranges counted from "
             "0 (e.g. 473-696 or 473-696,709-842). Each range is analyzed as "
             "its own image and written to its own bundle, suffixed _r<start>-"
             "<stop>; --scale-um / --scale-y-um still give the WHOLE scan's "
             "size and the stored Y size is scaled to the range. Use this to "
             "exclude scan lines disturbed by feedback glitches: several "
             "stages take a threshold from a statistic over the whole image, "
             "so leaving them in changes what the rest is compared against. "
             "Default: analyze the whole image.",
    )
    p_proc.add_argument(
        "--strict", action="store_true",
        help="fail when the --params file contains unknown keys "
             "(catches typos that would silently fall back to defaults)",
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

    p_measure = sub.add_parser(
        "measure",
        help="trace fibers in .b2z bundles and write per-fiber statistics CSV",
    )
    p_measure.add_argument(
        "inputs", nargs="+",
        help="input .b2z bundle files or folders "
             "(glob patterns are expanded; folders take all bundles inside)",
    )
    p_measure.add_argument(
        "--scale-um", type=float, default=None, metavar="UM",
        help="full physical image width (X) in micrometers; the X pixel size "
             "is scale / image width. Applied to both axes unless --scale-y-um "
             "is given. Optional: when omitted, the scan size recorded in each "
             "bundle is used; bundles without a recorded scan size are reported "
             "as failures.",
    )
    p_measure.add_argument(
        "--scale-y-um", type=float, default=None, metavar="UM",
        help="full physical image height (Y) in micrometers for rectangular "
             "scans; the Y pixel size is scale / image height. Requires "
             "--scale-um. When omitted, the Y size equals --scale-um.",
    )
    p_measure.add_argument(
        "--output-dir", metavar="DIR",
        help="directory for <stem>_fibers.csv outputs "
             "(default: next to each bundle)",
    )
    p_measure.set_defaults(func=cmd_measure)

    p_heights = sub.add_parser(
        "heights",
        help="collect skeleton-pixel heights (GUI03 histogram data) "
             "from .b2z bundles",
    )
    p_heights.add_argument(
        "inputs", nargs="+",
        help="input .b2z bundle files or folders "
             "(glob patterns are expanded; folders take all bundles inside)",
    )
    p_heights.add_argument(
        "--output", metavar="CSV",
        help="write all height values to a long-format CSV "
             "(columns: bundle, height_nm)",
    )
    p_heights.set_defaults(func=cmd_heights)

    p_validate = sub.add_parser(
        "validate",
        help="check .b2z bundles against the bundle contract "
             "(keys, shapes, units, format version)",
    )
    p_validate.add_argument(
        "inputs", nargs="+",
        help="input .b2z bundle files or folders "
             "(glob patterns are expanded; folders take all bundles inside)",
    )
    p_validate.set_defaults(func=cmd_validate)

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
