"""
Take the GUI screenshots of the README and the manual from the running plugins.
README とマニュアルの GUI スクリーンショットを、実際に動かしたプラグインから撮る。

Each screenshot is taken in a process of its own: the language is set before
the plugin is imported, the plugin's ``App`` runs its own ``mainloop``, and a
scenario drives it through the same public methods its command-line start
uses (``load_folder``, ``open_path``, ``add_files``, ``open_bundle``), then
through real Tk events (a table selection, a right-click on the heat map).
The window is captured by its own handle with ``PrintWindow``, so whatever
else is on the screen never enters the image.
スクリーンショットは 1 枚ごとに別のプロセスで撮る。プラグインを import する前に
言語を設定し、プラグインの ``App`` が自身の ``mainloop`` で動き、シナリオが
コマンドライン起動と同じ公開メソッド（``load_folder``・``open_path``・
``add_files``・``open_bundle``）と、本物の Tk イベント（表の選択、ヒートマップ
の右クリック）で操作する。ウィンドウは自身のハンドルから ``PrintWindow`` で
撮るので、画面上のほかのものは画像に入らない。

The scans are copies of the bundled tunicate and higher-plant scans, analyzed
with the default settings into ``.tmp/example_scans/``. Windows only.
スキャンは同梱のチュニケートと高等植物のスキャンの複製で、既定の設定で
``.tmp/example_scans/`` に解析する。Windows 専用。

Usage::

    .venv\\Scripts\\python.exe scripts\\capture_screenshots.py [--lang English Japanese]
        [--only gui01 gui02 ...]

Images are written to ``.tmp/screens/<language>/<target>.png``, with the
four-panel ``guis.png`` beside them; copy the ones to keep into ``figures/``.
画像は ``.tmp/screens/<言語>/<対象>.png`` に書き、4 面の ``guis.png`` も同じ
場所に作る。残すものを ``figures/`` に複製する。
"""

import argparse
import ctypes
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".tmp" / "example_scans"
# GUI00 needs files in a format the analysis does not read itself; the bundled
# scans are written there as Gwyddion Simple Field (.gsf) files.
# GUI00 には解析が自分では読まない形式のファイルが要る。同梱スキャンを
# Gwyddion Simple Field（.gsf）として書き出して使う。
VENDOR_DIR = ROOT / ".tmp" / "example_vendor_files"
RANGE_DIR = ROOT / ".tmp" / "example_ranges"
# Bundled bundles GUI05 shows besides the ones analyzed here: a rectangular
# scan, and the scan of another instrument (Bruker).
# GUI05 で、ここで解析したものに加えて表示する同梱バンドル。長方形の走査と、
# 別の装置（Bruker）の走査。
GALLERY_EXTRA = ("sample_anisotropic.b2z", "NDTOC250306.000.b2z")
OUT_DIR = ROOT / ".tmp" / "screens"

# The bundled scans the screenshots show, with the scan size of a file whose
# header records none (testdata/scale_table_sample.csv).
# スクリーンショットに写す同梱スキャン。ヘッダに走査範囲の無いファイルには、
# その走査範囲（testdata/scale_table_sample.csv）を添える。
SCANS = {
    "TunicateACTOCCNF.txt": (5.0, 5.0),
    "_20250318-164122_T.ssp .txt": None,
}
MAIN_SCAN = "TunicateACTOCCNF.txt"

MODULES = {
    "gui00": "guis.GUI00_Format_Converter",
    "gui01": "guis.GUI01_Image_Preprocessor",
    "gui02": "guis.GUI02_PlotProfiler",
    "gui03": "guis.GUI03_Fiber_Morphology_Statistics",
    "gui04": "guis.GUI04_Tracking_fiber",
    "gui05": "guis.GUI05_Thumbnail_Viewer",
    "gui06": "guis.GUI06_Bundle_Editor",
}
WINDOW_SIZE = (1450, 880)
# A small window keeps its own default size, which its layout was made for.
# 小さなウィンドウは、配置の前提である自身の既定の大きさのままにする。
# None leaves a window that sizes itself to its controls as it opens.
# None は、開くときに操作欄に合わせて自分で大きさを決めるウィンドウをそのままにする。
WINDOW_SIZES = {"gui00": (960, 620), "gui05": None}
CHILD_TIMEOUT_S = 300
# Longest time one scenario step may wait before the child gives up.
# シナリオの 1 段階が待てる最長の時間。超えたら子プロセスは諦める。
WAIT_TIMEOUT_S = 60


# ----- Preparation (parent process) -----

def write_gsf(path: Path, height_nm, x_um: float, y_um: float) -> None:
    """
    Write a height image as a Gwyddion Simple Field file.
    高さ画像を Gwyddion Simple Field ファイルとして書き出す。

    The header is followed by one to four NUL bytes, so the little-endian
    float32 data (heights in metres) starts at a multiple of four bytes.
    ヘッダの後に 1〜4 バイトの NUL を置き、リトルエンディアン float32 の
    データ（高さ、m 単位）が 4 バイトの倍数の位置から始まるようにする。
    """
    import numpy as np

    rows, cols = height_nm.shape
    header = (
        "Gwyddion Simple Field 1.0\n"
        f"XRes = {cols}\nYRes = {rows}\n"
        f"XReal = {x_um * 1e-6!r}\nYReal = {y_um * 1e-6!r}\n"
        "XYUnits = m\nZUnits = m\n"
        f"Title = {path.stem}\n"
    ).encode("ascii")
    pad = 4 - len(header) % 4
    data = (np.asarray(height_nm, dtype="<f4") * np.float32(1e-9)).astype("<f4")
    path.write_bytes(header + b"\0" * pad + data.tobytes())


def prepare_vendor_files() -> None:
    """
    Write the bundled scans as .gsf files with no converted copy beside them.
    同梱スキャンを .gsf として書き出し、横に変換済みの複製が無い状態にする。
    """
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    import trash
    from afm_nanofiber_analyzer.afm_io import load_afm_text, read_scan_size

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    stale = list(VENDOR_DIR.glob("*_converted.gwy"))
    if stale:
        trash.send_to_trash(stale)
    for name, size in SCANS.items():
        src = ROOT / "testdata" / name
        if size is None:
            recorded = read_scan_size(str(src))
            size = (recorded.x_um, recorded.y_um)
        stem = name[: -len(".txt")].strip()
        write_gsf(VENDOR_DIR / f"{stem}.gsf", load_afm_text(str(src)), *size)


def prepare_data(fresh: bool) -> dict:
    """
    Copy and analyze the scans, and choose the fiber the screenshots point at.
    スキャンを複製・解析し、スクリーンショットで指す繊維を選ぶ。

    Parameters
    ----------
    fresh
        Analyze again even where a bundle is already there.
        バンドルが既にあっても解析し直すかどうか。
    """
    sys.path.insert(0, str(ROOT))
    from afm_nanofiber_analyzer.measure import measure_bundle
    from afm_nanofiber_analyzer.pipeline import (
        ProcParams, bundle_path_for, process_file, row_range_suffix,
    )

    def analyzed(path: Path, size=None, rows=None) -> str:
        bundle = bundle_path_for(os.path.splitext(str(path))[0] + row_range_suffix(rows))
        if fresh or not os.path.exists(bundle):
            print(f"analyzing {path.name} {rows or ''}", flush=True)
            process_file(str(path), ProcParams(), scan_size_um=size, row_range=rows)
        return bundle

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for name, size in SCANS.items():
        dst = DATA_DIR / name
        shutil.copyfile(ROOT / "testdata" / name, dst)
        bundles[name] = analyzed(dst, size)

    # The higher-plant scan analyzed as the two glitch-free scan-line ranges
    # GUI01 proposes for it, in a folder of their own so GUI01's folder keeps
    # one entry per scan.
    # 高等植物のスキャンを、GUI01 が提案する縞ノイズの無い 2 つの走査線範囲として
    # 解析する。GUI01 のフォルダが 1 スキャン 1 項目のままになるよう、別の
    # フォルダに置く。
    RANGE_DIR.mkdir(parents=True, exist_ok=True)
    other = next(name for name in SCANS if name != MAIN_SCAN)
    shutil.copyfile(ROOT / "testdata" / other, RANGE_DIR / other)
    range_bundles = [analyzed(RANGE_DIR / other, rows=rows)
                     for rows in ((0, 817), (834, 1024))]
    gallery = (
        [bundles[MAIN_SCAN], bundles[other]] + range_bundles
        + [str(ROOT / "testdata" / name) for name in GALLERY_EXTRA]
    )

    # A long, nearly straight fiber that stays inside the scan shows a profile
    # along one fiber and a highlighted row that is easy to find.
    # 走査範囲の内側にある長くほぼまっすぐな繊維は、1 本の繊維に沿った
    # プロファイルや、見つけやすい強調表示の行になる。
    measured = measure_bundle(bundles[MAIN_SCAN])
    candidates = [s for s in measured.stats
                  if s.straightness >= 0.95 and not s.touches_frame]
    best = max(candidates, key=lambda s: s.length_nm)
    fiber = measured.fibers[best.index]
    x = fiber.xtrack + fiber.data[0]
    y = fiber.ytrack + fiber.data[1]
    # GUI06 edits the kinks the bundle stores (`kp`, on skeleton pixels): the
    # one nearest to this fiber's first kink is the one clicked there.
    # GUI06 はバンドルに記録されたキンク（`kp`、細線化画素の上）を編集する。この
    # 繊維の最初のキンクに最も近いものを、そこでクリックする。
    import numpy as np
    from afm_nanofiber_analyzer.blosc2_io import load_bundle

    kp = load_bundle(bundles[MAIN_SCAN], keys=["kp"])["kp"]
    first = int(np.asarray(fiber.kink_indices, dtype=int)[0])
    nearest = int(np.argmin(np.hypot(kp[0] - x[first], kp[1] - y[first])))
    kink_pixel = [int(kp[0][nearest]), int(kp[1][nearest])]

    # Points close enough together that the polyline follows the fiber's bends.
    # 折れ線が繊維の曲がりに沿うだけの間隔で点を置く。
    picks = [round(i * (len(x) - 1) / 15) for i in range(16)]
    return {
        "bundles": bundles,
        "gallery": gallery,
        "fiber_index": best.index,
        "kink_pixel": kink_pixel,
        "fiber_pixels": [[float(x[i]), float(y[i])] for i in picks],
    }


# ----- Scenarios (child process) -----
# Each scenario is a generator. A yielded callable is waited on until it
# returns True; a yielded number is a pause in seconds.
# 各シナリオはジェネレーター。callable を yield すると True を返すまで待ち、
# 数値を yield するとその秒数だけ待つ。

def scenario_gui00(app, info):
    import guis.GUI00_Format_Converter as plugin

    # The folder dialog is the one step a script cannot answer, so it returns
    # the example folder; the buttons themselves are pressed.
    # フォルダのダイアログだけはスクリプトが応答できないので、例のフォルダを
    # 返すようにする。ボタンそのものは押す。
    plugin.filedialog.askdirectory = lambda **_kw: str(VENDOR_DIR)
    app.btn_folder.invoke()
    yield 1.0
    app.btn_convert.invoke()
    yield lambda: app._running
    yield lambda: not app._running
    yield 1.0


def scenario_gui01(app, info):
    from guis.GUI01_Image_Preprocessor import COL_NAME

    app.load_folder(str(DATA_DIR))
    app.overwrite_existing_var.set(True)
    yield 1.0
    app.on_run_all()
    yield lambda: app.is_running
    yield lambda: not app.is_running
    row = next(iid for iid, item in app.item_by_iid.items()
               if os.path.basename(item.txt_path) == MAIN_SCAN)
    app.sheet.select_cell(row, COL_NAME, redraw=True)
    app._on_sheet_select()
    yield lambda: app._preview_shown_item is not None
    app.overlay_mode_var.set("KP")
    app.on_redraw_preview()
    yield 2.0


def scenario_gui01_settings(app, info):
    from guis.GUI01_Image_Preprocessor import SettingsDialog

    app.load_folder(str(DATA_DIR))
    yield 1.0
    # The dialog is modal and waits in a nested event loop, so the button is
    # pressed from a callback of its own and this scenario keeps ticking.
    # ダイアログはモーダルで、入れ子のイベントループで待つ。そのためボタンは別の
    # コールバックから押し、このシナリオは進み続ける。
    app.after(0, app.btn_settings.invoke)
    yield lambda: any(isinstance(w, SettingsDialog) for w in app.winfo_children())
    yield 1.5
    app._capture_window = next(w for w in app.winfo_children()
                               if isinstance(w, SettingsDialog))


def scenario_gui01_split(app, info):
    from guis.GUI01_Image_Preprocessor import COL_NAME

    app.load_folder(str(DATA_DIR))
    yield lambda: all(it.stripe_noise is not None for it in app.items)
    row = next(iid for iid, item in app.item_by_iid.items()
               if os.path.basename(item.txt_path) != MAIN_SCAN)
    app.sheet.select_cell(row, COL_NAME, redraw=True)
    app._on_sheet_select()
    yield lambda: app._preview_shown_item is not None
    yield 1.0
    app.btn_split_rows.invoke()
    yield 2.0


def scenario_gui05(app, info):
    app.add_paths(info["gallery"])
    yield lambda: len(app.readable_items()) == len(info["gallery"])
    yield 2.0


def scenario_gui06(app, info):
    import guis.GUI06_Bundle_Editor as plugin

    app.open_bundle(info["bundles"][MAIN_SCAN])
    yield lambda: app.session is not None and not app._loading
    yield 1.0
    kx, ky = info["kink_pixel"]
    # Close enough that the two arms of the kink, about 1.5 apparent widths
    # long, are clearly drawn.
    # キンクの 2 本の腕（見かけ幅の 1.5 倍ほどの長さ）がはっきり見える拡大率。
    half = 45
    app.ax.set_xlim(kx - half, kx + half)
    app.ax.set_ylim(ky + half, ky - half)
    app.canvas.draw()
    yield 0.5
    # The tools act on the layer whose name was clicked, as the layer pane says.
    # ツールは、名前をクリックしたレイヤーに働く（レイヤー欄の説明のとおり）。
    app.select_layer(plugin.LAYER_KINKS)
    yield 0.5
    app.tool_var.set(plugin.TOOL_EDIT_KINK)
    app._on_tool_chosen()
    yield 0.5
    # A real left click on the kink, as for the points in GUI02.
    # GUI02 の点と同じく、キンクの上で本物の左クリックをする。
    canvas = app.canvas
    widget = canvas.get_tk_widget()
    ratio = getattr(canvas, "device_pixel_ratio", 1.0) or 1.0
    dx, dy = app.ax.transData.transform((kx, ky))
    wx = int(round(dx / ratio))
    wy = int(round((canvas.figure.bbox.height - dy) / ratio))
    widget.event_generate("<ButtonPress-1>", x=wx, y=wy)
    widget.event_generate("<ButtonRelease-1>", x=wx, y=wy)
    yield lambda: app._selected_kink is not None
    yield 1.5


def scenario_gui02(app, info):
    app.open_path(info["bundles"][MAIN_SCAN])
    yield lambda: getattr(app, "aximg", None) is not None
    yield 1.0
    x_ext, y_ext = app.aximg.get_extent()[1], app.aximg.get_extent()[3]
    rows, cols = app.img.shape
    canvas = app.canvas
    widget = canvas.get_tk_widget()
    ratio = getattr(canvas, "device_pixel_ratio", 1.0) or 1.0
    fig_h = canvas.figure.bbox.height
    for px, py in info["fiber_pixels"]:
        # Pixel (c, r) covers [c, c + 1) along x and row 0 is drawn at the top.
        # 画素 (c, r) は x 方向に [c, c + 1) を占め、行 0 は上端に描かれる。
        xd = (px + 0.5) * x_ext / cols
        yd = y_ext - (py + 0.5) * y_ext / rows
        dx, dy = app.ax.transData.transform((xd, yd))
        wx, wy = int(round(dx / ratio)), int(round((fig_h - dy) / ratio))
        widget.event_generate("<ButtonPress-3>", x=wx, y=wy)
        widget.event_generate("<ButtonRelease-3>", x=wx, y=wy)
        yield 0.3
    yield lambda: len(app.xlist) == len(info["fiber_pixels"])
    yield 2.0


def scenario_gui03(app, info):
    main = info["bundles"][MAIN_SCAN]
    other = next(p for name, p in info["bundles"].items() if name != MAIN_SCAN)
    app.add_files(app.groups[0], [main])
    app.on_add_group()
    app.add_files(app.groups[1], [other])
    yield 1.0
    child = app.tree.get_children(app.groups[0].id)[0]
    app.tree.selection_set(child)
    app.tree.focus(child)
    app.tree.event_generate("<<TreeviewSelect>>")
    yield 2.0
    # The default range ends at 10 nm, below a fifth of the tunicate samples.
    # 既定の範囲は 10 nm までで、チュニケートの標本の 2 割ほどがそれを超える。
    app.max_var.set("20")
    app.on_run()
    yield lambda: app.is_running
    yield lambda: not app.is_running
    yield 2.0


def scenario_gui03_stats(app, info):
    main = info["bundles"][MAIN_SCAN]
    other = next(p for name, p in info["bundles"].items() if name != MAIN_SCAN)
    app.add_files(app.groups[0], [main])
    app.on_add_group()
    app.add_files(app.groups[1], [other])
    yield 1.0
    # One fiber per sample: the between-group tests run for the fiber and
    # image units only, and each group here holds one scan, fewer than the
    # three scans a test per image needs.
    # 1 本の繊維を 1 標本とする。群間の検定は fiber と image の単位でだけ行われ、
    # ここでは各群が 1 スキャンしか持たず、image 単位の検定に要る 3 スキャンに
    # 足りないためである。
    app.unit_var.set("fiber")
    app.cmb_unit.event_generate("<<ComboboxSelected>>")
    yield 0.5
    app.max_var.set("20")
    app.on_run()
    yield lambda: app.is_running
    yield lambda: not app.is_running
    yield 1.0
    app.on_show_statistics()
    yield 2.0
    app._capture_window = app.stats_window


def scenario_gui04(app, info):
    app.open_bundle(info["bundles"][MAIN_SCAN])
    yield lambda: bool(app.fiber_tree.get_children())
    yield 1.0
    iid = str(info["fiber_index"])
    app.fiber_tree.selection_set(iid)
    app.fiber_tree.focus(iid)
    app.fiber_tree.see(iid)
    app.fiber_tree.event_generate("<<TreeviewSelect>>")
    yield 2.0


SCENARIOS = {
    "gui00": scenario_gui00,
    "gui01": scenario_gui01,
    "gui01_settings": scenario_gui01_settings,
    "gui01_split": scenario_gui01_split,
    "gui02": scenario_gui02,
    "gui03": scenario_gui03,
    "gui03_stats": scenario_gui03_stats,
    "gui04": scenario_gui04,
    "gui05": scenario_gui05,
    "gui06": scenario_gui06,
}


def capture_window(hwnd: int, path: Path) -> None:
    """
    Save the window with handle `hwnd` as a PNG through PrintWindow.
    ハンドル `hwnd` のウィンドウを PrintWindow で PNG に保存する。
    """
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    # PW_RENDERFULLCONTENT draws the window as composed by DWM.
    user32.PrintWindow(hwnd, mdc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0,
                              0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(header), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    image = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    # The window rectangle includes the invisible resize border, which
    # PrintWindow leaves pure black; rows and columns of nothing else are cut.
    # ウィンドウ矩形には見えないリサイズ枠が含まれ、PrintWindow はそこを真っ黒の
    # まま残す。真っ黒だけの行と列は切り落とす。
    import numpy as np

    pixels = np.asarray(image)
    content = pixels.any(axis=2)
    # Only the outermost kept row and column matter, so a black image panel
    # inside the window cannot shift the crop.
    cols = np.flatnonzero(content.mean(axis=0) > 0.5)
    rows = np.flatnonzero(content.mean(axis=1) > 0.5)
    image.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1)).save(path)


def own_windows() -> list:
    """
    Return the visible top-level windows of this process, dialogs included.
    このプロセスの見えているトップレベルウィンドウを、ダイアログを含めて返す。

    Windows are told apart by process id, never by title, so a window of
    another program with the same title is never taken.
    ウィンドウはタイトルではなくプロセス ID で見分ける。同じタイトルの別の
    プログラムのウィンドウを撮ることはない。
    """
    user32 = ctypes.windll.user32
    found = []
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def run_child(target: str, lang: str, out: Path, info_path: Path) -> None:
    """
    Start one plugin in `lang`, play its scenario, and capture its window.
    1 つのプラグインを `lang` で起動し、シナリオを再生してウィンドウを撮る。
    """
    sys.path.insert(0, str(ROOT))
    from afm_nanofiber_analyzer import translator

    translator.set_language(lang)
    info = json.loads(info_path.read_text(encoding="utf-8"))
    # "gui01_settings" is another view of the plugin "gui01".
    module = importlib.import_module(MODULES[target.split("_")[0]])
    if hasattr(module, "_settings_path"):
        # GUI01 starts from its settings file beside the plugin, which holds
        # this PC's choices; a fresh file under .tmp/ gives the defaults and
        # leaves that file untouched.
        # GUI01 はプラグインの横の設定ファイル（この PC での選択）から始まる。
        # .tmp/ に新しく作るファイルを使えば既定値になり、元のファイルにも触れない。
        settings = OUT_DIR / f"{target}_{lang}_settings.json"
        if settings.exists():
            sys.path.insert(0, str(ROOT / "scripts"))
            import trash
            trash.send_to_trash([settings])
        module._settings_path = lambda: str(settings)
    app = module.App()
    size = WINDOW_SIZES.get(target, WINDOW_SIZE)
    if size is not None:
        app.geometry("{0}x{1}+40+40".format(*size))
    steps = SCENARIOS[target](app, info)
    state = {"wait": None, "until": 0.0, "step": 0, "since": time.monotonic()}

    def watchdog() -> None:
        # Runs in a thread of its own, so a modal dialog that stops the Tk
        # callbacks cannot stop it. The windows are captured for a look at
        # what the scenario was waiting on.
        # 別スレッドで動くので、Tk のコールバックを止めるモーダルなダイアログが
        # 出ても止まらない。シナリオが何を待っていたかを見るためにウィンドウを撮る。
        while True:
            time.sleep(1.0)
            if time.monotonic() - state["since"] > WAIT_TIMEOUT_S:
                print(f"timed out after {WAIT_TIMEOUT_S} s at step {state['step']}",
                      flush=True)
                for i, hwnd in enumerate(own_windows()):
                    path = out.with_name(f"{out.stem}_timeout{i}.png")
                    capture_window(hwnd, path)
                    print(f"  captured {path}", flush=True)
                os._exit(2)

    threading.Thread(target=watchdog, daemon=True).start()

    def tick() -> None:
        try:
            if state["wait"] is not None and not state["wait"]():
                app.after(100, tick)
                return
            state["wait"] = None
            if time.monotonic() < state["until"]:
                app.after(100, tick)
                return
            step = next(steps)
            state["step"] += 1
            state["since"] = time.monotonic()
        except StopIteration:
            app.update_idletasks()
            # A scenario that opened a dialog names it as the window to take.
            # ダイアログを開いたシナリオは、撮るウィンドウとしてそれを指定する。
            window = getattr(app, "_capture_window", app)
            capture_window(int(window.wm_frame(), 16), out)
            print(f"captured {out}", flush=True)
            # A plugin's worker threads or pending callbacks can keep the
            # process alive after destroy(); the image is saved, so it ends here.
            # destroy() の後もプラグインのワーカースレッドや保留中のコールバックが
            # プロセスを残すことがある。画像は保存済みなので、ここで終える。
            app.destroy()
            os._exit(0)
        except Exception:
            import traceback
            traceback.print_exc()
            # sys.exit inside a Tk callback would only be reported by Tk.
            os._exit(1)
        if callable(step):
            state["wait"] = step
        else:
            state["until"] = time.monotonic() + float(step)
        app.after(100, tick)

    app.after(500, tick)
    app.mainloop()


def make_panel(images, out: Path) -> None:
    """
    Put four screenshots in a 2 x 2 figure labelled (a) to (d).
    4 枚のスクリーンショットを (a)〜(d) のラベル付きで 2 × 2 に並べる。
    """
    from PIL import Image, ImageDraw, ImageFont

    tiles = [Image.open(p).convert("RGB") for p in images]
    w = max(t.width for t in tiles)
    h = max(t.height for t in tiles)
    label_h, gap = 60, 24
    sheet = Image.new("RGB", (2 * w + gap, 2 * (h + label_h) + gap), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arialbd.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    for i, tile in enumerate(tiles):
        x = (i % 2) * (w + gap)
        y = (i // 2) * (h + label_h + gap)
        draw.text((x + 4, y + 6), "({0})".format("abcd"[i]), fill="black", font=font)
        sheet.paste(tile, (x, y + label_h))
    sheet.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--lang", nargs="+", default=["English", "Japanese"])
    parser.add_argument("--only", nargs="+", choices=sorted(SCENARIOS))
    parser.add_argument("--fresh", action="store_true",
                        help="analyze the example scans again even where bundles exist")
    parser.add_argument("--child", nargs=4, metavar=("TARGET", "LANG", "OUT", "INFO"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        target, lang, out, info = args.child
        run_child(target, lang, Path(out), Path(info))
        return

    info = prepare_data(args.fresh)
    info_path = OUT_DIR / "info.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    targets = args.only or sorted(SCENARIOS)
    failed = []
    for lang in args.lang:
        folder = OUT_DIR / lang
        folder.mkdir(parents=True, exist_ok=True)
        for target in targets:
            out = folder / f"{target}.png"
            print(f"{lang} {target} ...", flush=True)
            if target == "gui00":
                prepare_vendor_files()
            try:
                subprocess.run(
                    [sys.executable, __file__, "--child", target, lang, str(out),
                     str(info_path)],
                    cwd=ROOT, timeout=CHILD_TIMEOUT_S, check=True,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"  failed: {e}", flush=True)
                failed.append((lang, target))
        panels = [folder / f"gui0{i}.png" for i in range(1, 5)]
        if all(p.exists() for p in panels):
            make_panel(panels, folder / "guis.png")
    if failed:
        sys.exit("failed: " + ", ".join(f"{lang} {t}" for lang, t in failed))


if __name__ == "__main__":
    main()
