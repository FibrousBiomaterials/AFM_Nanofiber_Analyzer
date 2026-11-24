# -*- coding: utf-8 -*-
"""
Tests for launching a plugin with a path handed to it.
パスを渡してプラグインを起動する処理のテスト。

GUI01 opens GUI02, GUI03 and GUI04 on what it has analyzed through
`afm_nanofiber_analyzer.plugin_launch`, the same code the launcher uses, so the command has to
reach `Main.py`'s ``--run-plugin`` in both a source run and a frozen build, and
the path has to arrive in the plugin's ``sys.argv``.
GUI01 は解析した結果を `afm_nanofiber_analyzer.plugin_launch` で GUI02・GUI03・GUI04 に開かせる。
ランチャーと同じコードであるため、コマンドはソース実行でも凍結ビルドでも
`Main.py` の ``--run-plugin`` に届き、パスはプラグインの ``sys.argv`` に届く
必要がある。
"""

import sys
from pathlib import Path

import Main
from afm_nanofiber_analyzer import plugin_launch

ROOT = Path(__file__).resolve().parent.parent


def test_source_run_goes_through_main_py(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    cmd = plugin_launch.plugin_command("guis.GUI04_Tracking_fiber", ["a b.b2z"])
    assert cmd == [
        sys.executable, str(ROOT / "Main.py"),
        "--run-plugin", "guis.GUI04_Tracking_fiber", "a b.b2z",
    ]


def test_frozen_build_calls_the_executable_itself(monkeypatch, tmp_path):
    exe = tmp_path / "Main.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    cmd = plugin_launch.plugin_command("guis.GUI03_Fiber_Morphology_Statistics", [tmp_path])
    assert cmd == [
        str(exe), "--run-plugin", "guis.GUI03_Fiber_Morphology_Statistics",
        str(tmp_path),
    ]
    assert plugin_launch.app_base_dir() == tmp_path.resolve()


def test_main_hands_the_arguments_after_the_module_to_the_plugin(monkeypatch):
    seen = []
    monkeypatch.setattr(Main, "_run_plugin_and_exit", lambda m, a=(): seen.append((m, list(a))))
    monkeypatch.setattr(
        sys, "argv", ["Main.py", "--run-plugin", "guis.GUI02_PlotProfiler", "x.b2z"],
    )
    Main.main()
    assert seen == [("guis.GUI02_PlotProfiler", ["x.b2z"])]


def test_paths_travel_through_a_list_file(tmp_path):
    """
    A list file carries any number of paths, non-ASCII ones included, and is removed once read.
    一覧ファイルは任意の数のパスを運ぶ。非 ASCII のパスも運び、読んだら消える。

    A command line holds a limited number of characters, so GUI01 and GUI05
    hand GUI03 its bundles through a file; paths given as plain arguments are
    read by the same call.
    コマンドラインに入る文字数には上限があるため、GUI01 と GUI05 は GUI03 へ
    バンドルをファイルで渡す。パスをそのまま引数に書いた場合も、同じ呼び出しで読む。
    """
    paths = [str(tmp_path / ("scan %03d 試料.b2z" % i)) for i in range(400)]
    args = plugin_launch.path_list_arguments(paths)
    assert args[0] == plugin_launch.PATH_LIST_FLAG and len(args) == 2
    assert Path(args[1]).is_file()
    # Longer than a Windows command line can be.
    # Windows のコマンドラインに入る長さを超えている。
    assert sum(len(p) + 1 for p in paths) > 32767

    assert plugin_launch.read_path_arguments(["first.b2z"] + args + ["last.b2z"]) == (
        ["first.b2z"] + paths + ["last.b2z"])
    assert not Path(args[1]).exists()

    # A list file that is gone contributes nothing; plain arguments still arrive.
    # 無くなった一覧ファイルは何も加えない。そのままの引数は届く。
    assert plugin_launch.read_path_arguments(args + ["plain.b2z"]) == ["plain.b2z"]
    assert plugin_launch.read_path_arguments([]) == []


class _FakeWindow:
    """Window that maps after a number of polls, recording scheduled calls."""

    def __init__(self, mapped_after):
        self.polls = 0
        self.mapped_after = mapped_after
        self.pending = []

    def winfo_ismapped(self):
        self.polls += 1
        return self.polls > self.mapped_after

    def after_idle(self, fn):
        self.pending.append(fn)

    def after(self, _ms, fn):
        self.pending.append(fn)

    def run(self):
        while self.pending:
            self.pending.pop(0)()


def test_handed_over_file_opens_only_once_the_window_is_shown():
    """
    A dialog raised before the window is mapped would leave it hidden.
    ウインドウの表示前にダイアログを出すと、ウインドウは隠れたままになる。
    """
    window = _FakeWindow(mapped_after=3)
    opened = []
    plugin_launch.call_when_shown(window, opened.append, "scan.b2z")
    window.run()
    assert opened == ["scan.b2z"]
    assert window.polls == 4
