# -*- coding: utf-8 -*-
"""
Construction smoke tests for the GUI plugins.
GUI プラグインの構築スモークテスト。

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

from conftest import pump_until, requires_tk

from lib import gwy_convert
from lib.connect_selection import (
    ChainMember, ConnectionPlan, connect_path_for, load_connect_plan,
    save_connect_plan,
)
from lib.fiber_selection import exclusion_path_for, load_exclusions

import guis.GUI00_Format_Converter as gui00
import guis.GUI01_Image_Preprocessor as gui01
import guis.GUI02_PlotProfiler as gui02
import guis.GUI03_Fiber_Morphology_Statistics as gui03
import guis.GUI04_Tracking_fiber as gui04
import guis.GUI05_Thumbnail_Viewer as gui05

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


def test_gui00_window_builds(tk_app):
    _assert_window_built(tk_app(gui00.App))


def test_gui00_lists_the_folder_and_shows_each_outcome(tk_app, tmp_path, monkeypatch):
    """
    GUI00 lists only conversion candidates and fills each row from its result.
    GUI00 は変換対象だけを一覧にし、各行を変換結果で埋める。

    The converter is replaced by a stub, so this checks the window's handling
    of `lib.gwy_convert` results, not Gwyddion (tests/test_gwy_convert.py).
    変換プログラムは代替に置き換えるため、ここで確かめるのは結果の扱いで、
    Gwyddion の変換ではない（tests/test_gwy_convert.py が担う）。
    """
    for name in ("a.000", "b.spm", "c.txt", "d.000"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "d.000_converted.gwy").write_bytes(b"earlier conversion")

    def fake_convert(path, converter=None, timeout=None):
        output = gwy_convert.converted_path_for(path)
        if os.path.exists(output):
            return gwy_convert.ConversionResult(path, output, gwy_convert.STATUS_EXISTS)
        if path.endswith(".spm"):
            return gwy_convert.ConversionResult(
                path, output, gwy_convert.STATUS_FAILED, message="unreadable")
        return gwy_convert.ConversionResult(
            path, output, gwy_convert.STATUS_CONVERTED, module="shimadzu")

    monkeypatch.setattr(gui00.filedialog, "askdirectory", lambda **kw: str(tmp_path))
    monkeypatch.setattr(gwy_convert, "find_converter", lambda explicit=None: "gwyconvert")
    monkeypatch.setattr(gwy_convert, "convert_file", fake_convert)

    app = tk_app(gui00.App)
    app.on_choose_folder()
    names = [app.tree.item(i, "values")[0] for i in app.tree.get_children()]
    assert names == ["a.000", "b.spm", "d.000"]
    assert app.tree.item("2", "tags") == (gwy_convert.STATUS_EXISTS,)

    app.on_convert()
    pump_until(app, lambda: not app._running, timeout=30)
    tags = [app.tree.item(i, "tags")[0] for i in app.tree.get_children()]
    assert tags == [gwy_convert.STATUS_CONVERTED, gwy_convert.STATUS_FAILED,
                    gwy_convert.STATUS_EXISTS]
    assert app.tree.item("1", "values")[3] == "unreadable"


def test_gui00_reports_a_missing_converter(tk_app, tmp_path, monkeypatch, silence_dialogs):
    """Without the converter, pressing convert opens an error and converts nothing."""
    (tmp_path / "a.000").write_bytes(b"x")

    def missing(explicit=None):
        raise gwy_convert.ConverterNotFoundError("gwyconvert not found")

    monkeypatch.setattr(gui00.filedialog, "askdirectory", lambda **kw: str(tmp_path))
    monkeypatch.setattr(gwy_convert, "find_converter", missing)
    dialogs = silence_dialogs(gui00)

    app = tk_app(gui00.App)
    app.on_choose_folder()
    app.on_convert()
    assert [kind for kind, _title, _msg in dialogs] == ["showerror"]
    assert gwy_convert.INSTALL_COMMAND in dialogs[0][2]
    assert not app._running


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
    assert str(app._btn_save_curation.cget("state")) == "disabled"


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


def _stub_plan(*anchors):
    """
    Build a plan whose one chain joins the given anchor pixels.
    与えられたアンカー画素を 1 本の連鎖で繋ぐプランを作る。

    The anchors need not resolve to any fragment: these tests are about the
    pending state and the button wiring, which read the plan itself.
    アンカーがどの断片に対応している必要もない。これらのテストが対象とするのは
    保留状態とボタンの結線であり、いずれもプラン自体を読むためである。
    """
    return ConnectionPlan(
        chains=(tuple(ChainMember(anchor=a, flip=False) for a in anchors),),
    )


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
    assert "excluded fragments: 1" in calls[-1]["title_suffix"]


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


def test_gui04_non_isolated_exclusion_is_an_ordinary_exclusion(tk_app, monkeypatch):
    """
    "非孤立を除外" records anchors and undoes exactly like "選択を除外".
    「非孤立を除外」は「選択を除外」と同じようにアンカーを記録し、同じように戻る。

    Making it an exclusion rather than a view filter is the whole point of the
    feature: the judgement then survives the session in the sidecar, is listed
    with its reason in 「除外設定」, and comes back in one undo press. The
    note is what separates these from fibers rejected by eye.
    表示フィルターではなく除外にしたことが本機能の要点である。これにより判断は
    サイドカーとしてセッションを越えて残り、「除外設定」に理由付きで一覧され、
    取り消し 1 回で戻る。メモは目視で棄却したファイバーとの区別を与える。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    fibers = [_StubFiber(0, 0), _StubFiber(4, 0), _StubFiber(0, 4)]
    app.current_fibers = fibers
    app.current_fragments = fibers
    monkeypatch.setattr(app, "_recurate_population", lambda: None)
    monkeypatch.setattr(gui04.messagebox, "askyesno", lambda *a, **k: True)
    # Only the first fiber was measured over its whole length; the other two
    # are what the button has to exclude.
    # 全長を計測できたのは先頭のみで、残る 2 本が除外対象となる。
    monkeypatch.setattr(
        gui04, "isolated_fiber_flags", lambda *a, **k: [True, False, False],
    )

    app._on_exclude_non_isolated()

    assert len(app._excluded_records) == 2
    assert all(r["note"] == "not isolated" for r in app._excluded_records)
    assert app._exclusion_groups == [2], "one press is one undo step"

    app._on_undo_last_exclusion()

    assert app._excluded_records == []
    assert app._exclusion_groups == []


def test_gui04_non_isolated_exclusion_judges_the_measured_population(
    tk_app, monkeypatch
):
    """
    The isolation verdict is taken on `current_fibers`, not on the display list.
    孤立判定は表示リストではなく `current_fibers` に対して行う。

    With the height filter active the display list holds sub-segments cut out
    of a fibril, whose ends are the filter's cuts rather than the fiber's own,
    so "was this measured over its whole length?" has no meaning for them. The
    verdict has to be taken on the fibers as they were traced — which is also
    what lets the height filter be applied to the isolated population
    afterwards, instead of the two narrowings having to exclude each other.
    高さフィルターが有効なとき、表示リストはフィブリルから切り出された部分区間を
    保持する。その端はファイバー本来の端ではなくフィルターの切断面であるため、
    「全長を計測できたか」という問い自体が成立しない。判定は追跡された状態の
    ファイバーに対して行わなければならない。これにより、2 つの絞り込みを排他に
    することなく、孤立ファイバーの母集団へ高さフィルターを後からかけられる。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    traced = [_StubFiber(0, 0), _StubFiber(4, 0)]
    app.current_fibers = traced
    app.current_fragments = traced
    # A height filter is on, so the display list is a different, longer list of
    # sub-segments; the verdict must not be taken on it.
    # 高さフィルターが有効で、表示リストは別物（部分区間の、より長いリスト）で
    # ある。判定をこちらに対して行ってはならない。
    app._filter_active = True
    app._filtered_fibers = [_StubFiber(0, 0), _StubFiber(1, 0), _StubFiber(4, 0)]
    monkeypatch.setattr(app, "_recurate_population", lambda: None)
    monkeypatch.setattr(gui04.messagebox, "askyesno", lambda *a, **k: True)

    judged = []

    def _flags(image, fibers, params=None):
        judged.append(list(fibers))
        return [True] * len(fibers)

    monkeypatch.setattr(gui04, "isolated_fiber_flags", _flags)
    monkeypatch.setattr(gui04.messagebox, "showinfo", lambda *a, **k: None)

    app._on_exclude_non_isolated()

    assert judged, "the button has to reach the isolation test"
    assert judged[-1] == traced


def test_gui04_non_isolated_exclusion_requires_no_connection(tk_app, monkeypatch):
    """
    The button refuses while anything is connected, and changes nothing.
    何かが連結されている間、本ボタンは実行を拒否し、何も変更しない。

    Isolation is defined on the fragments as traced, and connection joins a
    fiber across a crossing into the network so that it stops being isolated.
    The two are alternative answers to fragmentation — measure only what is
    whole, or make it whole — so the precondition is reported rather than
    fixed silently: taking the connection apart here would discard decisions
    as a side effect of pressing an exclusion button.
    孤立は追跡された状態の断片に対して定義され、連結は交差を越えてファイバーを
    ネットワークへつなぐため、そのファイバーは孤立でなくなる。両者は断片化に対する
    代替の答え（完全なものだけを測るか、完全にするか）であるため、前提条件は黙って
    修正せず報告する。ここで連結を解体すると、除外ボタンを押した副作用として判断が
    捨てられてしまう。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    app.current_fibers = [_StubFiber(0, 0)]
    app.current_fragments = app.current_fibers
    app.connect_plan = _stub_plan((0, 0), (5, 5))

    informed = []
    monkeypatch.setattr(
        gui04.messagebox, "showinfo", lambda *a, **k: informed.append(a),
    )
    monkeypatch.setattr(gui04, "isolated_fiber_flags", _unreachable_flags)

    app._on_exclude_non_isolated()

    assert informed, "the precondition has to be reported"
    assert app._excluded_records == []
    assert app.connect_plan.chains, "the connection must be left alone"


def _unreachable_flags(*args, **kwargs):
    """Fail if the isolation test runs when the precondition rejects the press."""
    raise AssertionError("isolation must not be evaluated with connection on")


def test_gui04_curation_save_starts_disabled(tk_app):
    """
    The curation-save button is disabled until a dataset is loaded.
    データセットを読み込むまで、キュレーションの保存ボタンは無効である。

    There is no bundle to write the sidecars beside, so the button can only
    report that there is nothing to do.
    サイドカーを書き出す対象のバンドルが無いため、ボタンは「対象が無い」としか
    返せない。
    """
    app = tk_app(gui04.App)
    assert app._connect_saved_key is None
    assert app._curation_dirty() is False
    assert str(app._btn_save_curation.cget("state")) == "disabled"


def test_gui04_curation_pending_covers_connection_as_well_as_exclusions(tk_app):
    """
    One pending state spans both sidecars, and follows content not clicks.
    保留状態は 1 つで両サイドカーにまたがり、クリックの有無ではなく内容に従う。

    They are saved by one press, so they must be tracked as one state:
    tracking them separately is what let the pair on disk record a combination
    that was never on screen. Turning a switch and turning it back leaves
    nothing to write, exactly as an exclusion followed by its undo does.
    両者は 1 回の押下で保存されるため、1 つの状態として追跡しなければならない。
    別々に追跡していたことが、ディスク上の 2 ファイルが画面に一度も存在しなかった
    組み合わせを記録する原因だった。スイッチを切り替えて戻せば書き出すものは残ら
    ない。除外してから取り消した場合と同じである。
    """
    app = tk_app(gui04.App)
    # Stand in for a loaded dataset whose sidecars match the current state.
    # サイドカーが現在の状態と一致している、読み込み済みデータセットを模す。
    app.current_image = _StubImage()
    app._connect_saved_key = app._current_connect_key()
    app._refresh_curation_button()
    assert str(app._btn_save_curation.cget("state")) == "disabled"

    app.connect_plan = _stub_plan((1, 1), (2, 2))
    app._refresh_curation_button()
    assert app._curation_dirty() is True
    assert str(app._btn_save_curation.cget("state")) == "normal"

    app.connect_plan = gui04.ConnectionPlan()
    app._refresh_curation_button()
    assert str(app._btn_save_curation.cget("state")) == "disabled"

    # An exclusion change alone also lights the one button.
    # 除外側の変更だけでも、この 1 つのボタンが点灯する。
    app._exclusions_dirty = True
    app._refresh_curation_button()
    assert str(app._btn_save_curation.cget("state")) == "normal"


def test_gui04_thresholds_alone_are_never_pending(tk_app):
    """
    Editing a threshold changes no fiber, so it is never something to save.
    しきい値の編集はどのファイバーも変えないため、保存対象になることはない。

    Thresholds are inputs to the automatic search, and the search is an action
    the user takes; once the chains are recorded they no longer take part in
    building a fiber. Announcing an edit as pending would prompt on every
    dataset switch for a difference that changes no number.
    しきい値は自動探索への入力であり、探索はユーザーが起こす操作である。連鎖が
    記録された後、しきい値はファイバーの構築に関与しない。編集を保留として知らせ
    ると、どの数値も変えない差分のためにデータセット切替のたびに確認が出ることに
    なる。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    app._connect_saved_key = app._current_connect_key()
    app.connect_params = gui04.ConnectParams(clusters_range=44.0)
    assert app._curation_dirty() is False

    # Still nothing to save once a connection exists and is recorded.
    # 連結が存在し記録済みであっても、しきい値の変更だけでは保存対象にならない。
    app.connect_plan = _stub_plan((1, 1), (2, 2))
    app._connect_saved_key = app._current_connect_key()
    app.connect_params = gui04.ConnectParams(clusters_range=7.0)
    assert app._curation_dirty() is False


def test_gui04_a_bundle_without_a_sidecar_keeps_the_thresholds(
    tk_app, tmp_path
):
    """
    An unrecorded bundle starts unconnected but keeps the tuned thresholds.
    未記録のバンドルは未連結で始まるが、調整済みのしきい値は保たれる。

    A connection result cannot carry over to another image, because its chains
    name fragments of the image it was made on; the thresholds can, and
    resetting them at every step of a folder would undo the user's tuning.
    連結結果は別の画像へ持ち越せない。その連鎖は、作られた画像の断片を指している
    ためである。しきい値は持ち越せるものであり、フォルダを 1 枚進むたびにリセット
    してはユーザーの調整を無に帰す。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    tuned = gui04.ConnectParams(clusters_range=33.0)
    app.connect_params = tuned
    app.connect_plan = _stub_plan((1, 1), (2, 2))

    app._restore_connect_plan(os.path.join(tmp_path, "unrecorded"))

    assert app.connect_params == tuned
    assert app.connect_plan.chains == ()
    app._refresh_curation_button()
    assert str(app._btn_save_curation.cget("state")) == "disabled"


def test_gui04_an_unrecorded_bundle_with_connection_off_is_not_pending(
    tk_app, tmp_path
):
    """
    A missing sidecar compares equal to "not connected".
    サイドカーが無い状態は「連結なし」と等価に比較される。

    Absence and a stored result with no chains measure identically, so the
    common case of opening an uncurated bundle must not raise a save prompt.
    ファイルの不在と、連鎖を持たない保存済み結果は計測上等価であるため、未
    キュレーションのバンドルを開くという通常の操作で保存確認が出てはならない。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()

    app._restore_connect_plan(os.path.join(tmp_path, "unrecorded"))

    assert app._curation_dirty() is False


def test_gui04_one_save_keeps_both_sidecars_describing_one_screen(
    tk_app, tmp_path
):
    """
    A save-toggle-curate-save sequence leaves the two sidecars in agreement.
    保存・切替・キュレーション・保存の操作手順の後も、2 つのサイドカーが一致すること。

    Save with connection on, turn it off, curate as fragments, save again.
    With a save button of its own for each, only the exclusion file would
    advance and the connection file would still say "connected", so GUI03
    would aggregate whole fibrils where the window shows fragments, with
    nothing to say so. One press writes both, so whatever is on disk after any
    save is a state that was on screen.
    連結 ON で保存し、OFF にして断片としてキュレーションし、再び保存する。両者に
    別々の保存ボタンがあると除外ファイルだけが進み、連結ファイルは「連結する」と
    言ったままになる。その結果、ウインドウが断片を表示しているのに GUI03 は
    フィブリルを集計し、それを知らせるものが無い。1 回の押下で両方を書くため、
    任意の保存の後にディスク上にあるのは画面に存在した状態である。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    app.current_stem = os.path.join(tmp_path, "scan")
    bundle = app.current_stem + ".b2z"

    # Step 1: connected, saved.
    # 手順 1: 連結した状態で保存。
    app.connect_plan = _stub_plan((1, 1), (2, 2))
    assert app._on_save_curation() is True
    assert load_connect_plan(connect_path_for(bundle)).chains

    # Step 2: connection taken apart, fibers excluded as fragments, saved.
    # 手順 2: 連結を解除し、断片としてファイバーを除外して保存。
    app.connect_plan = gui04.ConnectionPlan()
    app._excluded_records = [{"x": 1, "y": 2, "note": "debris"}]
    app._exclusions_dirty = True
    assert app._on_save_curation() is True

    # Both files describe the same screen: not connected, one exclusion.
    # 両ファイルが同じ画面を記述している。連結なし、除外 1 件。
    assert load_connect_plan(connect_path_for(bundle)).chains == ()
    assert len(load_exclusions(exclusion_path_for(bundle))) == 1
    assert app._curation_dirty() is False


def test_gui04_a_saved_sidecar_is_restored_on_load(tk_app, tmp_path):
    """
    A bundle that records how it should be connected is shown that way.
    連結方法を記録したバンドルは、その通りに表示される。

    Otherwise GUI04's view and GUI03's aggregation of the same file could
    disagree, which is the whole point of storing the decision.
    そうでなければ、同じファイルについて GUI04 の表示と GUI03 の集計が食い違い
    うる。決定を保存する意義はまさにそこにある。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    stem = os.path.join(tmp_path, "scan")
    saved = gui04.ConnectionPlan(
        chains=_stub_plan((3, 4), (7, 8)).chains,
        params=gui04.ConnectParams(clusters_range=12.5),
    )
    save_connect_plan(connect_path_for(stem + ".b2z"), "scan.b2z", saved)

    app._restore_connect_plan(stem)

    assert len(app.connect_plan.chains) == 1
    assert app.connect_params.clusters_range == 12.5
    app._refresh_curation_button()
    assert str(app._btn_save_curation.cget("state")) == "disabled"


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

    monkeypatch.setattr(app, "_confirm_unsaved_curation", _unexpected)
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
    assert app._confirm_unsaved_curation() is True


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
    app.current_image = _StubImage()
    app._excluded_records = [{"x": 1, "y": 2, "note": ""}]
    app._exclusions_dirty = True

    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", lambda *a, **k: None)
    assert app._confirm_unsaved_curation() is False
    # Cancelling keeps the work pending rather than resolving it either way.
    # キャンセルは、どちらにも決着させず作業を保留のまま残す。
    assert app._exclusions_dirty is True

    # Declining discards the change and lets the caller proceed.
    # 「いいえ」は変更を破棄し、呼び出し側の処理を続行させる。
    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", lambda *a, **k: False)
    assert app._confirm_unsaved_curation() is True
    assert app._exclusions_dirty is False


def test_gui04_save_asks_before_overwriting_sidecars_written_elsewhere(
    tk_app, tmp_path, monkeypatch
):
    """
    A save over sidecars another window wrote since the load asks first.
    読み込み後に別のウインドウが書いたサイドカーへの保存は、先に確認する。

    GUI01 opens a new GUI04 window per press, so one bundle can be open twice;
    without the check the later save silently replaces the earlier one's work.
    GUI01 は押すたびに新しい GUI04 ウインドウを開くため、1 つのバンドルが 2 つ
    開いていることがある。確認が無ければ、後の保存が先の作業を黙って置き換える。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    app.current_stem = os.path.join(tmp_path, "scan")
    bundle = app.current_stem + ".b2z"
    app._record_sidecar_snapshot()

    # Another window saves an exclusion after this one read the sidecars.
    # このウインドウがサイドカーを読んだ後に、別のウインドウが除外を保存する。
    gui04.save_exclusions(
        exclusion_path_for(bundle), "scan.b2z",
        [{"x": 5, "y": 5, "note": "other window"}],
    )
    app._excluded_records = [{"x": 1, "y": 2, "note": "this window"}]
    app._exclusions_dirty = True

    asked = []
    monkeypatch.setattr(
        gui04.messagebox, "askyesno",
        lambda *a, **k: asked.append(a[0]) or False,
    )
    assert app._on_save_curation() is False
    assert asked, "the overwrite was not asked about"
    assert load_exclusions(exclusion_path_for(bundle))[0]["note"] == "other window"

    monkeypatch.setattr(gui04.messagebox, "askyesno", lambda *a, **k: True)
    assert app._on_save_curation() is True
    assert load_exclusions(exclusion_path_for(bundle))[0]["note"] == "this window"

    # Its own save is not mistaken for someone else's on the next save.
    # 自身の保存を、次の保存で他者の変更と取り違えない。
    def _unexpected(*_args, **_kwargs):
        raise AssertionError("this window's own save must not prompt")

    monkeypatch.setattr(gui04.messagebox, "askyesno", _unexpected)
    app._excluded_records = []
    app._exclusions_dirty = True
    assert app._on_save_curation() is True


def test_gui04_refuses_a_file_that_is_not_a_bundle(
    tk_app, tmp_path, silence_dialogs
):
    """
    A file without GUI04's keys is reported and leaves the window as it was.
    GUI04 のキーを持たないファイルは報告し、ウインドウは元のままにする。
    """
    calls = silence_dialogs(gui04)
    app = tk_app(gui04.App)
    not_bundle = tmp_path / "scan_param.json"
    not_bundle.write_text("{}", encoding="utf-8")

    app.open_bundle(str(not_bundle))
    app.open_bundle(str(tmp_path / "missing.b2z"))

    assert [kind for kind, _t, _m in calls] == ["showerror", "showerror"]
    assert app.current_stem == "" and app.is_running is False


def test_gui01_hand_over_buttons_follow_the_preview(
    tk_app, isolated_gui01_settings, tmp_path, monkeypatch
):
    """
    GUI02/GUI04 open the bundle on screen; GUI03 opens the folder's bundles.
    GUI02/GUI04 は画面上のバンドルを、GUI03 はフォルダのバンドルを開く。

    The buttons are off without something to hand over and while an analysis
    may be rewriting it, so they never pass a file the user is not looking at.
    GUI03 is handed every bundle directly inside the folder through a list
    file, and nothing else that sits there.
    渡すものが無いとき、および解析がそれを書き換えうる間は押せない。ユーザーが
    見ていないファイルを渡すことはない。GUI03 には、フォルダ直下の全バンドルを
    一覧ファイルで渡し、そこにある他のファイルは渡さない。
    """
    from lib import plugin_launch

    launched = []
    monkeypatch.setattr(
        gui01, "launch_plugin", lambda module, args=(): launched.append((module, list(args)))
    )
    app = tk_app(gui01.App)
    buttons = (app.btn_open_gui02, app.btn_open_gui03, app.btn_open_gui04)

    def enabled():
        return tuple(not b.instate(["disabled"]) for b in buttons)

    app._update_controls_state()
    assert enabled() == (False, False, False)

    item = gui01.FileItem(txt_path=str(tmp_path / "scan.txt"))
    item.status = gui01.STATUS_ANALYZED
    app.folder_path = str(tmp_path)
    app.items = [item]
    app._update_controls_state()
    assert enabled() == (False, True, False)

    app._preview_shown_item = item
    app._update_controls_state()
    assert enabled() == (True, True, True)

    bundle = str(tmp_path / "scan") + gui01.BUNDLE_EXT
    other = str(tmp_path / "other_r0-256") + gui01.BUNDLE_EXT
    for path in (bundle, other, str(tmp_path / "scan_param.json")):
        with open(path, "wb"):
            pass

    app.btn_open_gui04.invoke()
    app.btn_open_gui02.invoke()
    app.btn_open_gui03.invoke()
    assert launched[:2] == [
        (gui01.TRACKER_MODULE, [bundle]),
        (gui01.PROFILER_MODULE, [bundle]),
    ]
    module, args = launched[2]
    assert module == gui01.STATISTICS_MODULE
    assert args[0] == plugin_launch.PATH_LIST_FLAG
    assert plugin_launch.read_path_arguments(args) == [other, bundle]

    app.is_running = True
    app._update_controls_state()
    assert enabled() == (False, False, False)


def test_gui01_font_sizes_are_set_in_their_own_window(
    tk_app, isolated_gui01_settings
):
    """
    The preview's font sizes commit from their window and never linger unseen.
    プレビューのフォントサイズは専用ウインドウから確定し、見えないまま残らない。

    The window is only hidden when closed, so a size typed but not confirmed
    would wait in it unseen; closing puts the entries back to the sizes the
    preview is drawn with.
    ウインドウは閉じても隠れるだけなので、入力したが確定していないサイズは
    見えないまま残ってしまう。閉じるときに、入力欄をプレビューを描いている
    サイズへ戻す。
    """
    app = tk_app(gui01.App)
    window = app._font_size_window
    assert not window.winfo_viewable()

    app.btn_font_sizes.invoke()
    app.update_idletasks()
    assert window.winfo_viewable()

    app.ent_title_fs.delete(0, "end")
    app.ent_title_fs.insert(0, "24")
    app._commit_all_unconfirmed(app._font_size_entries)
    assert app.fs_title == 24

    # The main window's Enter does not reach the font sizes.
    # メインウインドウの Enter はフォントサイズに届かない。
    app.ent_label_fs.delete(0, "end")
    app.ent_label_fs.insert(0, "30")
    app._commit_all_unconfirmed(app._unconfirmed_entries)
    assert app.fs_label != 30

    app._close_font_size_window()
    assert not window.winfo_viewable()
    assert float(app.ent_label_fs.get()) == app.fs_label


def test_gui03_registers_handed_over_bundles(tk_app, tmp_path, silence_dialogs):
    """
    The bundles GUI01 or GUI05 hands over join the group GUI03 starts with.
    GUI01 や GUI05 から渡されたバンドルは、GUI03 の起動時のグループに登録される。

    A path that is not an existing bundle, and a bundle the group already
    holds, are left out with a line in the log and no dialog, so one wrong
    path among many does not stop the rest from being registered.
    存在するバンドルではないパスと、グループが既に持つバンドルは、ダイアログを
    出さずログに 1 行出して追加しない。多数のうち 1 つのパスが誤っていても、残りの
    登録は止まらない。
    """
    calls = silence_dialogs(gui03)
    app = tk_app(gui03.App)
    group = app.groups[0]
    first = tmp_path / ("a" + gui03.BUNDLE_EXT)
    second = tmp_path / ("b" + gui03.BUNDLE_EXT)
    for path in (first, second, tmp_path / "notes.txt"):
        path.write_bytes(b"")

    app.add_files(group, [str(first), str(tmp_path), str(tmp_path / "notes.txt"),
                          str(tmp_path / ("missing" + gui03.BUNDLE_EXT)),
                          str(second)])
    assert group.files == [os.path.normpath(str(first)), os.path.normpath(str(second))]
    assert app.tree.get_children(group.id) == tuple(
        app._file_iid(group, path) for path in group.files)
    assert app.tree.set(group.id, "count") == "2"

    # The same file given with other separators and letter case is the same file.
    # 区切り文字や大文字小文字が違っても、同じファイルは同じファイルである。
    app.add_files(group, [str(first).replace("\\", "/").upper()
                          if os.name == "nt" else str(first)])
    assert len(group.files) == 2
    assert calls == []


def test_gui03_moves_files_between_groups(tk_app, tmp_path):
    """
    Moving file rows re-registers them in the target group and marks the result stale.
    ファイル行を移すと、移動先のグループに登録し直され、表示中の結果に古い旨の印が付く。

    A file the target already holds stays where it is, because a group that
    held one bundle twice would be refused by the run.
    移動先が既に持つファイルは動かさない。1 つのバンドルを二重に持つグループは、
    実行で拒否されるためである。
    """
    app = tk_app(gui03.App)
    source = app.groups[0]
    target = app._add_group_internal("Group 2")
    paths = []
    for name in ("a", "b", "c"):
        path = tmp_path / (name + gui03.BUNDLE_EXT)
        path.write_bytes(b"")
        paths.append(os.path.normpath(str(path)))
    app.add_files(source, paths)
    app.add_files(target, paths[2:])
    app._has_result = True

    rows = [(app._file_iid(source, p), source, p) for p in paths]
    app.move_files(rows, target)

    assert source.files == paths[2:]
    assert target.files == [paths[2], paths[0], paths[1]]
    assert app.tree.get_children(source.id) == (app._file_iid(source, paths[2]),)
    assert app.tree.get_children(target.id) == tuple(
        app._file_iid(target, p) for p in target.files)
    assert set(app.tree.selection()) == {
        app._file_iid(target, paths[0]), app._file_iid(target, paths[1])}
    assert app.stale_var.get() != ""


def test_gui03_statistics_window_is_hidden_not_destroyed(tk_app):
    """
    The statistics window opens from its button and survives being closed.
    統計ウィンドウはボタンから開き、閉じても破棄されない。

    The tables live in it, so a run fills them whether it is shown or not and
    reopening shows the latest result.
    表はこのウィンドウにあるため、表示の有無にかかわらず実行のたびに埋まり、開き
    直せば最新の結果が見える。
    """
    app = tk_app(gui03.App)
    window = app.stats_window
    assert window.state() == "withdrawn"
    assert str(app.btn_stats.cget("state")) == "disabled"
    assert app.result_tree.winfo_toplevel() is window
    assert app.comparison_tree.winfo_toplevel() is window

    app.btn_stats.configure(state="normal")
    app.btn_stats.invoke()
    app.update_idletasks()
    assert window.state() == "normal"

    window.tk.call(window.protocol("WM_DELETE_WINDOW"))
    assert window.state() == "withdrawn"
    assert window.winfo_exists()


def test_gui04_undoing_every_exclusion_leaves_nothing_unsaved(tk_app, monkeypatch):
    """
    A set walked back to what is on disk stops counting as unsaved.
    ディスク上の内容まで戻した集合は、未保存として扱われなくなる。

    The unsaved flag decides both the save button and the prompt raised on the
    way out of a dataset, so marking any touch of the set as pending asked the
    user to save or discard a difference that did not exist. A confirmation
    with nothing at stake trains the reflex that loses the work when the
    prompt is real.
    未保存フラグは保存ボタンと、データセットからの離脱時に出る確認ダイアログの
    両方を決める。そのため集合に触れただけで保留扱いにすると、存在しない差分の
    保存・破棄をユーザーに尋ねることになる。失うものが無い確認は、本当に必要な
    確認のときに作業を失う反射を育てる。
    """
    app = tk_app(gui04.App)
    app.current_image = _StubImage()
    fibers = [_StubFiber(0, 0), _StubFiber(4, 0), _StubFiber(0, 4)]
    app.current_fibers = fibers
    app.current_fragments = fibers
    monkeypatch.setattr(app, "_recurate_population", lambda: None)

    app._sel_indices = [0, 2]
    app._sel_idx = 0
    app._on_exclude_selected()

    assert app._exclusions_dirty is True
    assert str(app._btn_save_curation.cget("state")) == "normal"

    app._on_undo_last_exclusion()

    assert app._excluded_records == []
    assert app._exclusions_dirty is False
    assert str(app._btn_save_curation.cget("state")) == "disabled"

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("an unchanged exclusion set must not prompt")

    monkeypatch.setattr(gui04.messagebox, "askyesnocancel", _unexpected)
    assert app._confirm_unsaved_curation() is True

    # The order the records sit in is not content: an anchor excludes whatever
    # fiber passes through it, so re-excluding the same fibers in another order
    # leaves nothing to write.
    # レコードの並び順は内容ではない。アンカーはそこを通るファイバーを除外する
    # ものであり、同じファイバーを別の順序で除外し直しても書き出すものは無い。
    records = [{"x": 1, "y": 2, "note": ""}, {"x": 3, "y": 4, "note": "not isolated"}]
    assert (gui04.exclusion_state_key(records)
            == gui04.exclusion_state_key(list(reversed(records))))
    assert (gui04.exclusion_state_key(records)
            != gui04.exclusion_state_key(records[:1]))


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
    # The worker only checks that the file exists; the contents never get read
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
            "files": _gui03_bundles(folder),
        }],
        "param": gui03.PARAM_HEIGHT,
        "unit": gui03.UNIT_PIXEL,
        "apply_exclusions": False,
        "apply_connection": False,
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


def _gui03_bundles(folder):
    """
    Return the bundle files directly inside a folder, as one group's file list.
    フォルダ直下のバンドルファイルを、1 グループ分のファイル一覧として返す。
    """
    return sorted(
        os.path.join(str(folder), name) for name in os.listdir(str(folder))
        if name.endswith(gui03.BUNDLE_EXT)
    )


def _gui03_run_args(files_by_group, **overrides):
    """
    Build the minimal argument dict of a GUI03 worker run.
    GUI03 ワーカー実行の最小の引数辞書を作る。
    """
    args = {
        "groups": [
            {"id": name, "name": name, "color": "#1f77b4", "files": files}
            for name, files in files_by_group
        ],
        "param": gui03.PARAM_HEIGHT,
        "unit": gui03.UNIT_FIBER,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 10.0, "step": 0.2,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    }
    args.update(overrides)
    return args


def _gui03_drain(app):
    """
    Return every message a GUI03 worker run queued, in order.
    GUI03 ワーカー実行が積んだメッセージを順にすべて返す。
    """
    messages = []
    while not app.ui_queue.empty():
        messages.append(app.ui_queue.get_nowait())
    return messages


def _range_bundle(path, sha, rows=None):
    """
    Write a bundle carrying only the provenance the overlap check reads.
    重なりの検査が読む来歴だけを持つバンドルを書く。
    """
    from lib.blosc2_io import save_bundle
    from lib.bundle_schema import SOURCE_REGION_KEY

    meta = {"input_sha256": sha} if sha else {}
    if rows is not None:
        meta[SOURCE_REGION_KEY] = {
            "row_start": rows[0], "row_stop": rows[1], "row_total": 1024}
    save_bundle(str(path), {"calibrated": np.zeros((2, 2))}, vlmeta=meta)


def test_gui03_finds_analyses_of_the_same_scan_lines(tmp_path):
    """
    Two analyses of the same scan lines of one input file are reported as a pair.
    1 つの入力ファイルの同じ走査線を解析した 2 つの結果を組として報告する。

    GUI01 keeps the whole-image bundle when a scan is later analyzed as
    scan-line ranges, so a group can hold both; pooled, every fiber of the
    overlap is counted twice (116 fibers read as 190 on a test scan). Ranges
    that do not intersect are two images and must not be reported.
    GUI01 は走査を後から走査線範囲で解析しても画像全体のバンドルを残すため、1 つの
    グループに両方が入りうる。まとめると重なった部分の繊維をすべて二度数える
    （試験走査で 116 本が 190 本になった）。交わらない範囲は 2 枚の画像であり、
    報告してはならない。
    """
    find = gui03.App._overlapping_inputs

    _range_bundle(tmp_path / "scan.b2z", "a")
    _range_bundle(tmp_path / "scan_r0-512.b2z", "a", (0, 512))
    _range_bundle(tmp_path / "scan_r256-768.b2z", "a", (256, 768))
    _range_bundle(tmp_path / "scan_r512-1024.b2z", "a", (512, 1024))
    _range_bundle(tmp_path / "other.b2z", "b")
    _range_bundle(tmp_path / "copy.b2z", "b")
    (tmp_path / "broken.b2z").write_bytes(b"")

    def names(paths):
        pairs, by_name = find([str(tmp_path / p) for p in paths])
        return {tuple(sorted(os.path.basename(p) for p in pair))
                for pair in pairs}, by_name

    assert names(["scan.b2z", "scan_r0-512.b2z"]) == (
        {("scan.b2z", "scan_r0-512.b2z")}, 0)
    assert names(["scan_r0-512.b2z", "scan_r256-768.b2z"])[0] == {
        ("scan_r0-512.b2z", "scan_r256-768.b2z")}
    assert names(["scan_r0-512.b2z", "scan_r512-1024.b2z"]) == (set(), 0)
    assert names(["other.b2z", "copy.b2z"])[0] == {("copy.b2z", "other.b2z")}
    assert names(["scan.b2z", "other.b2z", "broken.b2z"]) == (set(), 0)

    # A bundle that records no input file is traced to it by its name alone.
    # 入力ファイルの記録が無いバンドルは、名前だけで入力ファイルを突き止める。
    _range_bundle(tmp_path / "old.b2z", None)
    _range_bundle(tmp_path / "old_r0-512.b2z", None, (0, 512))
    _range_bundle(tmp_path / "old_r512-1024.b2z", None, (512, 1024))
    assert names(["old.b2z", "old_r0-512.b2z", "old_r512-1024.b2z"]) == (
        {("old.b2z", "old_r0-512.b2z"), ("old.b2z", "old_r512-1024.b2z")}, 3)


def test_gui03_worker_refuses_a_group_with_overlapping_analyses(
        tk_app, tmp_path, monkeypatch):
    """
    A group holding two analyses of the same scan lines is refused, not pooled.
    同じ走査線の解析を 2 つ含むグループは、まとめずに拒否する。

    The refusal comes before any bundle is measured, so no figure, table or
    test of the double-counted population is ever produced.
    拒否はどのバンドルを計測するより前に行うため、二重に数えた母集団の図・表・検定
    は一切作られない。
    """
    app = tk_app(gui03.App)
    measured = []
    monkeypatch.setattr(
        app, "_collect_bundle_values",
        lambda paths, param, unit, **kwargs: (
            measured.append(list(paths)) or ([1.0, 2.0, 3.0], None, 3, 1, [])),
    )

    overlapping = tmp_path / "overlapping"
    overlapping.mkdir()
    _range_bundle(overlapping / "scan.b2z", "a")
    _range_bundle(overlapping / "scan_r0-512.b2z", "a", (0, 512))
    app._worker_run(_gui03_run_args([("G", _gui03_bundles(overlapping))]))
    kinds = [kind for kind, _body in _gui03_drain(app)]
    assert kinds.count("fatal") == 1
    assert "done" not in kinds
    assert measured == []

    disjoint = tmp_path / "disjoint"
    disjoint.mkdir()
    _range_bundle(disjoint / "scan_r0-512.b2z", "a", (0, 512))
    _range_bundle(disjoint / "scan_r512-1024.b2z", "a", (512, 1024))
    app._worker_run(_gui03_run_args([("G", _gui03_bundles(disjoint))]))
    kinds = [kind for kind, _body in _gui03_drain(app)]
    assert "fatal" not in kinds
    assert "done" in kinds


def test_gui03_histogram_reaches_the_entered_maximum(
        tk_app, tmp_path, monkeypatch):
    """
    The histogram's last bin ends at the entered maximum, not one step short.
    ヒストグラムの最後のビンは、入力した最大値の 1 step 手前ではなく最大値で終わる。

    Bin edges built with an arange to the maximum stopped a step short of it,
    so the last bin was missing from the figure and its samples were logged
    as outside the range: 24.5 % instead of 22.4 % on a test scan.
    最大値までの arange で作ったビンの端は 1 step 手前で止まり、最後のビンが図から
    欠け、その標本が範囲外としてログに出ていた。試験走査で 22.4 % のところが
    24.5 % になった。
    """
    app = tk_app(gui03.App)
    folder = tmp_path / "bundles"
    folder.mkdir()
    (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
    monkeypatch.setattr(
        app, "_collect_bundle_values",
        lambda paths, param, unit, **kwargs: ([0.5, 9.9, 10.0], None, 3, 1, []),
    )

    app._worker_run(_gui03_run_args([("G", _gui03_bundles(folder))]))
    done = [body for kind, body in _gui03_drain(app) if kind == "done"]
    assert len(done) == 1
    assert done[0]["edges"][-1] == 10.0
    assert len(done[0]["edges"]) == 51
    assert done[0]["results"][0]["n_in_range"] == 3.0
    # The only notice with a percentage is the share outside the range.
    # 割合を含む通知は範囲外の割合だけである。
    assert not [e for e in done[0]["errors"] if "%" in e]

    app._worker_run(_gui03_run_args([("G", _gui03_bundles(folder))], step=0.3))
    done = [body for kind, body in _gui03_drain(app) if kind == "done"]
    assert done[0]["edges"][-1] >= 10.0
    assert done[0]["results"][0]["n_in_range"] == 3.0


def test_gui03_length_floor_log_names_bundles_it_cannot_cut(monkeypatch):
    """
    Bundles without a scan size are logged as not cut, not as cut at the floor.
    走査範囲の無いバンドルは、下限で切ったとではなく切らないとログに出す。

    A floor in nanometers cannot be applied without a pixel size:
    `skeleton_height_values` measures such a bundle whole, and every other
    collector cannot read it. A bundle that records a scan size but not its
    settings or width is still cut at the common floor.
    ピクセルサイズが無ければ nm の下限は当てられない。`skeleton_height_values` は
    そのバンドルを全体のまま計測し、ほかの collector は読み込めない。走査範囲は
    あるが設定や幅を記録していないバンドルには、共通の下限が当たる。
    """
    import queue

    floors = {"known": 40.0}
    scans = {"known": (2.0, 2.0), "scan_a": (2.0, 2.0), "scan_b": (2.0, 2.0)}
    monkeypatch.setattr(gui03, "length_floor_nm", lambda p: floors.get(p))
    monkeypatch.setattr(gui03, "read_scan_size_from_bundle", lambda p: scans.get(p))

    app = object.__new__(gui03.App)
    app.ui_queue = queue.Queue()
    floor = app._common_length_floor(
        ["known", "scan_a", "scan_b", "none_a", "none_b", "none_c"], True)
    assert floor == 40.0
    logs = [body for kind, body in _gui03_drain(app) if kind == "log"]
    # The common floor, the 2 bundles cut at it, the 3 bundles not cut.
    # 共通の下限、それで切る 2 バンドル、切らない 3 バンドル。
    assert len(logs) == 3
    assert "2" in logs[1] and "3" not in logs[1]
    assert "3" in logs[2]


def test_gui03_warns_when_a_group_pools_pixel_sizes():
    """
    A group whose bundles differ in pixel size by more than 1 % is warned about.
    画素サイズが 1 % を超えて違うバンドルをまとめるグループには警告を出す。

    The `pixel` unit counts every skeleton pixel once, so a finer pixel size
    weighs more in the group's distribution.
    `pixel` 単位はスケルトン画素を 1 点ずつ数えるため、画素サイズが細かいほど
    グループの分布での重みが大きくなる。
    """
    import queue

    app = object.__new__(gui03.App)
    app.ui_queue = queue.Queue()
    app._log_group_pixel_size_spread("G", [3.9, 3.92])
    app._log_group_pixel_size_spread("G", [3.9])
    assert not _gui03_drain(app)
    app._log_group_pixel_size_spread("G", [3.9, 7.8])
    logs = [body for kind, body in _gui03_drain(app) if kind == "log"]
    assert len(logs) == 1
    assert "[G]" in logs[0] and "3.90" in logs[0] and "7.80" in logs[0]


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
    # Empty the cache so the table recomputes, which is the path the height
    # filter takes; it must fill the same columns.
    # キャッシュを空にしてテーブル側で再計算させる。高さフィルターが通る経路で
    # あり、同じ列が埋まらなければならない。
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

    # The recomputed row marks a lower-bound length exactly as the stats do.
    # 再計算した行は、統計値と同じ基準で下限値の長さに印を付ける。
    prefix = "≥ " if gui04.length_is_lower_bound(result.stats[0]) else ""
    assert str(values[cols.index("length (nm)")]) == (
        prefix + f"{result.fibers[0].length:.0f}")

    curvature = values[cols.index(curvature_col[0])]
    assert str(curvature).strip(), "a fiber longer than the window is measurable"
    assert float(curvature) > 0.0


def test_gui04_blank_curvature_cell_for_a_fiber_short_of_the_window():
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


def test_gui03_and_gui04_agree_on_the_kink_quantities():
    """
    GUI03's per-fiber kink values come from the same `lib.measure` functions
    GUI04 shows, so a value checked beside a fiber is the value histogrammed.
    GUI03 のファイバー単位のキンク値は、GUI04 が表示するのと同じ `lib.measure` の
    関数から得る。ファイバーの横で確認した値が、そのままヒストグラム化される。

    Two separate implementations of "the kink density of a fiber" would let
    the two windows disagree, which is exactly what the GUI04 columns exist to
    rule out. Kink angle has no per-fiber value in either window: every unit
    receives the kinks themselves.
    「ファイバーのキンク密度」の実装が 2 つあると 2 つのウインドウが食い違いうる。
    それを排除することこそが GUI04 の列の存在理由である。キンク角はどちらの
    ウインドウでもファイバー単位の値を持たず、どの単位にもキンクそのものが渡る。
    """
    from lib.measure import FiberStats, fiber_kink_density

    stat = FiberStats(
        index=0, length_nm=2000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=3, kink_angles_deg=(100.0, 120.0, 170.0),
        straightness=0.8,
    )
    assert gui03._fiber_value(stat, gui03.PARAM_KINK_DENSITY) == pytest.approx(
        fiber_kink_density(stat)
    )
    assert gui03._fiber_value(stat, gui03.PARAM_KINK_ANGLE) is None
    for unit in (gui03.UNIT_KINK, gui03.UNIT_IMAGE):
        assert gui03._fiber_samples(stat, gui03.PARAM_KINK_ANGLE, unit) == [
            100.0, 120.0, 170.0]
    assert gui03.UNIT_FIBER not in gui03.PARAM_SPECS[gui03.PARAM_KINK_ANGLE]["units"]

    # A kinkless fiber has no angle to contribute, but its density is a real
    # zero, so GUI03 must drop the first and keep the second.
    # キンクの無いファイバーは寄与する角度を持たないが、密度は実在の 0 である。
    # GUI03 は前者を落とし、後者は残さなければならない。
    kinkless = FiberStats(
        index=1, length_nm=1000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=0, kink_angles_deg=(), straightness=1.0,
    )
    assert gui03._fiber_samples(
        kinkless, gui03.PARAM_KINK_ANGLE, gui03.UNIT_IMAGE) == []
    assert gui03._fiber_value(kinkless, gui03.PARAM_KINK_DENSITY) == 0.0


def _kink_stat(length_nm, angles):
    """Return a fiber row with the given contour length and kink angles."""
    from lib.measure import FiberStats

    return FiberStats(
        index=0, length_nm=length_nm, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=len(angles), kink_angles_deg=tuple(angles),
        straightness=1.0,
    )


def test_gui03_pools_kinks_per_image():
    """
    The image unit pools kinks rather than summarizing per fiber.
    画像単位はファイバーごとに要約せず、キンクをまとめる。

    Kink density divides the pooled count by the pooled judged length, so an
    image whose kinkless fibers outnumber the kinked ones still reads the kinks
    it holds; a median of per-fiber densities would read 0 there. Kink angle is
    the median of every kink, so a fiber with three kinks weighs three times one
    with a single kink.
    キンク密度はまとめたキンク数をまとめた判定長で割る。キンクの無いファイバーが
    キンクのあるファイバーより多い画像でも、含まれるキンクが読める。ファイバーごとの
    密度の中央値ならそこは 0 になる。キンク角は全キンクの中央値であり、キンク 3 個の
    ファイバーはキンク 1 個のファイバーの 3 倍の重みを持つ。
    """
    image_a = [_kink_stat(1000.0, (150.0, 160.0, 170.0)),
               _kink_stat(1000.0, ()), _kink_stat(1000.0, ())]
    image_b = [_kink_stat(2000.0, (90.0,)), _kink_stat(2000.0, ())]
    per_source = [("a.b2z", image_a), ("b.b2z", image_b)]

    values, weights, n_fibers, n_images = gui03.App._values_from_fiber_stats(
        per_source, gui03.PARAM_KINK_DENSITY, gui03.UNIT_IMAGE)
    # 3 kinks over 3 um and 1 kink over 4 um; the per-fiber medians are 0.
    # 3 µm に 3 個、4 µm に 1 個。ファイバーごとの中央値ならどちらも 0。
    assert values == [pytest.approx(1.0), pytest.approx(0.25)]
    assert weights is None and (n_fibers, n_images) == (5, 2)

    values, _w, n_fibers, _m = gui03.App._values_from_fiber_stats(
        per_source, gui03.PARAM_KINK_ANGLE, gui03.UNIT_IMAGE)
    assert values == [160.0, 90.0]
    assert n_fibers == 2

    # An image value is the median of the image's fibers, one value per image.
    # 画像の値はその画像のファイバーの中央値で、画像 1 枚につき 1 つである。
    lengths = [("a.b2z", [_kink_stat(v, ()) for v in (100.0, 200.0, 900.0)]),
               ("b.b2z", [_kink_stat(v, ()) for v in (300.0, 400.0)])]
    values, _w, n_fibers, n_images = gui03.App._values_from_fiber_stats(
        lengths, gui03.PARAM_LENGTH, gui03.UNIT_IMAGE)
    assert values == [200.0, 350.0] and (n_fibers, n_images) == (5, 2)
    values, _w, n_fibers, n_images = gui03.App._curvature_values(
        [("a.b2z", np.array([1.0, 2.0, np.nan])), ("b.b2z", np.array([9.0]))],
        gui03.UNIT_IMAGE)
    assert values == [1.5, 9.0] and (n_fibers, n_images) == (3, 2)


def test_gui03_standard_deviation_is_the_sample_one():
    """
    An unweighted SD divides by n - 1; one sample has none.
    重みなしの標準偏差は n - 1 で割る。標本 1 個には標準偏差が無い。
    """
    stats = gui03._summary_stats(np.array([1.0, 2.0, 3.0, 6.0]))
    assert stats["std"] == pytest.approx(np.std([1.0, 2.0, 3.0, 6.0], ddof=1))
    assert stats["std_definition"] == gui03.STD_SAMPLE
    assert np.isnan(gui03._summary_stats(np.array([4.0]))["std"])

    weighted = gui03._summary_stats(np.array([1.0, 3.0]), np.array([1.0, 3.0]))
    # Weighted mean 2.5; variance (1 * 2.25 + 3 * 0.25) / 4.
    # 重み付き平均 2.5、分散 (1 * 2.25 + 3 * 0.25) / 4。
    assert weighted["std"] == pytest.approx(np.sqrt(0.75))
    assert weighted["std_definition"] == gui03.STD_WEIGHTED


def test_gui03_tests_images_and_warns_at_fiber():
    """
    Image samples are testable, and the fiber unit carries a note pointing at them.
    画像の標本は検定でき、fiber 単位には image 単位を案内する注意書きが付く。

    Every quantity can be aggregated per image, so the unit the note points
    at is always on offer.
    どの計測量も画像単位で集計できるため、注意書きが案内する単位は常に選べる。
    """
    assert gui03.TESTABLE_UNITS == (gui03.UNIT_FIBER, gui03.UNIT_IMAGE)
    for spec in gui03.PARAM_SPECS.values():
        assert gui03.UNIT_IMAGE in spec["units"]
    assert gui03._comparison_caveat(gui03.UNIT_IMAGE) == ""
    assert gui03.UNIT_IMAGE in gui03._comparison_caveat(gui03.UNIT_FIBER)


def test_gui03_names_pairs_too_small_to_reach_significance():
    """
    A pair of three samples against three is named; four against four is not.
    3 標本対 3 標本のペアは挙げ、4 対 4 は挙げない。
    """
    from lib.group_compare import compare_groups

    small = compare_groups([("A", np.arange(3.0)), ("B", np.arange(3.0, 6.0))])
    note = gui03._attainable_p_note(small)
    assert "A vs B: 0.1" in note
    larger = compare_groups([("A", np.arange(4.0)), ("B", np.arange(4.0, 8.0))])
    assert gui03._attainable_p_note(larger) == ""


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


def test_gui04_every_fiber_table_column_is_explained(tk_app):
    """
    Every fiber-table column has an in-GUI explanation, and nothing else does.
    ファイバー一覧のすべての列に GUI 内の説明があり、存在しない列の説明は無い。

    A column added without an explanation would leave the user guessing what
    the number is; a stale entry would explain a column that no longer exists.
    説明の無い列を追加すると利用者は値の意味を推測するしかなくなり、古い項目は
    もう存在しない列を説明してしまう。
    """
    app = tk_app(gui04.App)
    columns = tuple(app.fiber_tree.cget("columns"))
    help_entries = gui04.fiber_column_help()

    assert set(help_entries) == set(columns)
    for column, entry in help_entries.items():
        assert entry.meaning.strip(), f"{column} has no explanation"
        assert entry.section.startswith("3."), (
            f"{column} must point at its docs/gui04_measurements.md §3 subsection"
        )
        # A computation is given exactly for the values a formula produces;
        # a count or a statistic is explained by its meaning alone.
        # 計算方法は計算式で求める値にだけ付け、数や統計量は意味の説明だけにする。
        assert bool(entry.method.strip()) == bool(entry.formula.strip()), column
    for column in ("#", "EP count", "Kink count", "unjudged"):
        assert not help_entries[column].method, f"{column} is a count, not a formula"
    for column in ("length (nm)", "straightness", "reliable"):
        assert help_entries[column].method, f"{column} lost its computation"

    window = gui04.ColumnHelpWindow(app, columns)
    try:
        body = window._text.get("1.0", "end")
        for column in columns:
            assert column in body, f"{column} is missing from the help window"
    finally:
        window.destroy()


def test_gui04_fiber_table_headings_fit_their_columns(tk_app):
    """
    No fiber-table heading is wider than its column.
    ファイバー一覧のどの見出しも、その列の幅に収まる。

    A clipped "median (n" reads as a broken widget, and fixed pixel widths
    clip as soon as display scaling enlarges the heading font.
    "median (n" のように切れた見出しはウィジェットの不具合に見え、固定の画素幅は
    表示倍率で見出しのフォントが大きくなるとすぐに切れる。
    """
    from tkinter import font as tkfont

    app = tk_app(gui04.App)
    tree = app.fiber_tree
    font_name = gui04.ttk.Style(tree).lookup("Treeview.Heading", "font")
    heading_font = tkfont.nametofont(font_name or "TkHeadingFont")
    # On Windows at 133 % scaling a heading was visibly clipped with 8 px to
    # spare and drawn whole with 12 px (the 3 px padding on each side plus
    # the border and separator).
    # Windows の 133 % 表示では、余り 8 px の見出しは目に見えて切れ、12 px（左右
    # 3 px のパディングと枠・区切り線）なら全体が描かれた。
    for column in tree.cget("columns"):
        text_width = heading_font.measure(str(tree.heading(column, "text")))
        assert tree.column(column, "width") >= text_width + 12, column


def test_gui04_fiber_table_reports_width_reliability_and_unjudged(tk_app, tmp_path):
    """
    The table says at what scale each fiber was judged and how much of it was
    located, so a number can be doubted for the right reason.
    一覧は各ファイバーをどの尺度で判定し、どれだけを位置決めできたかを示し、
    数値を正しい理由で疑えるようにする。
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
    cols = list(app.fiber_tree.cget("columns"))
    for heading in ("p90 (nm)", "unjudged", "W (nm)", "reliable"):
        assert heading in cols, f"the table must carry a {heading!r} column"

    app.current_image = result.image
    app.current_fibers = result.fibers
    app._fiber_stats = []
    app._populate_fiber_table(result.fibers)
    values = app.fiber_tree.item(app.fiber_tree.get_children("")[0])["values"]
    stat = result.stats[0]
    assert stat.width_measured
    assert float(values[cols.index("W (nm)")]) == pytest.approx(stat.width_nm, abs=0.06)
    assert float(values[cols.index("reliable")]) == pytest.approx(
        stat.line_reliable_fraction, abs=0.006)
    assert float(values[cols.index("p90 (nm)")]) == pytest.approx(
        stat.height_p90_nm, abs=0.006)
    assert int(values[cols.index("unjudged")]) == stat.unjudged_count


def _frame_stat(length_nm, touches_frame, cut_end_count, frame_weight):
    """
    Build a per-fiber row carrying only what the frame mode reads.
    枠の扱いが読む項目だけを持つファイバー単位の行を作る。
    """
    from lib.measure import FiberStats

    return FiberStats(
        index=0, length_nm=length_nm, height_median_nm=1.0,
        height_max_nm=2.0, ep_count=2, kink_count=0, kink_angles_deg=(),
        touches_frame=touches_frame, cut_end_count=cut_end_count,
        frame_weight=frame_weight,
    )


def test_gui03_frame_mode_filters_and_weights_contour_length():
    """
    The frame mode drops frame-touching fibers and weights the rest.
    枠の扱いは枠に達したファイバーを外し、残りを重み付けする。

    A source that does not record the frame test is left out whole, because
    mixing judged and unjudged fibers biases the distribution in a direction
    nobody can state; a fiber with a cut end is kept and counted.
    枠の判定を記録していないソースは丸ごと外す。判定済みと未判定のファイバーを
    混ぜると、向きを誰も言えない偏りが分布に入るためである。切断端を持つ
    ファイバーは残して本数を数える。
    """
    judged = [
        _frame_stat(100.0, False, 0, 1.0),
        _frame_stat(500.0, True, 0, float("nan")),
        _frame_stat(300.0, False, 1, 2.0),
    ]
    unrecorded = [_frame_stat(200.0, None, None, float("nan"))]
    per_source = [("a.b2z", judged), ("old_fibers.csv", unrecorded)]

    # `include` removes nothing and still counts what the frame cut.
    # `include` は何も外さず、枠で切れたものは数える。
    kept, report = gui03._apply_frame_mode(per_source, gui03.FRAME_INCLUDE)
    assert kept is per_source
    assert report == {"total": 3, "frame": 1, "lower_bound": 1,
                      "unrecorded": ["old_fibers.csv"]}

    kept, report = gui03._apply_frame_mode(per_source, gui03.FRAME_EXCLUDE)
    assert [[s.length_nm for s in stats] for _p, stats in kept] == [[100.0, 300.0]]
    assert report == {"total": 3, "frame": 1, "lower_bound": 1,
                      "unrecorded": ["old_fibers.csv"]}

    values, weights, n_fibers, n_images = gui03.App._values_from_fiber_stats(
        kept, gui03.PARAM_LENGTH, gui03.UNIT_FIBER, frame_weighted=True,
    )
    assert values == [100.0, 300.0]
    assert weights == [1.0, 2.0]
    assert (n_fibers, n_images) == (2, 1)

    # The image unit takes each image's weighted median and stays unweighted.
    # image 単位は画像ごとの重み付き中央値を取り、重みなしのままにする。
    values, weights, _n, _m = gui03.App._values_from_fiber_stats(
        kept, gui03.PARAM_LENGTH, gui03.UNIT_IMAGE, frame_weighted=True,
    )
    assert weights is None
    assert values == [pytest.approx(gui03._summary_stats(
        np.array([100.0, 300.0]), np.array([1.0, 2.0]))["median"])]


def test_gui03_kaplan_meier_weights_the_fibers_seen_whole():
    """
    Kaplan-Meier keeps the fibers seen whole, weighted, and reports the rest.
    Kaplan-Meier は全長を見たファイバーを重み付きで残し、残りを報告する。

    A fiber cut at one end is censored: it carries no weight itself but moves
    its share onto the longer fibers seen whole. A source that does not record
    the frame ends is left out whole.
    片端が切れたファイバーは打ち切りであり、自身は重みを持たないが、その分を
    より長い全長のファイバーへ移す。枠の端を記録していないソースは丸ごと外す。
    """
    import dataclasses

    def stat(length, cut, frame_end):
        return dataclasses.replace(
            _frame_stat(length, frame_end > 0, cut, float("nan")),
            frame_end_count=frame_end)

    judged = [stat(100.0, 0, 0), stat(300.0, 0, 0), stat(200.0, 1, 0),
              stat(50.0, 2, 0), stat(400.0, 0, 2)]
    unrecorded = [_frame_stat(250.0, False, 0, float("nan"))]
    per_source = [("a.b2z", judged), ("old_fibers.csv", unrecorded)]

    kept, report = gui03._apply_frame_mode(per_source, gui03.FRAME_KAPLAN_MEIER)
    assert [[s.length_nm for s in stats] for _p, stats in kept] == [[100.0, 300.0]]
    assert [s.frame_weight for s in kept[0][1]] == [
        pytest.approx(1.0), pytest.approx(1.5)]
    assert report["unrecorded"] == ["old_fibers.csv"]
    assert (report["total"], report["complete"], report["censored"],
            report["no_own_end"]) == (5, 2, 1, 2)
    assert report["unassigned"] == pytest.approx(0.0)
    assert report["longest_nm"] == 300.0
    assert gui03.App._frame_weighted(gui03.PARAM_LENGTH, gui03.FRAME_KAPLAN_MEIER)


def test_gui03_kaplan_meier_summary_leaves_what_it_cannot_place_blank():
    """
    Quartiles beyond the longest fiber seen whole, and the mean, are not reported.
    全長を見た最長のファイバーより長い側の四分位数と、平均は報告しない。

    Two fibers seen whole carry one fiber each and two more lie beyond them,
    so the estimate reaches half the fibers and no further: the median is the
    longest fiber seen whole, the upper quartile is beyond it, and without
    anything beyond the statistics are the weighted ones.
    全長を見た 2 本が 1 本ずつを担い、さらに 2 本がその先にあるため、推定は
    半数のファイバーまでしか届かない。中央値は全長を見た最長のファイバーで、
    上側四分位数はその先にある。先に何も無ければ重み付き統計値になる。
    """
    values = np.array([100.0, 300.0])
    weights = np.array([1.0, 1.0])
    stats = gui03._kaplan_meier_summary(values, weights, [(300.0, 2.0)])
    assert np.isnan(stats["mean"]) and np.isnan(stats["std"])
    assert stats["q1"] == pytest.approx(200.0)
    assert stats["median"] == pytest.approx(300.0)
    assert np.isnan(stats["q3"])

    r = dict(stats, quantile_bounds=stats["bounds"])
    assert gui03._quantile_text(r, "q3", "{0:.1f}") == "> 300.0"
    assert gui03._quantile_text(r, "median", "{0:.1f}") == "300.0"
    assert gui03._quantile_text(dict(r, quantile_bounds={}), "q3", "{0:.1f}") == "-"

    whole = gui03._kaplan_meier_summary(values, weights, [(300.0, 0.0)])
    assert whole == dict(gui03._summary_stats(values, weights), bounds={})


def test_gui03_kaplan_meier_places_each_estimates_share_beyond_its_own_fiber():
    """
    An estimate's unplaced share lies beyond that estimate's longest fiber, not the pooled one.
    推定の置けなかった分は、まとめた全体ではなくその推定の最長のファイバーより先にある。

    One estimate saw a fiber of 100 nm whole and places one more fiber beyond
    it; another saw a fiber of 300 nm whole and places nothing beyond. The
    unplaced fiber may be as short as just over 100 nm, so the median lies
    anywhere from 100 to 300 nm and the upper quartile anywhere above 200 nm;
    reading the share as lying beyond 300 nm would report a median of 300 nm
    and an upper quartile above 300 nm.
    一方の推定は 100 nm のファイバーを全長で見て、その先にさらに 1 本を置く。
    もう一方は 300 nm のファイバーを全長で見て、先には何も置かない。置けなかった
    1 本は 100 nm をわずかに超えるだけかもしれないため、中央値は 100〜300 nm の
    どこか、上側四分位数は 200 nm より先のどこかにある。その分を 300 nm より先に
    あるとみなすと、中央値 300 nm、上側四分位数 300 nm 超と報告してしまう。
    """
    values = np.array([100.0, 300.0])
    weights = np.array([1.0, 1.0])
    stats = gui03._kaplan_meier_summary(values, weights, [(100.0, 1.0), (300.0, 0.0)])
    assert stats["bounds"]["q1"] == pytest.approx((100.0, 150.0))
    assert stats["bounds"]["median"] == pytest.approx((100.0, 300.0))
    assert stats["bounds"]["q3"][0] == pytest.approx(200.0)
    assert np.isinf(stats["bounds"]["q3"][1])
    assert all(np.isnan(stats[key]) for key in ("q1", "median", "q3"))
    r = dict(stats, quantile_bounds=stats["bounds"])
    assert gui03._quantile_text(r, "median", "{0:.1f}") == "[100.0, 300.0]"
    assert gui03._quantile_text(r, "q3", "{0:.1f}") == "> 200.0"
    assert gui03._range_csv_values(stats["bounds"]) == [
        "100.000", "150.000", "100.000", "300.000", "200.000", "inf"]


def test_gui03_kaplan_meier_interval_is_reproducible_and_spans_the_bounds():
    """
    The resampling interval is the same on every run and contains the bounds of the data.
    リサンプリング区間は毎回同じで、データ自身の範囲を含む。
    """
    rng = np.random.default_rng(3)
    samples = []
    for longest in (150.0, 400.0):
        lengths = rng.uniform(20.0, longest, 60)
        own = rng.choice([0, 1, 2], size=60, p=[0.2, 0.3, 0.5])
        samples.append((lengths, own))
    first = gui03._kaplan_meier_interval(samples, resamples=50)
    assert first == gui03._kaplan_meier_interval(samples, resamples=50)
    values, weights, estimates = [], [], []
    for lengths, own in samples:
        w, rest = gui03.kaplan_meier_length_weights(lengths, own)
        keep = (own == 2) & (w > 0.0)
        values.append(lengths[keep])
        weights.append(w[keep])
        estimates.append((float(lengths[own == 2].max()), rest * own.sum() / 2.0))
    bounds = gui03._kaplan_meier_bounds(
        np.concatenate(values), np.concatenate(weights), estimates)
    for key in ("q1", "median", "q3"):
        assert first[key][0] <= bounds[key][0] + 1e-9
        assert first[key][1] >= bounds[key][1] - 1e-9
    assert gui03._kaplan_meier_interval([]) == {}


def test_gui03_weights_fiber_kink_density_by_judged_length(tk_app, tmp_path, monkeypatch):
    """
    Fiber-unit kink densities are weighted by the judged length and not tested.
    ファイバー単位のキンク密度は判定長で重み付けされ、検定されない。

    A short fragment reads a large density from a single kink; weighted by its
    judged length it counts as much as that length, and the weighted mean is the
    pooled density the image unit reports. A run reports the fibers measured,
    not the weight, and the rank tests are not applied to weighted samples.
    短い断片はキンク 1 個で大きな密度を示すが、判定長で重み付けすればその長さの
    分だけ数えられ、重み付き平均は画像単位が報告するまとめた密度と一致する。実行は
    重みではなく計測した本数を報告し、重み付きの標本には順位検定をかけない。
    """
    stats = [_kink_stat(10.0, (150.0,)), _kink_stat(1000.0, ()), _kink_stat(2000.0, (90.0,))]
    values, weights, n_fibers, _n = gui03.App._values_from_fiber_stats(
        [("a.b2z", stats)], gui03.PARAM_KINK_DENSITY, gui03.UNIT_FIBER)
    assert n_fibers == 3
    assert weights == [pytest.approx(10.0), pytest.approx(1000.0), pytest.approx(2000.0)]
    weighted_mean = np.average(values, weights=weights)
    pooled, _w, _f, _i = gui03.App._values_from_fiber_stats(
        [("a.b2z", stats)], gui03.PARAM_KINK_DENSITY, gui03.UNIT_IMAGE)
    assert weighted_mean == pytest.approx(pooled[0])

    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))
    monkeypatch.setattr(app, "_collect_bundle_values",
                        lambda *a, **k: (values, weights, 3, 1, []))
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": gui03.PARAM_KINK_DENSITY,
        "unit": gui03.UNIT_FIBER,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 200.0, "step": 10.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })
    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert done["comparisons"] == []
    assert gui03.UNIT_IMAGE in done["comparison_note"]
    r = done["results"][0]
    assert r["n_samples"] == 3.0 and r["n_in_range"] == 3.0
    assert r["weight_total"] == pytest.approx(3010.0)
    assert r["mean"] == pytest.approx(pooled[0])


def test_gui03_frame_weighted_run_reports_fibers_and_skips_tests(
        tk_app, tmp_path, monkeypatch):
    """
    A Miles-Lantuejoul run counts fibers, not weights, and runs no test.
    Miles-Lantuejoul の実行は重みではなく本数を数え、検定を行わない。

    The total weight is an estimated fiber count rather than what was
    observed, and Mann-Whitney U and KS take no weights.
    重みの合計は観測した本数ではなく推定本数であり、Mann-Whitney U と KS は
    重みを受け付けない。
    """
    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))

    seen = {}

    def _collect(paths, param, unit, **kwargs):
        seen["frame_mode"] = kwargs.get("frame_mode")
        return [100.0, 200.0, 300.0], [1.0, 1.5, 2.0], 3, 1, []

    monkeypatch.setattr(app, "_collect_bundle_values", _collect)
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": gui03.PARAM_LENGTH,
        "unit": gui03.UNIT_FIBER,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "frame_mode": gui03.FRAME_MILES_LANTUEJOUL,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 3000.0, "step": 100.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert seen["frame_mode"] == gui03.FRAME_MILES_LANTUEJOUL
    assert done["comparisons"] == []
    assert gui03.FRAME_MILES_LANTUEJOUL in done["comparison_note"]
    # The way to a test keeps the correction: it names the image unit, not
    # the mode whose bias the correction exists to remove.
    # 検定への道は補正を保つ。案内するのは image 単位であり、補正が取り除くはずの
    # 偏りを持つモードではない。
    assert gui03.FRAME_EXCLUDE not in done["comparison_note"]
    assert gui03.UNIT_IMAGE in done["comparison_note"]
    r = done["results"][0]
    assert r["n_samples"] == 3.0
    assert r["weight_total"] == pytest.approx(4.5)
    assert r["n_in_range"] == 3.0


def test_gui03_scan_size_note_names_each_group_when_sizes_differ():
    """
    The scan-size warning appears only when sizes differ, per group.
    走査範囲の警告は違うときだけ、グループごとに出る。
    """
    for mode in (gui03.FRAME_INCLUDE, gui03.FRAME_EXCLUDE):
        assert gui03._scan_size_spread_note({}, mode) == ""
        assert gui03._scan_size_spread_note({"A": [(2.0, 2.0)]}, mode) == ""
        # Within one percent is the rounding of a header value, not a difference.
        # 1 % 以内はヘッダの値の丸めであり、違いではない。
        assert gui03._scan_size_spread_note(
            {"A": [(2.0, 2.0)], "B": [(2.01, 2.01)]}, mode) == ""
        text = gui03._scan_size_spread_note(
            {"A": [(2.0, 2.0)], "B": [(5.0, 5.0), (5.0, 5.0)]}, mode)
        assert mode in text and gui03.FRAME_MILES_LANTUEJOUL in text
        assert "A: 2×2" in text and "B: 5×5" in text
        # One axis differing is enough: the frame cuts along both.
        # 片方の軸の違いで足りる。枠は両軸で切る。
        assert gui03._scan_size_spread_note(
            {"A": [(2.0, 2.0)], "B": [(2.0, 1.0)]}, mode) != ""


def _kink_condition(threshold=150.0, version="1.6", pixel_nm=2.0, width_px=8.0,
                    height_nm=2.0, noise_nm=0.02):
    """Build one `App._bundle_kink_conditions` entry."""
    return {"threshold": threshold, "version": version,
            "pixel_nm": pixel_nm, "width_px": width_px,
            "height_nm": height_nm, "noise_nm": noise_nm}


def test_gui03_kink_definitions_that_differ_block_the_test():
    """
    A different threshold stops the test; imaging only warns.
    しきい値の違いは検定を止め、撮像条件の違いは警告にとどまる。
    """
    report = gui03._kink_condition_report
    same = {"A": [_kink_condition()], "B": [_kink_condition()]}
    assert report(same, False) == ([], "")

    thresholds = {"A": [_kink_condition()], "B": [_kink_condition(threshold=160.0)]}
    warnings, blocking = report(thresholds, False)
    assert warnings == [] and "150, 160" in blocking
    # Applying one threshold to every bundle removes the difference.
    # 全バンドルに 1 つのしきい値を適用すれば違いは無くなる。
    assert report(thresholds, True) == ([], "")

    imaging ={"A": [_kink_condition()],
               "B": [_kink_condition(pixel_nm=5.0, version="1.5")]}
    warnings, blocking = report(imaging, False)
    assert blocking == "" and len(warnings) == 2
    assert "2.00" in warnings[0] and "5.00" in warnings[0]
    assert "1.5, 1.6" in warnings[1]


def test_gui03_kink_report_warns_only_below_the_noise_limit():
    """
    Noise warns at the limit the analysis warns at, not at any difference.
    ノイズは解析が警告する限度で警告し、差があるだけでは警告しない。
    """
    from lib.pipeline import MIN_FIBER_SNR

    report = gui03._kink_condition_report
    above = _kink_condition(height_nm=2.0, noise_nm=2.0 / (MIN_FIBER_SNR + 1))
    below = _kink_condition(height_nm=2.0, noise_nm=2.0 / (MIN_FIBER_SNR - 1))
    unread = _kink_condition(height_nm=None, noise_nm=None)
    # A difference above the limit, or a bundle that could not be read, says
    # nothing about the limit.
    # 限度より上の差や、読めなかったバンドルは限度について何も言わない。
    assert report({"A": [_kink_condition()], "B": [above]}, False) == ([], "")
    assert report({"A": [unread], "B": [above]}, False) == ([], "")
    warnings, blocking = report({"A": [above], "B": [below]}, False)
    assert blocking == "" and len(warnings) == 1
    assert "1/2" in warnings[0]


def test_gui03_frame_bias_note_names_the_uncorrected_length_modes():
    """
    Only uncorrected lengths carry the frame-bias note.
    枠の偏りの注記は、補正していない長さにだけ付く。
    """
    note = gui03._frame_bias_note
    assert gui03.FRAME_INCLUDE in note(gui03.PARAM_LENGTH, gui03.FRAME_INCLUDE)
    assert gui03.FRAME_EXCLUDE in note(gui03.PARAM_LENGTH, gui03.FRAME_EXCLUDE)
    assert note(gui03.PARAM_LENGTH, gui03.FRAME_MILES_LANTUEJOUL) == ""
    assert note(gui03.PARAM_LENGTH, gui03.FRAME_KAPLAN_MEIER) == ""
    assert note(gui03.PARAM_HEIGHT, gui03.FRAME_INCLUDE) == ""


@pytest.mark.parametrize("param", [
    gui03.PARAM_LENGTH, gui03.PARAM_HEIGHT, gui03.PARAM_CURVATURE,
    gui03.PARAM_KINK_DENSITY,
])
def test_gui03_worker_does_not_test_across_centerlines(
        tk_app, tmp_path, monkeypatch, param):
    """
    Bundles on different centerlines get no test, whatever the quantity.
    中心線の違うバンドルは、どの計測量でも検定しない。

    Every measurement reads the line, so the difference may be the line alone.
    すべての測定は線を読むため、差は線の違いだけによるかもしれない。
    """
    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))

    lines = iter(("half_max_025w", "crest"))
    monkeypatch.setattr(app, "_count_bundles_by_line",
                        lambda paths: {next(lines): 1})
    monkeypatch.setattr(
        app, "_collect_bundle_values",
        lambda paths, param, unit, **kw: ([1.0, 2.0, 3.0], None, 3, 3, []))
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": param,
        "unit": gui03.UNIT_IMAGE,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 30.0, "step": 1.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert done["comparisons"] == []
    assert "crest" in done["comparison_note"]
    assert "half_max_025w" in done["comparison_note"]


def test_gui03_one_centerline_does_not_block_the_test():
    """
    One line, or none recorded, leaves the test to run.
    線が 1 種類、または記録が無ければ、検定は実行される。
    """
    assert gui03._centerline_block_note(set()) == ""
    assert gui03._centerline_block_note({"crest"}) == ""


def test_gui03_median_width_uses_the_bundles_that_record_one():
    """
    The group's width is in nanometers, over the bundles that record both values.
    グループの幅は nm で、両方の値を記録したバンドルにわたって求める。
    """
    width = gui03._median_width_nm
    assert width([]) is None
    assert width([_kink_condition(width_px=None)]) is None
    assert width([_kink_condition(pixel_nm=None)]) is None
    assert width([_kink_condition(pixel_nm=2.0, width_px=8.0),
                  _kink_condition(pixel_nm=5.0, width_px=6.0),
                  _kink_condition(width_px=None)]) == pytest.approx(23.0)


def test_gui03_worker_does_not_test_kinks_of_different_thresholds(
        tk_app, tmp_path, monkeypatch):
    """
    Kink density of bundles judged at different thresholds gets no test.
    異なるしきい値で判定したバンドルのキンク密度は検定しない。
    """
    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))

    thresholds = iter((150.0, 160.0))
    monkeypatch.setattr(
        gui03.App, "_bundle_kink_conditions",
        staticmethod(lambda paths: [_kink_condition(threshold=next(thresholds))]))
    monkeypatch.setattr(
        app, "_collect_bundle_values",
        lambda paths, param, unit, **kw: ([1.0, 2.0, 3.0], None, 3, 3, []))
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": gui03.PARAM_KINK_DENSITY,
        "unit": gui03.UNIT_IMAGE,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 30.0, "step": 1.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert done["comparisons"] == []
    assert "150, 160" in done["comparison_note"]
    assert done["results"][0]["width_nm"] == pytest.approx(16.0)


@pytest.mark.parametrize(
    "frame_mode, share",
    [(gui03.FRAME_INCLUDE, pytest.approx(0.5)), (gui03.FRAME_EXCLUDE, None)],
)
def test_gui03_include_reports_the_share_cut_by_the_frame(
        tk_app, tmp_path, monkeypatch, frame_mode, share):
    """
    `include` reports per group what share of its fibers reach the frame.
    `include` はグループごとに枠に達したファイバーの割合を報告する。
    """
    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))

    def _collect(paths, param, unit, **kwargs):
        kwargs["frame_report"].update(
            {"total": 4, "frame": 2, "lower_bound": 1, "unrecorded": []})
        return [100.0, 200.0, 300.0, 400.0], None, 4, 1, []

    monkeypatch.setattr(app, "_collect_bundle_values", _collect)
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": gui03.PARAM_LENGTH,
        "unit": gui03.UNIT_FIBER,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "frame_mode": frame_mode,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 3000.0, "step": 100.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert [r["frame_share"] for r in done["results"]] == [share, share]


def test_gui03_frame_weighted_image_unit_is_tested(
        tk_app, tmp_path, monkeypatch):
    """
    Miles-Lantuejoul at the image unit is tested as corrected.
    image 単位の Miles-Lantuejoul は補正したまま検定する。

    Each sample is the weighted median of one scan, an unweighted value, so
    the rank tests apply to it.
    各標本は 1 画像の重み付き中央値という重みのない値なので、順位検定を適用できる。
    """
    unit = gui03.UNIT_IMAGE
    app = tk_app(gui03.App)
    folders = []
    for name in ("A", "B"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ("sample" + gui03.BUNDLE_EXT)).write_bytes(b"")
        folders.append(str(folder))

    samples = iter(([100.0, 200.0, 300.0], [400.0, 500.0, 600.0]))

    def _collect(paths, param, unit, **kwargs):
        return next(samples), None, 3, 3, []

    monkeypatch.setattr(app, "_collect_bundle_values", _collect)
    app._worker_run({
        "groups": [
            {"id": n, "name": n, "color": "#1f77b4", "files": _gui03_bundles(f)}
            for n, f in zip(("A", "B"), folders)
        ],
        "param": gui03.PARAM_LENGTH,
        "unit": unit,
        "apply_exclusions": False,
        "apply_connection": False,
        "curvature_window": gui03.DEFAULT_CURVATURE_WINDOW_NM,
        "frame_mode": gui03.FRAME_MILES_LANTUEJOUL,
        "plot_type": gui03.PLOT_HISTOGRAM,
        "min_h": 0.0, "max_h": 3000.0, "step": 100.0,
        "yaxis_mode": "density", "display_mode": gui03.App.MODE_STACK,
        "show_height_text": True,
        "fig_w": 6.0, "fig_h": 3.0,
        "label_fs": 15.0, "tick_fs": 15.0, "ann_fs": 15.0,
        "group_name_fs": 15.0,
    })

    done = None
    while not app.ui_queue.empty():
        kind, payload = app.ui_queue.get_nowait()
        if kind == "done":
            done = payload
    assert done is not None
    assert done["comparison_note"] == ""
    assert len(done["comparisons"]) == 1
    assert done["comparisons"][0].mannwhitney_p == pytest.approx(0.1)


def test_gui04_marks_a_length_that_is_a_lower_bound():
    """
    A length cut by the frame or at a cut end is shown as a lower bound.
    枠または切断端で切れた長さは下限値として表示される。
    """
    assert gui04.length_is_lower_bound(_frame_stat(1.0, True, 0, float("nan")))
    assert gui04.length_is_lower_bound(_frame_stat(1.0, False, 1, 1.0))
    assert not gui04.length_is_lower_bound(_frame_stat(1.0, False, 0, 1.0))
    # Nothing recorded is not evidence of a cut.
    # 何も記録されていないことは切断の証拠ではない。
    assert not gui04.length_is_lower_bound(
        _frame_stat(1.0, None, None, float("nan")))


def _write_gui05_bundle(path, shape=(40, 60), scan_um=(1.5, 1.0), peak=10.0):
    """
    Write a small bundle holding what GUI05 reads: a height image with one
    bright line, its skeleton, and optionally a recorded scan size.
    GUI05 が読む内容だけを持つ小さなバンドルを書く。明るい線が 1 本ある高さ像、
    そのスケルトン、および任意で記録された走査範囲。
    """
    from lib.blosc2_io import save_bundle
    from lib.bundle_schema import SPATIAL_CALIBRATION_KEY, make_spatial_calibration

    rng = np.random.default_rng(0)
    image = rng.normal(0.0, 0.2, shape)
    row = shape[0] // 2
    image[row, 5:-5] = peak
    skeleton = np.zeros(shape, dtype=bool)
    skeleton[row, 5:-5] = True
    vlmeta = None
    if scan_um is not None:
        vlmeta = {SPATIAL_CALIBRATION_KEY:
                  make_spatial_calibration(scan_um[0], scan_um[1], "manual")}
    save_bundle(str(path), {"calibrated": image, "skeletonized": skeleton},
                vlmeta=vlmeta)
    return str(path)


def _gui05_idle(app) -> None:
    """Pump the event loop until GUI05's worker has no job left."""
    pump_until(app, lambda: app._outstanding == 0 and not app._relayout_pending,
               timeout=60)


@pytest.fixture
def gui05_app(tk_app):
    """
    Build a GUI05 window after collecting the windows of earlier tests.
    先行するテストのウィンドウを回収してから、GUI05 のウィンドウを作る。

    A destroyed window is freed by the garbage collector, whenever it next
    runs. GUI05 reads and draws in a worker thread, and a collection that
    starts there would release the Tk variables of an earlier test's window
    from a thread Tk does not accept calls from. Collecting here, in the main
    thread, leaves nothing of that kind for the worker.
    破棄されたウィンドウは、ガベージコレクタが次に動いたときに解放される。GUI05 は
    読み込みと描画をワーカースレッドで行うため、そこで回収が始まると、先行する
    テストのウィンドウが持つ Tk の変数が、Tk が呼び出しを受け付けないスレッドから
    解放されてしまう。ここ（メインスレッド）で回収して、ワーカーに残さない。
    """
    import gc

    gc.collect()
    return tk_app(gui05.App)


def test_gui05_window_builds(tk_app):
    _assert_window_built(tk_app(gui05.App))


def test_gui05_window_is_wide_enough_for_its_two_rows_of_controls(tk_app):
    """
    The window never takes a width that cuts off a row of controls, unless
    the screen itself is narrower.
    ウィンドウは、操作欄の行が切れる幅にはならない（画面自体がそれより狭い場合を
    除く）。
    """
    app = tk_app(gui05.App)
    needed = max(row.winfo_reqwidth() for row in app._control_rows) + 16
    # `apply_window_size` keeps a margin of 100 px from the screen edge.
    # `apply_window_size` は画面端から 100 px の余白を保つ。
    assert app.minsize()[0] == min(needed, app.winfo_screenwidth() - 100)
    assert len(app._control_rows) == 2


def test_gui05_opens_without_the_drop_package(tk_app, monkeypatch):
    """
    Without tkinterdnd2 the window still opens and says dropping is off.
    tkinterdnd2 が無くてもウィンドウは開き、ドロップが使えないことを知らせる。
    """
    import sys

    # A None entry makes `import tkinterdnd2` raise ImportError.
    monkeypatch.setitem(sys.modules, "tkinterdnd2", None)
    app = tk_app(gui05.App)
    _assert_window_built(app)
    assert not app.dnd_enabled
    assert "tkinterdnd2" in app.log_text.get("1.0", "end")


def test_gui05_lists_a_folder_and_keeps_going_past_an_unreadable_bundle(
        gui05_app, tmp_path):
    """
    A folder adds its bundles once; a file that is not a bundle is listed as
    unreadable instead of stopping the others.
    フォルダはその直下のバンドルを 1 回だけ追加する。バンドルでないファイルは
    読めなかったものとして並び、他の読み込みを止めない。
    """
    _write_gui05_bundle(tmp_path / "scan2.b2z")
    _write_gui05_bundle(tmp_path / "scan10.b2z", scan_um=None)
    (tmp_path / "broken.b2z").write_text("not a bundle", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_gui05_bundle(sub / "inner.b2z")

    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)

    # A folder is read in natural name order, scan2 before scan10, and the
    # subfolder is not searched.
    # フォルダは自然な名前順（scan2 が scan10 より前）で読み、サブフォルダは探さない。
    assert [item.name for item in app.items] == [
        "broken.b2z", "scan2.b2z", "scan10.b2z"]
    by_name = {item.name: item for item in app.items}
    assert by_name["broken.b2z"].error
    assert by_name["scan2.b2z"].scan_size_um == (1.5, 1.0)
    assert by_name["scan10.b2z"].scan_size_um is None
    assert by_name["scan2.b2z"].preview.shape == (40, 60)
    # Two images on the page, and the unreadable file in the list below it.
    # ページに 2 画像、その下の一覧に読めなかったファイル。
    assert [box[0] for box in app._page_boxes] == [
        by_name["scan2.b2z"].key, by_name["scan10.b2z"].key]
    assert len(app._tile_boxes) == 3
    assert str(app.btn_export.cget("state")) == "normal"

    # The same folder again, and one of its files named another way, add nothing.
    # 同じフォルダをもう一度、またその中のファイルを別の書き方で指定しても増えない。
    app.add_paths([str(tmp_path), str(tmp_path / "sub" / ".." / "scan2.b2z")])
    _gui05_idle(app)
    assert len(app.items) == 3


def test_gui05_keeps_the_physical_aspect_of_a_scan():
    """
    A thumbnail has the scan's physical proportions, not the pixel grid's.
    サムネイルは画素の格子ではなく、走査の物理的な縦横比を持つ。
    """
    # 255 x 767 stored pixels of a 3.75 x 1.25 um scan: one third as tall.
    # 3.75 × 1.25 µm の走査の保存画素 255 × 767。高さは幅の 3 分の 1。
    assert gui05.height_over_width((3.75, 1.25), (255, 767)) == pytest.approx(
        1 / 3, rel=0.01)
    # 512 lines of 256 pixels over a square scan are drawn square.
    # 正方形の走査を 512 行 × 256 画素で測ったものは、正方形に描く。
    assert gui05.height_over_width((2.0, 2.0), (511, 255)) == pytest.approx(
        1.0, rel=0.01)
    # Without a scan size the pixels are taken as square.
    # 走査範囲が無ければ、画素を正方形とみなす。
    assert gui05.height_over_width(None, (100, 400)) == pytest.approx(0.25)
    assert gui05.fit_box(0.25, 200, 200) == pytest.approx((200, 50))
    assert gui05.fit_box(4.0, 200, 200) == pytest.approx((50, 200))


def test_gui05_reducing_an_image_keeps_a_thin_fiber():
    """
    A one-pixel line survives a tenfold reduction, which decimation would lose.
    1 画素幅の線は 10 分の 1 に縮小しても残る。間引きでは失われる。
    """
    image = np.zeros((100, 100))
    image[:, 37] = 10.0
    reduced = gui05.resample_area(image, 10, 10)
    assert reduced.shape == (10, 10)
    # The line's column keeps a tenth of its height in every row.
    # 線のある列は、どの行でも高さの 10 分の 1 を保つ。
    assert reduced[:, 3] == pytest.approx(1.0)
    assert image[::10, ::10].max() == 0.0


def test_gui05_shortened_names_keep_their_ends():
    """A long file name is cut in the middle, so the range suffix stays."""
    name = "TunicateACTOCCNF_a_long_description_r100-300.b2z"
    short = gui05.elide_middle(name, lambda s: len(s) <= 24)
    assert len(short) == 24
    assert short.startswith("Tunicate") and short.endswith("100-300.b2z")
    assert gui05.elide_middle("short.b2z", lambda s: len(s) <= 24) == "short.b2z"
    assert gui05.elide_end("abcdefghij", lambda s: len(s) <= 5) == "abcd…"


def test_gui05_selecting_all_gives_every_image_one_color_range(gui05_app, tmp_path):
    """
    With every image selected, the entries show only what the images share,
    and what is entered becomes the range of all of them.
    すべての画像を選択すると、入力欄は画像に共通する値だけを表示し、入力した値が
    全画像の範囲になる。
    """
    _write_gui05_bundle(tmp_path / "low.b2z", peak=4.0)
    _write_gui05_bundle(tmp_path / "high.b2z", peak=30.0)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    low, high = app.items
    ranges = [app._vrange_for(item) for item in app.items]
    # The two automatic ranges share their lower bound and differ above.
    # 2 つの自動範囲は、下限が同じで上限が異なる。
    assert ranges[0][0] == ranges[1][0] and ranges[0][1] != ranges[1][1]

    assert app._on_select_all() == "break"
    assert app.selected == {low.key, high.key}
    # A value shown is a value all selected images have; the other is blank.
    # 表示される値は、選択した全画像が持つ値。もう一方は空欄。
    assert float(app.ent_vmin.get()) == ranges[0][0]
    assert app.ent_vmax.get() == ""

    # A blank entry is left alone: only vmin changes, each vmax stays.
    # 空欄の側は変えない。vmin だけが変わり、各画像の vmax はそのまま。
    app.ent_vmin.delete(0, "end")
    app.ent_vmin.insert(0, "0")
    assert app._commit_vrange()
    assert [app._vrange_for(item) for item in app.items] == [
        (0.0, ranges[0][1]), (0.0, ranges[1][1])]
    assert app.ent_vmax.get() == ""

    app.ent_vmax.insert(0, "20")
    assert app._commit_vrange()
    assert {app._vrange_for(item) for item in app.items} == {(0.0, 20.0)}
    assert (app.ent_vmin.get(), app.ent_vmax.get()) == ("0", "20")
    # The sheet is written with the range every image now has.
    # シートは、全画像が持つようになったこの範囲で書き出される。
    assert {entry.vrange for entry in app.sheet_entries()} == {(0.0, 20.0)}


def test_gui05_a_range_that_would_be_empty_changes_nothing(gui05_app, tmp_path,
                                                           silence_dialogs):
    """
    When one selected image would get a vmax not above its vmin, no image is
    changed.
    選択した画像の 1 枚でも vmax が vmin 以下になるなら、どの画像も変えない。
    """
    _write_gui05_bundle(tmp_path / "low.b2z", peak=4.0)
    _write_gui05_bundle(tmp_path / "high.b2z", peak=30.0)
    dialogs = silence_dialogs(gui05)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    before = [app._vrange_for(item) for item in app.items]
    app._on_select_all()

    # Above the lower image's vmax, below the higher one's.
    # 低い方の画像の vmax より上で、高い方の vmax より下。
    app.ent_vmin.delete(0, "end")
    app.ent_vmin.insert(0, str(before[0][1] + 1))
    assert not app._commit_vrange()
    assert [app._vrange_for(item) for item in app.items] == before
    assert all(item.manual_vrange is None for item in app.items)

    app.ent_vmin.delete(0, "end")
    app.ent_vmin.insert(0, "abc")
    assert not app._commit_vrange()
    assert [kind for kind, _title, _message in dialogs] == ["showerror", "showerror"]


def test_gui05_dropped_paths_with_spaces_are_split_correctly(
        gui05_app, monkeypatch):
    """
    One drop delivers a Tcl list; a path with spaces arrives in braces.
    1 回のドロップは Tcl リストで届き、空白を含むパスは波括弧で囲まれる。
    """
    from types import SimpleNamespace

    app = gui05_app
    received = []
    monkeypatch.setattr(app, "add_paths", lambda paths: received.extend(paths))
    event = SimpleNamespace(
        data="{C:/data/a folder} {C:/data/sample one.b2z} C:/data/日本語.b2z",
        action="copy")
    assert app._on_drop(event) == "copy"
    assert received == ["C:/data/a folder", "C:/data/sample one.b2z",
                        "C:/data/日本語.b2z"]


def test_gui05_removing_a_tile_deletes_no_file(gui05_app, tmp_path):
    """Taking a tile out of the gallery leaves the bundle on disk."""
    path = _write_gui05_bundle(tmp_path / "keep.b2z")
    _write_gui05_bundle(tmp_path / "other.b2z")
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)

    app.selected = {gui05.bundle_key(path)}
    app.on_remove_selected()
    assert [item.name for item in app.items] == ["other.b2z"]
    assert os.path.exists(path)
    # A removed bundle can be added again.
    # 外したバンドルは、もう一度追加できる。
    app.add_paths([path])
    _gui05_idle(app)
    assert len(app.items) == 2


def test_gui05_sheet_is_written_as_numbered_png_pages_or_one_pdf(
        gui05_app, tmp_path, monkeypatch):
    """
    A sheet of several pages is one PNG per page, or all pages in one PDF,
    each page at A4 size.
    複数ページのシートは、PNG ではページごとに 1 ファイル、PDF では全ページを
    1 ファイルに書き出す。各ページは A4 の大きさ。
    """
    import re

    from PIL import Image

    data = tmp_path / "data"
    data.mkdir()
    for name in ("a.b2z", "b.b2z", "c.b2z"):
        _write_gui05_bundle(data / name)
    (data / "broken.b2z").write_text("not a bundle", encoding="utf-8")
    opened = []
    monkeypatch.setattr(gui05, "open_in_default_app", opened.append)

    app = gui05_app
    app.add_paths([str(data)])
    _gui05_idle(app)
    app.cols_var.set("1")
    app.rows_var.set("2")
    # The unreadable bundle is left out: three images on two pages.
    # 読めないバンドルは含めない。3 画像で 2 ページ。
    assert [entry.name for entry in app.sheet_entries()] == ["a.b2z", "b.b2z", "c.b2z"]

    png = tmp_path / "sheet.png"
    monkeypatch.setattr(gui05.filedialog, "asksaveasfilename", lambda **kw: str(png))
    app.on_export()
    _gui05_idle(app)
    pages = [tmp_path / "sheet_p01.png", tmp_path / "sheet_p02.png"]
    assert all(page.exists() for page in pages) and not png.exists()
    with Image.open(pages[0]) as image:
        width, height = image.size
    # A4 portrait at the project's figure resolution.
    # プロジェクトの図の解像度での A4 縦。
    assert width == round(210 / 25.4 * gui05.FIGURE_SAVE_DPI)
    assert abs(height - 297 / 25.4 * gui05.FIGURE_SAVE_DPI) <= 1
    assert opened == [str(pages[0])]

    pdf = tmp_path / "sheet.pdf"
    monkeypatch.setattr(gui05.filedialog, "asksaveasfilename", lambda **kw: str(pdf))
    app.on_export()
    _gui05_idle(app)
    content = pdf.read_bytes()
    assert content.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b", content)) == 2
    assert opened[-1] == str(pdf)


def test_gui05_new_bundles_go_to_the_end_and_the_order_can_be_changed(
        gui05_app, tmp_path):
    """
    A later addition lands after what is shown, whatever its name; sorting
    and moving rearrange the gallery, and the sheet follows.
    後から追加したものは、名前にかかわらず表示中のものの後ろに入る。並べ替えと
    移動は一覧を並べ直し、シートもそれに従う。
    """
    first = tmp_path / "first"
    later = tmp_path / "later"
    first.mkdir()
    later.mkdir()
    for name in ("m.b2z", "z.b2z"):
        _write_gui05_bundle(first / name)
    early_name = _write_gui05_bundle(later / "a.b2z")
    os.utime(early_name, (1_000_000, 1_000_000))

    app = gui05_app
    app.add_paths([str(first)])
    _gui05_idle(app)
    app.add_paths([str(later)])
    _gui05_idle(app)

    def names():
        return [item.name for item in app.items]

    # "a" sorts first by name, yet it was added last.
    # 「a」は名前順では先頭だが、追加は最後だった。
    assert names() == ["m.b2z", "z.b2z", "a.b2z"]

    keys = {item.name: item.key for item in app.items}
    app.move_items([keys["a.b2z"]], keys["z.b2z"])
    assert names() == ["m.b2z", "a.b2z", "z.b2z"]
    app.move_items([keys["m.b2z"], keys["a.b2z"]], None)
    assert names() == ["z.b2z", "m.b2z", "a.b2z"]
    # Aiming at a tile that is itself moving means the next one that stays.
    # 動かす側のタイルを目標にした場合は、動かない次のタイルが目標になる。
    app.move_items([keys["z.b2z"], keys["m.b2z"]], keys["m.b2z"])
    assert names() == ["z.b2z", "m.b2z", "a.b2z"]
    assert [entry.name for entry in app.sheet_entries()] == names()

    # The sort menu holds the two orders: by name, then by date.
    # 並べ替えのメニューは 2 つの順を持つ。名前順、次に更新日時順。
    assert str(app.btn_sort.cget("state")) == "normal"
    app.sort_menu.invoke(0)
    assert names() == ["a.b2z", "m.b2z", "z.b2z"]
    app.move_items([keys["z.b2z"]], keys["a.b2z"])
    app.sort_menu.invoke(1)
    assert names()[0] == "a.b2z"


def test_gui05_a_drag_drops_in_front_of_or_behind_the_nearest_tile():
    """
    The left half of a tile means "before it", the right half "after it".
    タイルの左半分は「その前」、右半分は「その後」を表す。
    """
    boxes = [("a", 0, 0, 100, 100), ("b", 110, 0, 210, 100),
             ("c", 0, 110, 100, 210)]
    assert gui05.insertion_point(boxes, 20, 50) == ("a", (0, 0, 100))
    assert gui05.insertion_point(boxes, 90, 50) == ("b", (100, 0, 100))
    assert gui05.insertion_point(boxes, 200, 50) == ("c", (210, 0, 100))
    # Behind the last tile is the end of the gallery.
    # 最後のタイルの後ろは、一覧の末尾。
    assert gui05.insertion_point(boxes, 95, 150) == (None, (100, 110, 210))
    # Beside a row, in the margin, the pointer still aims at that row.
    # 行の横の余白にあるポインタも、その行を指す。
    assert gui05.insertion_point(boxes, 400, 160) == (None, (100, 110, 210))
    assert gui05.insertion_point([], 10, 10) is None


def test_gui05_the_gallery_is_laid_out_as_the_pages_of_the_sheet(
        gui05_app, tmp_path):
    """
    Images per row and rows per page arrange the screen as they do the sheet.
    1 行の画像数と 1 ページの行数は、シートと同じく画面の配置を決める。
    """
    for name in ("a.b2z", "b.b2z", "c.b2z"):
        _write_gui05_bundle(tmp_path / name)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)

    def boxes():
        _gui05_idle(app)
        return app._page_boxes

    app.cols_var.set("3")
    app.rows_var.set("2")
    one_row = boxes()
    # Three images side by side on one page.
    # 1 ページに 3 画像が横に並ぶ。
    assert len({box[2] for box in one_row}) == 1
    assert one_row[0][1] < one_row[1][1] < one_row[2][1]

    app.cols_var.set("1")
    stacked = boxes()
    # One image per row, two rows per page: the third starts a second page.
    # 1 行に 1 画像、1 ページに 2 行。3 枚目は 2 ページ目から始まる。
    assert len({box[1] for box in stacked}) == 1
    row_step = stacked[1][2] - stacked[0][2]
    assert stacked[2][2] - stacked[1][2] > row_step
    assert stacked[0][3] - stacked[0][1] > one_row[0][3] - one_row[0][1]


def test_gui05_bars_take_their_lines_from_the_image():
    """
    A scale bar and a color bar each take a line under the image, in the cell.
    スケールバーとカラーバーは、セルの中で画像の下にそれぞれ 1 行を取る。
    """
    plain = gui05.SheetLayout(4, 5, show_scale_bar=False,
                              show_colorbar=False).cell_parts(0, 1.0)
    # Both bars are part of a layout unless it turns them off.
    # 2 つのバーは、外さない限り配置に含まれる。
    both = gui05.SheetLayout(4, 5).cell_parts(0, 1.0)
    assert plain.scale_bar_y is None and plain.colorbar_y is None
    # Top to bottom: name, image, scale bar, color bar, inside the cell.
    # 上から順に、名前・画像・スケールバー・カラーバー。すべてセルの中。
    image_top = both.image[1] + both.image[3]
    cell_bottom = gui05.SheetLayout(4, 5).cell_box_mm(0)[1]
    assert (both.name_top > image_top > both.image[1] > both.scale_bar_y
            > both.colorbar_y > cell_bottom)
    assert both.image[3] < plain.image[3]
    # The name keeps its place, so cells with and without bars align.
    # 名前の位置は変わらない。バーの有無でセルの名前がずれない。
    assert both.name_top == pytest.approx(plain.name_top)

    # Larger fonts take taller lines, and the image gives up the height.
    # 大きなフォントは行を高くし、その分だけ画像が低くなる。
    large = gui05.SheetLayout(4, 5, name_pt=12.0, colorbar_pt=14.0).cell_parts(0, 1.0)
    assert large.image[3] < both.image[3]
    assert large.name_top == pytest.approx(plain.name_top)

    # The longest of 1, 2 or 5 times a power of ten within 30 % of the width.
    # 幅の 30 % 以内で、10 の累乗の 1・2・5 倍のうち最長のもの。
    assert gui05.scale_bar_for(5.0) == (1.0, "1 µm")
    assert gui05.scale_bar_for(2.0)[1] == "500 nm"
    assert gui05.scale_bar_for(0.32)[1] == "50 nm"
    assert gui05.scale_bar_for(20.0) == (5.0, "5 µm")


def test_gui05_sheet_page_prints_the_name_the_bar_labels_and_the_page_number():
    """
    A sheet page carries each image's name, the labels of its two bars and
    the page number, and no other text.
    シートのページに載る文字は、各画像の名前、2 つのバーのラベル、ページ番号だけ。
    """
    entry = gui05.SheetEntry(path="unused.b2z", name="scan.b2z", aspect=1.0,
                             vrange=(-1.0, 4.0), scale_bar=(0.25, "500 nm"))

    def page_texts(layout):
        figure, failed = gui05.render_sheet_page(
            [entry], layout, 2, 3, lambda path: np.zeros((8, 8)))
        assert not failed
        return figure, {text.get_text(): text for text in figure.texts}

    figure, texts = page_texts(gui05.SheetLayout(4, 5, name_pt=9.0))
    # The scale bar's length, and the two heights at the ends of the color bar.
    # スケールバーの長さと、カラーバーの両端の 2 つの高さ。
    assert set(texts) == {"scan.b2z", "500 nm", "-1", "4 nm", "2 / 3"}
    # The name stands above the image, at the size the layout gives it, and
    # the bar labels below it.
    # 名前は画像の上にあり、大きさは配置で指定したもの。バーのラベルは画像の下。
    image_axes = figure.axes[0].get_position()
    assert texts["scan.b2z"].get_position()[1] > image_axes.y1
    assert texts["500 nm"].get_position()[1] < image_axes.y0
    assert texts["4 nm"].get_position()[1] < texts["500 nm"].get_position()[1]
    assert texts["scan.b2z"].get_fontsize() == 9.0

    # With both bars turned off, only the name and the page number remain.
    # 2 つのバーを外すと、名前とページ番号だけが残る。
    _figure, texts = page_texts(gui05.SheetLayout(
        4, 5, show_scale_bar=False, show_colorbar=False))
    assert set(texts) == {"scan.b2z", "2 / 3"}


def test_gui05_zoom_is_chosen_or_changed_with_the_wheel(gui05_app, tmp_path):
    """
    A percentage draws the page at that share of the paper size, and Ctrl
    with the wheel steps from the size shown.
    百分率は、用紙の実寸に対するその割合でページを描く。Ctrl+ホイールは、
    表示中の大きさから倍率を刻む。
    """
    from types import SimpleNamespace

    _write_gui05_bundle(tmp_path / "a.b2z")
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    paper = app._paper_scale()

    app.cmb_zoom.current(2 + gui05.ZOOM_PRESETS.index(50))
    app.cmb_zoom.event_generate("<<ComboboxSelected>>")
    app.update()
    assert app._page_scale == pytest.approx(paper * 0.5)
    half_width = app._page_boxes[0][3] - app._page_boxes[0][1]

    assert app._on_zoom_wheel(SimpleNamespace(delta=120, num=0)) == "break"
    assert app._zoom_percent == pytest.approx(50 * gui05.ZOOM_WHEEL_FACTOR)
    assert app.cmb_zoom.get() == "55%"
    assert app._page_boxes[0][3] - app._page_boxes[0][1] > half_width
    app._on_zoom_wheel(SimpleNamespace(delta=-120, num=0))
    assert app._zoom_percent == pytest.approx(50.0)

    # The wheel cannot leave the range of zooms.
    # ホイールでは、倍率の範囲の外へは出られない。
    app.set_zoom_percent(1.0)
    assert app._zoom_percent == gui05.ZOOM_MIN_PERCENT
    app.set_zoom_percent(10_000.0)
    assert app._zoom_percent == gui05.ZOOM_MAX_PERCENT

    # From a fitted view the wheel steps from the size that view has.
    # 枠に合わせた表示からは、その表示の大きさを起点に刻む。
    app.cmb_zoom.current(0)
    app.cmb_zoom.event_generate("<<ComboboxSelected>>")
    app.update()
    fitted = app._page_scale / paper * 100.0
    app._on_zoom_wheel(SimpleNamespace(delta=120, num=0))
    assert app._zoom_percent == pytest.approx(
        min(gui05.ZOOM_MAX_PERCENT, fitted * gui05.ZOOM_WHEEL_FACTOR))


def test_gui05_font_sizes_reach_the_screen_and_the_sheet(gui05_app, tmp_path):
    """
    The three font sizes are part of the layout the sheet is written with.
    3 つのフォントサイズは、シートの書き出しに使う配置の一部になる。
    """
    _write_gui05_bundle(tmp_path / "a.b2z")
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    default_height = app._sheet_layout().cell_parts(0, 1.0).image[3]

    app.on_open_font_sizes()
    dialog = app._font_dialog
    assert dialog.winfo_exists()
    app.on_open_font_sizes()
    assert app._font_dialog is dialog

    app.font_vars[gui05.FONT_NAME].set("12.0")
    app.font_vars[gui05.FONT_SCALE_BAR].set("9.0")
    _gui05_idle(app)
    layout = app._sheet_layout()
    assert (layout.name_pt, layout.scale_bar_pt) == (12.0, 9.0)
    assert layout.cell_parts(0, 1.0).image[3] < default_height

    # An unusable value falls back to the default instead of breaking the view.
    # 使えない値は、表示を壊さずに既定値へ戻る。
    app.font_vars[gui05.FONT_COLORBAR].set("")
    assert app._sheet_layout().colorbar_pt == gui05.DEFAULT_FONT_PT[gui05.FONT_COLORBAR]

    app.on_reset_font_sizes()
    assert app._sheet_layout() == gui05.SheetLayout(
        gui05.DEFAULT_SHEET_COLS, gui05.DEFAULT_SHEET_ROWS)
    dialog.destroy()


def test_gui05_a_color_range_can_be_set_for_selected_images(gui05_app, tmp_path):
    """
    The vmin/vmax entries change the selected images alone, and "Auto"
    returns them to the automatic range.
    vmin/vmax の入力欄は選択した画像だけを変え、「自動」は自動範囲に戻す。
    """
    _write_gui05_bundle(tmp_path / "a.b2z", peak=4.0)
    _write_gui05_bundle(tmp_path / "b.b2z", peak=30.0)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    first, second = app.items
    automatic = app._vrange_for(first)

    # With nothing selected there is nothing to edit.
    # 何も選択していなければ、編集する対象が無い。
    assert str(app.ent_vmin.cget("state")) == "disabled"
    app._set_selection({first.key}, anchor=first.key)
    assert str(app.ent_vmin.cget("state")) == "normal"
    assert (float(app.ent_vmin.get()), float(app.ent_vmax.get())) == automatic

    app.ent_vmin.delete(0, "end")
    app.ent_vmin.insert(0, "0.5")
    app.ent_vmax.delete(0, "end")
    app.ent_vmax.insert(0, "3")
    assert app._commit_vrange()
    assert app._vrange_for(first) == (0.5, 3.0)
    assert second.manual_vrange is None
    assert app.sheet_entries()[0].vrange == (0.5, 3.0)

    # "Auto" returns the selected image to its automatic range.
    # 「自動」は、選択した画像を自動範囲に戻す。
    app.on_auto_range()
    assert first.manual_vrange is None
    assert app._vrange_for(first) == automatic
    assert (float(app.ent_vmin.get()), float(app.ent_vmax.get())) == automatic

    # It can always be pressed: with nothing to do it only says so.
    # いつでも押せる。することが無いときは、その旨を伝えるだけ。
    lines = len(app.log_text.get("1.0", "end").splitlines())
    app.on_auto_range()
    app._set_selection(set(), anchor=None)
    app.on_auto_range()
    assert len(app.log_text.get("1.0", "end").splitlines()) == lines + 2
    assert [item.manual_vrange for item in app.items] == [None, None]


def test_gui05_opens_the_selected_bundles_in_another_gui(gui05_app, tmp_path,
                                                         monkeypatch):
    """
    Each selected bundle opens in a window of its own; from four on, the user
    is asked first and can cancel.
    選択した各バンドルは、それぞれ別のウィンドウで開く。4 件以上では先に確認し、
    キャンセルできる。
    """
    for name in ("a.b2z", "b.b2z", "c.b2z", "d.b2z"):
        _write_gui05_bundle(tmp_path / name)
    (tmp_path / "broken.b2z").write_text("not a bundle", encoding="utf-8")
    launched = []
    asked = []
    answer = {"ok": False}

    def ask(title=None, message=None, **_kwargs):
        asked.append(message)
        return answer["ok"]

    monkeypatch.setattr(gui05, "launch_plugin",
                        lambda module, args: launched.append((module, list(args))))
    monkeypatch.setattr(gui05.messagebox, "askokcancel", ask)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    keys = {item.name: item.key for item in app.items}

    # Nothing selected: nothing opens.
    # 選択が無ければ、何も開かない。
    app.on_open_selected_in(gui05.PROFILER_MODULE, "GUI02")
    assert not launched and not asked

    # Three open at once, in display order, by their full paths.
    # 3 件はすぐに、表示の順に、絶対パスで開く。
    app._set_selection({keys["c.b2z"], keys["a.b2z"], keys["b.b2z"]}, anchor=None)
    app.on_open_selected_in(gui05.PROFILER_MODULE, "GUI02")
    assert not asked
    assert launched == [
        (gui05.PROFILER_MODULE, [os.path.abspath(str(tmp_path / name))])
        for name in ("a.b2z", "b.b2z", "c.b2z")]

    # Everything selected: the unreadable file is left out, and four ask first.
    # 全選択では、読めないファイルを除いた 4 件について、先に確認する。
    launched.clear()
    app._on_select_all()
    app.on_open_selected_in(gui05.TRACKER_MODULE, "GUI04")
    assert len(asked) == 1 and "4" in asked[0] and "GUI04" in asked[0]
    assert not launched

    answer["ok"] = True
    app.on_open_selected_in(gui05.TRACKER_MODULE, "GUI04")
    assert [module for module, _args in launched] == [gui05.TRACKER_MODULE] * 4


def test_gui05_opens_the_selection_in_one_gui03_window(gui05_app, tmp_path,
                                                       monkeypatch):
    """
    Every selected bundle goes to one GUI03 window, through a list file.
    選択した全バンドルは、一覧ファイルを通して 1 つの GUI03 ウィンドウへ渡る。

    GUI03 aggregates a group together, so the selection is one launch whatever
    its size, without the question the per-bundle windows ask first, and the
    unreadable file is left out.
    GUI03 はグループをまとめて集計するため、選択の件数にかかわらず起動は 1 回で、
    バンドルごとにウィンドウを開くときの確認は出さない。読めないファイルは渡さない。
    """
    from lib import plugin_launch

    for name in ("a.b2z", "b.b2z", "c.b2z", "d.b2z"):
        _write_gui05_bundle(tmp_path / name)
    (tmp_path / "broken.b2z").write_text("not a bundle", encoding="utf-8")
    launched = []
    asked = []
    monkeypatch.setattr(gui05, "launch_plugin",
                        lambda module, args: launched.append((module, list(args))))
    monkeypatch.setattr(gui05.messagebox, "askokcancel",
                        lambda *a, **k: asked.append(a) or True)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)

    app.on_open_selected_in_statistics()
    assert not launched

    app._on_select_all()
    app.on_open_selected_in_statistics()
    assert not asked
    assert len(launched) == 1
    module, args = launched[0]
    assert module == gui05.STATISTICS_MODULE
    assert args[0] == plugin_launch.PATH_LIST_FLAG
    assert plugin_launch.read_path_arguments(args) == [
        os.path.abspath(str(tmp_path / name))
        for name in ("a.b2z", "b.b2z", "c.b2z", "d.b2z")]


def test_gui05_sheet_carries_the_bars_shown_on_the_screen(gui05_app, tmp_path,
                                                          monkeypatch):
    """
    The bars are shown from the start and are written to the sheet; turning
    one off takes it out of the layout.
    バーは最初から表示され、シートにも書き出される。外すと配置から無くなる。
    """
    _write_gui05_bundle(tmp_path / "a.b2z")
    _write_gui05_bundle(tmp_path / "b.b2z", scan_um=None)
    monkeypatch.setattr(gui05, "open_in_default_app", lambda path: None)
    app = gui05_app
    app.add_paths([str(tmp_path)])
    _gui05_idle(app)
    assert app.scale_bar_var.get() and app.colorbar_var.get()
    app.colorbar_var.set(False)
    assert not app._sheet_layout().show_colorbar
    app.colorbar_var.set(True)
    _gui05_idle(app)

    entries = app.sheet_entries()
    # 30 % of a 1.5 um wide image allows a 200 nm bar; no scan size, no bar.
    # 幅 1.5 µm の画像の 30 % に収まるのは 200 nm のバー。走査範囲が無ければ、
    # バーも無い。
    assert entries[0].scale_bar[1] == "200 nm"
    assert entries[1].scale_bar is None
    assert app._sheet_layout().show_scale_bar and app._sheet_layout().show_colorbar

    png = tmp_path / "bars.png"
    monkeypatch.setattr(gui05.filedialog, "asksaveasfilename", lambda **kw: str(png))
    app.on_export()
    _gui05_idle(app)
    assert png.exists()
