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

import os

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

    def __init__(self, x0, y0, length=100.0):
        self.data = (x0, y0, 2, 2, None)
        self.xtrack = np.array([0, 1], dtype=int)
        self.ytrack = np.array([0, 0], dtype=int)
        # Reported in the exclusion log line.
        # 除外時のログ行に出力される。
        self.length = length


class _StubImage:
    """Minimal stand-in exposing the calibrated image the overview needs."""

    def __init__(self):
        self.calibrated_image = np.zeros((8, 8), dtype=float)


def test_gui04_overview_is_numbered_from_the_displayed_fibers(tk_app, monkeypatch):
    """
    Excluding a fiber renumbers the overview labels with the fiber table.
    ファイバーを除外すると、全体像のラベルも一覧テーブルと同じ採番になる。

    The overview shortcut draws every fiber with its position in
    `current_fibers`. Exclusions are applied before reconnection, so by the
    time the overview runs they are already out of `current_fibers`; what this
    checks is that the labels still come from `_display_fibers`, the one list
    the table is built from, and that the excluded count reaches the title.
    全体像のショートカットは全ファイバーを `current_fibers` 内の位置で描画する。
    除外は再結合より前に適用されるため、全体像が動く時点で既に `current_fibers`
    から取り除かれている。ここで確認するのは、ラベルが一覧テーブルの構築元と同じ
    `_display_fibers` から採番されること、および除外件数がタイトルへ届くことである。
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

    # The middle fiber was excluded, so the curated population holds the other
    # two and the sidecar keeps its anchor.
    # 中央のファイバーが除外された状態。キュレーション済み母集団には残り 2 本が
    # あり、サイドカーはそのアンカーを保持している。
    app.current_fibers = [_StubFiber(0, 0), _StubFiber(0, 4)]
    app._excluded_records = [{"x": 4, "y": 0, "note": ""}]
    app._rebuild_overview_artists()

    displayed = app._display_fibers()
    assert len(displayed) == 2
    assert calls[-1]["labeled_fibers"] == list(enumerate(displayed))
    assert "1 excluded" in calls[-1]["title_suffix"]


def test_gui04_batch_exclusion_undoes_in_one_press(tk_app, monkeypatch):
    """
    Excluding several selected fibers is taken back by one undo press.
    複数選択したファイバーの除外は、取り消し 1 回でまとめて戻る。

    Debris is judged in groups while looking at the overview, so a mis-click
    must give back the act the user performed, not the last anchor that act
    happened to write.
    ゴミは全体像を見ながらまとめて判断するため、誤クリックの取り消しは、その操作
    がたまたま最後に書いたアンカー 1 件ではなく、ユーザーが行った操作を戻さなけれ
    ばならない。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    fibers = [_StubFiber(0, 0), _StubFiber(4, 0), _StubFiber(0, 4)]
    app.current_fibers = fibers
    app.current_fragments = fibers
    # The rebuild after an exclusion needs a real measurement; this test is
    # about the record bookkeeping, so stub it out.
    # 除外後の再構築は実際の計測を必要とするが、本テストの対象は記録の管理なので
    # その部分は差し替える。
    monkeypatch.setattr(app, "_recurate_population", lambda: None)

    app._sel_indices = [0, 2]
    app._sel_idx = 0
    app._on_exclude_selected()

    assert len(app._excluded_records) == 2
    assert app._exclusion_groups == [2]

    app._on_undo_last_exclusion()

    assert app._excluded_records == []
    assert app._exclusion_groups == []


def test_gui04_reanalysis_keeps_unsaved_exclusions(tk_app, monkeypatch):
    """
    Re-analyzing the loaded dataset carries its exclusions through untouched.
    読み込み済みデータセットの再解析は、その除外に手を触れず引き継ぐ。

    Turning fiber connection on, changing the scale, or editing the connection
    parameters all re-analyze the dataset that is staying loaded. Routing that
    through the dataset-switch path asked whether to save the exclusions first
    and discarded them on "no", so a user who had curated a scan and then
    pressed "ファイバー連結" lost the curation. Saving is a deliberate act, so
    the set lives in memory until the user saves it and a re-analysis must not
    consult the sidecar.
    ファイバー連結の ON、スケール変更、連結パラメータの編集は、いずれも読み込まれた
    ままのデータセットを再解析する。これをデータセット切替の経路に通すと、先に除外を
    保存するか尋ね、「いいえ」で破棄していた。そのため、走査像をキュレーションした
    後に「ファイバー連結」を押したユーザーはその作業を失っていた。保存は意図的な
    操作であり、集合はユーザーが保存するまでメモリ上に存在するので、再解析が
    サイドカーを参照してはならない。
    """
    app = tk_app(gui04.App)
    app.current_stem = "dataset"
    app.current_image = _StubImage()

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("a re-analysis must not prompt about exclusions")

    monkeypatch.setattr(app, "_confirm_unsaved_exclusions", _unexpected)
    started = []
    monkeypatch.setattr(
        app, "_start_analysis",
        lambda stem, reuse_exclusions=False: started.append((stem, reuse_exclusions)),
    )

    app._reload_current_file()

    assert started == [("dataset", True)]


def test_gui04_fiber_table_allows_multiple_selection(tk_app):
    """
    The fiber table selects like Explorer, and re-enables that way after load.
    ファイバー一覧は Explorer と同じ選択方式で、読み込み後もその方式に戻る。
    """
    app = tk_app(gui04.App)
    assert str(app.fiber_tree.cget("selectmode")) == "extended"

    app._set_ui_enabled(False)
    assert str(app.fiber_tree.cget("selectmode")) == "none"

    app._set_ui_enabled(True)
    assert str(app.fiber_tree.cget("selectmode")) == "extended"


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
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "plot_type": gui03.PLOT_HISTOGRAM,
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
        "plot_type": gui03.PLOT_HISTOGRAM,
        "comparisons": [],
        "comparison_note": "",
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


def test_gui04_fiber_table_shows_straightness_and_curvature(tk_app, tmp_path):
    """
    The fiber table reports the per-fiber shape values GUI03 aggregates.
    ファイバー一覧は、GUI03 が集約するファイバーごとの形状値を表示する。

    GUI03 only ever shows these pooled into a distribution, where a wrong
    value is invisible. Putting them beside the fiber they describe is the
    only way a user can check them against the rendered fiber, so the columns
    existing and being filled is the property worth pinning.
    GUI03 はこれらを分布としてしか示さないため、値が誤っていても気付けない。
    対象のファイバーの隣に並べることだけが、描画されたファイバーと照合する手段
    である。よって列が存在し値が入ることが、固定すべき性質である。
    """
    from lib.measure import measure_bundle
    from lib.pipeline import ProcParams, process_file
    from conftest import write_synthetic_fiber_txt

    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    bundle = process_file(txt, ProcParams(bg_method="tophat"),
                          output_dir=out_dir).bundle_path
    result = measure_bundle(bundle, scale_um=1.92)

    app = tk_app(gui04.App)
    assert "straightness" in app.fiber_tree.cget("columns")
    curvature_col = [c for c in app.fiber_tree.cget("columns")
                     if str(c).startswith("curvature")]
    assert curvature_col, "the table must carry a curvature column"

    app.current_image = result.image
    app.current_fibers = result.fibers
    # Empty the cache so the table recomputes, which is the path a height or
    # isolated-fiber filter takes; it must fill the same columns.
    # キャッシュを空にしてテーブル側で再計算させる。高さ／孤立ファイバーフィルター
    # が通る経路であり、同じ列が埋まらなければならない。
    app._fiber_stats = []
    app._populate_fiber_table(result.fibers)

    rows = app.fiber_tree.get_children("")
    assert len(rows) == len(result.fibers)
    values = app.fiber_tree.item(rows[0])["values"]
    cols = list(app.fiber_tree.cget("columns"))
    straight = float(values[cols.index("straightness")])
    # The synthetic fiber is drawn with one bend, so it is neither a straight
    # line nor a doubled-back tangle.
    # 合成ファイバーは折れ目 1 つで描かれるため、直線でも折り返した塊でもない。
    assert 0.5 < straight <= 1.0
    assert straight == pytest.approx(result.stats[0].straightness, abs=5e-4)

    curvature = values[cols.index(curvature_col[0])]
    assert str(curvature).strip(), "a fiber longer than the window is measurable"
    assert float(curvature) > 0.0


def test_gui04_blank_curvature_cell_for_a_fiber_short_of_the_window(tk_app):
    """
    A fiber the curvature window cannot span leaves the cell blank, not zero.
    曲率窓を張れないファイバーのセルは 0 ではなく空欄になる。

    A zero would read as "perfectly straight", which is the opposite of "not
    measured" and would silently enter any comparison the user makes by eye.
    0 は「完全な直線」と読まれ、「未計測」とは正反対の意味になる。目視での比較に
    そのまま紛れ込んでしまう。
    """
    assert gui04.blank_if_nan(float("nan"), "{0:.2f}") == ""
    assert gui04.blank_if_nan(3.14159, "{0:.2f}") == "3.14"


def test_gui03_and_gui04_agree_on_the_kink_quantities(tk_app):
    """
    GUI03's per-fiber kink values come from the same `lib.measure` functions
    GUI04 shows, so a value checked beside a fiber is the value histogrammed.
    GUI03 のファイバー単位のキンク値は、GUI04 が表示するのと同じ `lib.measure` の
    関数から得る。ファイバーの横で確認した値が、そのままヒストグラム化される。

    Two separate implementations of "the kink angle of a fiber" would let the
    two windows disagree, which is exactly what the GUI04 columns exist to
    rule out.
    「ファイバーのキンク角」の実装が 2 つあると 2 つのウインドウが食い違いうる。
    それを排除することこそが GUI04 の列の存在理由である。
    """
    from lib.measure import FiberStats, fiber_kink_angle, fiber_kink_density

    stat = FiberStats(
        index=0, length_nm=2000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=3, kink_angles_deg=(100.0, 120.0, 170.0),
        straightness=0.8,
    )
    assert gui03._fiber_value(stat, gui03.PARAM_KINK_ANGLE) == pytest.approx(
        fiber_kink_angle(stat)
    )
    assert gui03._fiber_value(stat, gui03.PARAM_KINK_DENSITY) == pytest.approx(
        fiber_kink_density(stat)
    )

    # A kinkless fiber has no angle to contribute, but its density is a real
    # zero, so GUI03 must drop the first and keep the second.
    # キンクの無いファイバーは寄与する角度を持たないが、密度は実在の 0 である。
    # GUI03 は前者を落とし、後者は残さなければならない。
    kinkless = FiberStats(
        index=1, length_nm=1000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=0, kink_angles_deg=(), straightness=1.0,
    )
    assert gui03._fiber_value(kinkless, gui03.PARAM_KINK_ANGLE) is None
    assert gui03._fiber_value(kinkless, gui03.PARAM_KINK_DENSITY) == 0.0


def test_gui04_fiber_table_covers_every_gui03_quantity(tk_app):
    """
    Every GUI03 quantity is readable per fiber in GUI04, except kink angle.
    GUI03 の計測量は、キンク角を除きすべて GUI04 でファイバーごとに読める。

    GUI03 shows these only pooled into a distribution, where a wrong value is
    invisible. This test is what keeps a newly added GUI03 quantity from
    shipping without a way for the user to check it against a real fiber.
    GUI03 はこれらを分布としてしか示さないため、値が誤っていても気付けない。この
    テストは、GUI03 に計測量を追加したとき、実際のファイバーと照合する手段が無い
    まま出荷されることを防ぐ。

    Kink angle is deliberately absent, and the reason is scientific rather
    than a matter of table width: a cell holds one number, but the kinks along
    a fiber are distinct defect events, not repeated measurements of one fiber
    property the way height pixels are. A per-fiber median of them is not a
    property of the fiber, and for most fibers it degenerates anyway -- in the
    tunicate test image 27 of 37 fibers carry zero or one kink, so the median
    is either undefined or just that single angle. The individual angles reach
    the user through the CSV, which stores all of them.
    キンク角を意図的に外しているのは、表の幅の問題ではなく科学的な理由による。
    セルが持てる数値は 1 つだが、1 本のファイバー上の複数のキンクは、高さ画素の
    ように 1 つのファイバー特性を繰り返し測ったものではなく、それぞれ独立した
    欠陥事象である。その中央値はファイバーの性質ではなく、しかも大半の
    ファイバーでは統計として成立しない。テスト画像では 37 本中 27 本がキンク
    0 本または 1 本であり、中央値は未定義か単一の角度そのものになる。個々の角度は
    全て CSV に保存され、そちらから参照できる。
    """
    app = tk_app(gui04.App)
    columns = " | ".join(str(c) for c in app.fiber_tree.cget("columns"))

    # Column headings carry units, so match on the quantity name alone.
    # 列見出しには単位が付くため、計測量の名前だけで照合する。
    expected = {
        gui03.PARAM_HEIGHT: "median",
        gui03.PARAM_LENGTH: "length",
        gui03.PARAM_STRAIGHTNESS: "straightness",
        gui03.PARAM_CURVATURE: "curvature",
        gui03.PARAM_KINK_DENSITY: "kink density",
    }
    # Recorded here so removing the column stays a decision, not a regression.
    # 列を持たないことを決定として記録し、退行と区別できるようにする。
    deliberately_absent = {gui03.PARAM_KINK_ANGLE}

    assert set(expected) | deliberately_absent == set(gui03.PARAM_ORDER), (
        "a GUI03 quantity was added or removed; give it a GUI04 column and "
        "update this mapping, or record it as deliberately absent with the "
        "reason it cannot be shown per fiber"
    )
    for param, heading in expected.items():
        assert heading in columns, f"{param} has no GUI04 column"
    for param in deliberately_absent:
        assert param not in columns, (
            f"{param} is recorded as deliberately absent but has a column"
        )
