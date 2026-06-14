"""
Launcher entry point for AFM Nanofiber analysis GUI plugins.
AFM ナノファイバー解析 GUI プラグインのランチャーエントリポイント。

Multi-entry design:
  `Main.exe` (and `python Main.py`) behaves differently based on argv:
  `Main.exe`（および `python Main.py`）は argv によって挙動を切り替える。

    - no subcommand           -> launch the main launcher GUI
                                 ランチャー GUI を起動する（通常モード）
    - `--run-plugin <path>`   -> import the plugin module and call its main()
                                 指定プラグインを import して main() を呼ぶ
                                 （ランチャーから分離起動されたプラグイン）

  This multi-entry design is required because PyInstaller's bootloader
  does NOT honor `-c` or `-m` flags when invoking the frozen executable,
  so the naive "re-run sys.executable with -c/-m" approach would instead
  re-launch the launcher itself and fork-bomb the user's desktop.
  PyInstaller の bootloader は凍結済み実行ファイルに対して `-c` / `-m` を
  解釈しないため、単純に `sys.executable` を `-c` / `-m` 付きで呼ぶと
  自分自身のランチャーを再起動してしまいフォークボム化する。
  サブコマンド方式にすることでこの問題を回避している。

Plugin startup:
  `--run-plugin` shows a splash window while a worker thread imports the
  plugin module. Heavy libraries are pulled in transitively by that single
  import, so each plugin pays only for the libraries it actually uses.
  `--run-plugin` はスプラッシュウィンドウを表示しつつ、ワーカースレッドで
  プラグインモジュールを import する。重いライブラリはこの 1 回の import で
  推移的に読み込まれるため、各プラグインは実際に使うライブラリの分だけ
  起動コストを払う。
"""

import sys
import ast
import subprocess
import importlib
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk  # type: ignore

# =========================
# Paths
# =========================
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
# Register the external bundle root before importing local packages; otherwise
# PyInstaller's internal package copy can shadow modules copied under dist/Main.
# ローカルパッケージの import 前に外部バンドルルートを登録する。そうしないと
# PyInstaller 内部のパッケージコピーが dist/Main 配下へコピーしたモジュールを隠すことがある。
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from lib.ui_tools import apply_window_size
from lib.translator import _, current_language, set_language, SUPPORTED

# =========================
# Configuration constants
# =========================
APP_TITLE = "AFM NanoFiber Analyzer Launcher"
LEFT_WIDTH = 700
IMAGE_HEIGHT = 400
MSG_HEIGHT = 200
RIGHT_WIDTH = 260
IMAGE_CANVAS_CX = LEFT_WIDTH // 2
IMAGE_CANVAS_CY = IMAGE_HEIGHT // 2

GUIS_DIR_NAME = "guis"
ASSETS_DIR_NAME = "assets"
AFM_SYMBOL_FILENAME = "afm_symbol.png"

MSG_HOVER_IDLE = (
    "Hover over a button on the right to display its description."
)

def _run_plugin_and_exit(module_import_path: str):
    """
    Run a plugin after showing a splash progress window.
    スプラッシュ進捗ウィンドウを表示してからプラグインを実行する。

    Heavy imports run in a worker thread so the tkinter splash can keep
    updating while startup work proceeds.
    重い import はワーカースレッドで実行し、起動処理中も tkinter の
    スプラッシュ表示を更新できるようにする。
    """
    import tkinter as tk
    from tkinter import ttk

    # ---- 1) Build splash window ----
    splash = tk.Tk()
    splash.title("Loading...")
    splash.overrideredirect(True)
    splash.configure(bg="white")

    w, h = 400, 140
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    splash.geometry(f"{w}x{h}+{x}+{y}")
    splash.attributes("-topmost", True)

    frame = ttk.Frame(splash, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text=f"{module_import_path}",
        anchor="center",
    ).pack(pady=(4, 4))

    status_var = tk.StringVar(value="Loading...")
    ttk.Label(frame, textvariable=status_var, anchor="center").pack(pady=(0, 6))

    # Indeterminate mode: the plugin module is imported in a single step, so
    # there is no meaningful step count to display.
    # プラグインモジュールの import は単一ステップで進むため、表示すべき
    # 段階数が存在しない。よって不確定モードで動かす。
    pbar = ttk.Progressbar(frame, mode="indeterminate", length=360)
    pbar.pack(pady=4)
    pbar.start(12)

    # ---- 2) Share worker-thread state ----
    # The main (Tkinter) thread and the worker thread communicate via these.
    state = {
        "done": False,            # Completion flag.
        "module": None,           # Loaded plugin module.
        "error": None,            # Exception, if any.
    }

    def worker():
        """
        Import the plugin module in a worker thread.
        ワーカースレッドでプラグインモジュールを import する。

        Heavy third-party libraries are pulled in transitively by this single
        import, so each plugin pays only for the libraries it actually uses.
        重いサードパーティライブラリはこの 1 回の import で推移的に読み込ま
        れるため、各プラグインは実際に使うライブラリの分だけコストを払う。
        """
        try:
            # Fix the backend before the plugin imports matplotlib.pyplot.
            # プラグインが matplotlib.pyplot を import する前に backend を固定する。
            try:
                import matplotlib
                matplotlib.use("TkAgg")
            except Exception:
                pass

            state["module"] = importlib.import_module(module_import_path)
        except Exception as e:
            state["error"] = e
        finally:
            state["done"] = True

    threading.Thread(target=worker, daemon=True).start()

    # ---- 3) Poll completion from the main thread ----
    # Poll state every 50ms and exit the splash loop when the import is done.
    def poll():
        if state["done"]:
            splash.quit()  # Exit mainloop.
        else:
            splash.after(50, poll)

    splash.after(50, poll)
    splash.mainloop()

    # ---- 4) Clean up splash window ----
    # Stop the indeterminate animation before destroying the splash. Otherwise a
    # pending ttk Autoincrement "after" callback fires after the application is
    # destroyed, raising "TclError: application has been destroyed".
    # スプラッシュ破棄前に不確定モードのアニメーションを停止する。停止しないと
    # ttk の Autoincrement の after コールバックがアプリ破棄後に発火し、
    # 「TclError: application has been destroyed」が発生する。
    try:
        pbar.stop()
    except tk.TclError:
        pass
    splash.destroy()

    # ---- 5) Check load errors ----
    if state["error"] is not None:
        _show_startup_error(
            title="Plugin load failed",
            message=f"Failed to load plugin {module_import_path}:\n{state['error']}",
        )
        return

    mod = state["module"]
    if mod is None or not hasattr(mod, "main"):
        _show_startup_error(
            title="Plugin has no main()",
            message=f"{module_import_path} does not define a top-level main().",
        )
        return

    # ---- 6) Call plugin main() ----
    try:
        mod.main()
    except Exception as e:
        _show_startup_error(
            title="Plugin crashed",
            message=f"Error while running {module_import_path}:\n{e}",
        )


def _show_startup_error(title: str, message: str) -> None:
    """
    Show a tkinter error dialog for startup-time failures.
    起動時エラーを tkinter のダイアログで表示する。

    Used for cases where the caller is a child process with no console
    (e.g., PyInstaller windowed build) and stderr prints would be invisible.
    コンソールを持たない子プロセス（PyInstaller の windowed ビルド等）で
    stderr が見えないケース向け。
    """
    try:
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # Last-resort fallback to stderr.
        # 最後の手段として stderr に出す。
        print(f"[{title}] {message}", file=sys.stderr)


# =========================
# Scrollable button container
# =========================
class ScrollableFrame(ttk.Frame):
    """
    Canvas and inner frame for vertically scrollable buttons.
    縦スクロール可能なボタン群を保持する Canvas と内部 Frame。
    """

    def __init__(self, master, width: int, **kwargs):
        """
        Initialize the scrollable canvas/frame pair.
        スクロール可能な Canvas/Frame の組を初期化する。
        """
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Keep inner frame width synced with canvas width.
        # 内部フレームの横幅をキャンバス幅と同期させる。
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.window_id, width=e.width),
        )
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        """
        Scroll the canvas in response to a mouse-wheel event.
        マウスホイールイベントに応じて Canvas をスクロールする。
        """
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# =========================
# Plugin discovery
# =========================
def _extract_plugin_info_static(py_file: Path) -> tuple[dict, str]:
    """
    Parse a plugin file with `ast` and return its `PLUGIN_INFO` dict literal.
    プラグインファイルを `ast` でパースして `PLUGIN_INFO` の辞書リテラルを返す。

    This avoids importing the plugin module at launcher startup, which is
    critical because plugin files import heavy libraries (numpy, matplotlib,
    cv2, ...) at module top level. Importing every plugin just to read one
    metadata dict would load all those libraries into the launcher process
    and make the launcher window itself slow to appear.
    ランチャー起動時にプラグインモジュールを import しないためのヘルパー。
    プラグインは numpy / matplotlib / cv2 等をトップレベルで import するため、
    メタデータ 1 個を読むためだけに全プラグインを import すると、これら重い
    ライブラリがランチャープロセスに全部ロードされ、ランチャーウィンドウ自体の
    表示が遅くなる。これを回避するのが目的。

    `PLUGIN_INFO` must be a literal dict (only strings / numbers / lists /
    dicts / True / False / None). `ast.literal_eval` enforces this safely.
    `PLUGIN_INFO` は辞書リテラルであること（値は文字列・数値・リスト・dict・
    True・False・None のみ）。`ast.literal_eval` が安全に評価する。

    Returns
    -------
    tuple
        ``(info, error)``. On success ``error`` is an empty string; on any
        read / parse / literal-eval failure ``info`` is an empty dict and
        ``error`` holds a short reason, so the launcher can surface the
        failure instead of degrading silently.
        ``(info, error)`` の組。成功時は ``error`` が空文字列。読み込み /
        パース / literal_eval に失敗した場合は ``info`` が空 dict、``error``
        に短い理由が入り、ランチャーは静かに劣化せず失敗を表示できる。
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        return {}, f"could not read or parse the file: {e}"

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "PLUGIN_INFO":
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    return {}, (
                        "PLUGIN_INFO is not a literal dict (values must be "
                        "plain strings/numbers/lists/dicts; do not wrap them "
                        "with _() or compute them)"
                    )
                if not isinstance(value, dict):
                    return {}, "PLUGIN_INFO is not a dict"
                return value, ""
    return {}, "PLUGIN_INFO is not defined at module top level"


def _discover_plugins() -> list[dict]:
    """
    Scan `guis/` and return plugin metadata WITHOUT importing plugin modules.
    プラグインを import せずに `guis/` を走査してメタデータを返す。

    Each plugin is a `.py` file that defines a module-level `PLUGIN_INFO` dict.
    We read that dict statically via `ast` instead of calling
    `importlib.import_module`, because importing plugin modules would pull in
    their heavy dependencies (numpy, matplotlib, cv2, ...) and slow down
    launcher startup — which is exactly what we are trying to avoid.
    各プラグインはモジュールレベルで `PLUGIN_INFO` dict を定義した `.py`
    ファイル。`importlib.import_module` を使うとプラグインの重い依存
    （numpy, matplotlib, cv2 ...）がランチャーに全部読み込まれてしまい、
    高速化の趣旨に反するため、`ast` で静的に読み出す。

    Plugins MUST still guard their GUI launch behind
    ``if __name__ == "__main__":`` so that later import by the child process
    does not open any window at module-load time.
    プラグイン側は引き続き ``if __name__ == "__main__":`` で GUI 起動を
    ガードすること（子プロセスが import した時点でウィンドウが開かないように）。
    """
    guis_dir = BASE_DIR / GUIS_DIR_NAME
    if not guis_dir.is_dir():
        return []

    plugins = []
    for py_file in sorted(guis_dir.glob("*.py"), key=lambda p: p.name.lower()):
        if py_file.name == "__init__.py":
            continue

        module_name = py_file.stem
        import_path = f"{GUIS_DIR_NAME}.{module_name}"

        info, error = _extract_plugin_info_static(py_file)

        # gettext returns the PO header for "", so translate only when the
        # description is non-empty.
        # gettext は "" に対して PO ヘッダを返すため、説明文が非空のときだけ
        # 翻訳する。
        description = info.get("description", "")
        if isinstance(description, str) and description:
            description = _(description)

        # Optional "order" key: plugins with smaller numbers appear first;
        # plugins without it keep filename order after the ordered ones.
        # Unknown PLUGIN_INFO keys are ignored for forward compatibility.
        # 任意キー "order": 小さい数値のプラグインほど先頭に並ぶ。未指定の
        # プラグインは、指定済みの後ろにファイル名順で並ぶ。未知のキーは
        # 前方互換のため無視する。
        raw_order = info.get("order")
        if isinstance(raw_order, (int, float)) and not isinstance(raw_order, bool):
            order = float(raw_order)
        else:
            order = float("inf")

        plugins.append({
            "module": import_path,
            "name": info.get("name", module_name),
            "description": description,
            "order": order,
            # Non-empty when PLUGIN_INFO could not be read; shown on hover.
            # PLUGIN_INFO が読めなかったとき非空。ホバー時に表示する。
            "error": error,
        })

    # Stable sort: equal "order" values (including unset) keep filename order.
    # 安定ソート: "order" が同値（未指定含む）の場合はファイル名順を維持する。
    plugins.sort(key=lambda p: p["order"])
    return plugins


# =========================
# Main window
# =========================
class MainApp(tk.Tk):
    """
    Main launcher window for discovering and starting GUI plugins.
    GUI プラグインを検出して起動するメインランチャーウィンドウ。
    """

    def __init__(self):
        """
        Initialize the launcher window and populate plugin buttons.
        ランチャーウィンドウを初期化し、プラグインボタンを配置する。
        """
        super().__init__()
        self.title(APP_TITLE)
        default_w = LEFT_WIDTH + RIGHT_WIDTH + 30   # 990
        default_h = IMAGE_HEIGHT + MSG_HEIGHT + 40  # 640
        apply_window_size(self, default_w, default_h, min_w=850, min_h=520)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        self._build_left_pane(root)
        self._build_right_pane(root)

        self._load_symbol_image()
        self._populate_buttons()

    # -------- Layout construction --------
    def _build_left_pane(self, parent):
        """
        Build the image preview and message area on the left side.
        左側の画像プレビュー領域とメッセージ領域を構築する。
        """
        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_rowconfigure(0, weight=0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.image_canvas = tk.Canvas(
            left, width=LEFT_WIDTH, height=IMAGE_HEIGHT, bg="white", highlightthickness=1
        )
        self.image_canvas.grid(row=0, column=0, sticky="n")

        msg_frame = ttk.Frame(left)
        msg_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        msg_frame.grid_rowconfigure(0, weight=1)
        msg_frame.grid_columnconfigure(0, weight=1)

        self.msg_text = tk.Text(msg_frame, width=80, height=10, wrap="word")
        self.msg_text.grid(row=0, column=0, sticky="nsew")
        msg_scroll = ttk.Scrollbar(msg_frame, orient="vertical", command=self.msg_text.yview)
        msg_scroll.grid(row=0, column=1, sticky="ns")
        self.msg_text.configure(yscrollcommand=msg_scroll.set)
        self._set_message(MSG_HOVER_IDLE)

    def _build_right_pane(self, parent):
        """
        Build the plugin list, language selector, and status area.
        プラグイン一覧、言語セレクタ、ステータス領域を構築する。
        """
        right = ttk.Frame(parent, width=RIGHT_WIDTH)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=0)  # title
        right.grid_rowconfigure(1, weight=1)  # scrollable area
        right.grid_rowconfigure(2, weight=0)  # language selector
        right.grid_rowconfigure(3, weight=0)  # status
        right.grid_columnconfigure(0, weight=1)

        ttk.Label(right, text="Tools", font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6), padx=(100, 0)
        )

        self.scrollable = ScrollableFrame(right, width=RIGHT_WIDTH)
        self.scrollable.grid(row=1, column=0, sticky="nsew")

        # ---- Language selector (affects launcher plugin metadata and plugin GUIs) ----
        # Plugin subprocesses read `.lang_preference` through translator.
        # プラグイン子プロセスは translator 経由で `.lang_preference` を読み込み、
        # 言語設定を反映する。
        self._build_language_selector(right).grid(
            row=2, column=0, sticky="ew", padx=6, pady=(8, 4)
        )

        self._status_label = ttk.Label(right, text="", foreground="gray")
        self._status_label.grid(row=3, column=0, sticky="w", padx=6, pady=(4, 0))

    def _build_language_selector(self, parent):
        """
        Build the language selector used by plugin subprocesses.
        プラグイン子プロセスが参照する言語セレクタを構築する。
        """
        frame = ttk.Frame(parent)
        frame.grid_columnconfigure(1, weight=1)

        ttk.Label(frame, text="Language:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(
            frame,
            text=("Selected language applies to the plugin list and GUI tools."),
            foreground="gray",
            font=("", 8),
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # The folder names under locale/ (= SUPPORTED) are used directly
        # as dropdown items, no display-name mapping involved.
        current_code = current_language()
        initial_value = current_code if current_code in SUPPORTED else (
            SUPPORTED[0] if SUPPORTED else ""
        )

        self._lang_var = tk.StringVar(value=initial_value)
        combo = ttk.Combobox(
            frame,
            textvariable=self._lang_var,
            values=list(SUPPORTED),
            state="readonly",
            width=10,
        )
        combo.grid(row=0, column=1, sticky="ew")
        combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        return frame

    def _on_language_changed(self, _event=None):
        """
        Persist the selected language and refresh translated plugin metadata.
        選択言語を保存し、翻訳されたプラグインメタデータを再表示する。

        `PLUGIN_INFO` remains a static literal in each plugin file; Main.py
        applies gettext after AST parsing so plugin modules are not imported.
        `PLUGIN_INFO` は各プラグインファイル内で静的リテラルのまま維持し、
        Main.py が AST 解析後に gettext を適用することで import を避ける。
        """
        lang_code = self._lang_var.get()
        self._save_language_preference(lang_code)
        set_language(lang_code)
        self._populate_buttons()
        self._set_message(MSG_HOVER_IDLE)

    def _save_language_preference(self, lang_code: str):
        """
        Save the selected language code for plugin subprocesses.
        プラグイン子プロセス向けに選択された言語コードを保存する。
        """
        try:
            pref_file = BASE_DIR / ".lang_preference"
            pref_file.write_text(lang_code, encoding="utf-8")
        except Exception:
            pass  # Keep the launcher usable even if saving fails.

    # -------- UI helpers --------
    def _set_message(self, text: str):
        """
        Replace the launcher message text.
        ランチャーのメッセージテキストを置き換える。
        """
        self.msg_text.configure(state="normal")
        self.msg_text.delete("1.0", "end")
        self.msg_text.insert("1.0", text)
        self.msg_text.configure(state="disabled")

    def _set_status(self, text: str):
        """
        Update the short status label.
        短いステータスラベルを更新する。
        """
        self._status_label.configure(text=text)

    def _load_symbol_image(self):
        """
        Load and display the AFM symbol image if available.
        AFM シンボル画像があれば読み込んで表示する。
        """
        img_path = BASE_DIR / ASSETS_DIR_NAME / AFM_SYMBOL_FILENAME
        if not img_path.exists():
            self.image_canvas.create_text(
                IMAGE_CANVAS_CX, IMAGE_CANVAS_CY,
                text=f"AFM Symbol Image\n({ASSETS_DIR_NAME}/{AFM_SYMBOL_FILENAME} not found)",
                fill="gray",
            )
            return
        try:
            img = Image.open(img_path).convert("RGBA")
            img.thumbnail((LEFT_WIDTH, IMAGE_HEIGHT), Image.LANCZOS)
            self._tk_img = ImageTk.PhotoImage(img)
            self.image_canvas.create_image(IMAGE_CANVAS_CX, IMAGE_CANVAS_CY, image=self._tk_img)
        except Exception:
            self.image_canvas.create_text(
                IMAGE_CANVAS_CX, IMAGE_CANVAS_CY,
                text="Failed to load image.", fill="gray",
            )

    # -------- Plugin buttons --------
    def _populate_buttons(self):
        """
        Discover plugins and create launcher buttons for them.
        プラグインを検出し、起動用ボタンを作成する。
        """
        for child in self.scrollable.inner.winfo_children():
            child.destroy()

        plugins = _discover_plugins()
        if not plugins:
            self._set_message(f"No launchable GUI modules were found in {GUIS_DIR_NAME}/.")
            return

        for i, plugin in enumerate(plugins):
            btn = ttk.Button(
                self.scrollable.inner,
                text=plugin["name"],
                # Default-arg capture to avoid Python late-binding in lambda loops.
                # ループ内 lambda の遅延束縛を避けるため既定引数で固定する。
                command=lambda m=plugin["module"]: self._launch(m),
            )
            btn.grid(row=i, column=0, sticky="ew", pady=4, padx=6)

            desc = plugin.get("description", "") or "(no description)"
            if plugin.get("error"):
                # Surface broken plugin metadata loudly instead of showing a
                # bare "(no description)" and hiding the cause.
                # 壊れたプラグインメタデータは "(no description)" の裏に
                # 原因を隠さず、明示的に表示する。
                desc = (
                    f"[PLUGIN_INFO error] {plugin['error']}\n\n"
                    "The tool may still launch, but its launcher metadata "
                    "could not be read. See README \"Adding a GUI Plugin\"."
                )
            btn.bind("<Enter>", lambda _e, d=desc: self._set_message(d))

        self.scrollable.inner.grid_columnconfigure(0, weight=1)

    # -------- Plugin launching --------
    def _launch(self, module_import_path: str):
        """
        Launch a plugin in a subprocess.
        プラグインをサブプロセスで起動する。

        Subprocess isolation is important because tkinter/matplotlib expect to
        own the main thread. Running each plugin in its own process avoids
        conflicts between the launcher and plugin event loops.
        tkinter/matplotlib はメインスレッド支配を前提とするため、ランチャーと
        プラグインのイベントループ衝突を避ける目的でサブプロセス分離する。

        Frozen vs. source:
          Both modes use this project's ``--run-plugin`` subcommand. In frozen
          builds, ``sys.executable`` is ``Main.exe``; in source runs, this
          ``Main.py`` file is re-invoked with the same subcommand. Keeping both
          paths on ``--run-plugin`` centralizes splash handling and explicit
          ``main()`` invocation in `_run_plugin_and_exit`.
          凍結ビルドでもソース実行でも、本プロジェクト独自の
          ``--run-plugin`` サブコマンドを使う。凍結時は ``sys.executable`` が
          ``Main.exe``、ソース実行時はこの ``Main.py`` を同じサブコマンド付きで
          再起動する。これにより、スプラッシュ表示と ``main()`` の明示呼び出しを
          `_run_plugin_and_exit` に集約できる。
        """
        self._set_status("Launching...")
        try:
            # Use the same --run-plugin path for frozen and source runs.
            # 凍結ビルドでもソース実行でも `--run-plugin` 経路で統一する。
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--run-plugin", module_import_path]
            else:
                # Source run: re-invoke this Main.py with --run-plugin.
                cmd = [sys.executable, str(Path(__file__).resolve()),
                       "--run-plugin", module_import_path]

            # On Windows, detach the child so closing the launcher does not
            # kill it, and hide any spurious console window in windowed mode.
            # Windows では子プロセスを切り離し、ランチャー終了で道連れに
            # ならないようにする。また windowed モードで意図しないコンソールが
            # 出ないようにフラグを立てる。
            popen_kwargs: dict = {"cwd": str(BASE_DIR)}
            if sys.platform.startswith("win"):
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                )

            subprocess.Popen(cmd, **popen_kwargs)
        except Exception as e:
            self._set_message(f"Failed to launch:\n{e}")
        finally:
            # Clear the status after a short delay so the user sees it briefly.
            # 短時間表示してからステータスをクリアする。
            self.after(1500, lambda: self._set_status(""))


# =========================
# Entry point
# =========================
def main():
    """
    Dispatch subcommands, then launch the main launcher GUI.
    サブコマンドを振り分けた後、ランチャー GUI を起動する。

    Subcommand dispatching happens BEFORE any GUI is created so that
    `--run-plugin` never instantiates a launcher window.
    This is what prevents fork-bombing in the frozen build.
    ``--run-plugin`` でランチャー GUI が開かないよう、サブコマンドの
    振り分けは GUI を作るより前に行う。これが凍結ビルドでフォークボムを
    防いでいるキモの部分。
    """
    # ---- Subcommand dispatch ----
    argv = sys.argv[1:]
    if argv:
        head = argv[0]
        if head == "--run-plugin":
            if len(argv) < 2:
                _show_startup_error(
                    title="Invalid arguments",
                    message="`--run-plugin` requires a plugin import path argument.",
                )
                return
            _run_plugin_and_exit(argv[1])
            return
        # Unknown arguments are ignored and the launcher starts normally.
        # 未知の引数は無視してランチャーを通常起動する。

    # ---- Normal launcher mode ----
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
