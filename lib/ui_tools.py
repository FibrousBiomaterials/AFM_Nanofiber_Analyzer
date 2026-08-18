# -*- coding: utf-8 -*-
"""
Provide shared tkinter UI utilities used across the GUI.
GUI 全体で共通利用する tkinter ユーティリティを提供する。

The helpers cover shared theme and plotting defaults, file-save dialogs,
scrollable widgets, worker-to-UI queue draining, committed-entry handling,
logging, and tooltips.
共通テーマ・描画既定値、ファイル保存ダイアログ、スクロール可能ウィジェット、
ワーカーから UI へのキュー処理、入力欄の確定管理、ログ、ツールチップを扱う。
"""

import math
import os
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np

from lib.translator import _

# Resolution used when saving publication-ready PNG figures.
# 論文用 PNG 保存時の解像度。
FIGURE_SAVE_DPI = 300


def setup_ttk_theme(root: tk.Misc, *, theme: str = "clam",
                    unconfirmed_bg: str = "#cfe6ff") -> str:
    """
    Apply the shared ttk theme and styles used by the GUI windows.

    Returns the theme background color so callers can also apply it to
    non-ttk widgets such as tk.Tk, tk.Frame, or matplotlib toolbars.
    """
    style = ttk.Style(root)
    try:
        style.theme_use(theme)
    except tk.TclError:
        pass
    style.configure("Unconfirmed.TEntry", fieldbackground=unconfirmed_bg)

    bg = style.lookup("TFrame", "background") or "#dcdad5"

    # clam gives TCombobox its own -foreground/-fieldbackground maps, which
    # replace (not extend) the root style's "disabled -> gray" rule. A disabled
    # combobox therefore keeps black text, and because it has left the readonly
    # state it falls back to a white field, so an unavailable combobox looks
    # *more* editable than a usable one. Re-insert disabled entries ahead of the
    # theme's own so a disabled combobox dims like every other disabled widget.
    # clam の TCombobox は独自の -foreground/-fieldbackground map を持ち、ルート
    # スタイルの「disabled は灰色」を継承せず上書きする。そのため無効化しても
    # 文字は黒のままで、readonly 状態を抜けた分だけ地色が白へ戻り、選択可能な
    # ものより編集可能に見えてしまう。テーマ既定の前に disabled を差し込む。
    disabled_fg = style.lookup(".", "foreground", ["disabled"]) or "#999999"
    for option, value in (("foreground", disabled_fg), ("fieldbackground", bg)):
        style.map("TCombobox",
                  **{option: [("disabled", value)]
                     + list(style.map("TCombobox", option))})

    try:
        root.configure(bg=bg)
    except tk.TclError:
        pass
    return bg


def localized_combobox_width(values, min_width=4, max_width=16):
    """
    Return a bounded Combobox width for translated labels.
    翻訳後ラベルに合わせた上限付き Combobox 幅を返す。
    """
    if not values:
        return min_width
    try:
        font = tkfont.nametofont("TkDefaultFont")
        zero_width = max(font.measure("0"), 1)
        label_width = max(font.measure(str(value)) for value in values)
        width = int(label_width / zero_width) + 4
    except tk.TclError:
        width = max(len(str(value)) for value in values) + 2
    return max(min_width, min(max_width, width))


def rewrite_entries(pairs, *, formatter=str) -> None:
    """Rewrite Entry widgets with committed values, ignoring destroyed widgets.

    Entry に確定済み値を再書き込みする。``formatter`` は値を文字列に変換する
    呼び出し可能オブジェクト（既定は ``str``）。
    """
    for entry, value in pairs:
        try:
            entry.delete(0, tk.END)
            entry.insert(0, formatter(value))
        except (tk.TclError, AttributeError):
            pass


def mark_entry_state(entry, committed_str) -> None:
    """Mark an Entry as normal or unconfirmed by comparing it with committed text."""
    try:
        current = entry.get()
    except tk.TclError:
        return
    style_name = "TEntry" if current == committed_str else "Unconfirmed.TEntry"
    try:
        entry.configure(style=style_name)
    except tk.TclError:
        pass


def _set_text_state(text_widget, state: str) -> None:
    try:
        text_widget.configure(state=state)
    except (tk.TclError, AttributeError):
        pass


def append_log(text_widget, msg, *, timestamp: bool = True,
               readonly: bool = True) -> None:
    """Append one log message to a Text widget and keep the newest line visible."""
    line = str(msg).rstrip()
    if timestamp:
        line = "[{ts}] {line}".format(ts=time.strftime("%H:%M:%S"), line=line)

    if readonly:
        _set_text_state(text_widget, "normal")
    try:
        text_widget.insert(tk.END, line + "\n")
        text_widget.see(tk.END)
    except (tk.TclError, AttributeError):
        pass
    finally:
        if readonly:
            _set_text_state(text_widget, "disabled")


def replace_log_tail(text_widget, msg, *, readonly: bool = True) -> None:
    """Replace the previous log line with text, used for progress updates."""
    if readonly:
        _set_text_state(text_widget, "normal")
    try:
        text_widget.delete("end-2l", "end-1l")
        text_widget.insert("end-1c", str(msg).rstrip() + "\n")
        text_widget.see(tk.END)
    except (tk.TclError, AttributeError):
        pass
    finally:
        if readonly:
            _set_text_state(text_widget, "disabled")


def clear_text_widget_log(text_widget, *, readonly: bool = True) -> None:
    """Remove all text from a log Text widget, toggling readonly state as needed."""
    if readonly:
        _set_text_state(text_widget, "normal")
    try:
        text_widget.delete("1.0", tk.END)
    except (tk.TclError, AttributeError):
        pass
    finally:
        if readonly:
            _set_text_state(text_widget, "disabled")


def save_text_widget_log(parent, text_widget, *, initial_dir=None,
                         initialfile: str = "log.txt",
                         title=None, empty_warning: bool = False,
                         log_cb=None, success_message=None,
                         error_title=None, failure_message=None):
    """Save a Text widget's content as UTF-8 text through a file dialog."""
    try:
        content = text_widget.get("1.0", "end-1c")
    except (tk.TclError, AttributeError):
        content = ""

    if empty_warning and not content.strip():
        messagebox.showwarning(
            _("ログ無し"),
            _("保存するログがありません。"),
            parent=parent,
        )
        return None

    kwargs = {
        "parent": parent,
        "title": title or _("ログを保存"),
        "defaultextension": ".txt",
        "initialfile": initialfile,
        "filetypes": [(_("Text"), "*.txt"), (_("All"), "*.*")],
    }
    if initial_dir:
        kwargs["initialdir"] = initial_dir
    path = filedialog.asksaveasfilename(**kwargs)
    if not path:
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as exc:
        messagebox.showerror(
            error_title or _("保存失敗"),
            (failure_message or _("ログの保存に失敗しました:\n{e}")).format(e=exc),
            parent=parent,
        )
        return None

    if log_cb is not None:
        msg = success_message or _("ログを保存しました: {path}")
        log_cb(msg.format(path=path))
    return path


def create_scrolled_text(parent, *, scrollbar_side="right",
                         text_side="left", **text_kwargs):
    """
    Create a Text widget with a vertical scrollbar packed beside it.
    縦スクロールバー付きの Text ウィジェットを作成する。

    Parameters
    ----------
    parent
        Parent widget that receives the Text and scrollbar.
        Text とスクロールバーを配置する親ウィジェット。
    scrollbar_side
        Pack side for the vertical scrollbar.
        縦スクロールバーを pack する側。
    text_side
        Pack side for the Text widget.
        Text ウィジェットを pack する側。
    **text_kwargs
        Keyword arguments passed to ``tk.Text``.
        ``tk.Text`` に渡すキーワード引数。

    Returns
    -------
    tuple
        ``(text_widget, scrollbar)`` created and linked together.
        作成して相互接続した ``(text_widget, scrollbar)``。
    """
    text_widget = tk.Text(parent, **text_kwargs)
    scrollbar = ttk.Scrollbar(parent, orient="vertical",
                              command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    text_widget.pack(side=text_side, fill="both", expand=True)
    scrollbar.pack(side=scrollbar_side, fill="y")
    return text_widget, scrollbar


def create_scrolled_treeview(parent, *, columns=(), show="headings",
                             selectmode=None, height=None,
                             headings=None, column_options=None,
                             scrollbar_side="right", tree_side="left",
                             tree_pack_kwargs=None,
                             scrollbar_pack_kwargs=None,
                             **tree_kwargs):
    """
    Create a Treeview with a vertical scrollbar and optional column metadata.
    縦スクロールバー付き Treeview を作成し、任意の列メタデータを設定する。

    Parameters
    ----------
    parent
        Parent widget that receives the Treeview and scrollbar.
        Treeview とスクロールバーを配置する親ウィジェット。
    columns
        Treeview data columns.
        Treeview のデータ列。
    show
        Treeview ``show`` option.
        Treeview の ``show`` オプション。
    selectmode
        Selection mode passed to Treeview when provided.
        指定時に Treeview へ渡す選択モード。
    height
        Requested Treeview row height when provided.
        指定時に Treeview へ渡す表示行数。
    headings
        Mapping from column key to heading text.
        列キーから見出し文字列への対応。
    column_options
        Mapping from column key to ``tree.column`` keyword arguments.
        列キーから ``tree.column`` キーワード引数への対応。
    tree_pack_kwargs
        Optional keyword arguments merged into the Treeview ``pack`` call.
        Treeview の ``pack`` 呼び出しに追加する任意のキーワード引数。
    scrollbar_pack_kwargs
        Optional keyword arguments merged into the scrollbar ``pack`` call.
        スクロールバーの ``pack`` 呼び出しに追加する任意のキーワード引数。

    Returns
    -------
    tuple
        ``(tree, scrollbar)`` created and linked together.
        作成して相互接続した ``(tree, scrollbar)``。
    """
    kwargs = dict(tree_kwargs)
    kwargs["columns"] = columns
    kwargs["show"] = show
    if selectmode is not None:
        kwargs["selectmode"] = selectmode
    if height is not None:
        kwargs["height"] = height

    tree = ttk.Treeview(parent, **kwargs)
    for col, text in (headings or {}).items():
        tree.heading(col, text=text)
    for col, options in (column_options or {}).items():
        tree.column(col, **options)

    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree_pack = {"side": tree_side, "fill": "both", "expand": True}
    tree_pack.update(tree_pack_kwargs or {})
    scrollbar_pack = {"side": scrollbar_side, "fill": "y"}
    scrollbar_pack.update(scrollbar_pack_kwargs or {})
    tree.pack(**tree_pack)
    scrollbar.pack(**scrollbar_pack)
    return tree, scrollbar


# Widget classes whose Tk class bindings consume <MouseWheel> to change their
# own value (ttk::combobox::Scroll, ttk::spinbox::MouseWheel). Inside a scroll
# region the wheel must scroll the view, never silently edit a parameter, so
# `bind_mousewheel_scroll` overrides these per widget instance.
# Tk のクラスバインドが <MouseWheel> を自身の値変更に使うウィジェットクラス。
# スクロール領域内でホイールを回した際にパラメータが黙って書き換わるのを防ぐため、
# `bind_mousewheel_scroll` はこれらをウィジェット単位で上書きする。
_WHEEL_HIJACKING_CLASSES = ("TCombobox", "TSpinbox", "Spinbox")

# Scrollbars already scroll their own widget from a Tk class binding, at a
# coarser rate (4 units per notch). Adding a second handler on top of it would
# scroll five times per notch, so wheel events landing on a scrollbar are left
# to Tk and keep the behavior users already have there.
# スクロールバーは Tk のクラスバインドで既に自分のウィジェットを（1 ノッチ
# 4 単位という粗い刻みで）スクロールさせる。その上にハンドラを重ねると
# 1 ノッチで 5 倍動いてしまうため、スクロールバー上のホイールイベントは Tk に
# 任せ、そこでの既存の挙動をそのまま保つ。
_WHEEL_SELF_SCROLLING_CLASSES = ("TScrollbar", "Scrollbar")


def _wheel_scroll_steps(event) -> int:
    """
    Convert a wheel event into signed scroll units, or 0 when it carries none.
    ホイールイベントを符号付きスクロール単位へ変換する（無ければ 0）。

    Notes
    -----
    Windows and macOS deliver ``<MouseWheel>`` with ``event.delta`` (Windows
    reports multiples of 120 per notch, macOS small counts), while X11 sends
    ``<Button-4>`` / ``<Button-5>`` with no delta.
    Windows と macOS は ``event.delta`` 付きの ``<MouseWheel>``（Windows は
    1 ノッチ 120 単位、macOS は小さな値）を送り、X11 は delta を持たない
    ``<Button-4>`` / ``<Button-5>`` を送る。
    """
    num = getattr(event, "num", 0)
    if num == 4:
        return -1
    if num == 5:
        return 1
    delta = getattr(event, "delta", 0)
    if not delta:
        return 0
    if abs(delta) >= 120:
        return -int(delta / 120)
    return -1 if delta > 0 else 1


def bind_mousewheel_scroll(canvas, scope=None) -> None:
    """
    Scroll a canvas with the wheel anywhere inside a window, not only on its scrollbar.
    スクロールバー上だけでなく、ウィンドウ内のどこでもホイールで canvas をスクロールさせる。

    Parameters
    ----------
    canvas
        Scrollable canvas whose vertical view the wheel drives.
        ホイールで縦方向の表示位置を動かす、スクロール可能な canvas。
    scope
        Widget whose subtree reacts to the wheel; defaults to the canvas's own
        toplevel window. Pass the enclosing panel when the window holds more
        than one scrollable area, so each area answers only for itself.
        ホイールに反応させる部分木のウィジェット。既定は canvas 自身の
        トップレベルウィンドウ。1 つのウィンドウが複数のスクロール領域を
        持つ場合は、各領域が自分の範囲だけに応答するよう、囲んでいるパネルを
        渡すこと。

    Notes
    -----
    Tk has no wheel binding of its own for a canvas, so without this the only
    scrollable surface is the ttk.Scrollbar's own class binding — the wheel
    works only while the pointer sits on the scrollbar itself.
    Tk は canvas に対するホイールバインドを持たないため、これが無いと
    ttk.Scrollbar のクラスバインドだけが効き、ポインタがスクロールバーの
    上にあるときしかホイールが働かない。

    The handler is bound to the toplevel rather than through ``bind_all``, so
    it covers the window without leaking into other windows and dies with it.
    The toplevel is the only container in a widget's bindtags — intermediate
    frames are not — so a `scope` narrower than the window cannot be bound
    directly and is honored by filtering on the event widget's path instead.
    ハンドラは ``bind_all`` ではなくトップレベルに束縛するため、他のウィンドウ
    へ漏れずにウィンドウを覆い、ウィンドウと同時に破棄される。ウィジェットの
    bindtags に含まれるコンテナはトップレベルだけで中間フレームは含まれない
    ため、ウィンドウより狭い `scope` は直接束縛できず、代わりにイベント発生
    ウィジェットのパスで絞り込むことで実現する。

    Descendant comboboxes and spinboxes additionally get an instance binding,
    because instance bindings run before class bindings and can ``break`` out
    of them; call this after the subtree has been built so those widgets exist.
    子孫のコンボボックスとスピンボックスには加えてインスタンスバインドを張る。
    インスタンスバインドはクラスバインドより先に実行され ``break`` で打ち切れる
    ためである。対象ウィジェットが存在している必要があるので、部分木の構築後に
    呼ぶこと。

    Wheel events over a scrollbar are left to Tk so its existing rate is
    preserved; see `_WHEEL_SELF_SCROLLING_CLASSES`.
    スクロールバー上のホイールイベントは Tk に任せ、既存の刻み幅を保つ。
    `_WHEEL_SELF_SCROLLING_CLASSES` を参照。
    """
    target = scope if scope is not None else canvas.winfo_toplevel()
    scope_path = str(target)
    scope_prefix = scope_path if scope_path.endswith(".") else scope_path + "."

    def _in_scope(widget) -> bool:
        """
        Report whether a widget lies inside the scope subtree.
        ウィジェットが scope の部分木の内側にあるかを判定する。
        """
        path = str(widget)
        return path == scope_path or path.startswith(scope_prefix)

    def _scroll(event):
        steps = _wheel_scroll_steps(event)
        if not steps:
            return None
        widget = getattr(event, "widget", None)
        if widget is None or not hasattr(widget, "winfo_class"):
            return None
        if not _in_scope(widget):
            return None
        if widget.winfo_class() in _WHEEL_SELF_SCROLLING_CLASSES:
            return None
        try:
            first, last = canvas.yview()
            # Ignore the wheel when everything already fits, so it does not
            # drag a fully visible view around.
            if first <= 0.0 and last >= 1.0:
                return None
            canvas.yview_scroll(steps, "units")
        except tk.TclError:
            # The canvas was destroyed while the window was still alive.
            return None
        return None

    def _scroll_and_break(event):
        _scroll(event)
        return "break"

    toplevel = target.winfo_toplevel()
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        toplevel.bind(sequence, _scroll, add="+")

    def _override_hijackers(widget) -> None:
        """
        Rebind wheel events on value-changing widgets down the subtree.
        部分木を辿り、値が変わるウィジェットのホイールイベントを張り替える。
        """
        if widget.winfo_class() in _WHEEL_HIJACKING_CLASSES:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(sequence, _scroll_and_break, add="+")
        for child in widget.winfo_children():
            _override_hijackers(child)

    _override_hijackers(target)


def extent_scale_and_unit(scale_um: float, unit: str) -> tuple:
    """
    Return plot extent scale and label for micrometer/nanometer tick display.
    µm / nm の軸目盛表示に使う extent スケールと単位ラベルを返す。

    Parameters
    ----------
    scale_um
        Physical scan size in micrometers.
        物理スキャンサイズ (µm)。
    unit
        Requested display unit. ``"nm"`` selects nanometers; all other values
        select the shared micrometer symbol.
        表示単位。``"nm"`` なら nm、それ以外は共通の µm 表記を使う。

    Returns
    -------
    tuple
        ``(scale, unit_label)`` suitable for Matplotlib extent and axis labels.
        Matplotlib の extent と軸ラベルに使う ``(scale, unit_label)``。
    """
    if unit == "nm":
        return scale_um * 1000.0, "nm"
    return scale_um, UNIT_MICROMETER


def drain_ui_queue(ui_queue, handlers) -> bool:
    """
    Drain queued worker messages and dispatch each payload to a handler.
    ワーカーメッセージキューを空にし、各 payload を handler に渡す。

    Parameters
    ----------
    ui_queue
        Queue containing ``(kind, payload)`` messages from worker threads.
        ワーカースレッドからの ``(kind, payload)`` メッセージを持つキュー。
    handlers
        Mapping from message kind to callback. A callback may return ``False``
        to ask the caller to stop polling or skip rescheduling.
        メッセージ種別からコールバックへの対応。コールバックが ``False`` を
        返すと、呼び出し側にポーリング停止または再スケジュール省略を依頼する。

    Returns
    -------
    bool
        ``True`` when polling may continue; ``False`` when a handler requested
        an early stop.
        ポーリング継続可能なら ``True``、handler が停止を求めたら ``False``。
    """
    try:
        while True:
            kind, payload = ui_queue.get_nowait()
            handler = handlers.get(kind)
            if handler is None:
                continue
            if handler(payload) is False:
                return False
    except queue.Empty:
        return True


def csv_save_filetypes() -> list[tuple[str, str]]:
    """
    Filetypes list for CSV save dialogs.
    CSV 保存ダイアログ用の filetypes リスト。

    Returns
    -------
    list of tuple
        File type labels and glob patterns for CSV exports.
        CSV 出力用のファイル種別ラベルと glob パターン。
    """
    return [(_("CSV"), "*.csv"), (_("All files"), "*.*")]


def save_csv_with_dialog(
    parent,
    writer_cb,
    *,
    initial_name: str,
    initial_dir: str | None = None,
    title: str | None = None,
    log_cb=None,
    success_message=None,
    error_title=None,
    failure_message=None,
) -> str | None:
    """
    Show a CSV save dialog and run a caller-provided writer callback.
    CSV 保存ダイアログを表示し、呼び出し側が指定した書き込み処理を実行する。

    Parameters
    ----------
    parent
        Parent for modal file and error dialogs.
        ファイルダイアログとエラーダイアログの親ウィジェット。
    writer_cb
        Callback called as ``writer_cb(path)`` after the user chooses a path.
        ユーザーが選んだパスに対して ``writer_cb(path)`` として呼ぶ処理。
    initial_name
        Default CSV file name.
        既定の CSV ファイル名。
    initial_dir
        Initial directory; defaults to the current working directory.
        初期フォルダ。未指定時は現在の作業フォルダ。
    title
        Dialog title; defaults to a translated CSV save title.
        ダイアログタイトル。未指定時は翻訳済みの CSV 保存タイトル。
    log_cb
        Optional log callback receiving a formatted success message.
        成功メッセージを受け取る任意のログコールバック。

    Returns
    -------
    str or None
        Saved file path, or ``None`` if cancelled or failed.
        保存先パス。キャンセルまたは失敗時は ``None``。
    """
    path = filedialog.asksaveasfilename(
        parent=parent,
        title=title or _("CSVで保存"),
        defaultextension=".csv",
        initialdir=initial_dir or os.getcwd(),
        initialfile=initial_name,
        filetypes=csv_save_filetypes(),
    )
    if not path:
        return None
    try:
        writer_cb(path)
    except Exception as exc:
        messagebox.showerror(
            error_title or _("保存エラー"),
            (failure_message or _("CSVの保存に失敗しました:\n{e}")).format(e=exc),
            parent=parent,
        )
        return None
    if log_cb is not None:
        msg = success_message or _("CSV 保存完了: {path}")
        log_cb(msg.format(path=path))
    return path


# =============================================================================
# Mixins for sharing common GUI behavior through inheritance.
# GUI 共通の振る舞いを継承で配るための Mixin 群。
# -----------------------------------------------------------------------------
# Purpose
#   Centralize the unconfirmed-Entry mechanism and logging behavior that GUI01-04
#   and their sub-dialogs otherwise had to duplicate.
# 目的
#   GUI01〜04 の App / サブダイアログに同じ「未確定 Entry 機構」「ログ機構」を
#   コピペで持たせるのをやめ、Mixin として一箇所に集約する。
#
# Usage
#   class App(tk.Tk, UnconfirmedEntryMixin, LogMixin):
#       def __init__(self):
#           super().__init__()
#           self._init_unconfirmed_registry()  # 未確定 Entry を使うなら必須
#           ...                                 # log_text を作ったあと、_log() がそのまま使える
#
# Notes
#   - The mixins intentionally avoid __init__ so they do not disrupt tk.Tk MRO.
#     Call _init_unconfirmed_registry() explicitly once instead.
#   - LogMixin._log depends on self.log_text; do not call it before log_text exists.
#   - UnconfirmedEntryMixin owns the unconfirmed-Entry mechanism. Earlier
#     duplicate top-level helpers were removed, so classes using that mechanism
#     should inherit this mixin.
# 注意
#   - Mixin の __init__ は意図的に作らない（tk.Tk 系の MRO を壊さないため）。
#     代わりに明示メソッド _init_unconfirmed_registry() を一度だけ呼ぶ運用にする。
#   - LogMixin._log は self.log_text の存在に依存する。log_text を作る前には呼ばない。
#   - UnconfirmedEntryMixin のメソッドは「未確定 Entry 機構」の実体であり、
#     かつてあったトップレベル関数（register_unconfirmed_entry など）は
#     Mixin と二重化していたため削除した。Entry 機構を使うクラスは
#     必ずこの Mixin を継承する。
# =============================================================================


class UnconfirmedEntryMixin:
    """
    Provide the "Enter-to-commit" entry mechanism used by all four GUIs.
    GUI01〜04 で共通の「Enter 確定 Entry」機構を提供する Mixin。

    Subclasses must call ``_init_unconfirmed_registry()`` once (typically in
    ``__init__``) before registering any Entry. Sub-dialogs that need their
    own independent registry can hold a separate list and pass it via the
    ``registry`` keyword argument of ``_register_unconfirmed_entry``.

    使い方:
        class App(tk.Tk, UnconfirmedEntryMixin):
            def __init__(self):
                super().__init__()
                self._init_unconfirmed_registry()
                ...
                self._register_unconfirmed_entry(entry, getter, commit_cb)
    """

    def _init_unconfirmed_registry(self) -> None:
        """
        Initialize ``self._unconfirmed_entries`` for Enter-to-commit fields.
        Enter 確定 Entry 用の登録簿 ``self._unconfirmed_entries`` を初期化する。
        """
        self._unconfirmed_entries = []
        # Track whether the "press Enter to commit" log hint has already been
        # shown for this window. The hint is emitted once per window lifetime,
        # the first time any registered Entry transitions into the unconfirmed
        # (blue) state. Avoids spamming the log on every keystroke.
        # ウィンドウ単位で「Enter キーで確定」案内ログを 1 回だけ出すためのフラグ。
        # いずれかの登録 Entry が初めて未確定（青色）になった瞬間にログへ流し、
        # それ以降は重複表示しない。
        self._enter_hint_shown = False

    @staticmethod
    def _fmt_num(v) -> str:
        """
        Format a value before writing it back to an Entry widget.
        Entry に書き込む際の文字列フォーマッタを返す。
        """
        return str(v)

    def _maybe_show_enter_hint(self) -> None:
        """First-time hint emitter for the Enter-to-commit mechanism.

        Called from ``on_key_release`` when an Entry becomes unconfirmed.
        Emits a one-shot message to ``self.log_text`` (via ``LogMixin._log``)
        if available; otherwise silently does nothing. This rescues users who
        do not notice the tooltip on the blue Entry.

        Enter 確定機構の「初回案内ログ」を 1 回だけ出す。
        ツールチップに気づかないユーザーへの保険として ``log_text`` がある画面で
        だけ動作する（SingleViewDialog のように ``_log`` を持たないクラスでは
        何もしない）。
        """
        if self._enter_hint_shown:
            return
        # LogMixin._log requires self.log_text to exist; guard for classes
        # that do not own a log widget (e.g. modal sub-dialogs).
        log_fn = getattr(self, "_log", None)
        if log_fn is None or not hasattr(self, "log_text"):
            return
        self._enter_hint_shown = True
        try:
            log_fn(_("パラメータを変更しました。Enter キーで確定するとグラフに反映されます。"))
        except Exception:
            # Never let a log failure break the key-release handler.
            # キーイベント処理がログ失敗で巻き添えにならないよう握りつぶす。
            pass

    def _register_unconfirmed_entry(self, entry, get_committed_str, commit_cb,
                                    registry=None):
        """
        Register one Entry widget with the Enter-to-commit mechanism.
        1つの Entry を Enter 確定機構に登録する。

        ``registry`` を省略すると ``self._unconfirmed_entries`` を使う。
        サブダイアログが独自の登録簿を使うとき（メインウィンドウと混ぜたくない
        とき）は、明示的に ``registry`` を渡すこと。

        Also attaches a short hover tooltip ("press Enter to commit") to the
        Entry itself. This is the primary affordance that tells the user what
        the blue background means; the one-shot log hint below is the backup
        for users who never hover.

        併せて Entry 本体に「Enter キーで確定」ツールチップを付与する。
        青色背景の意味を伝える主たる手がかりであり、ホバーしないユーザー向けには
        ``_maybe_show_enter_hint`` で初回ログ案内を出す。
        """
        if registry is None:
            registry = self._unconfirmed_entries
        registry.append((entry, get_committed_str, commit_cb))

        # ① Hover affordance: tell the user how to commit when they notice the
        #    blue background and mouse over the field.
        # ① ホバー時の手がかり：青色に気づいてマウスを乗せたユーザーへの説明。
        try:
            ToolTip(entry, _("Enter キーで確定します"))
        except Exception:
            # Tooltip is purely advisory; never block registration on its failure.
            # ツールチップは補助機能。失敗しても登録処理は継続する。
            pass

        def on_key_release(_event=None, widget=entry, getter=get_committed_str):
            mark_entry_state(widget, getter())
            # ③ One-shot log hint: emitted the first time any Entry in this
            #    window becomes unconfirmed. Only fires when the current text
            #    differs from the committed value (i.e. the Entry just turned
            #    blue), so the hint is timed to the user's actual edit.
            # ③ ログへの初回案内：このウィンドウで初めて Entry が未確定になった
            #    瞬間に 1 回だけ出す。確定値と異なる入力になっている時にのみ
            #    発火するため、編集操作と同期して案内できる。
            try:
                if widget.get() != getter():
                    self._maybe_show_enter_hint()
            except tk.TclError:
                pass

        def on_return(_event=None, reg=registry):
            self._commit_all_unconfirmed(reg)

        entry.bind("<KeyRelease>", on_key_release)
        entry.bind("<Return>", on_return)
        mark_entry_state(entry, get_committed_str())
        return entry

    def _commit_all_unconfirmed(self, registry) -> None:
        """
        Commit all changed Entry widgets in a registry.
        登録簿中の全 Entry を Enter 確定として一括反映する。

        各登録簿項目は ``(entry, committed_text_getter, commit_callback)``。
        複数 Entry が同じ commit_cb を共有している場合、commit_cb は 1 回しか
        呼ばない（例: vmin / vmax がまとめて 1 関数で検証される設計）。
        """
        called_cbs = set()
        items = list(registry)
        for entry, getter, cb in items:
            try:
                current = entry.get()
            except tk.TclError:
                continue
            if current == getter():
                continue

            cb_id = id(cb)
            if cb_id in called_cbs:
                mark_entry_state(entry, getter())
                continue
            called_cbs.add(cb_id)

            ok = cb()
            if ok:
                rewrite_entries(((entry, getter()),))
            mark_entry_state(entry, getter())

        self._refresh_all_entry_states(items)

    def _refresh_all_entry_states(self, registry=None) -> None:
        """
        Refresh confirmed/unconfirmed styles for all registered Entry widgets.
        登録簿中の全 Entry の確定/未確定スタイルを再評価する。
        """
        if registry is None:
            registry = self._unconfirmed_entries
        for entry, getter, _cb in registry:
            mark_entry_state(entry, getter())

    # -------------------------------------------------------------------------
    # Numeric validation helper for committed Entry fields shared by GUI01-04.
    # 確定型 Entry の数値検証ヘルパー（GUI01〜04 の validate_* / _commit_* で共有）
    # -------------------------------------------------------------------------
    def _commit_float_fields(self, fields, *, cast=float,
                             validator=None, on_success=None,
                             parent=None) -> bool:
        """
        Validate and commit multiple Entry values as one operation.
        複数の Entry 値をまとめて検証・確定する共通ヘルパー。

        ``validate_vrange`` / ``_commit_filter_range`` のような関数は、
        「全 Entry を ``float`` に変換 → 制約検証 → 失敗時はエラーダイアログ →
        成功時は self.<attr> に代入し rewrite_entries で書き戻して再描画」という
        定型コードを書いていた。本ヘルパーはその定型部分をまとめる。

        Parameters
        ----------
        fields : list[tuple]
            ``(entry, attr_name, label)``、``(entry, attr_name, label, cast)``、
            または旧形式 ``(var, entry, attr_name, label)`` のタプル列。
              - entry: ttk.Entry（書き戻し対象）
              - attr_name: ``self.<attr_name>`` に新値を代入する属性名
              - label: エラーメッセージに使うフィールド名（``None`` 可）
              - cast: そのフィールドのみに使う変換関数（省略時は引数 ``cast``）
            数値の取得は常に ``entry.get().strip()`` から行う。
        cast : callable
            既定の変換関数（既定: ``float``）。フィールド側で個別指定があれば
            そちらが優先される。
        validator : callable[[dict[str, Any]], str | None] | None
            検証関数。新しい値を ``{attr_name: value, ...}`` の dict で受け取り、
            合格なら ``None``、不合格なら表示用エラーメッセージを返す。
            ``None`` の場合は cast 成功のみを検証とする。
        on_success : callable[[], None] | None
            検証通過後、内部状態に代入し書き戻した後に呼ばれるコールバック。
            描画や再計算をここで行う。
        parent : tk widget | None
            messagebox の親（既定: self）。

        Returns
        -------
        bool
            確定成功なら True、失敗（不正値）なら False。
        """
        parent = parent or self

        # 1. Convert each Entry to a number; fail immediately on the first invalid value.
        # 1. 各 Entry を数値に変換（一つでも失敗したら即エラー）
        new_values = {}
        rewrite_pairs = []
        for item in fields:
            field_cast = cast
            if len(item) == 3:
                entry, attr_name, _label = item
            elif len(item) == 4:
                # Four items: a callable tail is per-field cast; otherwise it is the legacy var.
                # 4 要素: 末尾が呼び出し可能なら個別 cast、そうでなければ旧形式の var
                if callable(item[3]):
                    entry, attr_name, _label, field_cast = item
                else:
                    # Accept the legacy (var, entry, attr_name, label) form and ignore var.
                    # 旧形式 (var, entry, attr_name, label) も受ける。var は無視する。
                    _var, entry, attr_name, _label = item
            else:
                raise ValueError(
                    "fields tuple must be (entry, attr, label), "
                    "(entry, attr, label, cast), or "
                    "(var, entry, attr, label)"
                )
            try:
                raw = entry.get().strip()
                new_values[attr_name] = field_cast(raw)
            except (ValueError, TypeError):
                messagebox.showerror(
                    _("エラー"), _("数値を入力してください"), parent=parent,
                )
                return False
            rewrite_pairs.append((entry, attr_name))

        # 2. Apply extra constraints such as ranges or ordering.
        # 2. 追加の制約検証（範囲、大小関係など）
        if validator is not None:
            err = validator(new_values)
            if err:
                messagebox.showerror(_("エラー"), err, parent=parent)
                return False

        # 3. Update internal state, rewrite Entries, and clear unconfirmed styling.
        # 3. 内部状態に反映 → Entry 書き戻し → 未確定スタイル解除
        for _entry, attr_name in rewrite_pairs:
            setattr(self, attr_name, new_values[attr_name])
        rewrite_entries(
            [(entry, getattr(self, attr_name)) for entry, attr_name in rewrite_pairs],
            formatter=self._fmt_num,
        )

        # 4. Run the success callback for redraws or recalculation.
        # 4. 成功コールバック（描画・再計算）
        if on_success is not None:
            on_success()

        self._refresh_all_entry_states()
        return True

    # -------------------------------------------------------------------------
    # Auto-compute vmin/vmax, update state, and rewrite Entries for GUI02/GUI04.
    # vmin/vmax の自動計算 → 内部状態反映 → Entry 書き戻し（GUI02/GUI04 共通）
    # -------------------------------------------------------------------------
    def _apply_auto_vrange(self, image_array, *, mask=None,
                           log: bool = False) -> tuple | None:
        """
        Compute vmin/vmax from an image array and commit them to state and Entries.
        画像配列から vmin/vmax を自動計算し、内部状態と Entry へ反映する。

        ``compute_auto_vrange`` で範囲を求め、``self.vmin`` / ``self.vmax`` に
        代入し、``self.ent_vmin`` / ``self.ent_vmax`` へ書き戻したうえで未確定
        スタイルを再評価する（共通化対象のステップ 1〜4）。再描画は呼び出し側の
        責務とし、本メソッドでは行わない。

        GUI02（素の Entry）と GUI04（textvariable 紐づけ Entry）の双方で動作する。
        ``rewrite_entries`` は Entry の delete/insert で書き込むため、
        textvariable が紐づいていれば StringVar 側にも自動的に反映される。

        Parameters
        ----------
        image_array : array-like
            高さ画像（2D 配列）。``compute_auto_vrange`` に渡す。
        mask : array-like or None
            任意のファイバーマスク（バンドルの ``skeletonized``）。上端の推定に
            使い、無い場合はマスク非依存の推定にフォールバックする。
        log : bool
            True かつ ``self._log`` が利用可能なら、確定値をログに出力する。

        Returns
        -------
        (v_lo, v_hi) : tuple of int | None
            計算した範囲。``ent_vmin`` / ``ent_vmax`` を持たない等で書き戻せない
            場合でも値自体は返す。
        """
        v_lo, v_hi = compute_auto_vrange(image_array, mask)
        self.vmin = float(v_lo)
        self.vmax = float(v_hi)

        ent_vmin = getattr(self, "ent_vmin", None)
        ent_vmax = getattr(self, "ent_vmax", None)
        if ent_vmin is not None and ent_vmax is not None:
            rewrite_entries(
                [(ent_vmin, self.vmin), (ent_vmax, self.vmax)],
                formatter=self._fmt_num,
            )
        self._refresh_all_entry_states()

        if log:
            log_fn = getattr(self, "_log", None)
            if log_fn is not None:
                log_fn(_("vmin/vmax を自動設定: {lo} / {hi}").format(lo=v_lo, hi=v_hi))

        return v_lo, v_hi


class LogMixin:
    """
    Provide a uniform ``_log`` / ``_log_exception`` API for GUI windows that
    own a ``self.log_text`` Text widget.

    ``self.log_text`` を持つ GUI に対して、共通の ``_log`` /
    ``_log_exception`` を提供する Mixin。``log_text`` を生成する前に
    呼んではいけない。

    使い方:
        class App(tk.Tk, LogMixin):
            def __init__(self):
                super().__init__()
                ...
                self.log_text = tk.Text(...)  # 先に生成しておく
                self._log("起動しました")
    """

    def _log(self, msg) -> None:
        """ログテキストウィジェットに1行追加する。"""
        append_log(self.log_text, msg)

    def _clear_log(self) -> None:
        """ログテキストウィジェットの内容を全消去する。"""
        clear_text_widget_log(self.log_text)

    def _log_exception(self, prefix: str, exc: BaseException) -> None:
        """例外をスタックトレース付きでログに出す。"""
        import traceback
        tb = traceback.format_exc()
        self._log(_("{0}: {1}\n{2}").format(prefix, exc, tb))


# Tooltip popup geometry, in pixels. The offsets place the popup clear of the
# pointer; the margin is the gap kept from the screen edge. The wrap bounds cap
# how wide a long message may grow before it is folded onto more lines: the
# minimum stays above the widest space-aligned tooltip in this project (about
# 390 px) so hand-formatted columns are not re-flowed.
# ツールチップの配置寸法（ピクセル）。オフセットはポインタを避けるための距離、
# マージンは画面端との間隔。折り返し幅の下限は、本プロジェクトで最も幅の広い
# 空白桁揃えツールチップ（約 390 px）より大きく取り、手で整形した列を保つ。
TOOLTIP_OFFSET_X = 12
TOOLTIP_OFFSET_Y = 18
TOOLTIP_MARGIN = 8
TOOLTIP_MIN_WRAP = 400
TOOLTIP_MAX_WRAP = 560


class ToolTip:
    """
    Display a popup tooltip when the mouse hovers over a widget.
    ウィジェットにマウスを乗せたとき、説明文をポップアップ表示するクラス。

    Attributes
    ----------
    widget
        Target widget that receives tooltip behavior.
        ツールチップ動作を付与する対象ウィジェット。
    text
        Message displayed inside the tooltip popup.
        ツールチップ内に表示するメッセージ。
    tooltip
        Popup window instance while visible, otherwise `None`.
        表示中はポップアップウィンドウ、非表示時は `None`。

    Examples
    --------
        btn = ttk.Button(parent, text="適用")
        ToolTip(btn, "フィルターを適用します")
    """

    def __init__(self, widget: tk.Widget, text: str) -> None:
        """
        Initialize tooltip behavior and bind mouse events.
        ツールチップ動作を初期化し、マウスイベントを関連付ける。

        Parameters
        ----------
        widget
            Widget to which the tooltip is attached.
            ツールチップを付与する tkinter ウィジェット。
        text
            Description text shown in the popup.
            ポップアップに表示する説明文。
        """
        # Store target widget for event binding.
        # widget: target tkinter widget for the tooltip.
        # Store tooltip text to display.
        # text: description text shown in the popup.
        self.widget = widget
        self.text = text
        # Keep popup window reference; starts as not shown.
        # ポップアップウィンドウを保持する変数（初期はなし）
        self.tooltip = None  # ポップアップウィンドウを保持する変数（初期はなし）
        # Call show_tooltip when pointer enters the widget area.
        # マウスがウィジェット上に入ったとき show_tooltip を呼ぶ
        self.widget.bind("<Enter>", self.show_tooltip)
        # Call hide_tooltip when pointer leaves the widget area.
        # マウスがウィジェット上から出たとき hide_tooltip を呼ぶ
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event):
        """
        Create and show the tooltip popup near the mouse cursor.
        マウスカーソル付近にツールチップのポップアップを作成して表示する。

        Parameters
        ----------
        event
            Tkinter event object for mouse-enter action.
            マウス進入時の tkinter イベントオブジェクト。

        Returns
        -------
        None
            This method updates UI state and does not return a value.
            UI 状態を更新するだけで戻り値はない。

        Notes
        -----
        Long messages are wrapped and the popup is flipped to the other side of
        the cursor when it would cross a screen edge, so a tooltip is never cut
        off at the display border.
        長い本文は折り返し、画面端を越える場合はカーソルの反対側へ反転させるため、
        ディスプレイの端でツールチップが途切れることはない。

        Edge handling uses `winfo_screenwidth` / `winfo_screenheight`, which
        report the primary display. On a multi-monitor setup a window moved to a
        secondary display is placed against the primary display's bounds.
        端の判定には `winfo_screenwidth` / `winfo_screenheight` を使うが、これらは
        プライマリディスプレイの寸法を返す。マルチモニタ環境でウィンドウをサブ
        ディスプレイへ移した場合、プライマリの境界を基準に配置される。
        """
        # A stale popup can linger if a previous <Leave> was missed (for
        # example during rapid Enter/Leave crossings over a child widget
        # overlaid on the target). Destroy it before creating a new one so
        # tooltips never accumulate and stay stuck on screen.
        # 直前の <Leave> を取りこぼすと古いポップアップが残ることがある（対象に
        # 重ねた子ウィジェット上での高速な出入りなど）。新規作成前に破棄し、
        # ツールチップが画面に溜まって消えなくなるのを防ぐ。
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None
        # Create a small top-level popup window.
        # tk.Toplevel creates a small child window for the tooltip.
        self.tooltip = tk.Toplevel(self.widget)
        # Remove window decorations for tooltip-like appearance.
        # 枠なし（タイトルバーを消してポップアップ風にする）
        self.tooltip.wm_overrideredirect(True)  # 枠なし（タイトルバーを消してポップアップ風にする）
        # Placement needs the rendered size, which is only known once the label
        # exists, so keep the popup hidden until the geometry is decided instead
        # of letting it flash at the default position.
        # 配置には描画後のサイズが必要で、それはラベル生成後にしか分からない。
        # 既定位置で一瞬ちらつかせないよう、位置決定まで非表示にしておく。
        self.tooltip.wm_withdraw()
        # Bound the width so a long message wraps instead of extending off the
        # screen as a single line. The floor keeps the wrap point above the
        # widest space-aligned tooltip in the project, so hand-formatted columns
        # are not re-flowed; the cap keeps the popup narrow on small displays.
        # 長文が 1 行のまま画面外へ伸びないよう幅に上限を設ける。下限は本プロジェクト
        # で最も幅の広い空白桁揃えツールチップより折り返し位置を右に保つためのもので、
        # 手で整形した列が崩れない。上限は小さな画面で幅を取りすぎないようにする。
        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()
        wrap = min(TOOLTIP_MAX_WRAP, max(TOOLTIP_MIN_WRAP, screen_w // 3))
        # Render tooltip text with simple bordered white label.
        # ポップアップの中身: 白背景・枠付きのラベル
        label = tk.Label(self.tooltip, text=self.text, background="white",
                         relief="solid", borderwidth=1,
                         wraplength=wrap, justify=tk.LEFT)
        label.pack()
        self.tooltip.update_idletasks()
        width = self.tooltip.winfo_reqwidth()
        height = self.tooltip.winfo_reqheight()

        # Offset the popup below-right of the cursor. Placing it directly under
        # the pointer makes the popup itself trigger a <Leave> on the target,
        # producing a hide/show flicker loop.
        # ポップアップはカーソルの右下にずらして表示する。ポインタ直下に出すと
        # ポップアップ自身が対象の <Leave> を誘発し、表示/非表示のちらつきが
        # 起きるため。
        # When that side would run past a screen edge, flip to the opposite side
        # of the cursor rather than sliding the popup back inside: sliding would
        # move the popup over the pointer and start exactly that flicker loop.
        # その側が画面端を越える場合は、内側へずらすのではなくカーソルの反対側へ
        # 反転させる。内側へずらすとポインタを覆い、上記のちらつきループを招く。
        x = event.x_root + TOOLTIP_OFFSET_X
        if x + width > screen_w - TOOLTIP_MARGIN:
            x = event.x_root - TOOLTIP_OFFSET_X - width
        y = event.y_root + TOOLTIP_OFFSET_Y
        if y + height > screen_h - TOOLTIP_MARGIN:
            y = event.y_root - TOOLTIP_OFFSET_Y - height
        # Last resort for a popup that fits on neither side; the pointer may end
        # up covered, but an unreadable off-screen popup is worse.
        x = max(TOOLTIP_MARGIN, min(x, screen_w - width - TOOLTIP_MARGIN))
        y = max(TOOLTIP_MARGIN, min(y, screen_h - height - TOOLTIP_MARGIN))
        self.tooltip.wm_geometry(f"+{x}+{y}")
        self.tooltip.wm_deiconify()

    def hide_tooltip(self, event):
        """
        Hide and destroy the tooltip popup if it is visible.
        ツールチップが表示中であれば非表示にして破棄する。

        Parameters
        ----------
        event
            Tkinter event object for mouse-leave action.
            マウス離脱時の tkinter イベントオブジェクト。

        Returns
        -------
        None
            This method updates UI state and does not return a value.
            UI 状態を更新するだけで戻り値はない。
        """
        # Destroy popup window only when it exists.
        # ツールチップが表示中であれば破棄する
        if self.tooltip:
            self.tooltip.destroy()
            # Reset reference to indicate hidden state.
            # 変数をリセットして「非表示状態」に戻す
            self.tooltip = None  # 変数をリセットして「非表示状態」に戻す


def center_window(win, w, h, taskbar_offset=40):
    """
    Center a window on screen with a small upward taskbar offset.
    指定サイズのウィンドウを画面中央に配置し、タスクバー分だけ少し上にずらす。

    Parameters
    ----------
    win
        Tk window to position.
        配置対象の Tk ウィンドウ。
    w
        Requested window width in pixels.
        指定するウィンドウ幅 (px)。
    h
        Requested window height in pixels.
        指定するウィンドウ高さ (px)。
    taskbar_offset
        Upward offset in pixels to avoid placing the lower edge too close
        to the taskbar.
        下端がタスクバーに近づきすぎないよう上へずらす量 (px)。
    """
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2 - taskbar_offset
    # Prevent negative coordinates when the requested size is close to screen size.
    # 画面外（マイナス座標）に行かないようガード。
    x = max(x, 0)
    y = max(y, 0)
    win.geometry(f"{w}x{h}+{x}+{y}")


def apply_window_size(win, default_w, default_h, min_w=None, min_h=None,
                     margin=100, center=True):
    """
    Apply initial size, minimum size, and optional centered placement.
    ウィンドウに初期サイズ・最小サイズ・配置を設定する。

    The requested size is clamped to fit on the current screen. The default
    margin prevents vertical clipping on 1366x768 displays.
    画面に収まらない場合は自動的に縮小し、必要なら中央に配置する。

    Parameters
    ----------
    win
        Target Tk or Toplevel window.
        対象ウィンドウ。
    default_w, default_h
        Preferred initial size in pixels.
        理想的な初期サイズ (px)。
    min_w, min_h
        Minimum size in pixels. If None, 70% of the default size is used.
        最小サイズ (px)。None なら default の 70% を使う。
    margin
        Screen-edge margin for taskbar and titlebar space.
        画面端からの余白（タスクバー・タイトルバー分）。
        1366x768 機での縦見切れを防ぐため 100 をデフォルトとする。
    center
        Whether to center the window after clamping.
        True なら画面中央に配置する。
    """
    # Read screen size and clamp the requested window size to fit.
    # 画面サイズを取得して、収まる範囲にクランプ。
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    w = min(default_w, sw - margin)
    h = min(default_h, sh - margin)

    if center:
        center_window(win, w, h)
    else:
        win.geometry(f"{w}x{h}")

    # Use 70% of the default size as the minimum when no explicit value is given.
    # 最小サイズ（指定なしなら default の 70%）。
    if min_w is None:
        min_w = int(default_w * 0.7)
    if min_h is None:
        min_h = int(default_h * 0.7)
    # Clamp minimum size as well so the window remains resizable on small screens.
    # 最小サイズも画面サイズでクランプ（リサイズ可能性を保証）。
    min_w = min(min_w, sw - margin)
    min_h = min(min_h, sh - margin)

    win.minsize(min_w, min_h)
    win.resizable(True, True)


# =============================================================================
# Plot style constants shared by GUI figures.
# グラフ表示の共通定数。
# -----------------------------------------------------------------------------
# Purpose
#   Centralize figure font-size defaults, save DPI/filetypes, and the Unicode
#   spelling of µm. GUIs should reference these constants for initial values,
#   while keeping GUI-specific plotting functions local.
# 目的
#   各 GUI で個別に定義されていた「軸ラベル・目盛りのフォントサイズ」
#   「保存 DPI / 対応形式」「µm の Unicode 表記」をプロジェクト全体で
#   1 箇所に集約する。各 GUI は「初期値を決める箇所でこれらを参照する」
#   という運用にとどめ、関数の共通化は意図的に行わない。
#
# Usage
#   from lib.ui_tools import PLOT_FS_DEFAULTS, UNIT_MICROMETER
#   self.label_fs_var = tk.StringVar(value=str(PLOT_FS_DEFAULTS["label_fs"]))
#   self.unit_var     = tk.StringVar(value=UNIT_MICROMETER)
#
# Notes
#   - These are defaults, not hard constraints. Individual GUIs may choose
#     different values when their layout requires it.
#   - Any default change should be accompanied by screenshot checks for each GUI.
# 注意
#   - これらは「迷ったら使う既定値」であり、各 GUI が固有の事情で
#     別の値を採用することを禁じるものではない（例: GUI04 の AFM 全体像は
#     スペース都合で小さめのフォントが望ましい等）。
#   - 値を変更する場合は、各 GUI のスクリーンショット確認を伴うこと。
# =============================================================================

# --- Default font sizes -------------------------------------------------------
# Values use Matplotlib fontsize units (roughly points).
# 単位は matplotlib の fontsize（ポイント相当）。
# Existing GUI defaults ranged from 12 to 15; these middle values work for
# both publication figures and on-screen review.
# 既存 GUI の値が 12〜15 でばらついていたものを、論文掲載・スクリーン確認の
# どちらでも破綻しない中間値に揃える。
PLOT_FS_DEFAULTS = {
    "label_fs":  14,   # 軸ラベル（"Length (nm)" 等）
    "tick_fs":   13,   # 軸目盛りの数値
    "title_fs":  16,   # グラフタイトル
    "cbar_fs":   13,   # カラーバーのラベル・目盛り
    "annot_fs":  13,   # グラフ内の注釈テキスト
    "legend_fs": 12,   # 凡例（legend）のテキスト
}

# --- Save defaults ------------------------------------------------------------
# Figure-save DPI lives in ``FIGURE_SAVE_DPI`` above; supported extensions
# live in ``figure_save_filetypes()``.
# 図保存の DPI は ``FIGURE_SAVE_DPI``（モジュール冒頭）を、
# 拡張子は ``figure_save_filetypes()`` を参照する。
# The old ``PLOT_SAVE_DEFAULTS`` dict was removed because it was unused and
# disagreed with ``figure_save_filetypes()`` on .tif/.tiff spelling.
# （かつてここに ``PLOT_SAVE_DEFAULTS`` 辞書を置いていたが、参照箇所がなく、
#  かつ ``figure_save_filetypes()`` と拡張子（.tif vs .tiff）で食い違いが
#  発生していたため削除した。一元管理は上記2つに集約する。）

# --- Unit strings -------------------------------------------------------------
# Standardize µm on MICRO SIGN (U+00B5).
# µm の表記は MICRO SIGN (U+00B5) に統一する。
# GREEK SMALL LETTER MU (U+03BC, "μm") looks almost identical but is a
# different code point that can confuse fonts, search, diffs, and gettext catalogs.
# GREEK SMALL LETTER MU (U+03BC, "μm") とは見た目がほぼ同じだが別文字であり、
# フォント環境・検索・diff・gettext カタログで混乱の原因となる。
# Replace any remaining U+03BC occurrences in code with this constant.
# 既存コードに "μm" (U+03BC) が残っている場合は、この定数で置換すること。
UNIT_MICROMETER = "\u00b5m"   # = "µm"

# --- Auto vmin/vmax defaults --------------------------------------------------
# Fallback AFM heatmap display range in nanometers.
# AFM ヒートマップで使う高さ表示範囲 (nm) のフォールバック値。
# Returned when compute_auto_vrange() cannot compute a range, such as for
# empty or all-NaN arrays.
# compute_auto_vrange() が空配列・NaN だらけ等で計算不能だったときに返す。
# Shared by GUI02 and GUI04; these values were moved here from GUI04.
# GUI02 / GUI04 で同じ値を共有する（過去 GUI04 内で定義されていたものを移管）。
DEFAULT_VMIN: float = -5.0
DEFAULT_VMAX: float = 20.0

# --- Auto vmin/vmax tuning constants ------------------------------------------
# Tunable inputs of compute_auto_vrange(). They are module constants rather
# than hard-coded literals so a caller can override one value per call without
# reimplementing the rule; the GUIs use the defaults.
# compute_auto_vrange() の調整値。呼び出し側が規則ごと書き直さずに 1 値だけ
# 上書きできるよう、リテラル埋め込みではなくモジュール定数にしてある。GUI は
# 既定値のまま使う。

# Lower bound = background level - k * background sigma. 3 sigma keeps the
# substrate noise band inside the dark end without letting a scratch or a
# spike set the bound.
# 下端 = 背景レベル - k × 背景σ。3σ なら基板ノイズ帯を暗側に収めつつ、
# スクラッチや単発スパイクに下端を決めさせない。
AUTO_VRANGE_K_LOW: float = 3.0

# Upper bound percentile taken over fiber-mask pixels (GUI04 / a GUI02 bundle).
# ファイバーマスク画素に対して取る上端パーセンタイル（GUI04 / GUI02 のバンドル）。
AUTO_VRANGE_FIBER_PCT: float = 99.0

# Upper bound percentile used when no mask is available, taken over the
# "above background" pixels only. It is higher than the mask percentile
# because that population also contains fiber flanks, which sit lower than
# the ridge the skeleton follows.
# マスクが無い場合に「背景より上」の画素だけを母集団として取る上端
# パーセンタイル。この母集団にはスケルトンが通る稜線より低いファイバー側面も
# 含まれるため、マスク版より高い値を使う。
AUTO_VRANGE_FG_PCT: float = 99.5

# Largest share of pixels (%) the lower bound may push below the display
# range. It matters for the raw, uncorrected images GUI02 can open: a tilted
# substrate spreads over several nanometers, so the background is no longer a
# narrow band and "level - k * sigma" would crush the low corner to black.
# 下端が表示範囲外へ追い出してよい画素の割合の上限 (%)。GUI02 が開ける未補正の
# 生画像で効く。傾斜した基板は数 nm に広がるため背景は狭い帯ではなくなり、
# "level - k × sigma" では低い側の隅が黒く潰れてしまう。
AUTO_VRANGE_LOW_CLIP_PCT: float = 0.5

# Minimum vmax - vmin in nanometers, so a nearly featureless image still gets
# a usable (non-degenerate) color range.
# vmax - vmin の下限 (nm)。ほぼ平坦な画像でも縮退しない表示範囲を保つ。
AUTO_VRANGE_MIN_SPAN: float = 1.0

# Histogram bins used to locate the background mode, and the smallest pixel
# count that makes a percentile of a subpopulation meaningful.
# 背景モードを求めるヒストグラムのビン数と、部分母集団のパーセンタイルが
# 意味を持つ最小画素数。
_AUTO_VRANGE_BG_BINS: int = 512
_AUTO_VRANGE_MIN_SUBSET: int = 50

# Scale factor converting a median absolute deviation into a Gaussian sigma.
# 中央絶対偏差を正規分布の σ に換算する係数。
_MAD_TO_SIGMA: float = 1.4826


def _background_level(values: np.ndarray) -> tuple:
    """
    Estimate the substrate level and its noise sigma from finite heights.
    有限値の高さ配列から基板レベルとそのノイズ σ を推定する。

    Parameters
    ----------
    values
        1D array of finite height values in nanometers.
        有限値のみを含む 1 次元の高さ配列 (nm)。

    Returns
    -------
    (level, sigma) : tuple of float
        Background height and its noise sigma, both in nanometers.
        背景の高さとそのノイズ σ（いずれも nm）。

    Notes
    -----
    The level is the histogram mode rather than the median, and sigma comes
    from the deviations *below* the mode only. On an AFM image everything
    that is not substrate — fibers, aggregates, dust — sits above the
    background, so the lower half of the height distribution is pure noise
    and cannot be contaminated by the sample. A plain median/MAD pair is
    contaminated instead: on a densely covered image the median walks up
    onto the fibers and the MAD inflates with fiber height.
    レベルは中央値ではなくヒストグラムのモード、σ はモードより下側の偏差
    だけから求める。AFM 画像では基板以外（ファイバー・凝集体・コンタミ）は
    常に背景より上に出るため、高さ分布の下半分は純粋なノイズであり試料に
    汚染されない。単純な中央値／MAD はこの性質を使えず、被覆率が高い画像では
    中央値がファイバー側へ乗り上げ、MAD もファイバー高さの分だけ膨らむ。

    The estimate assumes features protrude upward. On an image dominated by
    pits or holes below the substrate the lower half is no longer pure noise
    and sigma is overestimated; the caller clamps the bound to the data
    minimum, so the result degrades to the old behavior instead of failing.
    この推定は構造物が上向きに突出することを前提とする。基板より低い穴・
    ピットが支配的な画像では下半分がノイズだけではなくなり σ を過大評価
    するが、呼び出し側が下端をデータ最小値で頭打ちにするため、破綻せず
    従来挙動相当に劣化するだけで済む。
    """
    # Build the histogram over the central range so a far-out spike cannot
    # widen every bin and smear the background peak.
    # 遠方のスパイクが全ビン幅を広げて背景ピークをぼかさないよう、中央域だけで
    # ヒストグラムを作る。
    lo, hi = (float(v) for v in np.percentile(values, (0.1, 99.9)))
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return float(np.median(values)), 0.0

    counts, edges = np.histogram(values, bins=_AUTO_VRANGE_BG_BINS, range=(lo, hi))
    peak = int(np.argmax(counts))
    level = float(0.5 * (edges[peak] + edges[peak + 1]))

    below = values[values < level]
    if below.size >= _AUTO_VRANGE_MIN_SUBSET:
        # For a symmetric noise distribution the median deviation over the
        # lower half equals the full MAD, so this is the ordinary robust
        # sigma computed from the half that the sample cannot reach.
        # 対称なノイズ分布では下半分の偏差中央値は全体の MAD と一致するため、
        # これは試料が届かない側だけで計算した通常のロバスト σ に等しい。
        sigma = _MAD_TO_SIGMA * float(np.median(level - below))
    else:
        sigma = _MAD_TO_SIGMA * float(np.median(np.abs(values - level)))

    if not math.isfinite(sigma) or sigma <= 0.0:
        sigma = float(np.std(values))
    if not math.isfinite(sigma) or sigma <= 0.0:
        sigma = 0.0
    return level, sigma


def compute_auto_vrange(
    image_array,
    mask=None,
    *,
    k_low: float = AUTO_VRANGE_K_LOW,
    fiber_pct: float = AUTO_VRANGE_FIBER_PCT,
    fg_pct: float = AUTO_VRANGE_FG_PCT,
    low_clip_pct: float = AUTO_VRANGE_LOW_CLIP_PCT,
    min_span: float = AUTO_VRANGE_MIN_SPAN,
) -> tuple:
    """
    Compute outlier-resistant vmin/vmax from a 2D image array.
    画像配列から外れ値に強い vmin/vmax を返す。

    Rule / 計算規則
        vmin = floor(min(background_level - k_low * background_sigma,
                         percentile(image, low_clip_pct)))
        vmax = ceil (percentile of the fiber pixels)

    Both bounds are statistics of a chosen population, never a single
    extreme pixel. The previous rule used ``nanmin``/``nanmax`` directly, so
    one contamination spike set ``vmax`` far above the fibers and left the
    whole heatmap dark, and a few negative noise pixels dragged ``vmin``
    tens of sigma below the substrate and washed the image out.
    両端とも選んだ母集団の統計量で決め、単一の極値では決めない。従来規則は
    ``nanmin``/``nanmax`` を直接使っていたため、コンタミ 1 点で ``vmax`` が
    ファイバーより遥かに上へ張り付いて画像全体が暗くなり、負のノイズ数画素で
    ``vmin`` が基板より数十 σ 下がって画像が白っぽく飛んだ。

    The upper population is chosen in this order:

    1. ``mask`` pixels (the bundle's skeleton), if the mask is usable.
    2. otherwise pixels above ``level + 3 * sigma`` — the fiber body.
    3. otherwise ``level + 5 * sigma``, for an image with no features.

    上側の母集団は 1. マスク（バンドルのスケルトン）画素、2. 使えなければ
    ``level + 3σ`` を超える画素（ファイバー本体）、3. それも無ければ
    ``level + 5σ``（構造の無い画像）の順に選ぶ。

    Restricting the percentile to fiber pixels is what makes it safe here.
    A percentile over *all* pixels was tried before and withdrawn because it
    depends on fiber coverage: at the 0.2-0.9 % skeleton coverage of this
    project's test images, even the 99th percentile of the whole image still
    lands in the background, so the fibers saturate.
    パーセンタイルをファイバー画素に限定する点が要である。かつて全画素の
    パーセンタイルを試して撤回したのは、その値がファイバー被覆率に依存する
    ためで、本プロジェクトの試験画像のスケルトン被覆率 0.2〜0.9 % では全画素の
    99 パーセンタイルすら背景に落ち、ファイバーが飽和してしまう。

    Parameters
    ----------
    image_array
        Height image (2D array) in nanometers.
        高さ画像（2D 配列、単位 nm）。
    mask
        Optional fiber mask with the same shape, typically the bundle's
        ``skeletonized`` array. Pixels selected by the mask define the upper
        bound. ``None`` falls back to the coverage-independent estimate.
        任意のファイバーマスク（同形状、通常はバンドルの ``skeletonized``）。
        マスクが選ぶ画素で上端を決める。``None`` なら被覆率に依存しない推定に
        フォールバックする。
    k_low
        Number of background sigmas below the background level placed at
        ``vmin``.
        ``vmin`` を背景レベルの何 σ 下に置くか。
    fiber_pct
        Percentile taken over the mask pixels for ``vmax``.
        ``vmax`` を決めるためにマスク画素に対して取るパーセンタイル。
    fg_pct
        Percentile taken over the above-background pixels when no mask is
        given.
        マスクが無いとき、背景より上の画素に対して取るパーセンタイル。
    low_clip_pct
        Largest share of pixels, in percent, that ``vmin`` may leave below the
        display range.
        ``vmin`` が表示範囲より下へ追い出してよい画素の割合の上限 (%)。
    min_span
        Smallest allowed ``vmax - vmin`` in nanometers.
        許容する ``vmax - vmin`` の最小値 (nm)。

    Returns
    -------
    (vmin, vmax) : tuple of int
        Integer-valued bounds suitable for direct use as ``imshow(vmin=, vmax=)``.

    Notes
    -----
    The bounds are clamped to the data range, so the result never widens the
    display beyond what the image contains. Because the upper bound is a
    percentile, a small fraction of pixels is expected to saturate — on this
    project's test bundles under 0.12 %.
    両端はデータ範囲で頭打ちにするため、画像に含まれる以上に表示範囲が広がる
    ことはない。上端はパーセンタイルなので、わずかな画素は飽和する前提である
    （本プロジェクトの試験バンドルでは 0.12 % 未満）。

    NaN-tolerant. Empty arrays or unexpected types fall back to the
    project-wide defaults ``DEFAULT_VMIN`` / ``DEFAULT_VMAX``.
    NaN を含む可能性に備えて有限値だけを使う。空配列・想定外の型では
    プロジェクト共通の既定値 ``DEFAULT_VMIN`` / ``DEFAULT_VMAX`` を返す。
    """
    fallback = (int(math.floor(DEFAULT_VMIN)), int(math.ceil(DEFAULT_VMAX)))
    try:
        arr = np.asarray(image_array, dtype=float)
    except (ValueError, TypeError):
        return fallback
    if arr.size == 0:
        return fallback

    finite = np.isfinite(arr)
    values = arr[finite]
    # An all-NaN image has no height information to scale to.
    # 全 NaN の画像には基準にできる高さ情報が無い。
    if values.size == 0:
        return fallback

    level, sigma = _background_level(values)

    fiber_values = None
    if mask is not None:
        selected = np.asarray(mask).astype(bool, copy=False)
        if selected.shape == arr.shape:
            masked = arr[selected & finite]
            if masked.size >= _AUTO_VRANGE_MIN_SUBSET:
                fiber_values = masked
    if fiber_values is not None:
        top = float(np.percentile(fiber_values, fiber_pct))
    else:
        foreground = values[values > level + 3.0 * sigma]
        # Require the foreground to be more than a handful of stray pixels
        # before a percentile of it is trusted.
        # 前景が数画素の飛び値でないことを確認してからパーセンタイルを信用する。
        if foreground.size >= max(_AUTO_VRANGE_MIN_SUBSET, 0.0005 * values.size):
            top = float(np.percentile(foreground, fg_pct))
        else:
            top = level + 5.0 * sigma

    # Lower the bound if the sigma-based one would darken more than
    # low_clip_pct of the image, which happens on a tilted uncorrected scan
    # where the substrate is a broad ramp instead of a narrow noise band.
    # σ ベースの下端が画素の low_clip_pct 超を暗側へ潰す場合は下端を下げる。
    # 基板が狭いノイズ帯ではなく広い傾斜面になる未補正スキャンで起こる。
    bottom = min(level - k_low * sigma,
                 float(np.percentile(values, low_clip_pct)))

    # Clamp to the data range: widening past it only wastes the colormap.
    # データ範囲で頭打ちにする。これを超えて広げてもカラーマップを捨てるだけ。
    bottom = max(bottom, float(values.min()))
    top = min(top, float(values.max()))

    v_lo = int(math.floor(bottom))
    v_hi = int(math.ceil(top))
    if v_hi - v_lo < min_span:
        v_hi = v_lo + int(math.ceil(min_span))
    return v_lo, v_hi


def setup_matplotlib_style(font_size: int = 12) -> None:
    """
    Apply the project-wide matplotlib style.
    プロジェクト共通の matplotlib スタイルを適用する。

    Call this once from each GUI's __init__ before creating any Figure.
    各 GUI の __init__ で Figure を作る前に一度だけ呼ぶこと。
    """
    # Prefer sans-serif fonts suitable for publication figures.
    # フォント：論文体裁に合わせて sans-serif 系の Arial / Helvetica を優先。
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]

    # Enable minor ticks to improve readability of histograms and profiles.
    # 補助目盛を表示（ヒストグラム・プロファイルの可読性向上）。
    plt.rcParams["xtick.minor.visible"] = True
    plt.rcParams["ytick.minor.visible"] = True

    # Font size is caller-controlled because each GUI has different layout constraints.
    # フォントサイズは引数で受ける（GUIごとに最適値が違うため）。
    plt.rcParams["font.size"] = font_size

    # Embed editable fonts in PDF/PS/SVG output.
    # PDF/PS/SVG 出力時にフォントを編集可能な形式で埋め込む。
    # （Illustrator 等で投稿後の図ラベル修正ができるようにする）
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42
    plt.rcParams["svg.fonttype"] = "none"


def figure_save_filetypes() -> list[tuple[str, str]]:
    """
    Filetypes list for figure save dialogs.
    figure 保存ダイアログ用の filetypes リスト。

    Order matters: PNG first (most common), PDF/SVG for paper submission,
    TIFF for journals that require it.
    順序は意図的：PNG（最頻用）を先頭、PDF/SVG を論文投稿用に、
    TIFF を要求するジャーナル向けにも対応。

    Note: ラベル "PNG" "PDF" 等は技術用語のため _() 翻訳は不要。
    """
    return [
        ("PNG", "*.png"),
        ("PDF", "*.pdf"),
        ("SVG", "*.svg"),
        ("TIFF", "*.tiff"),
        ("All files", "*.*"),
    ]
def save_figure_with_dialog(
    parent,
    fig,
    *,
    initial_name: str,
    initial_dir: str | None = None,
    title: str | None = None,
    dpi: int | None = None,
    log_cb=None,
    notify_on_success: bool = False,
) -> str | None:
    """
    Show a 'Save as' dialog and save a matplotlib Figure with the project's
    standard filetypes / DPI / error handling.
    matplotlib Figure を共通の filetypes / DPI / エラー処理で保存する。

    Parameters
    ----------
    parent : tk widget
        Parent for dialogs (required for modal correctness).
    fig : matplotlib.figure.Figure
        Figure to save.
    initial_name : str
        Default file name shown in the dialog.
    initial_dir : str | None
        Initial directory; defaults to os.getcwd() when None.
    title : str | None
        Dialog title; defaults to _("図を保存") when None.
    dpi : int | None
        Save DPI; defaults to FIGURE_SAVE_DPI when None.
    log_cb : callable | None
        Optional log callback receiving a translated success message.
    notify_on_success : bool
        If True, also show a messagebox.showinfo on success.

    Returns
    -------
    str | None
        Saved file path, or None if cancelled or failed.
    """
    path = filedialog.asksaveasfilename(
        parent=parent,
        title=title or _("図を保存"),
        defaultextension=".png",
        initialdir=initial_dir or os.getcwd(),
        initialfile=initial_name,
        filetypes=figure_save_filetypes(),
    )
    if not path:
        return None
    try:
        fig.savefig(path, dpi=dpi or FIGURE_SAVE_DPI, bbox_inches="tight")
    except Exception as exc:
        messagebox.showerror(_("保存エラー"),
                             _("保存に失敗しました:\n{e}").format(e=exc),
                             parent=parent)
        return None
    msg = _("保存: {path}").format(path=path)
    if log_cb:
        log_cb(msg)
    if notify_on_success:
        messagebox.showinfo(_("保存完了"), msg, parent=parent)
    return path
