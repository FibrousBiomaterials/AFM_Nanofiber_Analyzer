# -*- coding: utf-8 -*-
"""
Code that reads a bundle never runs the stages that produce its arrays.
バンドルを読むコードは、その配列を作る解析段を実行しない。

A bundle is the record of one analysis: its skeleton, masks and points were
made by the pipeline with the settings it ran with. A reader that runs a stage
again — a loop collapse, a spur prune, a background fit — measures something
other than the record, and does it at its own defaults, so an analysis setting
that the stage takes is silently overridden. Compatibility with an older
bundle is handled by its format version and by asking for re-analysis
(AGENTS.md §8.16), never by repairing the arrays when they are read.
バンドルは 1 回の解析の記録であり、骨格・マスク・点はパイプラインが解析時の
設定で作ったものである。読み込み側が解析段（ループの潰し、スパーの除去、
背景の当てはめ）をもう一度実行すると、記録とは別のものを計測し、しかも自分の
既定値で行うため、その段が受け取る解析の設定を黙って上書きする。古い
バンドルへの対応は形式バージョンと再解析の依頼で行い（AGENTS.md §8.16）、
読み込み時に配列を修理することでは行わない。

This test parses the reader code and fails when it imports a name from a stage
module or the pipeline's stage drivers. Recomputing what the bundle's recorded
settings determine — placing the centerline, judging kinks on a reconnected
fibril — is measurement, not a stage, and is not restricted here.
このテストは読み込み側のコードを構文解析し、解析段のモジュールやパイプラインの
段の実行関数から名前を import していれば失敗する。バンドルに記録された設定が
決めるものの再計算（中心線の配置、再結合したフィブリルのキンク判定）は計測で
あって解析段ではないので、ここでは制限しない。
"""

# ===== Standard library =====
import ast
from pathlib import Path

# ===== Test libraries =====
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Modules whose functions produce or rewrite stored arrays. Every name defined
# in them is forbidden to readers, so a stage function added later is covered
# without editing this list.
# 保存される配列を作る、または書き換える関数のモジュール。ここで定義された名前は
# すべて読み込み側に禁止するので、後から足した段の関数もこの一覧を直さずに
# 対象になる。
STAGE_MODULES = ("bg_calibrator", "bg_calibrator_shimadzu", "segmenter", "skeletonizer")

# The pipeline's own stage drivers; the rest of `lib.pipeline` (`ProcParams`,
# parameter helpers) only describes an analysis and may be read.
# パイプライン自身の段の実行関数。`lib.pipeline` の残り（`ProcParams` と
# パラメータの補助関数）は解析を記述するだけなので読んでよい。
PIPELINE_DRIVERS = {"process_file", "build_stages", "PipelineStages"}

# Modules that only read bundles, checked whole.
# バンドルを読むだけのモジュール。全体を調べる。
READER_MODULES = (
    "lib/blosc2_io.py",
    "lib/bundle_schema.py",
    "lib/centerline.py",
    "lib/connect_selection.py",
    "lib/fiber.py",
    "lib/fiber_connector.py",
    "lib/fiber_selection.py",
    "lib/fiber_tracking_image.py",
    "lib/measure.py",
    "guis/GUI02_PlotProfiler.py",
    "guis/GUI03_Fiber_Morphology_Statistics.py",
    "guis/GUI04_Tracking_fiber.py",
)

# `cli.py` also analyzes (`process`), so only its bundle-reading commands are
# checked, by the names they call.
# `cli.py` は解析（`process`）も行うので、バンドルを読むコマンドだけを、
# 呼び出す名前で調べる。
CLI_READER_FUNCTIONS = ("cmd_measure", "cmd_heights", "cmd_validate", "cmd_export")


def _stage_module(module: str, level: int) -> bool:
    """
    Tell whether an import's module path names a stage module.
    import のモジュールパスが解析段のモジュールを指すかを判定する。
    """
    parts = module.split(".") if module else []
    if level == 0 and parts[:1] != ["lib"]:
        return False
    name = parts[-1] if parts else ""
    return name in STAGE_MODULES


def _pipeline_module(module: str, level: int) -> bool:
    """
    Tell whether an import's module path names `lib.pipeline`.
    import のモジュールパスが `lib.pipeline` を指すかを判定する。
    """
    return (level == 0 and module == "lib.pipeline") or (level >= 1 and module == "pipeline")


def forbidden_imports(source: str) -> list:
    """
    List the stage imports in one module's source, as ``(line, text)``.
    1 モジュールのソース中の解析段の import を ``(行, 内容)`` で列挙する。

    Imports inside functions count as well: the project defers heavy imports
    into functions to keep plugin startup fast (AGENTS.md §8.5), and a stage
    imported there runs just the same.
    関数内の import も数える。このプロジェクトはプラグインの起動を速く保つため
    重い import を関数内へ遅らせており（AGENTS.md §8.5）、そこで import した
    解析段も同じように実行されるためである。
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module, level = node.module or "", node.level
            if _stage_module(module, level):
                found.append((node.lineno, f"from {'.' * level}{module} import ..."))
            elif _pipeline_module(module, level):
                for alias in node.names:
                    if alias.name in PIPELINE_DRIVERS:
                        found.append((node.lineno, f"{alias.name} from {'.' * level}{module}"))
            elif (level == 0 and module == "lib") or (level == 1 and not module):
                for alias in node.names:
                    if alias.name in STAGE_MODULES or alias.name == "pipeline":
                        found.append((node.lineno, f"module {alias.name}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "lib" and (
                        alias.name.split(".")[-1] in STAGE_MODULES
                        or alias.name == "lib.pipeline"):
                    found.append((node.lineno, f"import {alias.name}"))
    return found


def forbidden_calls(source: str, functions) -> list:
    """
    List calls of pipeline stage drivers inside the named top-level functions.
    指定した最上位関数の中にある、パイプラインの段の実行関数の呼び出しを列挙する。
    """
    found = []
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    callee = sub.func
                    name = callee.id if isinstance(callee, ast.Name) else (
                        callee.attr if isinstance(callee, ast.Attribute) else "")
                    if name in PIPELINE_DRIVERS:
                        found.append((sub.lineno, f"{node.name} calls {name}"))
    return found


@pytest.mark.parametrize("rel", READER_MODULES)
def test_reader_module_imports_no_analysis_stage(rel):
    """A bundle reader imports nothing that produces or rewrites stored arrays."""
    found = forbidden_imports((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
    assert not found, (
        f"{rel} imports an analysis stage: {found}. A reader must measure the "
        "bundle as stored; see AGENTS.md §8.16."
    )


def test_cli_reader_commands_run_no_analysis_stage():
    """`cli.py`'s bundle-reading commands call no pipeline stage driver."""
    source = (PROJECT_ROOT / "cli.py").read_text(encoding="utf-8")
    defined = {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    assert set(CLI_READER_FUNCTIONS) <= defined, "a checked cli command was renamed"
    found = forbidden_calls(source, CLI_READER_FUNCTIONS)
    assert not found, (
        f"cli.py runs an analysis stage while reading bundles: {found}; "
        "see AGENTS.md §8.16."
    )


def test_the_check_catches_a_load_time_cleanup():
    """
    The check flags a reader that repairs the stored skeleton at load time.
    読み込み時に保存された骨格を修理する読み込み側を、この検査が検出する。
    """
    source = (
        "def _labeled_components(self, skeleton_image):\n"
        "    from .skeletonizer import collapse_skeleton_loops\n"
        "    return collapse_skeleton_loops(skeleton_image)\n"
    )
    assert forbidden_imports(source) == [(2, "from .skeletonizer import ...")]
    assert forbidden_imports("from lib.pipeline import ProcParams\n") == []
    assert forbidden_imports("from lib.pipeline import process_file\n") != []
    assert forbidden_calls(
        "def cmd_measure(args):\n    process_file(args.x)\n", ("cmd_measure",)
    ) == [(2, "cmd_measure calls process_file")]
