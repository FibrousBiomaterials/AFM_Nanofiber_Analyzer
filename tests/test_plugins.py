# -*- coding: utf-8 -*-
"""
Static contract tests for GUI plugin files under guis/.
guis/ 配下の GUI プラグインファイルに対する静的契約テスト。

The launcher (Main.py) discovers plugins by scanning guis/*.py and reading
PLUGIN_INFO with ast.literal_eval, without importing the modules. These tests
enforce that contract statically, so a plugin that violates it fails in CI
instead of degrading silently in the launcher. No plugin module is imported
here; everything is checked on the parsed source.
ランチャー (Main.py) は guis/*.py を走査し、モジュールを import せずに
ast.literal_eval で PLUGIN_INFO を読み取る。本テストはその契約を静的に
強制し、契約違反のプラグインがランチャー上で静かに劣化する代わりに CI で
失敗するようにする。プラグインモジュールは import せず、パース済み
ソースのみを検査する。
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIS_DIR = PROJECT_ROOT / "guis"

PLUGIN_FILES = sorted(
    p for p in GUIS_DIR.glob("*.py") if p.name != "__init__.py"
)


def _parse(py_file: Path) -> ast.Module:
    """Parse a plugin source file into an AST module."""
    return ast.parse(py_file.read_text(encoding="utf-8"))


def _plugin_info_node(tree: ast.Module):
    """Return the top-level `PLUGIN_INFO = ...` assignment node, or None."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "PLUGIN_INFO":
                return node
    return None


def _is_main_guard(node: ast.stmt) -> bool:
    """Return True for an `if __name__ == "__main__":` block."""
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def test_plugin_files_exist():
    """guis/ must contain at least the four shipped plugin files."""
    assert len(PLUGIN_FILES) >= 4, f"expected >= 4 plugins, found {PLUGIN_FILES}"


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_info_is_literal_dict(py_file):
    """PLUGIN_INFO must be a top-level dict readable by ast.literal_eval."""
    node = _plugin_info_node(_parse(py_file))
    assert node is not None, "PLUGIN_INFO is not defined at module top level"
    # Raises ValueError if the dict contains non-literal values such as _().
    # _() などのリテラル以外の値が含まれると ValueError になる。
    info = ast.literal_eval(node.value)
    assert isinstance(info, dict), "PLUGIN_INFO must be a dict literal"


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_info_required_fields(py_file):
    """PLUGIN_INFO must provide non-empty 'name' and 'description' strings."""
    node = _plugin_info_node(_parse(py_file))
    assert node is not None, "PLUGIN_INFO is not defined at module top level"
    info = ast.literal_eval(node.value)
    for key in ("name", "description"):
        assert key in info, f"PLUGIN_INFO is missing the '{key}' key"
        assert isinstance(info[key], str), f"PLUGIN_INFO['{key}'] must be str"
        assert info[key].strip(), f"PLUGIN_INFO['{key}'] must not be empty"


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_info_order_key_type(py_file):
    """The optional 'order' key, when present, must be an int or float.

    The launcher sorts buttons by this value (smaller first); plugins
    without it keep filename order. Unknown keys are ignored, so only the
    type of the reserved key is enforced here.
    """
    node = _plugin_info_node(_parse(py_file))
    assert node is not None, "PLUGIN_INFO is not defined at module top level"
    info = ast.literal_eval(node.value)
    if "order" in info:
        assert isinstance(info["order"], (int, float)) and not isinstance(
            info["order"], bool
        ), "PLUGIN_INFO['order'] must be an int or float"


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_defines_main(py_file):
    """Each plugin must define a top-level main() entry point."""
    tree = _parse(py_file)
    main_defs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert main_defs, "no top-level main() function is defined"
    assert not main_defs[0].args.args, "main() must take no arguments"


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_has_main_guard(py_file):
    """GUI launch must be guarded behind `if __name__ == "__main__":`."""
    tree = _parse(py_file)
    assert any(_is_main_guard(node) for node in tree.body), (
        'no `if __name__ == "__main__":` guard found'
    )


@pytest.mark.parametrize("py_file", PLUGIN_FILES, ids=lambda p: p.name)
def test_plugin_does_not_launch_at_import(py_file):
    """Module top level must not call main() or mainloop() unguarded.

    The launcher imports plugin modules in a child process before calling
    main(); an unguarded launch call would open a window at import time.
    ランチャーは子プロセスで main() 呼び出し前にプラグインを import する。
    ガード外の起動呼び出しは import 時点でウィンドウを開いてしまう。
    """
    tree = _parse(py_file)
    for node in tree.body:
        # Calls inside function/class bodies run only when invoked, and the
        # __main__ guard never runs under the launcher's import.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _is_main_guard(node):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if isinstance(func, ast.Name) and func.id == "main":
                pytest.fail("main() is called unguarded at module top level")
            if isinstance(func, ast.Attribute) and func.attr == "mainloop":
                pytest.fail("mainloop() is called unguarded at module top level")
