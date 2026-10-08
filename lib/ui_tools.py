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
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import ArrayLike

from lib.translator import _

if TYPE_CHECKING:
    # Annotation only: the Tk backend is imported at run time inside
    # `build_pan_zoom_toolbar`, which is the only function that needs it.
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Resolution used when saving publication-ready PNG figures.
# 論文用 PNG 保存時の解像度。
FIGURE_SAVE_DPI = 300


def setup_ttk_theme(root: tk.Misc, *, theme: str = "clam",
                    unconfirmed_bg: str = "#cfe6ff") -> str:
    """
    Apply the shared ttk theme and styles used by the GUI windows.
    GUI ウィンドウ共通の ttk テーマとスタイルを適用する。

    Parameters
    ----------
    root
        Window or widget whose ``ttk.Style`` is configured. Its background is
        also set to the theme background when it accepts one.
        ``ttk.Style`` を設定するウィンドウまたはウィジェット。背景色を受け付ける
        場合は、その背景もテーマの背景色にする。
    theme
        Name of the ttk theme to use. A name Tk does not know leaves the
        current theme in place.
        使用する ttk テーマ名。Tk が知らない名前なら現在のテーマのままにする。
    unconfirmed_bg
        Field background of the ``Unconfirmed.TEntry`` style, which marks an
        entry whose text has not been committed yet.
        未確定の入力欄を示す ``Unconfirmed.TEntry`` スタイルの入力欄背景色。

    Returns
    -------
    str
        Theme background color, so callers can also apply it to non-ttk
        widgets such as ``tk.Tk``, ``tk.Frame``, or Matplotlib toolbars.
        テーマの背景色。``tk.Tk``・``tk.Frame``・Matplotlib のツールバーなど、
        ttk 以外のウィジェットにも適用できるように返す。
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


def localized_combobox_width(values: Sequence[Any], min_width: int = 4,
                             max_width: int = 16) -> int:
    """
    Return a bounded Combobox width for translated labels.
    翻訳後ラベルに合わせた上限付き Combobox 幅を返す。

    Parameters
    ----------
    values
        Labels the combobox offers, already translated.
        Combobox が表示する翻訳済みの選択肢。
    min_width, max_width
        Bounds of the returned width, in characters.
        返す幅の下限と上限（文字数）。

    Returns
    -------
    int
        Width for ``ttk.Combobox(width=...)``: the widest label measured in
        the default font, in widths of ``"0"``, plus 4, or the longest label
        length plus 2 when the font cannot be measured, clipped to
        ``[min_width, max_width]``. An empty `values` gives `min_width`.
        ``ttk.Combobox(width=...)`` に渡す幅。既定フォントで測った最も広い
        ラベルの幅を ``"0"`` の幅単位で表した値に 4 を足したもの（フォントを
        測れないときは最長ラベルの文字数に 2 を足したもの）を
        ``[min_width, max_width]`` に収める。`values` が空なら `min_width`。
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


def rewrite_entries(pairs: Iterable[tuple[ttk.Entry, Any]], *,
                    formatter: Callable[[Any], str] = str) -> None:
    """
    Rewrite Entry widgets with committed values, ignoring destroyed widgets.
    Entry に確定済みの値を書き戻す。破棄済みのウィジェットは無視する。

    Parameters
    ----------
    pairs
        ``(entry, value)`` pairs. Each entry's text is replaced by its value.
        ``(entry, value)`` の組。各 entry の文字列を value で置き換える。
    formatter
        Callable that turns a value into the text written to the entry.
        値を entry に書き込む文字列へ変換する呼び出し可能オブジェクト。
    """
    for entry, value in pairs:
        try:
            entry.delete(0, tk.END)
            entry.insert(0, formatter(value))
        except (tk.TclError, AttributeError):
            pass


def mark_entry_state(entry: ttk.Entry, committed_str: str) -> None:
    """
    Mark an Entry as normal or unconfirmed by comparing it with committed text.
    入力欄の文字列を確定済みの文字列と比べ、通常表示か未確定表示にする。

    Parameters
    ----------
    entry
        Entry whose style is set: ``TEntry`` when its text equals
        `committed_str`, ``Unconfirmed.TEntry`` otherwise. A destroyed entry
        is left alone.
        スタイルを設定する入力欄。文字列が `committed_str` と等しければ
        ``TEntry``、異なれば ``Unconfirmed.TEntry`` にする。破棄済みの入力欄は
        何もしない。
    committed_str
        Text of the value currently committed for this entry.
        この入力欄で現在確定している値の文字列。
    """
    try:
        current = entry.get()
    except tk.TclError:
        return
    style_name = "TEntry" if current == committed_str else "Unconfirmed.TEntry"
    try:
        entry.configure(style=style_name)
    except tk.TclError:
        pass


def refresh_entry_placeholder(entry: ttk.Entry, ghost: tk.Widget, *,
                              x: int = 4) -> None:
    """
    Show or hide a placeholder ghost over an Entry.
    入力欄に重ねたプレースホルダのゴーストを表示/非表示する。

    Parameters
    ----------
    entry
        Entry the ghost belongs to.
        ゴーストが属する入力欄。
    ghost
        Widget placed over `entry` while the hint should be visible.
        ヒントを見せる間、`entry` の上に重ねて配置するウィジェット。
    x
        Ghost's left inset within the entry, in pixels.
        入力欄内でのゴーストの左オフセット（画素）。

    Notes
    -----
    The ghost is shown only while the entry is empty and unfocused, so it
    reads as placeholder text without ever contributing to ``Entry.get()``.
    Overlaying a separate widget is what keeps the hint out of the committed
    value; writing it into the entry would make the placeholder indis-
    tinguishable from something the user typed.
    ゴーストは入力欄が空かつ非フォーカスのときだけ表示し、``Entry.get()`` には
    一切影響しないプレースホルダとして読ませる。別ウィジェットを重ねること自体
    が、ヒントを確定値から切り離す手段である。入力欄へ文字を書き込む方式では、
    プレースホルダとユーザーの入力を区別できなくなる。
    """
    try:
        focused = entry.focus_get() is entry
        empty = entry.get() == ""
    except tk.TclError:
        return
    if empty and not focused:
        # Overlay the ghost at the left inner edge of the field.
        # フィールド左内側にゴーストを重ねる。
        ghost.place(x=x, rely=0.5, anchor="w")
    else:
        ghost.place_forget()


def _set_text_state(text_widget, state: str) -> None:
    try:
        text_widget.configure(state=state)
    except (tk.TclError, AttributeError):
        pass


def append_log(text_widget: tk.Text, msg: object, *, timestamp: bool = True,
               readonly: bool = True) -> None:
    """
    Append one log message to a Text widget and keep the newest line visible.
    Text ウィジェットにログを 1 件追記し、最新行が見えるようにする。

    Parameters
    ----------
    text_widget
        Log widget. A destroyed widget is left alone.
        ログ表示用のウィジェット。破棄済みなら何もしない。
    msg
        Message, written as ``str(msg)`` with trailing whitespace removed.
        メッセージ。``str(msg)`` から末尾の空白を除いて書き込む。
    timestamp
        When ``True``, prefix the line with the current time as
        ``[HH:MM:SS]``.
        ``True`` のとき、行頭に現在時刻を ``[HH:MM:SS]`` の形で付ける。
    readonly
        When ``True``, the widget is kept ``disabled`` and enabled only while
        the line is written, so the user cannot type into the log.
        ``True`` のとき、ウィジェットを ``disabled`` に保ち、書き込む間だけ
        有効にする。ユーザーがログに入力できないようにするため。
    """
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


def replace_log_tail(text_widget: tk.Text, msg: object, *,
                     readonly: bool = True) -> None:
    """
    Replace the previous log line with text, used for progress updates.
    直前のログ行を置き換える。進捗表示の更新に使う。

    Parameters
    ----------
    text_widget
        Log widget. A destroyed widget is left alone.
        ログ表示用のウィジェット。破棄済みなら何もしない。
    msg
        Replacement text, written as ``str(msg)`` with trailing whitespace
        removed and no timestamp.
        置き換える文字列。``str(msg)`` から末尾の空白を除き、時刻を付けずに
        書き込む。
    readonly
        When ``True``, the widget is kept ``disabled`` and enabled only while
        the line is replaced.
        ``True`` のとき、ウィジェットを ``disabled`` に保ち、置き換える間だけ
        有効にする。
    """
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


def clear_text_widget_log(text_widget: tk.Text, *,
                          readonly: bool = True) -> None:
    """
    Remove all text from a log Text widget, toggling readonly state as needed.
    ログ用 Text ウィジェットの文字列をすべて消す。必要に応じて読み取り専用状態を切り替える。

    Parameters
    ----------
    text_widget
        Log widget. A destroyed widget is left alone.
        ログ表示用のウィジェット。破棄済みなら何もしない。
    readonly
        When ``True``, the widget is kept ``disabled`` and enabled only while
        it is cleared.
        ``True`` のとき、ウィジェットを ``disabled`` に保ち、消去する間だけ
        有効にする。
    """
    if readonly:
        _set_text_state(text_widget, "normal")
    try:
        text_widget.delete("1.0", tk.END)
    except (tk.TclError, AttributeError):
        pass
    finally:
        if readonly:
            _set_text_state(text_widget, "disabled")


def save_text_widget_log(parent: tk.Misc, text_widget: tk.Text, *,
                         initial_dir: str | None = None,
                         initialfile: str = "log.txt",
                         title: str | None = None,
                         empty_warning: bool = False,
                         log_cb: Callable[[str], None] | None = None,
                         success_message: str | None = None,
                         error_title: str | None = None,
                         failure_message: str | None = None) -> str | None:
    """
    Save a Text widget's content as UTF-8 text through a file dialog.
    Text ウィジェットの内容をファイルダイアログ経由で UTF-8 テキストとして保存する。

    Parameters
    ----------
    parent
        Parent for the file, warning, and error dialogs.
        ファイル・警告・エラーの各ダイアログの親。
    text_widget
        Widget whose whole content is saved.
        内容全体を保存するウィジェット。
    initial_dir
        Folder the dialog opens in; ``None`` leaves it to Tk.
        ダイアログを開くフォルダ。``None`` なら Tk に任せる。
    initialfile
        File name the dialog proposes.
        ダイアログが提示するファイル名。
    title
        Dialog title; ``None`` uses the translated "save log" title.
        ダイアログのタイトル。``None`` なら翻訳済みの「ログを保存」を使う。
    empty_warning
        When ``True``, an empty log shows a warning instead of the dialog.
        ``True`` のとき、ログが空ならダイアログの代わりに警告を表示する。
    log_cb
        Called with the success message after the file is written.
        ファイルを書き込んだ後に成功メッセージを渡して呼ぶコールバック。
    success_message
        Success message format with a ``{path}`` field; ``None`` uses the
        translated default.
        ``{path}`` を含む成功メッセージの書式。``None`` なら翻訳済みの既定文。
    error_title
        Title of the error dialog shown when writing fails.
        書き込みに失敗したときのエラーダイアログのタイトル。
    failure_message
        Error message format with an ``{e}`` field for the exception.
        例外を入れる ``{e}`` を含むエラーメッセージの書式。

    Returns
    -------
    str or None
        Saved file path, or ``None`` when the log was empty and
        `empty_warning` is set, the dialog was cancelled, or writing failed.
        保存先のパス。ログが空で `empty_warning` が有効な場合、ダイアログが
        キャンセルされた場合、書き込みに失敗した場合は ``None``。
    """
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


def create_scrolled_text(parent: tk.Misc, *, scrollbar_side: str = "right",
                         text_side: str = "left",
                         **text_kwargs: Any) -> tuple[tk.Text, ttk.Scrollbar]:
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


def create_scrolled_treeview(
        parent: tk.Misc, *,
        columns: Sequence[str] = (),
        show: str = "headings",
        selectmode: str | None = None,
        height: int | None = None,
        headings: Mapping[str, str] | None = None,
        column_options: Mapping[str, Mapping[str, Any]] | None = None,
        scrollbar_side: str = "right",
        tree_side: str = "left",
        tree_pack_kwargs: Mapping[str, Any] | None = None,
        scrollbar_pack_kwargs: Mapping[str, Any] | None = None,
        hscroll: bool = False,
        **tree_kwargs: Any) -> tuple[ttk.Treeview, ttk.Scrollbar]:
    """
    Create a Treeview with scrollbars and optional column metadata.
    スクロールバー付き Treeview を作成し、任意の列メタデータを設定する。

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
    scrollbar_side
        Pack side for the vertical scrollbar.
        縦スクロールバーを pack する側。
    tree_side
        Pack side for the Treeview.
        Treeview を pack する側。
    tree_pack_kwargs
        Optional keyword arguments merged into the Treeview ``pack`` call.
        Treeview の ``pack`` 呼び出しに追加する任意のキーワード引数。
    scrollbar_pack_kwargs
        Optional keyword arguments merged into the scrollbar ``pack`` call.
        スクロールバーの ``pack`` 呼び出しに追加する任意のキーワード引数。
    hscroll
        When ``True``, also add a horizontal scrollbar along the bottom.
        ``True`` のとき、下端に横スクロールバーも追加する。
    **tree_kwargs
        Further keyword arguments passed to ``ttk.Treeview``.
        ``ttk.Treeview`` に渡すその他のキーワード引数。

    Returns
    -------
    tuple
        ``(tree, vertical_scrollbar)`` created and linked together. The
        horizontal scrollbar, when requested, is packed and wired but not
        returned, because callers only ever need to reach the tree.
        作成して相互接続した ``(tree, 縦スクロールバー)``。横スクロールバーは、
        要求された場合も配置と接続だけ行い戻り値には含めない。呼び出し側が必要と
        するのは常に tree だけであるため。

    Notes
    -----
    A Treeview requests the sum of its column widths, so a table with many
    columns pushes its container wide enough to squeeze whatever shares the
    window. `hscroll` lets the container be narrowed instead, keeping every
    column reachable on any screen width.
    Treeview は列幅の合計を要求サイズとするため、列の多いテーブルはコンテナを
    押し広げ、同じウインドウを共有する他の要素を圧迫する。`hscroll` を使うと
    代わりにコンテナを狭められるので、どの画面幅でも全ての列に到達できる。
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

    # Pack the horizontal bar first so it claims the full-width bottom strip;
    # packing it after the tree would leave it beside the tree instead.
    # 横バーを先に配置し、下端の全幅を確保する。tree の後に配置すると下端では
    # なく tree の横に並んでしまう。
    if hscroll:
        hbar = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=hbar.set)
        hbar.pack(side="bottom", fill="x")

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

    Parameters
    ----------
    event
        Tk ``<MouseWheel>``, ``<Button-4>`` or ``<Button-5>`` event.
        Tk の ``<MouseWheel>``・``<Button-4>``・``<Button-5>`` イベント。

    Returns
    -------
    int
        Scroll units, negative to scroll up: one per Windows notch of 120,
        and one for a smaller delta or an X11 button.
        スクロール単位。負なら上へ。Windows では 120 ごとに 1、それより小さい
        delta や X11 のボタンでは 1。

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


def bind_mousewheel_scroll(canvas: tk.Canvas,
                           scope: tk.Misc | None = None) -> None:
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


def scale_xy_um(scale_um: float, scale_y_um: float | None) -> tuple:
    """
    Return the (X, Y) scan size in micrometers, a blank Y following X.
    走査範囲 (X, Y) を µm で返す。Y が空の場合は X に従う。

    Parameters
    ----------
    scale_um
        Physical scan size along X (width), in micrometers.
        X（幅）方向の物理走査範囲 (µm)。
    scale_y_um
        Physical scan size along Y (height), or ``None`` when not set.
        Y（高さ）方向の物理走査範囲。未設定なら ``None``。

    Returns
    -------
    tuple
        ``(x_um, y_um)`` with the Y fallback already applied.
        Y のフォールバックを適用済みの ``(x_um, y_um)``。

    Notes
    -----
    An unset Y meaning "square scan" is a contract shared by every GUI that
    offers the two scale fields, so it is resolved in one place: a GUI that
    read a blank Y as zero, or as the image height in pixels, would draw and
    measure a different physical aspect from its siblings for the same file.
    Y 未設定を「正方スキャン」と解釈する規約は、2 つのスケール入力欄を持つ全 GUI
    で共有される。そのため解決は 1 か所で行う。空の Y を 0 や画素数として読む GUI
    があると、同じファイルに対して他の GUI と異なる物理アスペクトで描画・計測して
    しまう。
    """
    return scale_um, (scale_um if scale_y_um is None else scale_y_um)


def extent_scales_xy_and_unit(x_um: float, y_um: float, unit: str) -> tuple:
    """
    Return per-axis extent scales and the shared unit label.
    軸別の extent スケールと共通の単位ラベルを返す。

    Parameters
    ----------
    x_um
        Physical scan size along X (width), in micrometers.
        X（幅）方向の物理走査範囲 (µm)。
    y_um
        Physical scan size along Y (height), in micrometers.
        Y（高さ）方向の物理走査範囲 (µm)。
    unit
        Requested display unit, as `extent_scale_and_unit` reads it.
        表示単位。解釈は `extent_scale_and_unit` と同じ。

    Returns
    -------
    tuple
        ``(x_scale, y_scale, unit_label)`` for a Matplotlib extent and its
        axis labels.
        Matplotlib の extent と軸ラベルに使う ``(x_scale, y_scale, unit_label)``。

    Notes
    -----
    X takes the width scale and Y the height scale, so a rectangular scan or a
    non-square pixel grid draws with the correct physical aspect. Both axes are
    converted with the same unit, so the single returned label describes both.
    X は幅スケール、Y は高さスケールを取り、矩形スキャンや非正方ピクセル格子を
    正しい物理アスペクトで描画する。両軸とも同じ単位で換算するため、返す 1 つの
    ラベルが両軸を説明する。
    """
    x_scale, unit_label = extent_scale_and_unit(x_um, unit)
    y_scale, _unit_label = extent_scale_and_unit(y_um, unit)
    return x_scale, y_scale, unit_label


def drain_ui_queue(ui_queue: queue.Queue,
                   handlers: Mapping[str, Callable[[Any], Any]]) -> bool:
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
    parent: tk.Misc,
    writer_cb: Callable[[str], None],
    *,
    initial_name: str,
    initial_dir: str | None = None,
    title: str | None = None,
    log_cb: Callable[[str], None] | None = None,
    success_message: str | None = None,
    error_title: str | None = None,
    failure_message: str | None = None,
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
    success_message
        Success message format with a ``{path}`` field; ``None`` uses the
        translated default.
        ``{path}`` を含む成功メッセージの書式。``None`` なら翻訳済みの既定文。
    error_title
        Title of the error dialog shown when `writer_cb` raises; ``None``
        uses the translated default.
        `writer_cb` が例外を送出したときのエラーダイアログのタイトル。
        ``None`` なら翻訳済みの既定文。
    failure_message
        Error message format with an ``{e}`` field for the exception;
        ``None`` uses the translated default.
        例外を入れる ``{e}`` を含むエラーメッセージの書式。``None`` なら
        翻訳済みの既定文。

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
#   Keep the unconfirmed-Entry mechanism and the logging behavior shared by
#   GUI01-04 and their sub-dialogs in one place. Usage is shown in the
#   docstrings of `UnconfirmedEntryMixin` and `LogMixin`.
# 目的
#   GUI01〜04 の App とサブダイアログが共有する「未確定 Entry 機構」「ログ機構」を
#   Mixin として一箇所にまとめる。使い方は `UnconfirmedEntryMixin` と `LogMixin`
#   の docstring にある。
#
# Notes
#   - The mixins intentionally avoid __init__ so they do not disrupt tk.Tk MRO.
#     Call _init_unconfirmed_registry() explicitly once instead.
#   - LogMixin._log depends on self.log_text; do not call it before log_text exists.
#   - UnconfirmedEntryMixin owns the unconfirmed-Entry mechanism; classes
#     using that mechanism should inherit this mixin.
# 注意
#   - Mixin の __init__ は意図的に作らない（tk.Tk 系の MRO を壊さないため）。
#     代わりに明示メソッド _init_unconfirmed_registry() を一度だけ呼ぶ運用にする。
#   - LogMixin._log は self.log_text の存在に依存する。log_text を作る前には呼ばない。
#   - UnconfirmedEntryMixin のメソッドは「未確定 Entry 機構」の実体である。
#     Entry 機構を使うクラスは必ずこの Mixin を継承する。
# =============================================================================


class UnconfirmedEntryMixin:
    """
    Provide the "Enter-to-commit" entry mechanism used by all four GUIs.
    GUI01〜04 で共通の「Enter 確定 Entry」機構を提供する Mixin。

    Subclasses must call ``_init_unconfirmed_registry()`` once (typically in
    ``__init__``) before registering any Entry. Sub-dialogs that need their
    own independent registry can hold a separate list and pass it via the
    ``registry`` keyword argument of ``_register_unconfirmed_entry``.

    Usage::

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

        Parameters
        ----------
        v
            Committed value.
            確定済みの値。

        Returns
        -------
        str
            ``str(v)``.
            ``str(v)``。
        """
        return str(v)

    def _maybe_show_enter_hint(self) -> None:
        """
        Log the Enter-to-commit hint the first time an entry is left unconfirmed.
        入力欄が初めて未確定になったときに、Enter で確定する旨をログに 1 回だけ出す。

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

        When ``registry`` is omitted, ``self._unconfirmed_entries`` is used. A
        sub-dialog that keeps its own registry, so as not to mix its entries
        with the main window's, passes ``registry`` explicitly.
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

        Parameters
        ----------
        entry
            Entry widget to register.
            登録する入力欄。
        get_committed_str
            Returns the text of the value currently committed for the entry.
            その入力欄で現在確定している値の文字列を返す関数。
        commit_cb
            Validates and commits the entry's value; returns True on success.
            入力欄の値を検証・確定し、成功すれば True を返す関数。
        registry
            Registry list to add the entry to, as described above.
            入力欄を加える登録簿（上記参照）。

        Returns
        -------
        Entry
            `entry` itself.
            `entry` そのもの。
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

        Each registry item is ``(entry, committed_text_getter,
        commit_callback)``. When several changed entries share one
        commit_cb, it is called only once (vmin and vmax, for example, are
        validated together by one function).
        各登録簿項目は ``(entry, committed_text_getter, commit_callback)``。
        複数 Entry が同じ commit_cb を共有している場合、commit_cb は 1 回しか
        呼ばない（例: vmin / vmax がまとめて 1 関数で検証される設計）。

        Parameters
        ----------
        registry
            Registry list to commit.
            確定する登録簿。
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

        Parameters
        ----------
        registry
            Registry list to refresh; ``None`` uses ``self._unconfirmed_entries``.
            再評価する登録簿。``None`` なら ``self._unconfirmed_entries``。
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

        Each value is cast from its entry, the new values are checked together
        by `validator`, and only when every check passes are they assigned to
        ``self.<attr_name>``, written back to the entries, and followed by
        `on_success`. The first failure shows an error dialog and commits
        nothing.
        各値を Entry から変換し、新しい値をまとめて `validator` で検証する。
        すべて通ったときだけ ``self.<attr_name>`` に代入して Entry に書き戻し、
        `on_success` を呼ぶ。最初の失敗でエラーダイアログを表示し、何も確定しない。

        Parameters
        ----------
        fields : list[tuple]
            Tuples ``(entry, attr_name, label)``,
            ``(entry, attr_name, label, cast)``, or the legacy
            ``(var, entry, attr_name, label)``:
              - entry: ttk.Entry that is read and written back
              - attr_name: attribute ``self.<attr_name>`` that receives the
                new value
              - label: not used; it names the field so the call site reads
                clearly (may be ``None``)
              - cast: conversion used for this field only (the `cast`
                argument when omitted)
            The value is always read from ``entry.get().strip()``.
            ``(entry, attr_name, label)``、``(entry, attr_name, label, cast)``、
            または旧形式 ``(var, entry, attr_name, label)`` のタプル列。
              - entry: ttk.Entry（書き戻し対象）
              - attr_name: ``self.<attr_name>`` に新値を代入する属性名
              - label: 使われない。呼び出し側でフィールドを読みやすくするための値
                （``None`` 可）
              - cast: そのフィールドのみに使う変換関数（省略時は引数 ``cast``）
            数値の取得は常に ``entry.get().strip()`` から行う。
        cast : callable
            Default conversion; a per-field cast in `fields` takes precedence.
            既定の変換関数（既定: ``float``）。フィールド側で個別指定があれば
            そちらが優先される。
        validator : callable[[dict[str, Any]], str | None] | None
            Receives the new values as ``{attr_name: value, ...}`` and returns
            ``None`` to accept them or an error message to show. ``None``
            checks only that every cast succeeds.
            検証関数。新しい値を ``{attr_name: value, ...}`` の dict で受け取り、
            合格なら ``None``、不合格なら表示用エラーメッセージを返す。
            ``None`` の場合は cast 成功のみを検証とする。
        on_success : callable[[], None] | None
            Called after the values are assigned and written back; redrawing
            or recalculation goes here.
            検証通過後、内部状態に代入し書き戻した後に呼ばれるコールバック。
            描画や再計算をここで行う。
        parent : tk widget | None
            Parent of the error dialogs; ``None`` uses ``self``.
            messagebox の親（既定: self）。

        Returns
        -------
        bool
            ``True`` when the values were committed, ``False`` when one was
            invalid.
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

        The range comes from `compute_auto_vrange`. It is assigned to
        ``self.vmin`` / ``self.vmax`` and written back to ``self.ent_vmin`` /
        ``self.ent_vmax``, and the unconfirmed styles are re-evaluated.
        Redrawing is left to the caller.
        ``compute_auto_vrange`` で範囲を求め、``self.vmin`` / ``self.vmax`` に
        代入し、``self.ent_vmin`` / ``self.ent_vmax`` へ書き戻したうえで未確定
        スタイルを再評価する（共通化対象のステップ 1〜4）。再描画は呼び出し側の
        責務とし、本メソッドでは行わない。

        It works both in GUI02 (plain entries) and in GUI04 (entries bound to
        a textvariable): `rewrite_entries` writes through the entry's
        delete/insert, so a bound StringVar follows automatically.
        GUI02（素の Entry）と GUI04（textvariable 紐づけ Entry）の双方で動作する。
        ``rewrite_entries`` は Entry の delete/insert で書き込むため、
        textvariable が紐づいていれば StringVar 側にも自動的に反映される。

        Parameters
        ----------
        image_array : array-like
            Height image (2D array), passed to ``compute_auto_vrange``.
            高さ画像（2D 配列）。``compute_auto_vrange`` に渡す。
        mask : array-like or None
            Optional fiber mask (the bundle's ``skeletonized``) used for the
            upper bound; without it the estimate falls back to one that does
            not use a mask.
            任意のファイバーマスク（バンドルの ``skeletonized``）。上端の推定に
            使い、無い場合はマスク非依存の推定にフォールバックする。
        log
            When ``True`` and ``self._log`` is available, log the committed
            values.
            True かつ ``self._log`` が利用可能なら、確定値をログに出力する。

        Returns
        -------
        (v_lo, v_hi) : tuple of int | None
            Computed range. The values are returned even when they cannot be
            written back, for example when the window has no ``ent_vmin`` /
            ``ent_vmax``.
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
    Provide ``_log`` and ``_log_exception`` to GUI windows with a log widget.
    ログ用ウィジェットを持つ GUI ウィンドウに ``_log`` と ``_log_exception`` を提供する。

    The window must own a ``self.log_text`` Text widget, and the methods must
    not be called before it has been created.
    ``self.log_text`` を持つ GUI に対して、共通の ``_log`` /
    ``_log_exception`` を提供する Mixin。``log_text`` を生成する前に
    呼んではいけない。

    Usage::

        class App(tk.Tk, LogMixin):
            def __init__(self):
                super().__init__()
                ...
                self.log_text = tk.Text(...)  # create it before the first _log
                self._log("Ready.")
    """

    def _log(self, msg) -> None:
        """
        Append one line to the log Text widget.
        ログテキストウィジェットに1行追加する。

        Parameters
        ----------
        msg
            Message, written with a timestamp (`append_log`).
            時刻付きで書き込むメッセージ（`append_log`）。
        """
        append_log(self.log_text, msg)

    def _clear_log(self) -> None:
        """
        Remove everything from the log Text widget.
        ログテキストウィジェットの内容を全消去する。
        """
        clear_text_widget_log(self.log_text)

    def _log_exception(self, prefix: str, exc: BaseException) -> None:
        """
        Log an exception with the stack trace of the exception being handled.
        例外をスタックトレース付きでログに出す。

        Parameters
        ----------
        prefix
            Text written before the exception.
            例外の前に書く文字列。
        exc
            The exception; call this inside the ``except`` block that caught
            it, so the trace is the one being handled.
            例外。それを捕まえた ``except`` ブロックの中で呼ぶこと。そうすれば
            トレースは処理中の例外のものになる。
        """
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
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event: tk.Event) -> None:
        """
        Create and show the tooltip popup near the mouse cursor.
        マウスカーソル付近にツールチップのポップアップを作成して表示する。

        Parameters
        ----------
        event
            Tkinter event object for mouse-enter action.
            マウス進入時の tkinter イベントオブジェクト。

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
        self.tooltip = tk.Toplevel(self.widget)
        # Remove the title bar and borders so the window reads as a popup.
        self.tooltip.wm_overrideredirect(True)
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

    def hide_tooltip(self, event: tk.Event | None) -> None:
        """
        Hide and destroy the tooltip popup if it is visible.
        ツールチップが表示中であれば非表示にして破棄する。

        Parameters
        ----------
        event
            Tkinter event object for mouse-leave action.
            マウス離脱時の tkinter イベントオブジェクト。
        """
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class HeadingToolTip(ToolTip):
    """
    Show a per-column tooltip while the mouse is over a Treeview heading.
    Treeview の列見出しにマウスを乗せている間、列ごとの説明をポップアップ表示する。

    Attributes
    ----------
    texts
        Tooltip text per column identifier; a column without an entry shows
        nothing.
        列識別子ごとの説明文。登録の無い列では何も表示しない。

    Notes
    -----
    Treeview headings are not widgets, so `ToolTip`'s ``<Enter>`` binding
    cannot tell one heading from another. This class follows ``<Motion>``
    instead and asks the tree which heading is under the pointer; placement
    and screen-edge handling are inherited from `ToolTip`. Bindings are added
    with ``add="+"`` so the tree's existing handlers keep running.
    Treeview の見出しはウィジェットではないため、`ToolTip` の ``<Enter>`` では
    見出しを区別できない。本クラスは ``<Motion>`` を追い、ポインタ下の見出しを
    Treeview に問い合わせる。配置と画面端の処理は `ToolTip` から継承する。既存の
    ハンドラを残すため、バインドは ``add="+"`` で追加する。

    Examples
    --------
        HeadingToolTip(tree, {"length (nm)": "輪郭長"})
    """

    def __init__(self, tree: ttk.Treeview, texts: dict) -> None:
        """
        Attach heading tooltips to a Treeview.
        Treeview に見出し用ツールチップを付与する。

        Parameters
        ----------
        tree
            Treeview whose headings receive tooltips.
            見出しにツールチップを付ける Treeview。
        texts
            Mapping from column identifier to tooltip text.
            列識別子から説明文への対応。
        """
        # ToolTip.__init__ is not called: its <Enter>/<Leave> bindings would
        # show one text for the whole tree.
        self.widget = tree
        self.text = ""
        self.tooltip = None
        self.texts = dict(texts)
        self._column = None
        tree.bind("<Motion>", self._on_motion, add="+")
        tree.bind("<Leave>", self._on_leave, add="+")

    def _heading_column(self, event):
        """
        Return the column identifier of the heading under the pointer.
        ポインタ下にある見出しの列識別子を返す。

        Parameters
        ----------
        event
            Tk pointer event on the tree.
            Treeview 上の Tk ポインタイベント。

        Returns
        -------
        str or None
            Identifier of the displayed column whose heading is under the
            pointer, or ``None`` when the pointer is not on a heading.
            ポインタ下に見出しがある表示列の識別子。ポインタが見出し上に無ければ
            ``None``。
        """
        tree = self.widget
        if tree.identify_region(event.x, event.y) != "heading":
            return None
        # identify_column returns "#N" counted over the displayed columns,
        # 1-based, with "#0" being the tree column.
        position = tree.identify_column(event.x)
        try:
            index = int(position.lstrip("#")) - 1
        except ValueError:
            return None
        displayed = tuple(tree.cget("displaycolumns"))
        if not displayed or displayed[0] == "#all":
            displayed = tuple(tree.cget("columns"))
        if 0 <= index < len(displayed):
            return displayed[index]
        return None

    def _on_motion(self, event) -> None:
        """
        Show, switch, or hide the tooltip as the pointer moves.
        ポインタの移動に応じてツールチップを表示・切替・非表示にする。

        Parameters
        ----------
        event
            Tk ``<Motion>`` event on the tree.
            Treeview 上の Tk ``<Motion>`` イベント。
        """
        column = self._heading_column(event)
        # Staying on one heading keeps the popup where it is; re-creating it on
        # every motion event would make it chase the pointer and flicker.
        if column == self._column:
            return
        self.hide_tooltip(event)
        self._column = column
        text = self.texts.get(column) if column is not None else None
        if text:
            self.text = text
            self.show_tooltip(event)

    def _on_leave(self, event) -> None:
        """
        Hide the tooltip when the pointer leaves the tree.
        ポインタが Treeview から出たらツールチップを隠す。

        Parameters
        ----------
        event
            Tk ``<Leave>`` event on the tree.
            Treeview 上の Tk ``<Leave>`` イベント。
        """
        self._column = None
        self.hide_tooltip(event)


def center_window(win: tk.Tk | tk.Toplevel, w: int, h: int,
                  taskbar_offset: int = 40) -> None:
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


def apply_window_size(win: tk.Tk | tk.Toplevel, default_w: int,
                      default_h: int, min_w: int | None = None,
                      min_h: int | None = None, margin: int = 100,
                      center: bool = True) -> None:
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
#   「軸ラベル・目盛りのフォントサイズ」「保存 DPI / 対応形式」「µm の Unicode
#   表記」をプロジェクト全体で 1 箇所にまとめる。各 GUI は「初期値を決める箇所で
#   これらを参照する」という運用にとどめ、関数の共通化は意図的に行わない。
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
# The sizes are chosen to work both in publication figures and in on-screen
# review.
# 論文掲載とスクリーン確認のどちらでも破綻しない値にしている。
PLOT_FS_DEFAULTS = {
    "label_fs":  14,   # axis labels / 軸ラベル（"Length (nm)" 等）
    "tick_fs":   13,   # tick values / 軸目盛りの数値
    "title_fs":  16,   # plot title / グラフタイトル
    "cbar_fs":   13,   # colorbar label and ticks / カラーバーのラベル・目盛り
    "annot_fs":  13,   # annotations in the plot / グラフ内の注釈テキスト
    "legend_fs": 12,   # legend text / 凡例（legend）のテキスト
}

# --- Save defaults ------------------------------------------------------------
# Figure-save DPI lives in ``FIGURE_SAVE_DPI`` above; supported extensions
# live in ``figure_save_filetypes()``.
# 図保存の DPI は ``FIGURE_SAVE_DPI``（モジュール冒頭）を、
# 拡張子は ``figure_save_filetypes()`` を参照する。

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
    minimum, so the result degrades to that minimum instead of failing.
    この推定は構造物が上向きに突出することを前提とする。基板より低い穴・
    ピットが支配的な画像では下半分がノイズだけではなくなり σ を過大評価
    するが、呼び出し側が下端をデータ最小値で頭打ちにするため、破綻せず
    データ最小値を下端とする結果に劣化するだけで済む。
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
    image_array: ArrayLike,
    mask: ArrayLike | None = None,
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

    Rule / 計算規則::

        vmin = floor(min(background_level - k_low * background_sigma,
                         percentile(image, low_clip_pct)))
        vmax = ceil (percentile of the fiber pixels)

    Both bounds are statistics of a chosen population, never a single
    extreme pixel. With ``nanmin``/``nanmax``, one contamination spike would
    set ``vmax`` far above the fibers and leave the whole heatmap dark, and a
    few negative noise pixels would drag ``vmin`` far below the substrate and
    wash the image out.
    両端とも選んだ母集団の統計量で決め、単一の極値では決めない。
    ``nanmin``/``nanmax`` を使うと、コンタミ 1 点で ``vmax`` がファイバーより
    遥かに上へ張り付いて画像全体が暗くなり、負のノイズ数画素で ``vmin`` が
    基板より大きく下がって画像が白っぽく飛ぶ。

    The upper population is chosen in this order:

    1. ``mask`` pixels (the bundle's skeleton), if the mask is usable.
    2. otherwise pixels above ``level + 3 * sigma`` — the fiber body.
    3. otherwise ``level + 5 * sigma``, for an image with no features.

    上側の母集団は 1. マスク（バンドルのスケルトン）画素、2. 使えなければ
    ``level + 3σ`` を超える画素（ファイバー本体）、3. それも無ければ
    ``level + 5σ``（構造の無い画像）の順に選ぶ。

    Restricting the percentile to fiber pixels is what makes it safe here.
    A percentile over *all* pixels depends on fiber coverage: fibers cover so
    little of a typical image that even the 99th percentile of the whole image
    can land in the background, and the fibers then saturate.
    パーセンタイルをファイバー画素に限定する点が要である。全画素の
    パーセンタイルはファイバー被覆率に依存する。典型的な画像ではファイバーの
    占める割合が小さく、全画素の 99 パーセンタイルですら背景に落ちることがあり、
    そうなるとファイバーが飽和する。

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
        ``imshow(vmin=, vmax=)`` にそのまま使える整数値の上下限。

    Notes
    -----
    The bounds are clamped to the data range, so the result never widens the
    display beyond what the image contains. Because the upper bound is a
    percentile, a small fraction of pixels is expected to saturate.
    両端はデータ範囲で頭打ちにするため、画像に含まれる以上に表示範囲が広がる
    ことはない。上端はパーセンタイルなので、わずかな画素は飽和する前提である。

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

    Parameters
    ----------
    font_size
        Base font size (``rcParams["font.size"]``), in Matplotlib fontsize
        units.
        基準フォントサイズ（``rcParams["font.size"]``、matplotlib の fontsize 単位）。
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


def build_pan_zoom_toolbar(parent: tk.Misc, canvas: "FigureCanvasTkAgg", *,
                           clam_bg: str | None = None,
                           keep: Iterable[str] = ("Pan", "Zoom")) -> tuple:
    """
    Build a matplotlib navigation toolbar stripped to its Pan/Zoom buttons.
    matplotlib のナビゲーションツールバーを Pan/Zoom だけに絞って構築する。

    Parameters
    ----------
    parent
        Widget the toolbar frame is created in.
        ツールバー用フレームを作る親ウィジェット。
    canvas
        Matplotlib Tk canvas the toolbar drives.
        ツールバーが操作する matplotlib の Tk キャンバス。
    clam_bg
        Background color of the active ttk theme, or ``None`` to leave the
        toolbar's classic-tk colors untouched.
        使用中の ttk テーマの背景色。``None`` なら素の tk 配色のままにする。
    keep
        Button labels that stay visible; every other button is unmapped.
        表示したままにするボタンのラベル。他のボタンは非表示にする。

    Returns
    -------
    tuple
        ``(frame, toolbar)``. The caller places ``frame`` itself, because the
        surrounding row's packing order decides the layout (see Notes).
        ``(frame, toolbar)``。フレームの配置は呼び出し側が行う。同じ行の
        パック順序がレイアウトを左右するため（Notes 参照）。

    Notes
    -----
    Three workarounds are folded in here so every caller inherits them:

    1. ``NavigationToolbar2Tk`` is a figure-width frame with
       ``pack_propagate(False)``, which spreads Pan/Zoom and the right-aligned
       coordinate readout across the whole figure width. Propagation is
       re-enabled so the toolbar shrinks to just its buttons and leaves the
       rest of the row for the caller's own buttons.
    2. The toolbar uses classic tk widgets, which ignore the ttk theme, so the
       background is matched manually when ``clam_bg`` is given.
    3. Unwanted buttons are unmapped, never destroyed: matplotlib keeps
       Back/Forward in ``NavigationToolbar2Tk._buttons`` and configures their
       state from ``set_history_buttons()`` during Pan/Zoom, which raises
       ``TclError`` once the widgets are gone.

    3 点目は特に重要である。不要ボタンを破棄すると、matplotlib が Pan/Zoom
    操作中に呼ぶ ``set_history_buttons()`` が TclError になるため、レイアウト
    から外すだけにとどめる。

    Pack the caller's own buttons (``side="right"``) *before* placing the
    returned frame, so the toolbar's growable coordinate readout cannot squeeze
    them when the pointer moves over the canvas.
    独自ボタンは ``side="right"`` で先にパックし、その後にこのフレームを置く
    こと。ツールバーの座標表示はホバー時に横へ伸びるため、後から確保すると
    押し潰される。
    """
    # Local import: only GUIs that embed a navigation toolbar need the Tk
    # backend module, and ui_tools is imported by every GUI.
    # ローカル import：ツールバーを組み込む GUI だけが Tk バックエンドを必要と
    # するが、ui_tools は全 GUI から読み込まれるため。
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

    frame = ttk.Frame(parent)
    toolbar = NavigationToolbar2Tk(canvas, frame)
    toolbar.update()
    toolbar.pack_propagate(True)

    if clam_bg is not None:
        try:
            toolbar.configure(bg=clam_bg)
        except tk.TclError:
            pass
        for child in toolbar.winfo_children():
            try:
                child.configure(bg=clam_bg)
            except tk.TclError:
                # Skip widgets that do not expose a classic tk bg option.
                pass

    keep_texts = set(keep)
    for child in list(toolbar.winfo_children()):
        # Both tk.Button and ttk.Button expose a text option.
        try:
            txt = child.cget("text")
        except tk.TclError:
            continue
        if isinstance(child, (tk.Button, ttk.Button)) and txt not in keep_texts:
            child.pack_forget()

    return frame, toolbar


def figure_save_filetypes() -> list[tuple[str, str]]:
    """
    Filetypes list for figure save dialogs.
    figure 保存ダイアログ用の filetypes リスト。

    Order matters: PNG first (most common), PDF/SVG for paper submission,
    TIFF for journals that require it.
    順序は意図的：PNG（最頻用）を先頭、PDF/SVG を論文投稿用に、
    TIFF を要求するジャーナル向けにも対応。

    Returns
    -------
    list of tuple
        ``(label, pattern)`` pairs in that order, ending with all files.
        上記の順に並べた ``(ラベル, パターン)`` の組。最後は全ファイル。

    Notes
    -----
    The labels "PNG", "PDF" and so on are technical terms, so they are not
    translated with ``_()``.
    ラベル "PNG" "PDF" 等は技術用語のため _() 翻訳は不要。
    """
    return [
        ("PNG", "*.png"),
        ("PDF", "*.pdf"),
        ("SVG", "*.svg"),
        ("TIFF", "*.tiff"),
        ("All files", "*.*"),
    ]
def save_figure_with_dialog(
    parent: tk.Misc,
    fig: plt.Figure,
    *,
    initial_name: str,
    initial_dir: str | None = None,
    title: str | None = None,
    dpi: int | None = None,
    log_cb: Callable[[str], None] | None = None,
    notify_on_success: bool = False,
) -> str | None:
    """
    Save a matplotlib Figure through a 'Save as' dialog.
    「名前を付けて保存」ダイアログから matplotlib の Figure を保存する。

    The project's standard file types, DPI and error handling are applied.
    プロジェクト共通の filetypes・DPI・エラー処理を適用する。

    Parameters
    ----------
    parent
        Parent for dialogs (required for modal correctness).
        ダイアログの親（モーダル動作を正しくするために必要）。
    fig
        Figure to save.
        保存する Figure。
    initial_name
        Default file name shown in the dialog.
        ダイアログに表示する既定のファイル名。
    initial_dir
        Initial directory; defaults to os.getcwd() when None.
        初期フォルダ。None なら os.getcwd()。
    title
        Dialog title; defaults to the translated "save figure" title when
        None.
        ダイアログのタイトル。None なら翻訳済みの「図を保存」。
    dpi
        Save DPI; defaults to FIGURE_SAVE_DPI when None.
        保存時の DPI。None なら FIGURE_SAVE_DPI。
    log_cb
        Optional log callback receiving a translated success message.
        翻訳済みの成功メッセージを受け取る任意のログコールバック。
    notify_on_success
        If True, also show a messagebox.showinfo on success.
        True のとき、成功時に messagebox.showinfo も表示する。

    Returns
    -------
    str or None
        Saved file path, or None if cancelled or failed.
        保存先のパス。キャンセルまたは失敗時は None。
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
