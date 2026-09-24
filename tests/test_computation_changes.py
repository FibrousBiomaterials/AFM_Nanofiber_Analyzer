# -*- coding: utf-8 -*-
"""
Tests for the rule deciding whether an edit changes what a module computes.
編集がモジュールの計算を変えるかどうかを決める規則のテスト。

`scripts/doc_excerpts.computation_changes` is shared by the pre-commit hook,
the CI fingerprint test and the Claude Code reminder hook, so a false positive
here makes people bypass every check at once, and a false negative lets a stale
explanation through.
`scripts/doc_excerpts.computation_changes` は pre-commit フック・CI の指紋検査・
Claude Code の通知フックが共有する。ここでの誤検出は全検査をまとめて迂回させ、
見逃しは古い説明を通してしまう。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))
import doc_excerpts as d  # noqa: E402

BASE = (
    '"""Module."""\n'
    "import numpy as np\n"
    "K = 2\n\n"
    "def f(x):\n"
    '    """Scale."""\n'
    "    return np.abs(x) * K\n\n"
    "class C:\n"
    "    W = 1\n\n"
    "    def run(self, x):\n"
    "        return f(x) + self.W\n"
)
RECORDED = d.code_symbol_digests(BASE)


@pytest.mark.parametrize("name, source", [
    ("comment", BASE.replace("* K", "* K  # scale")),
    ("docstring", BASE.replace('"""Scale."""', '"""Scale by K."""')),
    ("module docstring", BASE.replace('"""Module."""', '"""Another module."""')),
    ("blank lines", BASE.replace("K = 2\n\n", "K = 2\n\n\n\n")),
    ("unused function", BASE + "\n\ndef _helper():\n    return 3\n"),
    ("unused constant", BASE + "\nNEW = 5\n"),
    ("deprecated alias", BASE + '\n_DEPRECATED_ALIASES = {"OLD": ("K", "3.0.0")}\n\n'
                               "def __getattr__(name):\n    return globals()[_DEPRECATED_ALIASES[name][0]]\n"),
    ("unused method", BASE + "\n    def extra(self):\n        return 0\n"),
])
def test_changes_that_cannot_alter_the_computation_pass(name, source):
    assert d.computation_changes(RECORDED, source) == [], name


@pytest.mark.parametrize("source, expected", [
    (BASE.replace("K = 2", "K = 3"), "changed K"),
    (BASE.replace("np.abs(x)", "np.abs(x) + 1"), "changed f"),
    (BASE.replace("import numpy as np", "import cupy as np"), "changed import:np"),
    (BASE.replace("W = 1", "W = 2"), "changed C.W"),
    (BASE.replace("f(x) + self.W", "f(x) - self.W"), "changed C.run"),
    (BASE.replace("class C:", "class C(dict):"), "changed C.<body>"),
    (BASE.replace("K = 2\n", ""), "removed K"),
])
def test_changes_to_existing_code_are_reported(source, expected):
    assert expected in d.computation_changes(RECORDED, source)


def test_a_new_name_existing_code_uses_is_reported():
    """Shadowing a builtin changes unchanged code."""
    base = "def f(x):\n    return abs(x)\n"
    shadowed = base + "\ndef abs(v):\n    return v\n"
    assert d.computation_changes(d.code_symbol_digests(base), shadowed) == [
        "added abs, which existing code refers to"]


def test_a_new_class_existing_code_uses_is_reported():
    base = "def f(x):\n    return Box(x)\n"
    with_class = base + "\nclass Box:\n    pass\n"
    assert any("Box.<body>" in c for c in
               d.computation_changes(d.code_symbol_digests(base), with_class))


def test_a_new_public_definition_other_project_code_calls_is_reported():
    """A detector method the fiber connector calls is part of the analysis."""
    added = BASE + "\n    def public_rule(self, x):\n        return x\n"
    assert d.computation_changes(RECORDED, added, external=set()) == []
    assert d.computation_changes(RECORDED, added, external={"public_rule"}) == [
        "added C.public_rule, which other project code refers to"]
    # A private helper is not callable from elsewhere by contract.
    private = BASE + "\ndef _private(x):\n    return x\n"
    assert d.computation_changes(RECORDED, private, external={"_private"}) == []


def test_the_project_code_scan_stays_out_of_environments():
    paths = d.project_code_paths()
    assert "lib/centerline.py" in paths and "cli.py" in paths
    assert not any(p.startswith((".venv", ".tmp", "tests/", "scripts/")) for p in paths)
