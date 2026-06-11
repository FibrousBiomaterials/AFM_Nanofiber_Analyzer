"""
Scan Python files and generate a minimal `requirements.txt`.
Python ファイルを走査し、最小限の `requirements.txt` を生成する。

This module is also used as a utility provider for `build.py`:
`IMPORT_TO_PIP`, `is_stdlib`, `top_level`, `extract_imports`, and
`iter_py_files` are imported from build.py to avoid duplicated logic.
このモジュールは `build.py` のユーティリティ提供元としても使われる：
`IMPORT_TO_PIP` / `is_stdlib` / `top_level` / `extract_imports` /
`iter_py_files` は build.py から import され、ロジック重複を避ける。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Runtime entry-point files to scan for `requirements.txt`.
TARGET_FILES = [ROOT / "Main.py"]

# Runtime package directories to scan for `requirements.txt`.
TARGET_DIRS = [ROOT / "guis", ROOT / "lib"]

# Ignore local project packages from external dependency list.
IGNORE_TOPLEVEL = {"guis", "lib"}

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
PACKAGE_CONSTRAINTS = {}


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
    # Resolve known import-name/package-name mismatches first.
    pip_name = IMPORT_TO_PIP.get(import_name, import_name)
    pip_name = PACKAGE_CONSTRAINTS.get(pip_name, pip_name)
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


def main() -> None:
    """
    Run dependency scan and write `requirements.txt`.
    依存パッケージを走査して `requirements.txt` を生成する。

    Notes
    -----
    Prints summary to console and writes file to project root.
    コンソールに要約を表示し、プロジェクトルートへファイルを書き出す。
    """
    externals = sorted(collect_external_imports(), key=str.lower)

    # Print human-readable summary to terminal.
    print("=== External (non-stdlib) top-level imports ===")
    for m in externals:
        print(m)
    print(f"\nCount: {len(externals)}")

    # Normalize to pip names and write deterministic requirements.txt.
    reqs = sorted({normalize_pip_name(m) for m in externals}, key=str.lower)
    req_path = ROOT / "requirements.txt"
    req_path.write_text("\n".join(reqs) + ("\n" if reqs else ""), encoding="utf-8")

    print(f"\nWrote: {req_path}")
    print("Install: pip install -r requirements.txt")


if __name__ == "__main__":
    # Script entry point when executed directly.
    main()
