"""
Cache folders for analyzed bundles, keyed by the code and libraries that made them.
解析済みバンドルのキャッシュフォルダ。作ったコードとライブラリで区別する。

The documentation experiments (`scripts/measure_docs.py`) and the kink
reference score (`scripts/kink_reference_score.py`) analyze the bundled scans
and synthetic inputs once and reuse the bundles. A bundle reused after the
analysis code changed reports what the old code computed while the recording
names the new code, so every cache lives in a folder named by `fingerprint`:
a change to what the analysis computes, to the code that generates the
synthetic inputs, or to a numerical library selects a new, empty folder, and
the bundles are made again. `cache_root` removes the folders of every other
fingerprint, which no run can use any more.
文書用の実験（`scripts/measure_docs.py`）とキンクの基準照合
（`scripts/kink_reference_score.py`）は、同梱スキャンと合成入力を一度だけ解析して
バンドルを使い回す。解析コードが変わった後に使い回したバンドルは、記録上は新しい
コードを名乗りながら古いコードの計算結果を報告する。そこでキャッシュはすべて
`fingerprint` の名前のフォルダに置く。解析の計算、合成入力を作るコード、数値計算
ライブラリのどれかが変わると新しい空のフォルダが選ばれ、バンドルは作り直される。
`cache_root` は、どの実行からももう使われない他の指紋のフォルダを消す。
"""

# ===== Standard library =====
import ast
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import doc_excerpts  # noqa: E402

# The pipeline driver; every analysis module a bundle depends on is reached
# from it through its imports.
# パイプラインの実行モジュール。バンドルが依存する解析モジュールはすべて、
# ここから import をたどって到達する。
PIPELINE_ROOTS = ("lib/pipeline.py",)

# Code outside lib/ that writes cached inputs: the synthetic suite and the
# synthetic fiber of the test fixtures.
# lib/ の外でキャッシュされる入力を書くコード。合成スイートと、テストの
# フィクスチャの合成繊維。
INPUT_GENERATORS = ("scripts/synthetic_suite.py", "tests/conftest.py")

# Numerical libraries whose results reach a bundle, by import name.
# 結果がバンドルに届く数値計算ライブラリ（import 名）。
LIBRARIES = ("numpy", "scipy", "skimage", "cv2", "lmfit", "blosc2")

# A cache folder name: the first characters of the fingerprint.
# キャッシュフォルダの名前。指紋の先頭の文字列。
FINGERPRINT_LENGTH = 12
_FOLDER_RE = re.compile(rf"[0-9a-f]{{{FINGERPRINT_LENGTH}}}")


def _lib_imports(rel: str) -> List[str]:
    """
    List the lib modules one module imports, as repository paths.
    1 つのモジュールが import する lib モジュールを、リポジトリのパスで列挙する。
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                if node.module:
                    out.append(f"lib/{node.module.replace('.', '/')}.py")
                else:
                    out += [f"lib/{a.name}.py" for a in node.names]
            elif node.module and node.module.startswith("lib"):
                if node.module == "lib":
                    out += [f"lib/{a.name}.py" for a in node.names]
                else:
                    out.append(node.module.replace(".", "/") + ".py")
        elif isinstance(node, ast.Import):
            out += [a.name.replace(".", "/") + ".py" for a in node.names
                    if a.name.startswith("lib.")]
    return [p for p in out if (ROOT / p).is_file()]


def closure(roots: Sequence[str]) -> List[str]:
    """
    List every lib module the given modules reach through their imports.
    指定したモジュールから import をたどって到達する lib モジュールをすべて列挙する。
    """
    seen: set = set()
    todo = list(roots)
    while todo:
        rel = todo.pop()
        if rel in seen or not (ROOT / rel).is_file():
            continue
        seen.add(rel)
        todo += _lib_imports(rel)
    return sorted(seen)


def library_versions() -> Dict[str, str]:
    """
    Report the version of each library in `LIBRARIES` and of Python.
    `LIBRARIES` の各ライブラリと Python のバージョンを返す。
    """
    import importlib
    versions = {"python": sys.version.split()[0]}
    for name in LIBRARIES:
        try:
            versions[name] = str(getattr(importlib.import_module(name), "__version__", "unknown"))
        except ImportError:
            versions[name] = "absent"
    return versions


def fingerprint_of(code: Dict[str, Dict[str, str]], versions: Dict[str, str]) -> str:
    """
    Combine per-definition code digests and library versions into a folder name.
    定義ごとのコードの指紋とライブラリのバージョンを、フォルダ名にまとめる。

    Parameters
    ----------
    code
        `doc_excerpts.code_symbol_digests` per repository path. Comments and
        docstrings do not enter these digests, so editing them keeps the cache.
        リポジトリのパスごとの `doc_excerpts.code_symbol_digests`。コメントと
        docstring はこの指紋に入らないので、それらを直してもキャッシュは保たれる。
    versions
        Library name to version string.
        ライブラリ名からバージョン文字列への対応。

    Returns
    -------
    str
        `FINGERPRINT_LENGTH` hexadecimal characters.
        `FINGERPRINT_LENGTH` 文字の 16 進文字列。
    """
    payload = json.dumps({"code": code, "versions": versions}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def fingerprint() -> str:
    """
    Fingerprint the code and libraries that cached bundles are made with.
    キャッシュするバンドルを作るコードとライブラリの指紋を取る。
    """
    paths = closure(PIPELINE_ROOTS) + [p for p in INPUT_GENERATORS if (ROOT / p).is_file()]
    code = {rel: doc_excerpts.code_symbol_digests((ROOT / rel).read_text(encoding="utf-8"))
            for rel in sorted(paths)}
    return fingerprint_of(code, library_versions())


def cache_root(base: Path, current: Optional[str] = None) -> Path:
    """
    Return the cache folder of the current fingerprint under `base`.
    `base` の下にある、今の指紋のキャッシュフォルダを返す。

    Folders under `base` named by any other fingerprint are removed; other
    files and folders there are left alone.
    `base` の下の、他の指紋の名前のフォルダは消す。それ以外のファイルや
    フォルダには触れない。

    Parameters
    ----------
    base
        Folder that holds one subfolder per fingerprint.
        指紋ごとのサブフォルダを置くフォルダ。
    current
        Fingerprint to use; ``None`` computes it with `fingerprint`.
        使う指紋。``None`` なら `fingerprint` で計算する。

    Returns
    -------
    Path
        ``base / current``, created if missing.
        ``base / current``。無ければ作る。
    """
    current = current or fingerprint()
    base = Path(base)
    if base.is_dir():
        for child in base.iterdir():
            if child.is_dir() and _FOLDER_RE.fullmatch(child.name) and child.name != current:
                shutil.rmtree(child)
    folder = base / current
    folder.mkdir(parents=True, exist_ok=True)
    return folder
