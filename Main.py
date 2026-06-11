"""
Launcher entry point for AFM Nanofiber analysis GUI plugins.
AFM ナノファイバー解析 GUI プラグインのランチャーエントリポイント。

Multi-entry design:
  `Main.exe` (and `python Main.py`) behaves differently based on argv:
  `Main.exe`（および `python Main.py`）は argv によって挙動を切り替える。

    - no subcommand           -> launch the main launcher GUI
                                 ランチャー GUI を起動する（通常モード）
    - `--warmup`              -> import PRELOAD_LIBS and exit immediately
                                 PRELOAD_LIBS を import して即終了する
                                 （OS ページキャッシュ温め専用の子プロセス）
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

Startup acceleration strategy:
  (A) Preload heavy libraries in a background thread right after launch.
      起動直後にバックグラウンドスレッドで重いライブラリを先読みする。
  (B) Fire a throwaway `--warmup` subprocess on launch to additionally
      warm the OS page cache from the child-process side.
      加えて `--warmup` 付きの使い捨てサブプロセスを1回だけ起動し、
      子プロセス側から見たページキャッシュも温めておく。
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
_PO_TRANSLATION_CACHE: dict[str, dict[str, str]] = {}

# Libraries to preload. Keep this list in sync with what plugins import.
# 事前ロード対象ライブラリ。プラグインが import するものと同期を保つ。
#
# Submodule names (e.g. "matplotlib.pyplot", "scipy.ndimage") are included
# explicitly so that the full import chain up to those submodules is executed
# during warmup. Importing only the top-level package does NOT pull in heavy
# submodules like pyplot, so naming them here matters for real wall-clock gain.
# サブモジュール名（例: "matplotlib.pyplot", "scipy.ndimage"）は明示的に
# 入れている。トップレベルパッケージだけを import しても pyplot のような
# 重いサブモジュールはロードされないため、ここに書くことが実時間短縮に効く。
PRELOAD_LIBS = [
    "numpy",
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.backends.backend_tkagg",
    "tkinter.colorchooser",
    "cv2",
    "scipy",
    "scipy.ndimage",
    "scipy.optimize",
    "scipy.signal",
    "skimage",
    "blosc2",
    "pandas",
    "lmfit",
    "lib.fiber_tracking_image",
    "lib.bg_calibrator_shimadzu",
    "lib.kink_detector",
    "lib.imp_tools",
]


# =========================
# Warmup
# =========================
def _do_warmup() -> None:
    """
    Import PRELOAD_LIBS with matplotlib backend pre-set.
    matplotlib backend を固定して PRELOAD_LIBS を順次 import する。

    Called from two contexts:
      - As a background thread in the launcher process (Strategy A).
        ランチャープロセスのバックグラウンドスレッドとして(戦略A)。
      - As the entry point of the `--warmup` subcommand (Strategy B's child).
        `--warmup` サブコマンドのエントリポイントとして(戦略Bの子プロセス側)。
    """
    try:
        import matplotlib
        matplotlib.use("TkAgg")
    except Exception:
        pass
    for name in PRELOAD_LIBS:
        try:
            importlib.import_module(name)
        except Exception:
            pass



def _warmup_in_subprocess() -> None:
    """
    Strategy B: fire a throwaway subprocess that imports the same libs.
    戦略B: 同じライブラリを import する使い捨てサブプロセスを1つ起動する。

    This is purely to warm the OS page cache from the child-process side.
    目的は子プロセス側から見た OS ページキャッシュを温めることのみ。
    The process is not reused for actual plugin launching.
    このプロセス自体はプラグイン起動に再利用しない。

    Implementation note:
      In frozen builds, `sys.executable` is `Main.exe` and the PyInstaller
      bootloader ignores `-c` / `-m`. Naively running
      `[sys.executable, "-c", "import ..."]` would therefore re-launch the
      full launcher GUI and fork-bomb the desktop.
      We instead pass our own `--warmup` subcommand, which is handled at
      the top of `main()` and exits before any GUI is created.
      凍結ビルドでは `sys.executable` が `Main.exe` であり、PyInstaller の
      bootloader は `-c` / `-m` を解釈しない。そのまま
      `[sys.executable, "-c", "import ..."]` とするとランチャー GUI が
      再度立ち上がってフォークボム化してしまう。
      そこで独自のサブコマンド `--warmup` を渡し、`main()` の冒頭で
      GUI を作る前に処理・終了させる。
    """
    try:
        subprocess.Popen(
            [sys.executable, "--warmup"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # On Windows, hide the console window of the child process.
            # Windows では子プロセスのコンソールウィンドウを隠す。
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
    except Exception:
        pass


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

    status_var = tk.StringVar(value="Preparing...")
    ttk.Label(frame, textvariable=status_var, anchor="center").pack(pady=(0, 6))

    # Determinate mode: PRELOAD_LIBS count + 1 step for the plugin module itself.
    total_steps = len(PRELOAD_LIBS) + 1
    pbar = ttk.Progressbar(
        frame, mode="determinate", length=360, maximum=total_steps
    )
    pbar.pack(pady=4)

    # ---- 2) Share worker-thread state ----
    # The main (Tkinter) thread and the worker thread communicate via these.
    state = {
        "progress": 0,            # Completed step count.
        "current": "",            # Module currently being loaded.
        "done": False,            # Completion flag.
        "module": None,           # Loaded plugin module.
        "error": None,            # Exception, if any.
    }

    def worker():
        """
        Import PRELOAD_LIBS and the plugin sequentially in a worker thread.
        ワーカースレッドで PRELOAD_LIBS とプラグインを順次 import する。
        """
        try:
            try:
                import matplotlib
                matplotlib.use("TkAgg")
            except Exception:
                pass

            for i, name in enumerate(PRELOAD_LIBS, 1):
                state["current"] = name
                try:
                    importlib.import_module(name)
                except Exception:
                    pass  # Best effort.
                state["progress"] = i

            # Plugin module itself.
            state["current"] = module_import_path
            state["module"] = importlib.import_module(module_import_path)
            state["progress"] = total_steps
        except Exception as e:
            state["error"] = e
        finally:
            state["done"] = True

    threading.Thread(target=worker, daemon=True).start()

    # ---- 3) Poll progress from the main thread ----
    # Poll state every 50ms and reflect it on the UI.
    def poll():
        pbar["value"] = state["progress"]
        if state["current"]:
            status_var.set(f"Loading {state['current']}...")
        if state["done"]:
            splash.quit()  # Exit mainloop.
        else:
            splash.after(50, poll)

    splash.after(50, poll)
    splash.mainloop()

    # ---- 4) Clean up splash window ----
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
def _extract_plugin_info_static(py_file: Path) -> dict:
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

    Returns an empty dict on any parse / read / literal-eval failure.
    パース / 読み込み / literal_eval のいずれかが失敗した場合は空 dict を返す。
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "PLUGIN_INFO":
                try:
                    value = ast.literal_eval(node.value)
                    return value if isinstance(value, dict) else {}
                except Exception:
                    return {}
    return {}


def _read_po_catalog(lang_code: str) -> dict[str, str]:
    """
    Read a gettext `.po` file into a simple singular-message dictionary.
    gettext の `.po` ファイルを単数メッセージ用の辞書として読み込む。

    This is a launcher-only fallback for plugin metadata. It keeps translated
    launcher descriptions available even when the compiled `.mo` catalog has
    not been regenerated yet.
    ランチャーのプラグインメタデータ専用のフォールバックである。コンパイル済み
    `.mo` カタログが未更新でも、ランチャー説明文の翻訳を利用できるようにする。
    """
    if lang_code in _PO_TRANSLATION_CACHE:
        return _PO_TRANSLATION_CACHE[lang_code]

    catalog: dict[str, str] = {}
    po_path = BASE_DIR / "locale" / lang_code / "LC_MESSAGES" / "messages.po"
    try:
        text = po_path.read_text(encoding="utf-8")
    except Exception:
        _PO_TRANSLATION_CACHE[lang_code] = catalog
        return catalog

    def _collect_quoted(lines: list[str], start: int, keyword: str) -> tuple[str, int]:
        first = lines[start][len(keyword):].strip()
        parts = [ast.literal_eval(first)]
        index = start + 1
        while index < len(lines) and lines[index].startswith('"'):
            parts.append(ast.literal_eval(lines[index]))
            index += 1
        return "".join(parts), index

    for block in text.split("\n\n"):
        lines = block.splitlines()
        if any(line.startswith("#~") for line in lines):
            continue
        if any(line.startswith("#,") and "fuzzy" in line for line in lines):
            continue
        msgid_index = next(
            (i for i, line in enumerate(lines) if line.startswith("msgid ")),
            None,
        )
        msgstr_index = next(
            (i for i, line in enumerate(lines) if line.startswith("msgstr ")),
            None,
        )
        if msgid_index is None or msgstr_index is None:
            continue
        try:
            msgid, _ = _collect_quoted(lines, msgid_index, "msgid ")
            msgstr, _ = _collect_quoted(lines, msgstr_index, "msgstr ")
        except Exception:
            continue
        if msgid and msgstr:
            catalog[msgid] = msgstr

    _PO_TRANSLATION_CACHE[lang_code] = catalog
    return catalog


def _translate_plugin_metadata(message: str) -> str:
    """
    Translate plugin metadata, falling back to `.po` when `.mo` is stale.
    `.mo` が古い場合は `.po` にフォールバックしてプラグインメタデータを翻訳する。
    """
    translated = _(message)
    if translated != message:
        return translated

    lang_code = current_language()
    if lang_code == "Japanese":
        return translated
    return _read_po_catalog(lang_code).get(message, translated)


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

        info = _extract_plugin_info_static(py_file)
        plugins.append({
            "module": import_path,
            "name": info.get("name", module_name),
            "description": _translate_plugin_metadata(info.get("description", "")),
        })

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
    `--warmup` and `--run-plugin` never instantiate a launcher window.
    This is what prevents fork-bombing in the frozen build.
    ``--warmup`` と ``--run-plugin`` でランチャー GUI が開かないよう、
    サブコマンドの振り分けは GUI を作るより前に行う。これが凍結ビルドで
    フォークボムを防いでいるキモの部分。
    """
    # ---- Subcommand dispatch ----
    argv = sys.argv[1:]
    if argv:
        head = argv[0]
        if head == "--warmup":
            _do_warmup()
            return
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
    # Strategy A: warm this process's import cache in the background.
    # 戦略A: バックグラウンドスレッドでこのプロセスのimportキャッシュを温める。
    threading.Thread(target=_do_warmup, daemon=True).start()

    # Strategy B: warm the OS page cache from a throwaway child process.
    # 戦略B: 使い捨て子プロセスからも OS ページキャッシュを温める。
    _warmup_in_subprocess()

    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
