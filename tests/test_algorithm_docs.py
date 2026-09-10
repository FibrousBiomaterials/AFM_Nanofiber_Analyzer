# -*- coding: utf-8 -*-
"""
Keep `docs/algorithms.md` honest about the code it describes.
`docs/algorithms.md` の記述をコード側と一致させ続けるためのテスト。

The algorithm document explains what background calibration, binarization,
skeletonization, and kink detection do, referencing the source by symbol name.
Prose has no compiler, so three mechanical checks stand in for one:
アルゴリズム解説文書は、背景補正・二値化・細線化・キンク検出の内容をシンボル名
でソースを参照しながら説明する。散文にはコンパイラが無いため、代わりに 3 つの
機械的検査を置く。

1. Every project symbol the document names still exists. This catches a rename
   or removal immediately and needs no manual bookkeeping.
2. Every user-settable parameter is documented, so a new `ProcParams` field
   cannot ship without an explanation.
3. The code of the four algorithm modules is fingerprinted with comments and
   docstrings removed. A change to what the code *computes* fails this test
   until the document has been reviewed and the fingerprint updated; a change
   to comments, docstrings, or formatting does not.

Check 3 is a tripwire, not a proof: nothing forces the person updating the
fingerprint to have actually reread the document. It exists so a change to the
algorithms cannot pass through *unnoticed*, which is the failure mode that
turns documentation into fiction. The rule that the document is updated as part
of such a change lives in `AGENTS.md` section 8.13.
検査 3 は proof ではなく tripwire である。指紋を更新する人が実際に文書を読み
直したことを強制するものではない。アルゴリズムの変更が *気づかれずに* 通過する
ことを防ぐためにあり、それこそが文書を虚構に変える失敗様式である。そうした変更
の一部として文書を更新するという規則は `AGENTS.md` 8.13 節にある。

Regenerate the fingerprints after reviewing the document:
文書を見直したうえで指紋を再生成するには:

    .venv\\Scripts\\python.exe tests\\test_algorithm_docs.py --update
"""

import ast
import dataclasses
import hashlib
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOC_EN = PROJECT_ROOT / "docs" / "algorithms.md"
DOC_JA = PROJECT_ROOT / "docs" / "algorithms.ja.md"
MANIFEST = Path(__file__).with_name("algorithm_doc_manifest.json")
LIB_DIR = PROJECT_ROOT / "lib"

# The four stages the document explains. A change inside one of these is what
# the fingerprint check reacts to.
# 文書が説明する 4 ステージ。指紋検査が反応するのはこれらの内部変更である。
ALGORITHM_MODULES = (
    "lib/bg_calibrator.py",
    "lib/segmenter.py",
    "lib/skeletonizer.py",
    "lib/kink_detector.py",
)

# A backticked span that is a dotted Python path, e.g. `Segmenter._binaryzation`
# or `bg_calibrator.BG_METHOD_NAMES`.
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
# A backticked span that is a single snake_case identifier, e.g. `mask_dilation`
# or `_extract_fiber`. The underscore requirement is what keeps ordinary prose
# in backticks (`trendfill`, `tophat`, `nm`) out of the check.
# 単一の snake_case 識別子。アンダースコアを必須にすることで、バッククォート内の
# 通常の語（`trendfill`、`tophat`、`nm`）を検査対象から外す。
_SNAKE = re.compile(r"^_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+_?$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _iter_code_spans(text: str) -> list[str]:
    """
    Yield the contents of every inline code span, skipping fenced blocks.
    フェンス付きブロックを除き、各インラインコードスパンの内容を返す。
    """
    spans: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        spans.extend(_CODE_SPAN.findall(line))
    return spans


def _index_lib() -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """
    Index every name defined under `lib/`, without importing anything.
    `lib/` 配下で定義された名前を、import せずに索引化する。

    Returns
    -------
    tuple
        ``(module_names, class_names, all_names)`` mapping module stem to its
        top-level names, class name to its attributes, and the flat union of
        every name including function parameters.
        ``(module_names, class_names, all_names)``。モジュール名 → トップレベル
        名、クラス名 → 属性、および関数引数を含む全名称の平坦な和集合。

    Notes
    -----
    Parsing rather than importing keeps this test independent of optional and
    heavy dependencies: `lib.ui_tools` imports tkinter at module level, which is
    absent on headless runners.
    import ではなく解析するのは、任意依存・重量依存からテストを独立させるため
    である。`lib.ui_tools` はモジュールレベルで tkinter を import するが、
    ヘッドレス環境には存在しない。
    """
    modules: dict[str, set[str]] = {}
    classes: dict[str, set[str]] = {}
    everything: set[str] = set()

    for path in sorted(LIB_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                top.add(node.name)
            elif isinstance(node, ast.Assign):
                top.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                top.add(node.target.id)
        modules[path.stem] = top
        everything |= top

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                attrs = classes.setdefault(node.name, set())
                for item in ast.walk(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        attrs.add(item.name)
                        continue
                    if isinstance(item, ast.AnnAssign):
                        targets = [item.target]
                    elif isinstance(item, ast.Assign):
                        targets = list(item.targets)
                    else:
                        continue
                    for target in targets:
                        if isinstance(target, ast.Name):
                            attrs.add(target.id)
                        # `self.foo = ...` and `self.foo: T = ...` inside a
                        # method both declare an attribute; the annotated form
                        # is how `ProcessedImage` declares every stage output.
                        # メソッド内の `self.foo = ...` と `self.foo: T = ...`
                        # はどちらも属性の宣言であり、`ProcessedImage` は各段の
                        # 出力を注釈付きの形で宣言している。
                        elif (isinstance(target, ast.Attribute)
                              and isinstance(target.value, ast.Name)
                              and target.value.id == "self"):
                            attrs.add(target.attr)
                everything |= attrs
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    everything.add(arg.arg)

    return modules, classes, everything


def _unresolved_symbols(text: str) -> list[str]:
    """
    Return the project symbols the document names that no longer exist.
    文書が名指ししているが既に存在しないプロジェクトシンボルを返す。

    Notes
    -----
    A dotted span is checked only when its first component is a `lib/` module or
    a class defined there; anything else is a third-party reference such as
    `skimage.filters.threshold_local` and is out of scope. A bare snake_case
    span is checked against the flat name index. Both rules are conservative by
    design: they never invent a requirement the document did not make, so a
    failure always means a real reference went stale.
    ドット付きスパンは、先頭要素が `lib/` のモジュールかそこで定義されたクラスの
    場合にのみ検査する。それ以外は `skimage.filters.threshold_local` のような
    サードパーティ参照であり対象外である。素の snake_case スパンは平坦な名称索引
    と照合する。どちらの規則も意図的に保守的であり、文書がしていない要求を作り
    出さない。したがって失敗は常に実在の参照が陳腐化したことを意味する。
    """
    modules, classes, everything = _index_lib()
    missing: list[str] = []

    for span in _iter_code_spans(text):
        if _DOTTED.match(span):
            head, second, *rest = span.split(".")
            if head in modules:
                if second not in modules[head]:
                    missing.append(span)
                elif rest and second in classes and rest[0] not in classes[second]:
                    missing.append(span)
            elif head in classes and second not in classes[head]:
                missing.append(span)
        elif _SNAKE.match(span) and span not in everything:
            missing.append(span)

    return sorted(set(missing))


def _code_digest(path: Path) -> str:
    """
    Fingerprint one module's code, ignoring comments, docstrings, and layout.
    コメント・docstring・体裁を無視して 1 モジュールのコードを指紋化する。

    Notes
    -----
    Comments are removed through `tokenize` rather than a regular expression,
    so a ``#`` inside a string literal is left alone. Docstrings are located by
    line number through `ast`. Both are stable across Python versions, unlike
    `ast.dump`, whose node fields change between releases and would make the
    fingerprint disagree between the two interpreters in the CI matrix.
    コメントの除去は正規表現ではなく `tokenize` を使うため、文字列リテラル内の
    ``#`` は影響を受けない。docstring は `ast` で行番号から特定する。どちらも
    Python バージョン間で安定している。一方 `ast.dump` はリリース間でノード
    フィールドが変わり、CI マトリクスの 2 つの処理系で指紋が食い違ってしまう。
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    # Truncate each line at the start of its comment, in place.
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            lines[row - 1] = lines[row - 1][:col]

    docstring_lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstring_lines.update(range(body[0].lineno, body[0].end_lineno + 1))

    kept = [
        line.rstrip()
        for number, line in enumerate(lines, start=1)
        if number not in docstring_lines and line.strip()
    ]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def _current_digests() -> dict[str, str]:
    return {rel: _code_digest(PROJECT_ROOT / rel) for rel in ALGORITHM_MODULES}


def _headings(text: str) -> list[str]:
    """Return the ``#`` prefix of every heading, outside fenced code blocks."""
    levels: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#"):
            levels.append(line.split(" ", 1)[0])
    return levels


@pytest.fixture(scope="module")
def doc_en() -> str:
    return DOC_EN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc_ja() -> str:
    return DOC_JA.read_text(encoding="utf-8")


def test_algorithm_documents_exist():
    """Both language versions of the algorithm document are present."""
    assert DOC_EN.is_file(), f"{DOC_EN} is missing"
    assert DOC_JA.is_file(), f"{DOC_JA} is missing"


@pytest.mark.parametrize("language", ["en", "ja"])
def test_documented_symbols_exist(language, doc_en, doc_ja):
    """Every project symbol the document names still exists in the source."""
    text = doc_en if language == "en" else doc_ja
    missing = _unresolved_symbols(text)
    assert not missing, (
        "docs/algorithms"
        + ("" if language == "en" else ".ja")
        + ".md references symbols that no longer exist: "
        + ", ".join(missing)
        + "\nRename them in the document, or correct the reference."
    )


@pytest.mark.parametrize("language", ["en", "ja"])
def test_every_proc_params_field_is_documented(language, doc_en, doc_ja):
    """
    Every user-settable analysis parameter appears in the document.
    利用者が設定できる解析パラメータがすべて文書に登場する。
    """
    from lib.pipeline import ProcParams

    text = doc_en if language == "en" else doc_ja
    missing = [
        field.name
        for field in dataclasses.fields(ProcParams)
        if not re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(field.name) + r"(?![A-Za-z0-9_])", text
        )
    ]
    assert not missing, (
        "ProcParams fields with no explanation in docs/algorithms"
        + ("" if language == "en" else ".ja")
        + ".md: "
        + ", ".join(missing)
    )


@pytest.mark.parametrize("language", ["en", "ja"])
def test_every_background_method_is_documented(language, doc_en, doc_ja):
    """Each selectable background method has an explanation."""
    from lib.bg_calibrator import BG_METHOD_NAMES, BG_METHOD_REMOVED

    text = doc_en if language == "en" else doc_ja
    missing = [name for name in BG_METHOD_NAMES if name not in text]
    assert not missing, f"undocumented bg_method values: {', '.join(missing)}"
    # A removed method still needs a mention, so a user holding an old
    # `_param.json` learns why the run stops instead of only seeing an error.
    # 削除済みの方式も記載が要る。古い `_param.json` を持つ利用者が、エラー
    # だけを見るのではなく実行が止まる理由を知れるようにするためである。
    missing_removed = [name for name in BG_METHOD_REMOVED if name not in text]
    assert not missing_removed, (
        f"removed bg_method values with no explanation: {', '.join(missing_removed)}"
    )


def test_document_pair_shares_one_structure(doc_en, doc_ja):
    """
    The English and Japanese documents have the same heading skeleton.
    英語版と日本語版の見出し構造が一致する。

    Notes
    -----
    They are a synchronized pair like the README pair, so a section added to one
    and not the other is a synchronization failure, not a translation choice.
    README の対と同様に同期されたペアであるため、片方にだけ節が追加された状態は
    翻訳上の判断ではなく同期漏れである。
    """
    assert _headings(doc_en) == _headings(doc_ja), (
        "docs/algorithms.md and docs/algorithms.ja.md have diverged in "
        "structure; add the corresponding section to the other file."
    )


def test_algorithm_code_matches_documented_fingerprint():
    """
    The four algorithm modules are unchanged since the document was reviewed.
    4 つのアルゴリズムモジュールが、文書の最終確認時から変わっていない。
    """
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))["modules"]
    current = _current_digests()

    moved = sorted(name for name in current if recorded.get(name) != current[name])
    assert not moved, (
        "the code of "
        + ", ".join(moved)
        + " changed since docs/algorithms.md was last reviewed.\n"
        "Review the affected sections of docs/algorithms.md and "
        "docs/algorithms.ja.md, update them if the explanation no longer "
        "matches, then refresh the fingerprints:\n"
        "    .venv\\Scripts\\python.exe tests\\test_algorithm_docs.py --update"
    )


def _update_manifest() -> None:
    """Rewrite the fingerprint manifest from the current sources."""
    payload = {
        "_comment": (
            "SHA-256 of each algorithm module with comments and docstrings "
            "removed. Refresh with "
            "`python tests/test_algorithm_docs.py --update` only after "
            "reviewing docs/algorithms.md against the change."
        ),
        "modules": _current_digests(),
    }
    MANIFEST.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"updated {MANIFEST}")


if __name__ == "__main__":
    if "--update" in sys.argv[1:]:
        _update_manifest()
    else:
        print(__doc__)
