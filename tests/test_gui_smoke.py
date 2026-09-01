# -*- coding: utf-8 -*-
"""
Construction smoke tests for the four GUI plugins.
4 つの GUI プラグインの構築スモークテスト。

Each test builds the plugin's window, lets Tk lay the widgets out, and destroys
it. That is deliberately all it asserts: the widget tree, its labels, and its
layout are free to change, and a test that pinned them down would fail on every
cosmetic edit. What it does catch is the largest class of real GUI regressions
— the window no longer builds at all, because an option name is wrong, an asset
is missing, a callback is misspelled, or a `lib.ui_tools` helper changed shape.
各テストはウィンドウを構築し、Tk にレイアウトさせ、破棄する。検証をこれだけに
留めるのは意図的で、ウィジェット構成・ラベル・レイアウトは自由に変更されるため、
それらを固定するテストは見た目の変更のたびに壊れる。一方でこのテストは、実際に
起こる GUI リグレッションの最大の類型——オプション名の誤り、アセットの欠落、
コールバック名の typo、`lib.ui_tools` ヘルパーのシグネチャ変更などにより
ウィンドウがそもそも構築できない——を確実に捕捉する。
"""

import numpy as np
import pytest

from conftest import requires_tk

import guis.GUI01_Image_Preprocessor as gui01
import guis.GUI02_PlotProfiler as gui02
import guis.GUI03_Fiber_Height_Histogram as gui03
import guis.GUI04_Tracking_fiber as gui04

pytestmark = requires_tk


@pytest.fixture
def isolated_gui01_settings(tmp_path, monkeypatch):
    """
    Redirect GUI01's startup settings file into a temporary directory.
    GUI01 の起動時設定ファイルを一時ディレクトリへ退避させる。

    `load_or_create_startup_params` writes `guis/afmpp_settings.json` when it is
    missing, so constructing the app in a test would otherwise create or
    overwrite the developer's own local settings.
    `load_or_create_startup_params` は設定ファイルが無ければ
    `guis/afmpp_settings.json` を作成するため、退避しないとテストが開発者の
    ローカル設定を作成・上書きしてしまう。
    """
    settings = tmp_path / "afmpp_settings.json"
    monkeypatch.setattr(gui01, "_settings_path", lambda: str(settings))
    return settings


def _assert_window_built(app) -> None:
    """Assert that the window exists and actually built a widget tree."""
    assert app.winfo_exists()
    assert app.title()
    assert app.winfo_children(), "the window built no widgets"


def test_gui01_window_builds(tk_app, isolated_gui01_settings):
    _assert_window_built(tk_app(gui01.App))


def test_gui02_window_builds(tk_app):
    _assert_window_built(tk_app(gui02.App))


def test_gui03_window_builds(tk_app):
    _assert_window_built(tk_app(gui03.App))


def test_gui04_window_builds(tk_app):
    _assert_window_built(tk_app(gui04.App))


def test_gui03_worker_stops_when_bin_edges_fail(tk_app, tmp_path, monkeypatch):
    """
    A failure building the bin edges reports once and ends the worker.
    ビン境界の生成に失敗したとき、1 回だけ報告してワーカーを終了する。

    This one worker path is worth pinning because its failure is invisible:
    the fatal message reaches the user either way, so an unhandled exception
    raised afterwards would only surface on stderr, which a windowed or frozen
    build does not show.
    このワーカー経路だけを固定するのは、失敗が目に見えないため。fatal 通知は
    どちらにせよユーザーへ届くので、その後に送出される未処理例外は stderr に
    しか現れず、ウィンドウアプリや凍結ビルドでは表示されない。
    """
    app = tk_app(gui03.App)

    folder = tmp_path / "bundles"
    folder.mkdir()
    # _find_pairs only filters on the extension; the contents never get read
    # because _collect_bundle_values is replaced below.
    (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")

    monkeypatch.setattr(
        app, "_collect_bundle_values",
        lambda paths, param, unit: ([1.0, 2.0, 3.0], None, 3, 1, []),
    )

    def _raise(*_args, **_kwargs):
        raise MemoryError("simulated allocation failure")

    monkeypatch.setattr(gui03.np, "arange", _raise)

    app._worker_run({
        "groups": [{
            "id": "g", "name": "G", "color": "#1f77b4",
            "folders": [str(folder)],
        }],
        "param": gui03.PARAM_HEIGHT,
        "unit": gui03.UNIT_PIXEL,
        "min_h": 0.0, "max_h": 10.0, "step": 0.2,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    kinds = []
    while not app.ui_queue.empty():
        kinds.append(app.ui_queue.get_nowait()[0])

    assert kinds.count("fatal") == 1
    assert "done" not in kinds


def test_gui03_non_fatal_notices_stay_in_the_log(tk_app, silence_dialogs):
    """
    A completed run reports its notices in the log and opens no dialog.
    完了した実行は通知をログに出し、ダイアログを開かない。

    Most notices are routine — samples outside the plotted range, a group too
    small for a histogram shape — so a modal dialog would interrupt every run
    and stop being read. The log panel is always on screen and carries the
    same text.
    通知の大半は日常的なもの（描画範囲外の標本、ヒストグラムの形が読めない小さな
    グループ）であり、モーダルダイアログは毎回の実行を中断させ、やがて読まれなく
    なる。ログ欄は常に画面上にあり、同じ本文を表示する。
    """
    app = tk_app(gui03.App)
    dialogs = silence_dialogs(gui03)

    counts = np.array([2, 1], dtype=float)
    app._handle_done({
        "results": [{
            "id": "g", "name": "G", "color": "#1f77b4",
            "values": np.array([1.0, 2.0, 3.0]), "weights": None,
            "mean": 2.0, "std": 0.8, "median": 2.0, "q1": 1.5, "q3": 2.5,
            "n_samples": 3.0, "n_raw": 3, "n_fibers": 3, "n_images": 1,
            "counts": counts, "total": float(counts.sum()), "mode": 1.5,
        }],
        "edges": np.array([0.0, 1.0, 2.0]),
        "param": gui03.PARAM_HEIGHT,
        "unit": gui03.UNIT_FIBER,
        "yaxis_mode": "density",
        "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
        "errors": ["notice one", "notice two"],
    })

    assert dialogs == []
    log = app.log_text.get("1.0", "end")
    assert "notice one" in log
    assert "notice two" in log
