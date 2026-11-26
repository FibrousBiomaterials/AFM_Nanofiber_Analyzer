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
}
WINDOW_SIZE = (1450, 880)
# A small window keeps its own default size, which its layout was made for.
# 小さなウィンドウは、配置の前提である自身の既定の大きさのままにする。
WINDOW_SIZES = {"gui00": (960, 620)}
CHILD_TIMEOUT_S = 300


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


def prepare_data() -> dict:
    """
    Copy and analyze the scans, and choose the fiber the screenshots point at.
    スキャンを複製・解析し、スクリーンショットで指す繊維を選ぶ。
    """
    sys.path.insert(0, str(ROOT))
    from afm_nanofiber_analyzer.measure import measure_bundle
    from afm_nanofiber_analyzer.pipeline import ProcParams, process_file

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for name, size in SCANS.items():
        src = ROOT / "testdata" / name
        dst = DATA_DIR / name
        shutil.copyfile(src, dst)
        result = process_file(str(dst), ProcParams(), scan_size_um=size)
        bundles[name] = result.bundle_path

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
    # Points close enough together that the polyline follows the fiber's bends.
    # 折れ線が繊維の曲がりに沿うだけの間隔で点を置く。
    picks = [round(i * (len(x) - 1) / 15) for i in range(16)]
    return {
        "bundles": bundles,
        "fiber_index": best.index,
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
    "gui02": scenario_gui02,
    "gui03": scenario_gui03,
    "gui04": scenario_gui04,
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


def run_child(target: str, lang: str, out: Path, info_path: Path) -> None:
    """
    Start one plugin in `lang`, play its scenario, and capture its window.
    1 つのプラグインを `lang` で起動し、シナリオを再生してウィンドウを撮る。
    """
    sys.path.insert(0, str(ROOT))
    from afm_nanofiber_analyzer import translator

    translator.set_language(lang)
    info = json.loads(info_path.read_text(encoding="utf-8"))
    module = importlib.import_module(MODULES[target])
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
    app.geometry("{0}x{1}+40+40".format(*WINDOW_SIZES.get(target, WINDOW_SIZE)))
    steps = SCENARIOS[target](app, info)
    state = {"wait": None, "until": 0.0}

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
        except StopIteration:
            app.update_idletasks()
            capture_window(int(app.wm_frame(), 16), out)
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
            app.destroy()
            sys.exit(1)
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
    parser.add_argument("--only", nargs="+", choices=sorted(MODULES))
    parser.add_argument("--child", nargs=4, metavar=("TARGET", "LANG", "OUT", "INFO"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        target, lang, out, info = args.child
        run_child(target, lang, Path(out), Path(info))
        return

    info = prepare_data()
    info_path = OUT_DIR / "info.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    targets = args.only or sorted(MODULES)
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
