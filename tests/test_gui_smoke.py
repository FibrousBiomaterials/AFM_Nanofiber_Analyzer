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


def test_gui04_exclusion_controls_start_disabled(tk_app):
    """
    Undo, the settings window, and save are disabled on a clean start.
    起動直後は取消・設定ウインドウ・保存のいずれも無効になっている。

    Undo and the settings window act on the exclusion set, and save follows
    the unsaved flag; with nothing excluded and nothing pending, all three can
    only report that there is nothing to do.
    取消と設定ウインドウは除外集合に対する操作、保存は未保存フラグに従う。除外
    も保留中の変更も無い状態では、3 つとも「対象が無い」としか返せない。
    """
    app = tk_app(gui04.App)
    assert app._excluded_records == []
    assert app._exclusions_dirty is False
    assert str(app._btn_undo_exclusion.cget("state")) == "disabled"
    assert str(app._btn_manage_exclusions.cget("state")) == "disabled"
    assert str(app._btn_save_exclusions.cget("state")) == "disabled"


class _StubFiber:
    """Minimal stand-in carrying only what exclusion and drawing code reads."""

    def __init__(self, x0, y0):
        self.data = (x0, y0, 2, 2, None)
        self.xtrack = np.array([0, 1], dtype=int)
        self.ytrack = np.array([0, 0], dtype=int)


class _StubImage:
    """Minimal stand-in exposing the calibrated image the overview needs."""

    def __init__(self):
        self.calibrated_image = np.zeros((8, 8), dtype=float)


def test_gui04_overview_is_numbered_from_the_displayed_fibers(tk_app, monkeypatch):
    """
    Excluding a fiber renumbers the overview labels with the fiber table.
    ファイバーを除外すると、全体像のラベルも一覧テーブルと同じ採番になる。

    The overview shortcut draws every fiber with its position in
    `current_fibers`, which is the right numbering only while nothing narrows
    the population. Exclusions narrow it without setting the filter flags, so
    without this the labels would keep counting the excluded fibers and stop
    naming the same objects as the table rows.
    全体像のショートカットは全ファイバーを `current_fibers` 内の位置で描画する。
    この番号が正しいのは母集団が絞られていない場合だけである。除外はフィルター
    フラグを立てずに母集団を絞るため、この対応が無いとラベルは除外分を数え続け、
    テーブルの行と同じ対象を指さなくなる。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    app.current_fibers = [_StubFiber(0, 0), _StubFiber(4, 0), _StubFiber(0, 4)]

    calls = []
    monkeypatch.setattr(
        app, "_draw_overview_background",
        lambda **kwargs: calls.append(kwargs),
    )

    app._rebuild_overview_artists()
    assert calls[-1].get("labeled_fibers") is None, (
        "with nothing excluded the overview draws every fiber as-is"
    )

    # Exclude the middle fiber by an anchor on its track.
    # 中央のファイバーを、そのトラック上のアンカーで除外する。
    app._excluded_records = [{"x": 4, "y": 0, "note": ""}]
    app._rebuild_overview_artists()

    displayed = app._display_fibers()
    assert len(displayed) == 2
    assert calls[-1]["labeled_fibers"] == list(enumerate(displayed))


def test_gui04_clean_exclusions_leave_without_prompting(tk_app, monkeypatch):
    """With nothing unsaved, leaving a dataset asks nothing."""
    app = tk_app(gui04.App)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("a clean exclusion set must not prompt")

    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", _unexpected)
    assert app._confirm_unsaved_exclusions() is True


def test_gui04_unsaved_exclusions_block_leaving_on_cancel(tk_app, monkeypatch):
    """
    Cancelling the unsaved-exclusion prompt stops the caller from proceeding.
    未保存の除外の確認をキャンセルすると、呼び出し側は処理を続行しない。

    Manual saving is only safe if leaving a dataset cannot silently drop the
    work, so this guard is what every exit path relies on.
    手動保存が成立するのは、データセットからの離脱が作業を黙って捨てない場合に
    限る。全ての離脱経路がこのガードに依存している。
    """
    app = tk_app(gui04.App)
    app._excluded_records = [{"x": 1, "y": 2, "note": ""}]
    app._exclusions_dirty = True

    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", lambda *a, **k: None)
    assert app._confirm_unsaved_exclusions() is False
    # Cancelling keeps the work pending rather than resolving it either way.
    # キャンセルは、どちらにも決着させず作業を保留のまま残す。
    assert app._exclusions_dirty is True

    # Declining discards the change and lets the caller proceed.
    # 「いいえ」は変更を破棄し、呼び出し側の処理を続行させる。
    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", lambda *a, **k: False)
    assert app._confirm_unsaved_exclusions() is True
    assert app._exclusions_dirty is False


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
        lambda paths, param, unit, **kwargs: ([1.0, 2.0, 3.0], None, 3, 1, []),
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
        "input_mode": gui03.INPUT_BUNDLE,
        "apply_exclusions": False,
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
