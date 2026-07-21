"""
Scan project imports, check dependency consistency, and pin versions.
プロジェクトの import を走査し、依存の整合性検査とバージョン固定を行う。

Modes
-----
``python check.py``
    Scan imports and regenerate the loose `requirements.txt` (historical
    behavior, kept compatible with the setup scripts that run before any
    dependency is installed). When packages are already installed, a
    consistency report is printed as warnings only.
    import を走査して緩い `requirements.txt` を再生成する（従来動作。依存
    インストール前に実行されるセットアップスクリプトとの互換を維持）。
    パッケージ導入済みの環境では整合性レポートを警告として表示する。
``python check.py --verify``
    Check-only mode for CI: report drift between scanned imports, pyproject
    dependencies, and the installed environment; exit nonzero on problems.
    CI 向けの検査専用モード。走査結果・pyproject の依存・実環境の食い違いを
    報告し、問題があれば非ゼロで終了する。
``python check.py --pin``
    Run all consistency checks plus the pytest suite, then regenerate
    `requirements.lock.txt` from the current environment only if everything
    passes, so the lock always records a test-verified version set.
    全整合性検査と pytest スイートを実行し、すべて合格した場合のみ現環境から
    `requirements.lock.txt` を再生成する。lock は常にテスト検証済みの
    バージョンセットを記録する。

The current `build.py` intentionally does not read `check.py` or
`requirements.txt` as its dependency source (see build.py's docstring), but
the helper functions here (`IMPORT_TO_PIP`, `is_stdlib`, `top_level`,
`extract_imports`, `iter_py_files`) keep stable signatures for reuse.
現在の `build.py` は意図的に `check.py` / `requirements.txt` をビルド依存の
情報源として使わない（build.py の docstring 参照）。ただし本モジュールの
ヘルパー関数（`IMPORT_TO_PIP` / `is_stdlib` / `top_level` /
`extract_imports` / `iter_py_files`）は再利用のためシグネチャを安定に保つ。
"""

from __future__ import annotations

import argparse
import ast
import datetime
import importlib.metadata
import importlib.util
import platform
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Runtime entry-point files to scan for `requirements.txt`.
TARGET_FILES = [ROOT / "Main.py"]

# Runtime package directories to scan for `requirements.txt`.
TARGET_DIRS = [ROOT / "guis", ROOT / "lib"]

# Ignore local project packages from external dependency list.
IGNORE_TOPLEVEL = {"guis", "lib"}

# ML modules whose imports are optional, training/inference-only dependencies
# declared in [project.optional-dependencies] (the `ml` extra), not in the base
# [project] dependencies. They are skipped by the base-dependency scan so that
# scikit-learn (and later skl2onnx / onnxruntime) do not leak into
# requirements.txt or the pyproject base dependency set. The base deps these
# modules also use (numpy, etc.) are still covered because other scanned files
# import them. Kept in sync with the `ml` extra and requirements-ml.txt by hand.
# import が任意の学習/推論専用依存（[project.optional-dependencies] の `ml`
# extra に宣言。基本の [project] dependencies ではない）である ML モジュール。
# 基本依存スキャンから除外し、scikit-learn（将来は skl2onnx / onnxruntime）が
# requirements.txt や pyproject の基本依存集合へ漏れないようにする。これらの
# モジュールが併用する基本依存（numpy 等）は他の走査対象ファイルが import する
# ため引き続きカバーされる。`ml` extra と requirements-ml.txt とは手動で同期する。
OPTIONAL_DEP_MODULE_NAMES = {"ml_train.py", "ml_model.py"}

# Map common import-name/package-name mismatches with a minimal explicit list.
# import名 -> pip名（代表的なズレだけ最小限で吸収）
IMPORT_TO_PIP = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "PyInstaller": "pyinstaller",
    "mpl_toolkits": "matplotlib",
    "pkg_resources": "setuptools",
    "dateutil": "python-dateutil",
    "fitz": "PyMuPDF",
}

# Submodules bundled with a parent package, such as matplotlib, and not installed separately.
# matplotlib等、親パッケージをインストールすれば自動で入るサブパッケージ
BUNDLED_WITH_PARENT = {
    "mpl_toolkits",  # Bundled with matplotlib.
    "pkg_resources",
    "dateutil",
    "fitz",
}

# Keep this map for version constraints that are confirmed by testing.
# Map pip name -> requirement string written into requirements.txt
# (e.g. {"numpy": "numpy>=2.0"}). Exact pins live in requirements.lock.txt,
# which `--pin` regenerates only after the test suite passes.
# テストで確認済みのバージョン制約を書く場所。pip 名 -> requirements.txt に
# 書き込む要求文字列（例: {"numpy": "numpy>=2.0"}）。厳密な固定は
# requirements.lock.txt が担い、`--pin` がテスト合格時のみ再生成する。
PACKAGE_CONSTRAINTS = {
    # Lower bound documents the oldest matplotlib series exercised by the test
    # suite (the lock lineage was 3.10.9) and pairs with requires-python>=3.10.
    # It guards fresh installs from resolving an unexpectedly old matplotlib
    # while staying loose enough not to obstruct JOSS reviewers; the exact
    # verified pin lives in requirements.lock.txt.
    "matplotlib": "matplotlib>=3.10",
}

# Distribution name of this project itself; excluded from the lock file
# because the editable self-install is not a third-party dependency.
# 本プロジェクト自身のディストリビューション名。editable インストールされた
# 自分自身はサードパーティ依存ではないため lock から除外する。
PROJECT_DIST_NAME = "afm-nanofiber-analyzer"

LOCK_FILENAME = "requirements.lock.txt"


def top_level(name: str) -> str:
    """
    Extract top-level package name from dotted module path.
    ドット区切りモジュール名からトップレベル名を取り出す。

    Parameters
    ----------
    name
        Module name such as `numpy.linalg`.
        `numpy.linalg` のようなモジュール名。

    Returns
    -------
    Top-level part such as `numpy`.
    `numpy` のような先頭要素。
    """
    return name.split(".", 1)[0]


def is_stdlib(name: str) -> bool:
    """
    Determine whether a module should be treated as stdlib/built-in.
    モジュールを標準ライブラリ/組み込み扱いにできるか判定する。

    If not found or undecidable, this function returns `False`
    to treat it as external dependency safely.
    見つからない、または判定不能な場合は `False` を返し、
    安全側として外部依存扱いにする。

    Parameters
    ----------
    name
        Top-level module name.
        トップレベルのモジュール名。

    Returns
    -------
    `True` for stdlib/built-in, `False` otherwise.
    標準/組み込みなら `True`、それ以外は `False`。
    """
    if not name:
        return True

    # Fast-path check using Python's stdlib module name set (3.10+).
    stdnames = getattr(sys, "stdlib_module_names", None)
    if stdnames is not None and name in stdnames:
        return True

    # built-in / frozen modules are stdlib-like by definition.
    try:
        spec = importlib.util.find_spec(name)
    except Exception:
        return False

    if spec is None:
        return False

    origin = spec.origin
    if origin is None or origin in ("built-in", "frozen"):
        return True

    o = origin.replace("\\", "/").lower()
    if "/site-packages/" in o or "/dist-packages/" in o:
        return False

    # Modules under Python runtime path (e.g., Lib/) are treated as stdlib.
    return True


def iter_py_files(
    dirs: list[Path] | None = None, files: list[Path] | None = None
) -> list[Path]:
    """
    Collect target Python files from configured directories.
    設定したディレクトリから対象 Python ファイルを収集する。

    Parameters
    ----------
    dirs
        Directories to scan. Defaults to `TARGET_DIRS`.
        走査対象ディレクトリ。省略時は `TARGET_DIRS`。
    files
        Individual Python files to scan. Defaults to `TARGET_FILES`.
        個別に走査する Python ファイル。省略時は `TARGET_FILES`。

    Returns
    -------
    Unique and stably sorted file paths (excluding `__init__.py`).
    `__init__.py` を除く、重複排除済みで順序安定なファイル一覧。
    """
    if dirs is None:
        dirs = TARGET_DIRS
    if files is None:
        files = TARGET_FILES

    py_files: list[Path] = []
    for f in files:
        if f.exists() and f.name != "__init__.py":
            py_files.append(f)

    for d in dirs:
        # Skip missing directories to keep script robust.
        if not d.exists():
            continue
        py_files += [p for p in d.glob("*.py") if p.name != "__init__.py"]

    # Drop modules whose imports are optional ML extras, not base dependencies,
    # so the base-dependency scan does not demand them in requirements.txt.
    # import が基本依存ではなく任意の ML extra であるモジュールを除外し、基本
    # 依存スキャンがそれらを requirements.txt に要求しないようにする。
    py_files = [p for p in py_files if p.name not in OPTIONAL_DEP_MODULE_NAMES]

    # Remove duplicates and keep deterministic ordering.
    return sorted(set(py_files), key=lambda p: p.as_posix().lower())


def extract_imports(pyfile: Path) -> set[str]:
    """
    Parse one Python file and collect imported top-level module names.
    1つの Python ファイルを解析して import のトップレベル名を集める。

    Parameters
    ----------
    pyfile
        Target Python file path.
        解析対象の Python ファイルパス。

    Returns
    -------
    Set of unique top-level import names.
    重複を除いたトップレベル import 名の集合。
    """
    # Read as UTF-8; ignore decode errors to continue scanning.
    src = pyfile.read_text(encoding="utf-8", errors="ignore")
    # Build AST once and walk nodes to find import statements.
    tree = ast.parse(src, filename=str(pyfile))
    mods: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(top_level(n.name))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (`from .x import ...`) are local-project modules.
            if node.level and node.level > 0:
                continue
            if node.module:
                mods.add(top_level(node.module))

    return mods


def normalize_pip_name(import_name: str) -> str:
    """
    Normalize import name into pip install name.
    import 名を pip インストール名へ正規化する。

    Parameters
    ----------
    import_name
        Module name found in source imports.
        ソース import から得たモジュール名。

    Returns
    -------
    Normalized package name for `requirements.txt`.
    `requirements.txt` 用に正規化したパッケージ名。
    """
    # Resolve known import-name/package-name mismatches first. Version
    # constraints are applied later by `write_requirements`, so this function
    # always returns a plain distribution name usable for metadata lookups.
    # バージョン制約は後段の `write_requirements` で適用するため、この関数は
    # 常にメタデータ照会に使える素のディストリビューション名を返す。
    pip_name = IMPORT_TO_PIP.get(import_name, import_name)
    # Trim whitespace to avoid accidental formatting variations.
    return pip_name.strip()


def collect_external_imports(files: list[Path] | None = None) -> set[str]:
    """
    Collect external (non-stdlib, non-local) top-level imports.
    外部（標準ライブラリ・プロジェクト内を除く）トップレベル import を収集する。

    Parameters
    ----------
    files
        Files to scan. Defaults to result of `iter_py_files()`.
        走査対象ファイル。省略時は `iter_py_files()` の結果。

    Returns
    -------
    External top-level import names (as they appear in `import` statements).
    外部トップレベル import 名（ソース上の import 名のまま）。
    """
    if files is None:
        files = iter_py_files()

    all_imports: set[str] = set()
    for f in files:
        all_imports |= extract_imports(f)

    # Remove local project packages and bundled submodules.
    all_imports -= IGNORE_TOPLEVEL
    all_imports -= BUNDLED_WITH_PARENT

    # Keep only non-stdlib modules as external dependencies.
    return {m for m in all_imports if not is_stdlib(m)}


def canonical_name(name: str) -> str:
    """
    Normalize a distribution name for comparison (PEP 503 style).
    比較用にディストリビューション名を正規化する（PEP 503 準拠）。
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_version(pip_name: str) -> str | None:
    """
    Return the installed version of a distribution, or None if absent.
    ディストリビューションの導入済みバージョンを返す。未導入なら None。
    """
    try:
        return importlib.metadata.version(pip_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def read_pyproject_dependencies() -> set[str] | None:
    """
    Return canonical dependency names declared in pyproject.toml.
    pyproject.toml に宣言された依存名を正規化した集合として返す。

    Returns
    -------
    set of str or None
        Canonical names from `[project] dependencies`, or None when the file
        is missing or `tomllib` is unavailable (Python 3.10).
        `[project] dependencies` の正規化名。ファイルが無い、または
        `tomllib` が使えない（Python 3.10）場合は None。
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        return None
    path = ROOT / "pyproject.toml"
    if not path.is_file():
        return None
    with open(path, "rb") as f:
        data = tomllib.load(f)
    names: set[str] = set()
    for spec in data.get("project", {}).get("dependencies", []):
        # Take the name part before any extras / version specifier.
        m = re.match(r"\s*([A-Za-z0-9._-]+)", spec)
        if m:
            names.add(canonical_name(m.group(1)))
    return names


def pip_names_from_externals(externals: Iterable[str]) -> list[str]:
    """
    Normalize and sort external import names into pip names.
    外部 import 名を pip 名へ正規化し整列する。

    Parameters
    ----------
    externals
        External top-level import names from `collect_external_imports()`.
        `collect_external_imports()` が返す外部トップレベル import 名。

    Returns
    -------
    Deduplicated pip names sorted case-insensitively.
    重複排除し大文字小文字を無視して整列した pip 名。
    """
    return sorted({normalize_pip_name(m) for m in externals}, key=str.lower)


def scan_pip_names() -> list[str]:
    """
    Return sorted pip names of all scanned direct dependencies.
    走査で得た直接依存の pip 名を整列したリストで返す。
    """
    return pip_names_from_externals(collect_external_imports())


def report_consistency(pip_names: list[str]) -> list[str]:
    """
    Check scanned imports against the environment and pyproject.toml.
    走査した import を実環境および pyproject.toml と突き合わせる。

    Two checks are performed: (1) every scanned direct dependency must be
    installed (its version is reported), and (2) the scanned dependency set
    must equal `[project] dependencies`, catching both "imported but not
    declared" and "declared but no longer imported" drift.
    検査は 2 つ。(1) 走査された直接依存がすべて導入済みであること（バージョン
    も報告する）。(2) 走査結果の依存集合が `[project] dependencies` と一致する
    こと。「import したのに宣言し忘れ」「もう使っていないのに宣言が残存」の
    両方向のずれを検出する。

    Parameters
    ----------
    pip_names
        Direct dependency pip names from `scan_pip_names()`.
        `scan_pip_names()` が返す直接依存の pip 名。

    Returns
    -------
    list of str
        Human-readable problem descriptions; empty when fully consistent.
        問題の説明文のリスト。完全に整合していれば空。
    """
    problems: list[str] = []

    print("=== Installed versions of scanned dependencies ===")
    missing: list[str] = []
    for name in pip_names:
        ver = installed_version(name)
        if ver is None:
            missing.append(name)
            print(f"{name:<24} NOT INSTALLED")
        else:
            print(f"{name:<24} {ver}")
    if missing:
        problems.append("not installed: " + ", ".join(missing))

    declared = read_pyproject_dependencies()
    if declared is None:
        print("note: pyproject.toml dependencies not checked "
              "(file missing or tomllib unavailable on Python 3.10)")
        return problems

    scanned = {canonical_name(n) for n in pip_names}
    only_code = sorted(scanned - declared)
    only_decl = sorted(declared - scanned)
    if only_code:
        problems.append(
            "imported in code but missing from pyproject dependencies: "
            + ", ".join(only_code)
        )
    if only_decl:
        problems.append(
            "declared in pyproject but not imported by scanned code: "
            + ", ".join(only_decl)
        )
    if not only_code and not only_decl:
        print("pyproject dependencies: in sync with scanned imports")
    return problems


def run_pip_check() -> bool:
    """
    Run `pip check` to detect version conflicts among installed packages.
    `pip check` を実行し、導入済みパッケージ間のバージョン矛盾を検出する。
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True, text=True,
    )
    output = (proc.stdout or "").strip()
    print(output if output else "pip check: no broken requirements found")
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr)
    return proc.returncode == 0


def run_pytest() -> bool:
    """
    Run the project test suite; pinning requires a green run.
    プロジェクトのテストスイートを実行する。固定にはグリーンが必須。
    """
    print("=== Running test suite (required before pinning) ===")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    return proc.returncode == 0


def collect_consistency_problems(pip_names: list[str]) -> list[str]:
    """
    Gather all dependency-consistency problems shared by verify and pin.
    verify と pin が共有する依存整合性の問題をまとめて収集する。

    Parameters
    ----------
    pip_names
        Direct dependency pip names from `scan_pip_names()`.
        `scan_pip_names()` が返す直接依存の pip 名。

    Returns
    -------
    Human-readable problem descriptions; empty when fully consistent.
    問題の説明文のリスト。完全に整合していれば空。
    """
    problems = report_consistency(pip_names)
    if not run_pip_check():
        problems.append("pip check reported broken requirements")
    return problems


def print_problems(header: str, problems: list[str]) -> None:
    """
    Print a header and a bulleted problem list to stderr.
    見出しと箇条書きの問題リストを stderr へ出力する。

    Parameters
    ----------
    header
        Leading line shown before the bullet list.
        箇条書きの前に表示する見出し行。
    problems
        Problem descriptions to list.
        列挙する問題の説明文。
    """
    print(header, file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)


def write_lock_file() -> Path:
    """
    Regenerate `requirements.lock.txt` from the current environment.
    現環境から `requirements.lock.txt` を再生成する。

    The editable self-install of this project is excluded; everything else
    (including dev tools such as pytest) is recorded so the snapshot
    reproduces the verified environment exactly.
    本プロジェクト自身の editable インストールは除外する。それ以外（pytest
    などの開発ツールを含む）はすべて記録し、検証済み環境を正確に再現できる
    スナップショットとする。
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True, text=True, check=True,
    )
    lines: list[str] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("-e "):
            continue
        name = re.split(r"==| @ ", line)[0]
        if canonical_name(name) == PROJECT_DIST_NAME:
            continue
        lines.append(line)

    header = [
        "# Test-verified full environment snapshot for reproducible installs.",
        f"# Generated by `python check.py --pin` on {datetime.date.today().isoformat()} "
        f"(Python {platform.python_version()}, {platform.system()}).",
        "# The pytest suite passed against exactly these versions.",
        "# Reproduce:  python -m pip install -r requirements.lock.txt",
        "# For loose runtime requirements see requirements.txt.",
    ]
    path = ROOT / LOCK_FILENAME
    path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    return path


def write_requirements(pip_names: list[str]) -> Path:
    """
    Write the loose `requirements.txt` from scanned dependencies.
    走査した依存から緩い `requirements.txt` を書き出す。
    """
    reqs = [PACKAGE_CONSTRAINTS.get(n, n) for n in pip_names]
    req_path = ROOT / "requirements.txt"
    req_path.write_text("\n".join(reqs) + ("\n" if reqs else ""), encoding="utf-8")
    return req_path


def main(argv: list[str] | None = None) -> int:
    """
    Dispatch scan / verify / pin modes and return a process exit code.
    scan / verify / pin の各モードへ振り分け、終了コードを返す。

    Notes
    -----
    The default mode must stay non-fatal: the setup scripts run it before any
    dependency is installed, so consistency findings are warnings there.
    既定モードは失敗してはならない。セットアップスクリプトが依存導入前に
    実行するため、整合性の指摘はそのモードでは警告に留める。
    """
    parser = argparse.ArgumentParser(
        description="Scan project imports, check dependency consistency, "
                    "and pin verified versions."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verify", action="store_true",
        help="check-only mode: report drift between code imports, pyproject "
             "dependencies, and the installed environment; exit 1 on problems",
    )
    group.add_argument(
        "--pin", action="store_true",
        help="run all consistency checks and the test suite, then regenerate "
             f"{LOCK_FILENAME} from the current environment",
    )
    args = parser.parse_args(argv)

    externals = sorted(collect_external_imports(), key=str.lower)
    print("=== External (non-stdlib) top-level imports ===")
    for m in externals:
        print(m)
    print(f"\nCount: {len(externals)}\n")

    pip_names = pip_names_from_externals(externals)

    if args.verify:
        problems = collect_consistency_problems(pip_names)
        if problems:
            print_problems("\nVERIFY FAILED:", problems)
            return 1
        print("\nVerify: OK (imports, pyproject, and environment are consistent)")
        return 0

    if args.pin:
        problems = collect_consistency_problems(pip_names)
        if problems:
            print_problems("\nPIN ABORTED (fix these before pinning):", problems)
            return 1
        if not run_pytest():
            print("\nPIN ABORTED: test suite failed; lock file not updated.",
                  file=sys.stderr)
            return 1
        req_path = write_requirements(pip_names)
        lock_path = write_lock_file()
        print(f"\nWrote: {req_path}")
        print(f"Wrote: {lock_path} (test-verified pin of the current environment)")
        return 0

    # Default mode: regenerate requirements.txt; report consistency only as
    # warnings, and only when the environment has at least one dependency
    # installed (the setup scripts run this before installing anything).
    # 既定モード: requirements.txt を再生成する。整合性は警告としてのみ報告し、
    # 依存が 1 つも入っていない環境（セットアップスクリプトの導入前実行）では
    # レポート自体を省略する。
    req_path = write_requirements(pip_names)
    print(f"Wrote: {req_path}")
    print("Install: pip install -r requirements.txt")

    if any(installed_version(n) is not None for n in pip_names):
        print()
        problems = report_consistency(pip_names)
        for p in problems:
            print(f"warning: {p}")
        print("\nRun `python check.py --verify` for a CI-style strict check, "
              "or `--pin` to refresh the lock file after tests pass.")
    return 0


if __name__ == "__main__":
    # Script entry point when executed directly.
    sys.exit(main())
