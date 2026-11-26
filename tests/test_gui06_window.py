# -*- coding: utf-8 -*-
"""
Window tests for GUI06, the bundle editor.
バンドル編集ツール GUI06 の、ウィンドウを開くテスト。

The functions behind the window are tested without one in
``test_bundle_edit.py``, ``test_bundle_editor.py``, ``test_kink_editor.py`` and
``test_gui06_layers.py``. These tests cover what only the window does: which
controls it offers for which layer, that pointer events on the image reach
the editor, that a stage run in the worker thread is taken over, and that the
layer rows stay drawn when they are reordered.
ウィンドウの裏の関数は、``test_bundle_edit.py``・``test_bundle_editor.py``・
``test_kink_editor.py``・``test_gui06_layers.py`` でウィンドウを開かずに確かめている。
ここで確かめるのは、ウィンドウだけが行うことである。どのレイヤーでどの操作を
提示するか、画像の上のポインタ操作がエディタに届くこと、ワーカースレッドで実行した
段の結果を取り込むこと、並べ替えてもレイヤーの行が描かれたままであること。
"""

import os
import shutil

import numpy as np
import pytest

import guis.GUI06_Bundle_Editor as gui06
from afm_nanofiber_analyzer.blosc2_io import load_bundle, load_bundle_meta, save_bundle
from afm_nanofiber_analyzer.bundle_edit import fiber_pixels
from afm_nanofiber_analyzer.bundle_schema import FIBER_MASK_KEY, MANUAL_EDIT_KEY
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file
from tests.conftest import pump_until, requires_tk, write_synthetic_fiber_txt

pytestmark = requires_tk


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    """
    A synthetic scan analyzed beside itself, shared across this module.
    合成走査を、その隣に解析結果を書く形で解析したもの。モジュール内で共有する。
    """
    folder = tmp_path_factory.mktemp("gui06_window")
    txt = write_synthetic_fiber_txt(folder)
    return txt, process_file(txt, ProcParams()).bundle_path


@pytest.fixture
def workspace(analyzed, tmp_path):
    """
    A private copy of the analyzed scan and its bundle; returns the bundle path.
    解析した走査とそのバンドルの、テストごとの写し。バンドルのパスを返す。
    """
    txt, bundle = analyzed
    shutil.copy2(txt, os.path.join(tmp_path, os.path.basename(txt)))
    return shutil.copy2(bundle, os.path.join(tmp_path, os.path.basename(bundle)))


@pytest.fixture
def window(tk_app, silence_dialogs, monkeypatch):
    """
    Build a GUI06 window whose dialogs are recorded and whose questions say yes.
    ダイアログを記録に置き換え、確認にはすべて「はい」と答える GUI06 のウィンドウを作る。

    Returns the window and the list its dialogs are recorded in.
    ウィンドウと、ダイアログが記録されるリストを返す。
    """
    import gc

    # A window of an earlier test is freed when the collector next runs; done
    # here, in the main thread, it cannot start in this window's worker.
    # 先行するテストのウィンドウは、ガベージコレクタが次に動いたときに解放される。
    # ここ（メインスレッド）で済ませれば、このウィンドウのワーカーで始まることは無い。
    gc.collect()
    dialogs = silence_dialogs(gui06)

    def ask(title=None, message=None, *args, **kwargs):
        dialogs.append(("askyesno", title, message))
        return True

    monkeypatch.setattr(gui06.messagebox, "askyesno", ask)
    return tk_app(gui06.App), dialogs


def _settle(app) -> None:
    """
    Pump the event loop until nothing is loading, running or being traced.
    読み込み・実行・追跡のどれも動いていない状態になるまで、イベントループを回す。
    """
    def idle() -> bool:
        return (not app._loading and not app._busy and not app._retracing
                and app._retrace_after is None and app._render_job is None
                and (app.state is None or not app.state.tracks_stale))

    pump_until(app, idle, timeout=120)


def _open(app, path) -> None:
    """
    Open a bundle and wait until it is shown.
    バンドルを開き、表示されるまで待つ。
    """
    app.open_bundle(path)
    pump_until(app, lambda: app.session is not None and not app._loading, timeout=120)
    _settle(app)


def _usable(buttons) -> set:
    """
    Return the keys of the buttons that are enabled.
    有効になっているボタンのキーを返す。
    """
    return {key for key, button in buttons.items() if str(button.cget("state")) == "normal"}


def _canvas_event(app, sequence, x, y) -> None:
    """
    Send a pointer event to the image at a position in image pixels.
    画像の上の、画像の画素で指定した位置へ、ポインタのイベントを送る。
    """
    display = app.ax.transData.transform((x, y))
    app.canvas.get_tk_widget().event_generate(
        sequence, x=int(round(display[0])),
        y=int(round(app.fig.bbox.height - display[1])))


def _fiber_middle(app):
    """
    Return ``(x, y)`` of the middle pixel of the longest fiber on screen.
    画面にある最も長い繊維の、中央の画素の ``(x, y)`` を返す。
    """
    fiber = max(app.state.fibers, key=lambda candidate: len(candidate.xtrack))
    track_x, track_y = fiber_pixels(fiber)
    middle = len(track_x) // 2
    return int(track_x[middle]), int(track_y[middle])


def test_window_builds_with_nothing_to_edit(window):
    """
    Before a bundle is opened every editing control is off.
    バンドルを開く前は、編集の操作はすべて無効である。
    """
    app, _dialogs = window

    assert app.winfo_exists() and app.title() and app.winfo_children()
    assert not _usable(app.tool_buttons)
    assert not _usable(app.stage_buttons)
    assert str(app.save_button.cget("state")) == "disabled"


def test_opened_bundle_offers_the_tools_of_the_chosen_layer(window, workspace):
    """
    Each layer enables its own tools; a layer that is not edited enables none.
    各レイヤーは、それ自身のツールだけを有効にする。編集しないレイヤーは何も有効に
    しない。
    """
    app, dialogs = window
    _open(app, workspace)

    assert [layer.key for layer in app.layers] == [
        key for key, *_rest in gui06.DEFAULT_STACK]
    assert not dialogs
    assert not _usable(app.tool_buttons)
    assert _usable(app.stage_buttons) == set(app.stage_buttons)

    app.select_layer(gui06.LAYER_CALIBRATED)
    assert app.active_layer is None

    app.select_layer(gui06.LAYER_BINARIZED)
    assert _usable(app.tool_buttons) == {
        gui06.TOOL_NONE, gui06.TOOL_PENCIL, gui06.TOOL_ERASER}
    app.select_layer(gui06.LAYER_SKELETON)
    assert _usable(app.tool_buttons) == {gui06.TOOL_NONE, gui06.TOOL_ERASER}
    app.select_layer(gui06.LAYER_KINKS)
    assert _usable(app.tool_buttons) == {
        gui06.TOOL_NONE, gui06.TOOL_ADD_KINK, gui06.TOOL_ERASE_KINK,
        gui06.TOOL_MOVE_KINK, gui06.TOOL_EDIT_KINK}
    assert str(app.brush_spin.cget("state")) == "disabled"


def test_bundle_without_its_raw_image_warns_and_drops_two_layers(window, workspace):
    """
    Without the input file the raw image and the ridge mask are not listed.
    入力ファイルが無ければ、生の画像とリッジマスクは並べない。
    """
    app, dialogs = window
    os.remove(os.path.splitext(workspace)[0] + ".txt")
    _open(app, workspace)

    keys = [layer.key for layer in app.layers]
    assert gui06.LAYER_RAW not in keys and gui06.LAYER_FIBER_MASK not in keys
    assert [kind for kind, _title, _message in dialogs] == ["showwarning"]
    assert gui06.STAGE_BACKGROUND not in _usable(app.stage_buttons)
    assert gui06.STAGE_BINARIZE in _usable(app.stage_buttons)


def test_bundle_of_an_older_format_is_shown_and_not_edited(window, workspace, tmp_path):
    """
    A bundle that is not of the current format opens with editing switched off.
    現在の形式でないバンドルは、編集を無効にして開く。
    """
    app, _dialogs = window
    meta = load_bundle_meta(workspace)
    meta["version"] = "1.7"
    older = os.path.join(tmp_path, "older.b2z")
    save_bundle(older, load_bundle(workspace), vlmeta=meta)
    _open(app, older)

    assert app.state is None and app.layers
    app.select_layer(gui06.LAYER_KINKS)
    assert app.active_layer is None
    assert not _usable(app.stage_buttons)
    assert "1.7" in app.log_text.get("1.0", "end")


def test_eraser_dragged_over_the_image_clears_the_chosen_mask(window, workspace):
    """
    Pointer events on the image reach the mask of the chosen layer.
    画像の上のポインタ操作が、選んだレイヤーのマスクに届く。
    """
    app, _dialogs = window
    _open(app, workspace)
    x, y = _fiber_middle(app)
    app.set_layer_visible(gui06.LAYER_BINARIZED, True)
    app.select_layer(gui06.LAYER_BINARIZED)
    app.tool_var.set(gui06.TOOL_ERASER)
    app.brush_var.set("5")
    _settle(app)
    assert app.state.binarized[y, x]

    _canvas_event(app, "<Button-1>", x - 8, y)
    _canvas_event(app, "<Motion>", x, y)
    _canvas_event(app, "<Motion>", x + 8, y)
    _canvas_event(app, "<ButtonRelease-1>", x + 8, y)
    _settle(app)

    assert not app.state.binarized[y, x - 8:x + 9].any()
    assert app._rows[gui06.LAYER_SKELETON].stale_var.get()
    assert app._rows[gui06.LAYER_KINKS].stale_var.get()
    assert not app._rows[gui06.LAYER_BINARIZED].stale_var.get()
    assert str(app.save_button.cget("state")) == "normal"

    app.on_undo()
    _settle(app)
    assert app.state.binarized[y, x]
    assert not app._rows[gui06.LAYER_SKELETON].stale_var.get()


def test_stage_run_again_is_taken_over_and_redrawn(window, workspace):
    """
    A stage runs in the worker thread and its result replaces the layer's.
    段はワーカースレッドで動き、その結果がレイヤーの内容を置き換える。
    """
    app, dialogs = window
    _open(app, workspace)
    x, y = _fiber_middle(app)
    app.select_layer(gui06.LAYER_SKELETON)
    app.tool_var.set(gui06.TOOL_ERASER)
    app.brush_var.set("1")
    fibers = len(app.state.fibers)
    _canvas_event(app, "<Button-1>", x, y)
    _canvas_event(app, "<ButtonRelease-1>", x, y)
    _settle(app)
    # The cut fiber is traced again without being asked.
    # 切った繊維は、求められなくても追跡し直される。
    assert not app.state.skeleton[y, x]
    assert len(app.state.fibers) == fibers + 1

    app.on_run_stage(gui06.STAGE_SKELETONIZE)
    assert app._busy and not _usable(app.stage_buttons)
    _settle(app)

    # The stage computed the skeleton afresh; the hand edit is asked about
    # first, and is gone.
    # 段はスケルトンを計算し直す。手の変更については先に確認し、変更は残らない。
    assert [kind for kind, _title, _message in dialogs] == ["askyesno"]
    assert app.state.skeleton[y, x]
    assert len(app.state.fibers) == fibers
    assert app._layer(gui06.LAYER_SKELETON).data is app.state.skeleton
    assert len(app._layer(gui06.LAYER_CENTERLINE).data) == fibers


def test_kink_tools_place_a_kink_and_set_its_angle(window, workspace):
    """
    A click with the add tool puts a kink on the fiber; dragging an arm end sets its angle.
    追加のツールでクリックすると繊維にキンクが置かれ、腕の端をドラッグすると角度が決まる。
    """
    app, _dialogs = window
    _open(app, workspace)
    x, y = _fiber_middle(app)
    app.select_layer(gui06.LAYER_KINKS)
    app.tool_var.set(gui06.TOOL_ADD_KINK)
    app.ax.set_xlim(x - 40, x + 40)
    app.ax.set_ylim(y + 40, y - 40)
    app.canvas.draw()

    _canvas_event(app, "<Button-1>", x, y)
    _canvas_event(app, "<ButtonRelease-1>", x, y)
    _settle(app)
    assert app.editor.kink_pixels() == [(x, y)]
    placed = app.editor.kink_values((x, y))[0]

    app.tool_var.set(gui06.TOOL_EDIT_KINK)
    _canvas_event(app, "<Button-1>", x, y)
    _canvas_event(app, "<ButtonRelease-1>", x, y)
    _settle(app)
    assert app._selected_kink == (x, y)
    assert len(app._arm_artists) == 3
    _angle, points, _by_hand = app._shown_arms()
    end = points[3]
    track_x, track_y = fiber_pixels(
        max(app.state.fibers, key=lambda candidate: len(candidate.xtrack)))
    pixels = list(zip(track_x.tolist(), track_y.tolist()))
    target = pixels[min(pixels.index(app.editor.arm_ends((x, y))[1]) + 15, len(pixels) - 2)]

    _canvas_event(app, "<Button-1>", end[0], end[1])
    _canvas_event(app, "<Motion>", target[0], target[1])
    _canvas_event(app, "<ButtonRelease-1>", target[0], target[1])
    _settle(app)

    assert app.editor.arm_ends((x, y))[1] == target
    assert app.editor.kink_values((x, y))[0] != placed


def test_reordered_layer_rows_stay_drawn(window, workspace):
    """
    Moving a layer keeps every widget of every row on screen.
    レイヤーを動かしても、どの行のどのウィジェットも画面に残る。
    """
    app, _dialogs = window
    _open(app, workspace)
    app.update()

    assert app.move_layer(gui06.LAYER_KINKS, 3)
    _settle(app)
    app.update()

    assert [layer.key for layer in app.layers][:3] == [
        gui06.LAYER_CENTERLINE, gui06.LAYER_SKELETON, gui06.LAYER_KINKS]
    for row in app._rows.values():
        for part in row.winfo_children():
            assert all(child.winfo_ismapped() for child in part.winfo_children())


def test_save_shortcuts_follow_the_opened_bundle(window, workspace, monkeypatch):
    """
    Ctrl+S saves over an edited bundle and asks for a name otherwise; Ctrl+Shift+S asks.
    Ctrl+S は編集済みのバンドルには上書き保存し、それ以外は名前を尋ねる。Ctrl+Shift+S は尋ねる。

    The bundle the analysis wrote is never saved over, so while it is edited
    "上書き保存" stays off and Ctrl+S opens the save dialog, as Save does for a
    document never saved. Neither shortcut acts while nothing has changed.
    解析が書いたバンドルには上書きしないため、それを編集している間「上書き保存」は
    押せず、Ctrl+S は保存ダイアログを開く。一度も保存していない文書に対する
    「上書き保存」と同じ動きである。変更が無い間は、どちらのショートカットも何もしない。
    """
    app, dialogs = window
    stem = os.path.splitext(workspace)[0]
    edited, copy = stem + "_edited.b2z", stem + "_copy.b2z"
    targets = [edited, copy]
    offered = []

    def ask_name(**kwargs):
        offered.append(kwargs.get("initialfile"))
        return targets.pop(0)

    monkeypatch.setattr(gui06.filedialog, "asksaveasfilename", ask_name)
    _open(app, workspace)
    app.focus_force()
    app.update()

    def paint(add):
        x, y = _fiber_middle(app)
        app.state.begin_stroke(gui06.LAYER_FIBER_MASK, add)
        app.state.paint(x - 3, y, x + 3, y, 5.0)
        app.state.end_stroke()
        app._update_controls()

    def usable(button):
        return str(button.cget("state")) == "normal"

    app.event_generate("<Control-s>")
    app.event_generate("<Control-Shift-S>")
    assert offered == [] and dialogs == []
    assert not usable(app.overwrite_button) and not usable(app.save_button)

    paint(False)
    assert not usable(app.overwrite_button) and usable(app.save_button)
    app.event_generate("<Control-s>")
    _settle(app)
    assert offered == [os.path.basename(edited)]
    assert app.session.bundle_path == edited
    assert not usable(app.overwrite_button)

    paint(True)
    assert usable(app.overwrite_button)
    dialogs.clear()
    app.event_generate("<Control-s>")
    _settle(app)
    # Saved over after its own confirmation, without asking for a name.
    # 名前を尋ねず、上書きの確認のあとで上書き保存した。
    assert offered == [os.path.basename(edited)]
    assert dialogs[0] == ("askyesno", gui06._("確認"), gui06._(
        "{name} に上書き保存しますか？").format(name=os.path.basename(edited)))
    assert len(load_bundle_meta(edited)[MANUAL_EDIT_KEY]) == 2
    assert app.session.bundle_path == edited and not app.state.modified

    paint(False)
    app.event_generate("<Control-Shift-S>")
    _settle(app)
    # An edited bundle is offered its own name, and another one was chosen.
    # 編集済みのバンドルには自分の名前が提案され、ここでは別の名前を選んだ。
    assert offered == [os.path.basename(edited)] * 2
    assert app.session.bundle_path == copy
    assert len(load_bundle_meta(copy)[MANUAL_EDIT_KEY]) == 3


def test_saved_edit_is_reopened_with_its_mask(window, workspace):
    """
    Saving writes the edited bundle beside the analysis and opens it.
    保存すると、編集したバンドルを解析結果の隣に書き出し、それを開く。
    """
    app, dialogs = window
    _open(app, workspace)
    x, y = _fiber_middle(app)
    app.state.begin_stroke(gui06.LAYER_FIBER_MASK, False)
    app.state.paint(x - 5, y, x + 5, y, 9.0)
    app.state.end_stroke()
    path = os.path.splitext(workspace)[0] + "_edited.b2z"

    assert not app.save_to(workspace)
    assert app.save_to(path)
    _settle(app)

    assert app.session.bundle_path == path
    assert not app.state.modified
    saved = load_bundle(path)
    assert not saved[FIBER_MASK_KEY][y, x]
    record = load_bundle_meta(path)[MANUAL_EDIT_KEY][-1]
    assert record["edited_layers"] == [gui06.LAYER_FIBER_MASK]
    # The stale results were asked about before saving, and refusing the
    # analyzed bundle as the target was an error.
    # 古い結果については保存前に確認し、解析バンドルを保存先にしたことはエラーに
    # なる。
    assert [kind for kind, _title, _message in dialogs] == ["showerror", "askyesno"]
    assert np.array_equal(app.state.fiber_mask, saved[FIBER_MASK_KEY].astype(bool))
    # The reopened bundle shows the heights as stale, as they were saved: the
    # mask was changed and the background stage not run again.
    # 開き直したバンドルは、保存したときのとおり、高さを古いものとして表示する。
    # マスクを変更したあと、背景補正を再実行していないためである。
    assert app._rows[gui06.LAYER_CALIBRATED].stale_var.get()
    assert not app._rows[gui06.LAYER_FIBER_MASK].stale_var.get()
