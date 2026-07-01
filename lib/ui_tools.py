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
    def _apply_auto_vrange(self, image_array, *, log: bool = False) -> tuple | None:
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
        log : bool
            True かつ ``self._log`` が利用可能なら、確定値をログに出力する。

        Returns
        -------
        (v_lo, v_hi) : tuple of int | None
            計算した範囲。``ent_vmin`` / ``ent_vmax`` を持たない等で書き戻せない
            場合でも値自体は返す。
        """
        v_lo, v_hi = compute_auto_vrange(image_array)
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
        # Read absolute pointer position on the screen.
        # event.x_root / event.y_root: absolute mouse coordinates on screen.
        x = event.x_root
        y = event.y_root
        # Create a small top-level popup window.
        # tk.Toplevel creates a small child window for the tooltip.
        self.tooltip = tk.Toplevel(self.widget)
        # Remove window decorations for tooltip-like appearance.
        # 枠なし（タイトルバーを消してポップアップ風にする）
        self.tooltip.wm_overrideredirect(True)  # 枠なし（タイトルバーを消してポップアップ風にする）
        # Offset the popup below-right of the cursor. Placing it directly under
        # the pointer makes the popup itself trigger a <Leave> on the target,
        # producing a hide/show flicker loop.
        # ポップアップはカーソルの右下にずらして表示する。ポインタ直下に出すと
        # ポップアップ自身が対象の <Leave> を誘発し、表示/非表示のちらつきが
        # 起きるため。
        self.tooltip.wm_geometry(f"+{x+12}+{y+18}")
        # Render tooltip text with simple bordered white label.
        # ポップアップの中身: 白背景・枠付きのラベル
        label = tk.Label(self.tooltip, text=self.text, background="white", relief="solid", borderwidth=1)
        label.pack()

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


def compute_auto_vrange(image_array) -> tuple:
    """
    Compute auto vmin/vmax from a 2D image array.
    画像配列から自動 vmin/vmax を返す。

    Rule / 計算規則
        vmin = floor(nanmin(arr))
        vmax = ceil (nanmax(arr) + 1)

    The lower bound is the minimum *raised* by 1 nm: AFM images often have
    a few pixels of negative noise / scratch artefacts that pull ``nanmin``
    well below the substrate level. Subtracting margin (the previous policy)
    stretched the colormap downward and made the whole image look washed
    out. Adding 1 nm instead trims the very bottom of the noise floor and
    keeps the bright end of ``afmhot`` aligned with actual fiber heights.
    下側は最小値をfloor で丸める

    The upper bound uses the raw nanmax: percentile-based clipping was
    attempted to suppress contamination spikes but was withdrawn because
    on samples with low fiber coverage the fibers themselves were treated
    as outliers and crushed into the dark end.
    上側は素の最大値を使う。コンタミ抑制目的でパーセンタイル切りを
    試みたが、ファイバー被覆率の低いサンプルではファイバー自身が
    外れ値扱いされて暗側に潰れたため撤回した。

    NaN-tolerant. Empty arrays or unexpected types fall back to the
    project-wide defaults ``DEFAULT_VMIN`` / ``DEFAULT_VMAX``.
    NaN を含む可能性に備えて nanmin/nanmax を使う。空配列・想定外の型では
    プロジェクト共通の既定値 ``DEFAULT_VMIN`` / ``DEFAULT_VMAX`` を返す。

    Returns
    -------
    (vmin, vmax) : tuple of int
        Integer-valued bounds suitable for direct use as ``imshow(vmin=, vmax=)``.
    """
    arr = np.asarray(image_array)
    # Empty arrays use the project-wide fallback range.
    # 空配列の場合は既定値で返す。
    if arr.size == 0:
        return int(math.floor(DEFAULT_VMIN)), int(math.ceil(DEFAULT_VMAX))
    try:
        mn = float(np.nanmin(arr))
        mx = float(np.nanmax(arr))
    except (ValueError, TypeError):
        return int(math.floor(DEFAULT_VMIN)), int(math.ceil(DEFAULT_VMAX))
    # All-NaN arrays make nanmin/nanmax return NaN (with RuntimeWarning).
    # All-NaN 配列のとき nanmin/nanmax は NaN を返す（RuntimeWarning 付き）。
    # NaN を放置すると int(math.floor(NaN)) で ValueError になるためここで弾く。
    if not (math.isfinite(mn) and math.isfinite(mx)):
        return int(math.floor(DEFAULT_VMIN)), int(math.ceil(DEFAULT_VMAX))
    return int(math.floor(mn + 1.0)), int(math.ceil(mx + 1.0))


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
