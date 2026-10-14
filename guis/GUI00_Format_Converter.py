"""
GUI plugin for converting vendor AFM files into Gwyddion ``.gwy`` files.
各社 AFM ファイルを Gwyddion の ``.gwy`` ファイルへ変換する GUI プラグイン。

The user selects a folder; every file directly inside it whose extension this
software does not already read (anything except ``.txt``, ``.csv``, ``.gwy``)
or write (``.b2z``, ``.json``, ``.npy``) is converted through Gwyddion's file
modules into ``<input file name>_converted.gwy`` in the same folder, which
GUI01 then analyzes. Inputs whose ``.gwy`` already exists are skipped. The
conversion is `lib.gwy_convert.convert_file`, the same code as
``cli.py convert``.
ユーザーがフォルダを選ぶと、その直下のファイルのうち、本ソフトが既に読める
拡張子（``.txt``・``.csv``・``.gwy``）でも書き出す拡張子（``.b2z``・
``.json``・``.npy``）でもないものを、Gwyddion のファイルモジュールで同じ
フォルダの ``<入力ファイル名>_converted.gwy`` へ変換する。変換結果は GUI01 で
解析できる。
``.gwy`` が既にある入力は飛ばす。変換処理は ``cli.py convert`` と同じ
`lib.gwy_convert.convert_file` である。

The converter comes from the optional ``convert`` dependency, which the
``run_venv`` / ``run_conda`` launchers install; without it the window opens
and reports how to install it (`lib.gwy_convert.INSTALL_COMMAND`). Nothing but
the ``.gwy`` files is written automatically; the log is saved through a file
dialog.
変換プログラムは任意依存の ``convert`` に含まれ、``run_venv`` / ``run_conda``
の起動スクリプトが入れる。無い場合もウィンドウは開き、インストール方法
（`lib.gwy_convert.INSTALL_COMMAND`）を表示する。自動で書き出すのは ``.gwy``
ファイルだけで、ログはファイルダイアログから保存する。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain string literals because literal_eval cannot parse gettext calls.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Format Converter",
    "description": (
        "Image Preprocessor で読めない形式の AFM 測定ファイルを、Gwyddion のファイル"
        "読み込み機能で .gwy ファイルへ一括変換します。\n"
        "選んだフォルダ直下の .txt / .csv / .gwy / .b2z / .json / .npy 以外のファイルを、"
        "同じフォルダの <元のファイル名>_converted.gwy に変換します（例: scan.ssp は "
        "scan.ssp_converted.gwy）。同じ名前の .gwy が既にあるファイルは変換しません。\n"
        "変換プログラム（gwyddionpy-converter）は run_venv / run_conda の起動スクリプトが"
        "インストールします。"
    )
}

# ===== Standard library =====
import os
import queue
import threading
from datetime import datetime
from typing import Any, List, Tuple

# ===== GUI libraries =====
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ===== Project libraries =====
from lib import gwy_convert
from lib.translator import _
from lib.ui_tools import (
    LogMixin, apply_window_size, create_scrolled_text, create_scrolled_treeview,
    drain_ui_queue, save_text_widget_log, setup_ttk_theme,
)

# ===== Internal state keys =====
# Row state before its file has been processed; the other states are the
# `lib.gwy_convert` STATUS_* keys.
# ファイルを処理する前の行の状態。それ以外の状態は `lib.gwy_convert` の
# STATUS_* キーを使う。
STATUS_PENDING = "pending"

# Treeview tags that color a finished row by its outcome.
# 処理済みの行を結果ごとに色分けする Treeview タグ。
_ROW_COLORS = {
    gwy_convert.STATUS_CONVERTED: "#1a7f37",
    gwy_convert.STATUS_EXISTS: "#6e7781",
    gwy_convert.STATUS_FAILED: "#cf222e",
}


class App(tk.Tk, LogMixin):
    """
    Folder-level batch converter from vendor AFM files to ``.gwy``.
    各社 AFM ファイルを ``.gwy`` へ変換するフォルダ単位の一括変換ウィンドウ。

    Attributes
    ----------
    folder_var
        Selected input folder, shown in the folder entry.
        選択中の入力フォルダ。フォルダ欄に表示する。
    paths
        Conversion candidates of the selected folder, in table-row order.
        選択フォルダの変換対象。表の行と同じ順。
    ui_queue
        Messages from the conversion thread to the Tk main loop.
        変換スレッドから Tk メインループへのメッセージ。
    """

    def __init__(self) -> None:
        """
        Build the converter window.
        変換ウィンドウを作成する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])
        # No Matplotlib figure is drawn here, so its defaults are not applied.
        setup_ttk_theme(self)
        apply_window_size(self, 960, 620, min_w=720, min_h=460)

        self.folder_var = tk.StringVar(value="")
        self.paths: List[str] = []
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._running = False

        self._build_widgets()
        self._log(_("フォルダを選択してください。"))

    # ----- Widgets -----

    def _build_widgets(self) -> None:
        """
        Create the folder row, the file table, and the log area.
        フォルダ欄、ファイル表、ログ欄を作成する。
        """
        frm_top = ttk.Frame(self)
        frm_top.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(frm_top, text=_("入力フォルダ")).pack(side=tk.LEFT)
        ttk.Entry(frm_top, textvariable=self.folder_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.btn_folder = ttk.Button(frm_top, text=_("フォルダを選択"),
                                     command=self.on_choose_folder)
        self.btn_folder.pack(side=tk.LEFT)
        self.btn_convert = ttk.Button(frm_top, text=_("変換開始"),
                                      command=self.on_convert, state="disabled")
        self.btn_convert.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(
            self,
            text=_(
                "変換対象: {skipped} 以外の拡張子のファイル。"
                "出力: 同じフォルダの <元のファイル名>{suffix}.gwy（既にあれば変換しない）。"
            ).format(skipped=" / ".join(gwy_convert.SKIPPED_EXTENSIONS),
                     suffix=gwy_convert.CONVERTED_SUFFIX),
            wraplength=900, justify=tk.LEFT,
        ).pack(fill=tk.X, padx=8, pady=(0, 4))

        frm_table = ttk.Frame(self)
        frm_table.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.tree, _tree_sb = create_scrolled_treeview(
            frm_table,
            columns=("file", "status", "module", "detail"),
            headings={
                "file": _("ファイル"),
                "status": _("状態"),
                "module": _("読み込んだ Gwyddion モジュール"),
                "detail": _("詳細"),
            },
            column_options={
                # The widths sum below the default window's table width; a
                # wider table pushes the vertical scrollbar out of the window.
                "file": {"width": 210, "anchor": tk.W},
                "status": {"width": 210, "anchor": tk.W},
                "module": {"width": 170, "anchor": tk.W},
                "detail": {"width": 270, "anchor": tk.W},
            },
            selectmode="browse",
        )
        for status, color in _ROW_COLORS.items():
            self.tree.tag_configure(status, foreground=color)

        frm_log = ttk.LabelFrame(self, text=_("ログ"))
        frm_log.pack(fill=tk.BOTH, padx=8, pady=(4, 8))
        frm_log_buttons = ttk.Frame(frm_log)
        frm_log_buttons.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(frm_log_buttons, text=_("ログを保存"),
                   command=self.on_save_log).pack(side=tk.LEFT)
        log_body = ttk.Frame(frm_log)
        log_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.log_text, _log_sb = create_scrolled_text(
            log_body, height=8, wrap=tk.WORD, state="disabled",
        )

    def _status_text(self, status: str) -> str:
        """
        Return the display text of a row state.
        行の状態の表示文字列を返す。
        """
        return {
            STATUS_PENDING: _("未変換"),
            gwy_convert.STATUS_CONVERTED: _("変換しました"),
            gwy_convert.STATUS_EXISTS: _("変換済み（.gwy あり）"),
            gwy_convert.STATUS_FAILED: _("変換できませんでした"),
        }[status]

    def _set_controls(self, running: bool) -> None:
        """
        Enable or disable the buttons for a running conversion.
        変換中かどうかに合わせてボタンの有効・無効を切り替える。
        """
        self._running = running
        self.btn_folder.configure(state="disabled" if running else "normal")
        self.btn_convert.configure(
            state="disabled" if running or not self.paths else "normal")

    # ----- Actions -----

    def on_choose_folder(self) -> None:
        """
        Ask for a folder and list its conversion candidates.
        フォルダを選ばせ、その変換対象を一覧にする。
        """
        folder = filedialog.askdirectory(
            title=_("変換するファイルを含むフォルダを選択"))
        if not folder:
            return
        try:
            paths = gwy_convert.list_conversion_candidates(folder)
        except OSError as e:
            self._log(_("フォルダを読み込めませんでした: {error}").format(error=e))
            return

        self.folder_var.set(folder)
        self.paths = paths
        self.tree.delete(*self.tree.get_children())
        n_exists = 0
        for i, path in enumerate(paths):
            # Already-converted inputs are marked now, so the table shows what
            # the run will do before it starts.
            if os.path.exists(gwy_convert.converted_path_for(path)):
                status = gwy_convert.STATUS_EXISTS
                n_exists += 1
            else:
                status = STATUS_PENDING
            self.tree.insert("", tk.END, iid=str(i), tags=(status,), values=(
                os.path.basename(path), self._status_text(status), "", ""))
        self._log(_("フォルダ選択: {folder}").format(folder=folder))
        self._log(_("変換対象 {n} 件（うち .gwy が既にあるもの {n_exists} 件）").format(
            n=len(paths), n_exists=n_exists))
        self._set_controls(False)

    def on_convert(self) -> None:
        """
        Start converting the listed files in a worker thread.
        一覧のファイルの変換をワーカースレッドで開始する。
        """
        if self._running or not self.paths:
            return
        try:
            converter = gwy_convert.find_converter()
        except gwy_convert.ConverterNotFoundError as e:
            self._log(str(e))
            messagebox.showerror(
                _("変換プログラムが見つかりません"),
                _(
                    "Gwyddion の変換プログラム gwyconvert が見つかりません。\n"
                    "次のコマンドでインストールしてから、もう一度実行してください。\n"
                    "{command}"
                ).format(command=gwy_convert.INSTALL_COMMAND),
                parent=self,
            )
            return

        self._set_controls(True)
        self._log(_("変換を開始します（{n} 件）。").format(n=len(self.paths)))
        threading.Thread(target=self._worker, args=(list(self.paths), converter),
                         daemon=True).start()
        self.after(50, self._poll_ui_queue)

    def _worker(self, paths: List[str], converter: str) -> None:
        """
        Convert each file and report every result through the UI queue.
        各ファイルを変換し、結果を 1 件ずつ UI キューで通知する。

        Runs in a worker thread; it never touches Tk widgets.
        ワーカースレッドで動き、Tk のウィジェットには触れない。
        """
        counts = {gwy_convert.STATUS_CONVERTED: 0, gwy_convert.STATUS_EXISTS: 0,
                  gwy_convert.STATUS_FAILED: 0}
        for i, path in enumerate(paths):
            try:
                result = gwy_convert.convert_file(path, converter=converter)
            except Exception as e:  # noqa: BLE001 - one file never aborts the batch
                result = gwy_convert.ConversionResult(
                    path, gwy_convert.converted_path_for(path),
                    gwy_convert.STATUS_FAILED, message=f"{type(e).__name__}: {e}")
            counts[result.status] += 1
            self.ui_queue.put(("row", (i, result)))
        self.ui_queue.put(("done", counts))

    def _poll_ui_queue(self) -> None:
        """
        Apply queued results to the table and keep polling while converting.
        キューの結果を表へ反映し、変換中はポーリングを続ける。
        """
        def on_row(payload) -> None:
            i, result = payload
            self.tree.item(str(i), tags=(result.status,), values=(
                os.path.basename(result.source), self._status_text(result.status),
                result.module or "", result.message))
            self.tree.see(str(i))
            if result.status == gwy_convert.STATUS_FAILED:
                self._log(_("{name}: 変換できませんでした ({reason})").format(
                    name=os.path.basename(result.source), reason=result.message))

        def on_done(counts) -> bool:
            self._set_controls(False)
            self._log(_(
                "完了: 変換 {converted} 件、変換済みのため省略 {exists} 件、"
                "変換できず {failed} 件"
            ).format(converted=counts[gwy_convert.STATUS_CONVERTED],
                     exists=counts[gwy_convert.STATUS_EXISTS],
                     failed=counts[gwy_convert.STATUS_FAILED]))
            if counts[gwy_convert.STATUS_CONVERTED]:
                self._log(_(
                    "Image Preprocessor でこのフォルダを選ぶと、変換した .gwy "
                    "ファイルを解析できます。"))
            return False

        if drain_ui_queue(self.ui_queue, {"row": on_row, "done": on_done}):
            self.after(50, self._poll_ui_queue)

    def on_save_log(self) -> None:
        """
        Save the log text through a file dialog.
        ログ本文をファイルダイアログ経由で保存する。
        """
        save_text_widget_log(
            self, self.log_text,
            initial_dir=self.folder_var.get() or None,
            initialfile="convert_log_{ts}.txt".format(
                ts=datetime.now().strftime("%Y%m%d_%H%M%S")),
            empty_warning=True,
            log_cb=self._log,
        )


def main() -> None:
    """
    Start the format-converter GUI.
    Format Converter GUI を起動する。
    """
    app = App()
    app.mainloop()


# Run the GUI only when this module is executed directly.
if __name__ == "__main__":
    main()
