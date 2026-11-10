# -*- coding: utf-8 -*-
"""
Generate the figures of ``docs/history.md``: past and current versions side by side.
``docs/history.md`` の図を生成する。過去と現在の版を並べて示す。

Each figure runs the analysis code of several pinned commits on the bundled
test scans and shows the results as whole images. The code of each commit is
taken from Git (``git archive``) into ``.tmp/history/src/<commit>`` and run in
its own process, so a past version computes exactly what it computed when it
was released, with the defaults it shipped with::

    .venv\\Scripts\\python.exe scripts\\make_history_figures.py
    .venv\\Scripts\\python.exe scripts\\make_history_figures.py --full
    .venv\\Scripts\\python.exe scripts\\make_history_figures.py --check

The default writes reduced figures to ``docs/images/history/``, the ones the
documents show. ``--full`` writes the same figures at about one screen pixel
per scan pixel to ``.tmp/history/full/`` instead; they are several megabytes
each and are not committed. The background figures, whose labels are version
names and units only, are shared by both language versions of the document;
the figures with a legend are drawn once per language (`LABELS`), with
a ``.ja`` file for Japanese, which needs a Japanese font. ``--check``
prints the measurements behind the statements the document makes about what
the figures show (`check_attributions`, `check_tophat_stripes`).
各図は、固定した複数のコミットの解析コードを同梱のテストスキャンに実行し、結果を
画像全体で示す。各コミットのコードは Git から（``git archive``）
``.tmp/history/src/<コミット>`` に取り出して別プロセスで実行するので、過去の版は
リリースした時と同じものを、その時の既定値で計算する。既定では文書に載せる縮小版を
``docs/images/history/`` に書く。``--full`` はスキャンの 1 画素を画面のほぼ 1 画素で
描いた同じ図を ``.tmp/history/full/`` に書く。1 枚が数 MB になるためコミットしない。
図中の文字が版の名前と単位だけの背景補正の図は、英語版と日本語版の文書で共有する。
凡例のある図は言語ごとに描き（`LABELS`）、日本語版は ``.ja`` の付いたファイルとする。日本語版には
日本語フォントが要る。
``--check`` は、図に見えることについて文書が述べる記述の裏付けとなる測定値を表示する
（`check_attributions`、`check_tophat_stripes`）。
"""

# ===== Standard library =====
import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = ROOT / ".tmp" / "history" / "src"
CACHE_BASE = ROOT / ".tmp" / "history" / "cache"
FULL_DIR = ROOT / ".tmp" / "history" / "full"
OUT_DIR = ROOT / "docs" / "images" / "history"

# Versions compared, oldest first: (label, commit). Commits are pinned so a
# figure keeps showing the code its caption describes after the code moves on.
# 比べる版（古い順）: (ラベル, コミット)。コードが先へ進んでも、図がキャプションの
# 説明するコードを示し続けるよう、コミットを固定する。
ERAS = (
    ("1.0.0", "3c28dec10f4cf77cb092fcfe7dd484c00b412097"),
    ("2.0.0", "f9c1ad897d354bbdea43f367e64a0f69beefbd4c"),
    ("c43409b", "c43409b48337b66f1f1ca570addc294bade32ed3"),
)

# Bundled test scans: (key, path, title).
# 同梱のテストスキャン: (キー, パス, 表題)。
SCANS = (
    ("tunicate", "testdata_tunicateCNF/TunicateACTOCCNF.txt", "Tunicate CNF"),
    ("higherplant", "testdata_higherplantTOC/_20250318-164122_T.ssp .txt", "Higher-plant TOC-CNF"),
    ("ndtoc", "testdata_Bruker_txt/NDTOC250306.000.txt", "NDTOC (Bruker)"),
)

# Background methods drawn for the document; "default" is each version's own.
# 文書に描く背景補正の方式。"default" は各版それぞれの既定。
BACKGROUND_METHODS = ("default", "tophat", "spline1d")

# Fixed display range of the row that shows what is left of the background.
# 背景の残りを示す段の固定表示範囲。
BACKGROUND_RANGE_NM = (-1.0, 1.0)

# Resolution of the reduced and the full figures. A panel is 10.5 in wide, so
# 120 dpi draws a 1023-pixel scan at about one pixel per pixel.
# 縮小版と原寸版の解像度。パネルの幅は 10.5 in なので、120 dpi で 1023 画素の
# スキャンをほぼ 1 画素ずつ描く。
REDUCED_DPI = 55
FULL_DPI = 120


def run_era(src: str, input_path: str, out_path: str, bg_method: str = "") -> None:
    """
    Run one version's background calibration on one scan and save the arrays.
    1 つの版の背景補正を 1 スキャンに実行し、配列を保存する。

    Called in a separate ``python -I`` process with that version's ``lib``
    first on ``sys.path``, so nothing of the current code is imported.
    その版の ``lib`` を ``sys.path`` の先頭に置いた別の ``python -I`` プロセスで
    呼ばれるので、現在のコードは何も import されない。

    Parameters
    ----------
    src
        Folder holding the version's ``lib`` package.
        その版の ``lib`` パッケージを含むフォルダ。
    input_path
        Raw scan to analyze.
        解析する生のスキャン。
    out_path
        ``.npz`` file to write: ``original``, ``calibrated`` and ``bg_method``.
        書き出す ``.npz``。``original``・``calibrated``・``bg_method``。
    bg_method
        Background method to use; empty keeps the version's default.
        使う背景補正の方式。空ならその版の既定のまま。
    """
    sys.path.insert(0, src)
    import numpy as np
    from lib import pipeline
    from lib.processed_image import ProcessedImage

    params = pipeline.ProcParams(bg_method=bg_method) if bg_method else pipeline.ProcParams()
    stages = pipeline.build_stages(params)
    loader = getattr(pipeline, "load_afm_text", None)
    if loader is None:
        from lib.afm_io import load_afm_text as loader
    height = loader(input_path)
    image = ProcessedImage(original_AFM=height, name="scan")
    stages.bg_calibrator(image)
    np.savez_compressed(out_path,
                        original=np.asarray(height, dtype=np.float32),
                        calibrated=np.asarray(image.calibrated_image, dtype=np.float32),
                        bg_method=np.array(str(params.bg_method)))


def run_segmenter(src: str, calibrated_path: str, out_path: str) -> None:
    """
    Run one version's binarization on a given calibrated image and save the mask.
    与えた補正後の画像に 1 つの版の二値化を実行し、マスクを保存する。

    Every version is given the same calibrated image, so the masks differ only
    by what the binarization of each version does. Called in a separate
    process, as `run_era` is.
    どの版にも同じ補正後の画像を与えるので、マスクの違いは各版の二値化の違いだけに
    なる。`run_era` と同じく別プロセスで呼ばれる。

    Parameters
    ----------
    src
        Folder holding the version's ``lib`` package.
        その版の ``lib`` パッケージを含むフォルダ。
    calibrated_path
        ``.npz`` written by `run_era`, whose ``calibrated`` array is binarized.
        `run_era` が書いた ``.npz``。その ``calibrated`` を二値化する。
    out_path
        ``.npz`` file to write: ``binarized``.
        書き出す ``.npz``。``binarized``。
    """
    sys.path.insert(0, src)
    import numpy as np
    from lib import pipeline
    from lib.processed_image import ProcessedImage

    calibrated = np.load(calibrated_path)["calibrated"].astype(np.float64)
    image = ProcessedImage(original_AFM=calibrated, name="scan")
    image.calibrated_image = calibrated
    pipeline.build_stages(pipeline.ProcParams()).segmenter(image)
    np.savez_compressed(out_path, binarized=np.asarray(image.binarized_image, dtype=bool))


def run_skeletonizer(src: str, calibrated_path: str, binarized_path: str, out_path: str) -> None:
    """
    Run one version's skeletonization on a given calibrated image and mask.
    与えた補正後の画像とマスクに 1 つの版のスケルトン化を実行する。

    As in `run_segmenter`, every version is given the same input, so the
    skeletons differ only by what the skeletonization of each version does.
    `run_segmenter` と同じく、どの版にも同じ入力を与えるので、スケルトンの違いは各版の
    スケルトン化の違いだけになる。

    Parameters
    ----------
    src
        Folder holding the version's ``lib`` package.
        その版の ``lib`` パッケージを含むフォルダ。
    calibrated_path
        ``.npz`` written by `run_era`, whose ``calibrated`` array gives the heights.
        `run_era` が書いた ``.npz``。その ``calibrated`` が高さを与える。
    binarized_path
        ``.npz`` written by `run_segmenter`, whose ``binarized`` mask is thinned.
        `run_segmenter` が書いた ``.npz``。その ``binarized`` を細線化する。
    out_path
        ``.npz`` file to write: ``skeleton``.
        書き出す ``.npz``。``skeleton``。
    """
    sys.path.insert(0, src)
    import numpy as np
    from lib import pipeline
    from lib.processed_image import ProcessedImage

    calibrated = np.load(calibrated_path)["calibrated"].astype(np.float64)
    image = ProcessedImage(original_AFM=calibrated, name="scan")
    image.calibrated_image = calibrated
    image.binarized_image = np.load(binarized_path)["binarized"]
    pipeline.build_stages(pipeline.ProcParams()).skeletonizer(image)
    np.savez_compressed(out_path, skeleton=np.asarray(image.skeleton_image, dtype=bool))


def run_kink_detector(src: str, calibrated_path: str, skeleton_path: str, out_path: str,
                      centerline_method: str = "") -> None:
    """
    Run one version's kink detection on a given calibrated image and skeleton.
    与えた補正後の画像とスケルトンに 1 つの版のキンク検出を実行する。

    The branch points are found with the version's own
    ``imp_tools.branchedPoints``, as its skeletonization sets them. The lines
    the kinks are judged on are recorded by wrapping the ``place_centerline``
    the version's ``kink_detector`` module calls; a version without it (1.0.0)
    judges on the skeleton itself and records no line.
    分岐点は、その版のスケルトン化と同じく、その版の ``imp_tools.branchedPoints`` で
    求める。キンクを判定する線は、その版の ``kink_detector`` モジュールが呼ぶ
    ``place_centerline`` を包んで記録する。これを持たない版（1.0.0）はスケルトンその
    もので判定し、線は記録しない。

    Parameters
    ----------
    src
        Folder holding the version's ``lib`` package.
        その版の ``lib`` パッケージを含むフォルダ。
    calibrated_path
        ``.npz`` written by `run_era`, whose ``calibrated`` array gives the heights.
        `run_era` が書いた ``.npz``。その ``calibrated`` が高さを与える。
    skeleton_path
        ``.npz`` written by `run_skeletonizer`, whose ``skeleton`` is traced.
        `run_skeletonizer` が書いた ``.npz``。その ``skeleton`` を追跡する。
    out_path
        ``.npz`` file to write: ``kinks`` (2, N) as (x = column, y = row);
        ``angles``, the interior angle the version stores for each kink, in
        radians; ``line_x``, ``line_y`` (column, row) and ``line_id`` for the
        recorded lines; ``width_px``, the median apparent width the version
        reports (NaN when it reports none).
        書き出す ``.npz``。``kinks``（2, N、x = 列、y = 行）、各キンクについてその版が
        保存する内角 ``angles``（ラジアン）、記録した線の ``line_x``・``line_y``
        （列・行）と ``line_id``、およびその版が報告する見かけ幅の中央値
        ``width_px``（報告しなければ NaN）。
    centerline_method
        Line to judge kinks on (``ProcParams.centerline_method``); empty keeps
        the version's default.
        キンクを判定する線（``ProcParams.centerline_method``）。空ならその版の既定。
    """
    sys.path.insert(0, src)
    import numpy as np
    from lib import imp_tools, kink_detector, pipeline
    from lib.processed_image import ProcessedImage

    lines = []
    if hasattr(kink_detector, "place_centerline"):
        placed = kink_detector.place_centerline

        def recording(*args, **kwargs):
            result = placed(*args, **kwargs)
            lines.append((np.asarray(result.x, dtype=float), np.asarray(result.y, dtype=float)))
            return result

        kink_detector.place_centerline = recording
    calibrated = np.load(calibrated_path)["calibrated"].astype(np.float64)
    skeleton = np.load(skeleton_path)["skeleton"].astype(np.uint8)
    image = ProcessedImage(original_AFM=calibrated, name="scan")
    image.calibrated_image = calibrated
    image.skeleton_image = skeleton
    image.bp = imp_tools.branchedPoints(skeleton)
    params = (pipeline.ProcParams(centerline_method=centerline_method) if centerline_method
              else pipeline.ProcParams())
    pipeline.build_stages(params).kink_detector(image)
    kinks = np.asarray(image.all_kink_coordinates, dtype=float).reshape(2, -1)
    angles = np.asarray(image.all_kink_angles, dtype=float).reshape(-1)
    ids = [np.full(len(x), i) for i, (x, _y) in enumerate(lines)]
    summary = getattr(image, "apparent_width_summary", None) or {}
    width = summary.get("median_px")
    np.savez_compressed(
        out_path, kinks=kinks, angles=angles, width_px=np.array(np.nan if width is None else float(width)),
        line_x=np.concatenate([x for x, _y in lines]) if lines else np.zeros(0),
        line_y=np.concatenate([y for _x, y in lines]) if lines else np.zeros(0),
        line_id=np.concatenate(ids) if ids else np.zeros(0, dtype=int))


def run_polyline_rule(src: str, lines_path: str, out_path: str) -> None:
    """
    Judge recorded lines by one version's polyline rule and save the kinks.
    記録した線を 1 つの版の折れ線規則で判定し、キンクを保存する。

    Applies the version's ``KinkDetector._binary_decompose_simple`` and
    ``KinkDetector._detect_kink_from_decomposed_indices`` at its defaults to
    every line `run_kink_detector` recorded, so the rule of 1.0.0 can be
    judged on a centerline it never saw. Called in a separate process, as
    `run_era` is.
    その版の ``KinkDetector._binary_decompose_simple`` と
    ``KinkDetector._detect_kink_from_decomposed_indices`` を既定値で、
    `run_kink_detector` が記録した各線に当てる。これにより、1.0.0 の規則を、それが
    扱ったことのない中心線の上で判定できる。`run_era` と同じく別プロセスで呼ばれる。

    Parameters
    ----------
    src
        Folder holding the version's ``lib`` package.
        その版の ``lib`` パッケージを含むフォルダ。
    lines_path
        ``.npz`` written by `run_kink_detector`, whose lines are judged.
        `run_kink_detector` が書いた ``.npz``。その線を判定する。
    out_path
        ``.npz`` file to write: ``kinks`` (2, N) as (x = column, y = row).
        書き出す ``.npz``。``kinks``（2, N、x = 列、y = 行）。
    """
    sys.path.insert(0, src)
    import numpy as np
    from lib.kink_detector import KinkDetector

    detector = KinkDetector()
    data = np.load(lines_path)
    found = [[], []]
    for line in np.unique(data["line_id"]):
        on = data["line_id"] == line
        x, y = data["line_x"][on], data["line_y"][on]
        vertices = detector._binary_decompose_simple(x, y, detector.threshold_distance)
        indices, _angles = detector._detect_kink_from_decomposed_indices(
            x, y, vertices, detector.threshold_angle_from_decomposed_indices)
        found[0].extend(x[indices])
        found[1].extend(y[indices])
    np.savez_compressed(out_path, kinks=np.asarray(found, dtype=float).reshape(2, -1))


def _source(commit: str) -> Path:
    """
    Extract a commit's ``lib`` into ``SRC_BASE`` once and return the folder.
    コミットの ``lib`` を一度だけ ``SRC_BASE`` に取り出し、そのフォルダを返す。
    """
    folder = SRC_BASE / commit
    if not (folder / "lib" / "pipeline.py").is_file():
        archive = subprocess.run(["git", "archive", commit, "lib"], cwd=ROOT,
                                 check=True, capture_output=True).stdout
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(folder, filter="data")
    return folder


def _cache_dir() -> Path:
    """
    Return the cache folder for the pinned commits and the installed libraries.
    固定したコミットと導入済みライブラリに対応するキャッシュフォルダを返す。

    The commits do not change, but the numerical libraries can, so the folder
    is named by both (`bundle_cache.fingerprint_of`).
    コミットは変わらないが数値計算ライブラリは変わりうるので、フォルダ名は両方から
    作る（`bundle_cache.fingerprint_of`）。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import bundle_cache
    import doc_excerpts
    digests = doc_excerpts.code_symbol_digests(Path(__file__).read_text(encoding="utf-8"))
    runners = ("run_era", "run_segmenter", "run_skeletonizer", "run_kink_detector",
               "run_polyline_rule", "run_synthetic_tophat")
    code = {"eras": dict(ERAS), "runner": {name: digests[name] for name in runners}}
    current = bundle_cache.fingerprint_of(code, bundle_cache.library_versions())
    return bundle_cache.cache_root(CACHE_BASE, current=current)


def _analyzed(cache: Path, commit: str, scan_key: str, scan_path: str,
              bg_method: str = "") -> Path:
    """
    Return the cached arrays of one version on one scan, analyzing when missing.
    1 つの版を 1 スキャンに実行した配列をキャッシュから返す。無ければ解析する。
    """
    out = cache / f"{commit[:12]}_{scan_key}_{bg_method or 'default'}.npz"
    if not out.is_file():
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-era",
                        str(_source(commit)), str(ROOT / scan_path), str(out), bg_method],
                       cwd=ROOT, check=True)
    return out


def _segmented(cache: Path, commit: str, scan_key: str, scan_path: str,
               calibration: str = ERAS[-1][1]) -> Path:
    """
    Return one version's mask of a scan's default calibration, from the cache.
    スキャンを既定で補正した画像に 1 つの版の二値化をかけたマスクを返す。

    The calibration is that of the commit `calibration`, the newest version's
    unless given.
    補正はコミット `calibration` のもので、指定がなければ最新版のものである。
    """
    suffix = "" if calibration == ERAS[-1][1] else f"_on_{calibration[:12]}"
    out = cache / f"{commit[:12]}_{scan_key}_segmented{suffix}.npz"
    if not out.is_file():
        calibrated = _analyzed(cache, calibration, scan_key, scan_path)
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-segmenter",
                        str(_source(commit)), str(calibrated), str(out)],
                       cwd=ROOT, check=True)
    return out


def _skeletonized(cache: Path, commit: str, scan_key: str, scan_path: str) -> Path:
    """
    Return one version's skeleton of the newest version's calibration and mask.
    最新版の補正後の画像とマスクに 1 つの版のスケルトン化をかけた結果を返す。
    """
    out = cache / f"{commit[:12]}_{scan_key}_skeletonized.npz"
    if not out.is_file():
        calibrated = _analyzed(cache, ERAS[-1][1], scan_key, scan_path)
        binarized = _segmented(cache, ERAS[-1][1], scan_key, scan_path)
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-skeletonizer",
                        str(_source(commit)), str(calibrated), str(binarized), str(out)],
                       cwd=ROOT, check=True)
    return out


# The commits between 1.0.0 and 2.0.0 that changed the skeleton, each as
# (label, commit before, commit), oldest first; §3 shows one column per change.
# 1.0.0 から 2.0.0 の間でスケルトンを変えたコミット。各要素は
# (ラベル, 直前のコミット, そのコミット) で、古い順。§3 は変更ごとに 1 列を示す。
SKELETON_CHANGES = (
    ("loops, spurs (7eb6199)", "06678b36aee9d02821d6cd994eb4880f3ce99e13",
     "7eb61994edc55f1b77adb9a38385a0be51570b59"),
    ("scan border (15368e3)", "21e8ed5c5de76dd43cbf11d2d23ff79c28f767da",
     "15368e335c25dc1f2ae9f812696bed95075e0d97"),
    ("branch tips (3a2415d)", "6942456c173d439c5cbd943c90f8b3f692a9cab3",
     "3a2415ded4fc80705cef16b4cf0dee6583c4e764"),
    ("end hooks (af4f501)", "104c184006503b3b3346491a4225c7664d7b4e23",
     "af4f5018fc9140fd00bbb88a1e00fa11777f1af5"),
)


def figure_skeletonization(cache: Path, out_dir: Path, dpi: int, lang: str = "en") -> None:
    """
    Draw what each change of `SKELETON_CHANGES` did to the skeleton.
    `SKELETON_CHANGES` の各変更がスケルトンをどう変えたかを描く。

    One row per scan and one column per change, all on the same calibrated
    image and mask (`_skeletonized`). Each panel shows the skeleton after the
    change in blue over the grey height image, the pixels the change added in
    green and those it removed in magenta, circled because at the size of a
    whole scan they are a few pixels across. Lines are drawn three pixels wide
    so that a one-pixel skeleton survives the reduction.
    スキャンごとに 1 段、変更ごとに 1 列で、どれも同じ補正後の画像とマスクを使う
    （`_skeletonized`）。各パネルは、変更後のスケルトンを灰色の高さ画像の上に青で、
    その変更が加えた画素を緑で、取り除いた画素をマゼンタで示し、スキャン全体の大きさ
    では数画素にしかならないため円で囲む。1 画素のスケルトンが縮小で消えないよう、
    線は 3 画素の幅で描く。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy import ndimage

    widen = np.ones((3, 3), dtype=bool)
    fig, axes = plt.subplots(len(SCANS), len(SKELETON_CHANGES),
                             figsize=(11 * len(SKELETON_CHANGES), 11.5 * len(SCANS)),
                             gridspec_kw={"wspace": 0.04, "hspace": 0.1}, squeeze=False)
    for r, (scan_key, scan_path, title) in enumerate(SCANS):
        calibrated = np.load(_analyzed(cache, ERAS[-1][1], scan_key, scan_path))["calibrated"]
        hi = float(np.percentile(calibrated, 99.5))
        grey = np.clip((calibrated + 0.5) / (hi + 0.5), 0.0, 1.0)
        for j, (label, before_commit, after_commit) in enumerate(SKELETON_CHANGES):
            before, after = (np.load(_skeletonized(cache, c, scan_key, scan_path))["skeleton"]
                             for c in (before_commit, after_commit))
            rgb = np.dstack([grey] * 3) * 0.7
            rgb[ndimage.binary_dilation(after, widen)] = (0.30, 0.55, 1.00)
            added, removed = after & ~before, before & ~after
            rgb[ndimage.binary_dilation(removed, widen)] = (1.0, 0.0, 1.0)
            rgb[ndimage.binary_dilation(added, widen)] = (0.0, 0.88, 0.0)
            axes[r, j].imshow(rgb)
            if r == 0:
                axes[r, j].set_title(label, fontsize=30)
            if j == 0:
                axes[r, j].set_ylabel(title, fontsize=30)
            changed, _count = ndimage.label(added | removed, structure=np.ones((3, 3)))
            for piece in ndimage.find_objects(changed):
                cy = (piece[0].start + piece[0].stop) / 2
                cx = (piece[1].start + piece[1].stop) / 2
                radius = max(25.0, 0.7 * max(piece[0].stop - piece[0].start,
                                             piece[1].stop - piece[1].start))
                axes[r, j].add_patch(plt.Circle((cx, cy), radius, fill=False,
                                                edgecolor="#ffd000", linewidth=3))
    for ax in axes.ravel():
        ax.set_xticks([])
        ax.set_yticks([])
    from matplotlib.lines import Line2D
    _legend(fig, [
        Line2D([], [], color=(0.30, 0.55, 1.00), linewidth=6, label=LABELS[lang]["skeleton_after"]),
        Line2D([], [], color=(0.0, 0.88, 0.0), linewidth=6, label=LABELS[lang]["pixels_added"]),
        Line2D([], [], color=(1.0, 0.0, 1.0), linewidth=6, label=LABELS[lang]["pixels_removed"]),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor="#ffd000", markeredgewidth=4, label=LABELS[lang]["changed_place"]),
    ], 4)
    path = _figure_path(out_dir, "skeletonization", lang)
    _save(fig, path, dpi)
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def _kinked(cache: Path, commit: str, scan_key: str, scan_path: str,
            centerline_method: str = "") -> Path:
    """
    Return one version's kinks and lines on the newest version's calibration and skeleton.
    最新版の補正後の画像とスケルトンに 1 つの版のキンク検出をかけた結果を返す。

    `centerline_method` chooses the line kinks are judged on, as
    ``ProcParams.centerline_method``; empty keeps the version's default.
    `centerline_method` はキンクを判定する線を ``ProcParams.centerline_method`` と
    同じく選ぶ。空ならその版の既定。
    """
    suffix = f"_{centerline_method}" if centerline_method else ""
    out = cache / f"{commit[:12]}_{scan_key}_kinks{suffix}.npz"
    if not out.is_file():
        calibrated = _analyzed(cache, ERAS[-1][1], scan_key, scan_path)
        skeleton = _skeletonized(cache, ERAS[-1][1], scan_key, scan_path)
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-kinks",
                        str(_source(commit)), str(calibrated), str(skeleton), str(out),
                        centerline_method], cwd=ROOT, check=True)
    return out


def _polylined(cache: Path, rule_commit: str, scan_key: str, scan_path: str,
               centerline_method: str = "") -> Path:
    """
    Return the kinks `rule_commit`'s polyline rule finds on the newest version's lines.
    最新版の線に `rule_commit` の折れ線規則を当てたキンクを返す。

    The lines are those the newest version judges on with `centerline_method`
    (`_kinked`).
    線は、最新版が `centerline_method` で判定する線である（`_kinked`）。
    """
    suffix = f"_{centerline_method}" if centerline_method else ""
    out = cache / f"{rule_commit[:12]}_{scan_key}_polyline{suffix}.npz"
    if not out.is_file():
        lines = _kinked(cache, ERAS[-1][1], scan_key, scan_path, centerline_method)
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-polyline",
                        str(_source(rule_commit)), str(lines), str(out)], cwd=ROOT, check=True)
    return out


# The line of the newest version that holds the skeleton pixels themselves
# (``centerline.SKELETON_PIXEL_LINE``), against which §4.1 compares the default.
# 最新版で、スケルトンの画素そのものを線とする選択（``centerline.SKELETON_PIXEL_LINE``）。
# §4.1 はこれと既定の線を比べる。
SKELETON_PIXEL_LINE = "skeleton_pixels"


# Section names of the bundled scans in the kink marks (docs/data/*_kink_marks.csv).
# キンクの印（docs/data/*_kink_marks.csv）での同梱スキャンの節名。
MARK_SCAN_NAMES = {"tunicate": "tunicate", "higherplant": "hplantTOC", "ndtoc": "NDTOC"}


def _both_marks(a, b, w: float) -> list:
    """
    Combine two people's marks into the reference of marks both call clear.
    2 人の印を、2 人とも明瞭とした印の基準にまとめる。

    As in ``docs/validation.md`` §4.19: marks pair one to one within `w`,
    nearest first; a pair both call clear is a clear mark at its midpoint, and
    every other mark of either person is ambiguous.
    ``docs/validation.ja.md`` §4.19 と同じく、印を `w` 以内で近いものから 1 対 1 に
    組み、2 人とも明瞭とした組をその中点の明瞭な印とし、それ以外の印はすべて曖昧と
    する。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs
    pairs = krs.match_marks(a, b, w)
    paired_a = {i for i, _j, _d in pairs}
    paired_b = {j for _i, j, _d in pairs}
    both = [dict(kind="clear" if a[i]["kind"] == b[j]["kind"] == "clear" else "ambiguous",
                 x=(a[i]["x"] + b[j]["x"]) / 2, y=(a[i]["y"] + b[j]["y"]) / 2)
            for i, j, _d in pairs]
    both += [dict(kind="ambiguous", x=r["x"], y=r["y"]) for i, r in enumerate(a) if i not in paired_a]
    both += [dict(kind="ambiguous", x=r["x"], y=r["y"]) for j, r in enumerate(b) if j not in paired_b]
    return both


def kink_scores(cache: Path, commits) -> dict:
    """
    Score each commit's kinks against the two people's marks, per scan.
    各コミットのキンクを、2 人の印に対してスキャンごとに採点する。

    Uses the matching of `scripts/kink_reference_score.py` (`score`,
    `match_marks`) against the three references of ``docs/validation.md``
    §4.19: A's marks, B's marks, and the marks both call clear. Every kink of
    every version is matched within the scan's median apparent width W as the
    newest version measures it, because a version that judges on the skeleton
    reports no width.
    `scripts/kink_reference_score.py` の照合（`score`、`match_marks`）を使い、
    ``docs/validation.ja.md`` §4.19 の 3 つの基準（A の印、B の印、2 人とも明瞭と
    した印）に対して採点する。スケルトン上で判定する版は幅を報告しないため、どの版の
    キンクも、最新版が測ったスキャンの見かけ幅の中央値 W 以内で照合する。

    An entry of `commits` may instead be a function of (scan key, scan path)
    returning the ``.npz`` of the kinks to score.
    `commits` の要素は、代わりに (スキャンのキー, スキャンのパス) から採点するキンクの
    ``.npz`` を返す関数でもよい。

    Returns
    -------
    dict
        (commit, scan key, reference) -> the counts of `score`, with
        ``detections`` added.
        (コミット, スキャンのキー, 基準) -> `score` の数え上げに ``detections`` を
        加えたもの。
    """
    import numpy as np
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs

    human = krs.load_human_reference()
    out = {}
    for scan_key, scan_path, _title in SCANS:
        w = float(np.load(_kinked(cache, ERAS[-1][1], scan_key, scan_path))["width_px"])
        a, b = human[MARK_SCAN_NAMES[scan_key]]["A"], human[MARK_SCAN_NAMES[scan_key]]["B"]
        both = _both_marks(a, b, w)
        for commit in commits:
            data = (np.load(_kinked(cache, commit, scan_key, scan_path))
                    if isinstance(commit, str) else np.load(commit(scan_key, scan_path)))
            xy = data["kinks"]
            angles = data["angles"] if "angles" in data else np.full(xy.shape[1], np.nan)
            kinks = [dict(x=float(x), y=float(y), w=w, angle=float(a))
                     for x, y, a in zip(xy[0], xy[1], angles)]
            for name, refs in (("A", a), ("B", b), ("both", both)):
                counts = krs.score(refs, kinks, [])
                counts["detections"] = len(kinks)
                out[(commit, scan_key, name)] = counts
    return out


# The commits after 2.0.0 that change the kinks or the centerline on the
# bundled scans, oldest first; §4.2 scores each.
# 2.0.0 の後で、同梱スキャンのキンクまたは中心線を変えたコミット（古い順）。§4.2 が
# それぞれを採点する。
KINK_CHANGES = (
    "491750ce282831e4380b67bb9e68cbfec49a631b",
    "5d493c4d35bdf07684445ca0411bc8ef9e2745a6",
    "d5460ea0e331650f19f4c921110dd44fad8092ee",
    "04760880a671ec8cea76b1bdee7e10184e299c96",
    "766649305032ab0ea812043310dba2481d6e2523",
)


def figure_centerline(cache: Path, out_dir: Path, dpi: int, lang: str = "en") -> None:
    """
    Draw the skeleton and the half-maximum centerline of one fiber per scan, enlarged.
    スキャンごとに 1 本のファイバーのスケルトンと半値中心線を拡大して描く。

    The fiber is chosen by rule, not by eye: the centerline of the newest
    version that has the most marks both people call clear within the scan's
    median apparent width. The left panel shows the skeleton pixels, which
    1.0.0 judged, with the kinks of 1.0.0; the right one the centerline with
    the kinks of the newest version. Marks both people call clear are yellow
    crosses; a kink is green when it matches one of them or lies near another
    of their marks, and magenta when it matches no mark (`kink_scores`).
    ファイバーは目で選ばず、規則で選ぶ。最新版の中心線のうち、スキャンの見かけ幅の
    中央値以内に、2 人とも明瞭とした印を最も多く持つものである。左のパネルは 1.0.0 が
    判定したスケルトンの画素と 1.0.0 のキンク、右のパネルは中心線と最新版のキンクを
    示す。2 人とも明瞭とした印は黄色の × で、キンクはそれらの印に対応するか 2 人の他の
    印の近くにあれば緑、どの印にも対応しなければマゼンタで描く（`kink_scores`）。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs

    old, new = ERAS[0][1], ERAS[-1][1]
    scores = kink_scores(cache, [old, new])
    human = krs.load_human_reference()
    fig, axes = plt.subplots(len(SCANS), 2, figsize=(22, 11.5 * len(SCANS)),
                             gridspec_kw={"wspace": 0.04, "hspace": 0.12}, squeeze=False)
    for r, (scan_key, scan_path, title) in enumerate(SCANS):
        calibrated = np.load(_analyzed(cache, new, scan_key, scan_path))["calibrated"]
        skeleton = np.load(_skeletonized(cache, new, scan_key, scan_path))["skeleton"]
        lines = np.load(_kinked(cache, new, scan_key, scan_path))
        width = float(lines["width_px"])
        names = MARK_SCAN_NAMES[scan_key]
        clear = [m for m in _both_marks(human[names]["A"], human[names]["B"], width)
                 if m["kind"] == "clear"]
        best, best_count = None, -1
        for line in np.unique(lines["line_id"]):
            on = lines["line_id"] == line
            points = np.column_stack([lines["line_x"][on], lines["line_y"][on]])
            count = sum(np.hypot(*(points - (m["x"], m["y"])).T).min() <= width for m in clear)
            if count > best_count:
                best, best_count = line, count
        on = lines["line_id"] == best
        x0 = max(0, int(lines["line_x"][on].min()) - 15)
        x1 = min(calibrated.shape[1], int(lines["line_x"][on].max()) + 16)
        y0 = max(0, int(lines["line_y"][on].min()) - 15)
        y1 = min(calibrated.shape[0], int(lines["line_y"][on].max()) + 16)
        hi = float(np.percentile(calibrated, 99.5))
        for j, (label, commit) in enumerate(((f"{ERAS[0][0]}   {LABELS[lang]['skeleton_pixels']}", old),
                                             (f"{ERAS[-1][0]}   {LABELS[lang]['centerline']}", new))):
            ax = axes[r, j]
            ax.imshow(calibrated, cmap="gray", vmin=-0.5, vmax=hi, interpolation="nearest")
            if commit == old:
                ys, xs = np.nonzero(skeleton[y0:y1, x0:x1])
                ax.plot(xs + x0, ys + y0, "s", markersize=4, color="#4a8cff")
            else:
                for line in np.unique(lines["line_id"]):
                    part = lines["line_id"] == line
                    ax.plot(lines["line_x"][part], lines["line_y"][part], color="#4a8cff", linewidth=2.5)
            for m in clear:
                ax.plot(m["x"], m["y"], "x", markersize=16, markeredgewidth=4, color="#ffd000")
            unmatched = {(k["x"], k["y"]) for k in scores[(commit, scan_key, "both")]["false_list"]}
            xy = np.load(_kinked(cache, commit, scan_key, scan_path))["kinks"]
            for x, y in zip(xy[0], xy[1]):
                colour = "#ff00ff" if (float(x), float(y)) in unmatched else "#00e000"
                ax.plot(x, y, "o", markersize=13, markerfacecolor=colour,
                        markeredgecolor="black", markeredgewidth=1)
            ax.set_xlim(x0 - 0.5, x1 - 0.5)
            ax.set_ylim(y1 - 0.5, y0 - 0.5)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(label, fontsize=26)
            if j == 0:
                ax.set_ylabel(title, fontsize=26)
                ax.set_xlabel(LABELS[lang]["location"].format(y0=y0, y1=y1, x0=x0, x1=x1), fontsize=20)
    from matplotlib.lines import Line2D
    _legend(fig, [
        Line2D([], [], linestyle="", marker="s", markersize=10, color="#4a8cff",
               label=LABELS[lang]["skeleton_pixels"]),
        Line2D([], [], color="#4a8cff", linewidth=4, label=LABELS[lang]["centerline"]),
        Line2D([], [], linestyle="", marker="x", markersize=18, markeredgewidth=4,
               color="#ffd000", label=LABELS[lang]["clear_mark"]),
        *_kink_handles(lang),
    ], 1)
    path = _figure_path(out_dir, "centerline", lang)
    _save(fig, path, dpi)
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def figure_kinks(cache: Path, out_dir: Path, dpi: int, lang: str = "en") -> None:
    """
    Draw every version's kinks on the line it judged them on, scored against the marks.
    各版のキンクを、それを判定した線の上に、印に対する採点とともに描く。

    One row per scan and one column per version, all on the same calibrated
    image and skeleton. The line is drawn in blue: the skeleton for a version
    that judges on it, the recorded centerlines otherwise. A kink that matches
    a mark both people call clear, or lies near one of their other marks, is
    drawn green; a kink that matches no mark magenta; and a clear mark the
    version missed is ringed in yellow (`kink_scores`, reference ``both``).
    スキャンごとに 1 段、版ごとに 1 列で、どれも同じ補正後の画像とスケルトンを使う。
    線は青で描く。スケルトン上で判定する版はスケルトン、それ以外は記録した中心線で
    ある。2 人とも明瞭とした印に対応するキンク、または 2 人の他の印の近くにあるキンクは
    緑、どの印にも対応しないキンクはマゼンタで描き、その版が見落とした明瞭な印を黄色の
    輪で囲む（`kink_scores`、基準 ``both``）。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    commits = [commit for _label, commit in ERAS]
    scores = kink_scores(cache, commits)
    fig, axes = plt.subplots(len(SCANS), len(ERAS), figsize=(11 * len(ERAS), 11.5 * len(SCANS)),
                             gridspec_kw={"wspace": 0.04, "hspace": 0.1}, squeeze=False)
    for r, (scan_key, scan_path, title) in enumerate(SCANS):
        calibrated = np.load(_analyzed(cache, ERAS[-1][1], scan_key, scan_path))["calibrated"]
        skeleton = np.load(_skeletonized(cache, ERAS[-1][1], scan_key, scan_path))["skeleton"]
        hi = float(np.percentile(calibrated, 99.5))
        for j, (label, commit) in enumerate(ERAS):
            ax = axes[r, j]
            ax.imshow(calibrated, cmap="gray", vmin=-0.5, vmax=hi)
            data = np.load(_kinked(cache, commit, scan_key, scan_path))
            if data["line_x"].size:
                for line in np.unique(data["line_id"]):
                    on = data["line_id"] == line
                    ax.plot(data["line_x"][on], data["line_y"][on], color="#4a8cff", linewidth=1.2)
            else:
                ys, xs = np.nonzero(skeleton)
                ax.plot(xs, ys, ",", color="#4a8cff")
            counts = scores[(commit, scan_key, "both")]
            unmatched = {(k["x"], k["y"]) for k in counts["false_list"]}
            xy = data["kinks"]
            for x, y in zip(xy[0], xy[1]):
                colour = "#ff00ff" if (float(x), float(y)) in unmatched else "#00e000"
                ax.plot(x, y, "o", markersize=9, markerfacecolor=colour,
                        markeredgecolor="black", markeredgewidth=0.8)
            for mark in counts["missed_list"]:
                ax.add_patch(plt.Circle((mark["x"], mark["y"]), 16, fill=False,
                                        edgecolor="#ffd000", linewidth=3))
            ax.set_xlim(-0.5, calibrated.shape[1] - 0.5)
            ax.set_ylim(calibrated.shape[0] - 0.5, -0.5)
            if r == 0:
                ax.set_title(label, fontsize=30)
            if j == 0:
                ax.set_ylabel(title, fontsize=30)
    for ax in axes.ravel():
        ax.set_xticks([])
        ax.set_yticks([])
    from matplotlib.lines import Line2D
    _legend(fig, [
        Line2D([], [], color="#4a8cff", linewidth=4,
               label=LABELS[lang]["judged_line"]),
        *_kink_handles(lang),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor="#ffd000", markeredgewidth=4,
               label=LABELS[lang]["missed_mark"]),
    ], 2)
    path = _figure_path(out_dir, "kinks", lang)
    _save(fig, path, dpi)
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def figure_background(cache: Path, out_dir: Path, dpi: int, bg_method: str = "") -> None:
    """
    Draw one background method of every version, one figure per scan.
    各版の 1 つの背景補正方式を、スキャンごとに 1 枚の図に描く。

    The top row shows the raw scan and the calibrated images at the GUI's
    automatic display range of the newest version's result, shared by all
    versions; the bottom row shows the calibrated images at
    `BACKGROUND_RANGE_NM`, where what is left of the background is visible.
    上の段は生のスキャンと、補正後の画像を最新版の結果に対する GUI の自動表示範囲で
    描き、全版で共有する。下の段は補正後の画像を `BACKGROUND_RANGE_NM` で描き、背景の
    残りを見えるようにする。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    sys.path.insert(0, str(ROOT))
    from lib.ui_tools import compute_auto_vrange

    for scan_key, scan_path, title in SCANS:
        data = [(label, np.load(_analyzed(cache, commit, scan_key, scan_path, bg_method)))
                for label, commit in ERAS]
        raw = data[-1][1]["original"]
        vmin, vmax = compute_auto_vrange(data[-1][1]["calibrated"])
        rmin, rmax = compute_auto_vrange(raw)
        lo, hi = BACKGROUND_RANGE_NM
        fig, axes = plt.subplots(2, len(ERAS) + 1, figsize=(11 * (len(ERAS) + 1), 22.5),
                                 gridspec_kw={"wspace": 0.04, "hspace": 0.08})
        im = axes[0, 0].imshow(raw, cmap="afmhot", vmin=rmin, vmax=rmax)
        axes[0, 0].set_title(f"raw   [{rmin:g}, {rmax:g}] nm", fontsize=34)
        cbar = fig.colorbar(im, ax=axes[0, 0], fraction=0.046, pad=0.02, location="left")
        cbar.ax.tick_params(labelsize=22)
        axes[1, 0].axis("off")
        axes[1, 0].text(0.5, 0.5, f"A   [{vmin:g}, {vmax:g}] nm\n\nB   [{lo:g}, {hi:g}] nm",
                        ha="center", va="center", fontsize=40, transform=axes[1, 0].transAxes)
        for j, (label, arrays) in enumerate(data, start=1):
            name = f"{label} ({arrays['bg_method']})"
            top = axes[0, j].imshow(arrays["calibrated"], cmap="afmhot", vmin=vmin, vmax=vmax)
            axes[0, j].set_title(f"A   {name}", fontsize=34)
            bottom = axes[1, j].imshow(arrays["calibrated"], cmap="afmhot", vmin=lo, vmax=hi)
            axes[1, j].set_title(f"B   {name}", fontsize=34)
        for row, img in ((0, top), (1, bottom)):
            cbar = fig.colorbar(img, ax=list(axes[row, 1:]), fraction=0.012, pad=0.01)
            cbar.set_label("height (nm)", fontsize=26)
            cbar.ax.tick_params(labelsize=22)
        for ax in axes.ravel():
            ax.set_xticks([])
            ax.set_yticks([])
        fig.suptitle(title, fontsize=40)
        path = _figure_path(out_dir, f"background_{bg_method or 'default'}_{scan_key}")
        _save(fig, path, dpi)
        plt.close(fig)
        print(f"wrote {path.relative_to(ROOT)}")


# Labels of the figures whose legends explain what they show, per language;
# ``docs/history.ja.md`` shows the ``.ja`` versions. Version names, commit
# names, scan names and units stay as they are in both documents.
# 何を示すかを凡例で説明する図のラベル（言語ごと）。``docs/history.ja.md`` は
# ``.ja`` の付いた版を示す。版の名前、コミット名、スキャン名、単位は両文書と同じままにする。
LABELS = {
    "en": {
        "mask": "binarized mask",
        "added_component": "component added to the column before",
        "removed_component": "component removed from the column before",
        "skeleton_after": "skeleton after the change",
        "pixels_added": "pixels the change added",
        "pixels_removed": "pixels the change removed",
        "changed_place": "place that changed",
        "judged_line": "line the kinks are judged on (1.0.0: skeleton pixels)",
        "kink_at_mark": "kink at a mark both authors call clear, or near another of their marks",
        "kink_no_mark": "kink matching no mark",
        "missed_mark": "mark both authors call clear, missed",
        "clear_mark": "mark both authors call clear",
        "skeleton_pixels": "skeleton pixels",
        "centerline": "half-maximum centerline",
        "location": "rows {y0}-{y1}, columns {x0}-{x1}",
    },
    "ja": {
        "mask": "二値化のマスク",
        "added_component": "前の列に対して加わった成分",
        "removed_component": "前の列に対して取り除かれた成分",
        "skeleton_after": "変更後のスケルトン",
        "pixels_added": "変更で加わった画素",
        "pixels_removed": "変更で取り除かれた画素",
        "changed_place": "変わった場所",
        "judged_line": "キンクを判定する線（1.0.0 はスケルトンの画素）",
        "kink_at_mark": "2 人とも明瞭とした印に対応するキンク、または 2 人の他の印の近くのキンク",
        "kink_no_mark": "どの印にも対応しないキンク",
        "missed_mark": "見落とした、2 人とも明瞭とした印",
        "clear_mark": "2 人とも明瞭とした印",
        "skeleton_pixels": "スケルトンの画素",
        "centerline": "半値中心線",
        "location": "行 {y0}-{y1}、列 {x0}-{x1}",
    },
}

# Japanese fonts tried in order, as in ``scripts/make_doc_figures.py``.
# 試す日本語フォントの順。``scripts/make_doc_figures.py`` と同じ。
JAPANESE_FONTS = ("Meiryo", "Yu Gothic", "MS Gothic", "Noto Sans CJK JP", "IPAexGothic")


def _font_context(lang: str) -> dict:
    """
    Return the Matplotlib settings that draw `lang`'s labels.
    `lang` のラベルを描く Matplotlib の設定を返す。
    """
    if lang != "ja":
        return {}
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next((name for name in JAPANESE_FONTS if name in available), None)
    if family is None:
        raise RuntimeError("no Japanese font found for the Japanese figures")
    return {"font.family": family}


# Figures kept as PNG in the documents; every other reduced figure is a JPEG.
# The scan noise keeps a PNG of a whole scan near 2 MB. A JPEG at quality 92
# with full-resolution colour (no chroma subsampling) is a third to a half of
# that and could not be told from the PNG at seven times magnification, while
# WebP, which always halves the colour resolution, blurred the thin coloured
# lines and markers. The enlarged centerline figure has little noise and is
# smaller as a PNG.
# 文書で PNG のままにする図。それ以外の縮小版は JPEG にする。スキャンのノイズのため、
# スキャン全体の PNG は 2 MB 近くになる。色を間引かない（クロマサブサンプリングなし）
# 品質 92 の JPEG はその 3 分の 1 から半分で、7 倍に拡大しても PNG と見分けられ
# なかった。色の解像度を必ず半分にする WebP は、細い色付きの線や印をにじませた。
# 中心線の拡大図はノイズが少なく、PNG のほうが小さい。
PNG_FIGURES = ("centerline",)
JPEG_OPTIONS = {"quality": 92, "subsampling": 0, "optimize": True}


def _figure_path(out_dir: Path, name: str, lang: str = "en") -> Path:
    """
    Return the file of figure `name` in `lang` (``.ja`` before the suffix for Japanese).
    言語 `lang` の図 `name` のファイルを返す（日本語は拡張子の前に ``.ja``）。

    The full-resolution figures of ``--full`` are PNG; the reduced ones are
    JPEG unless listed in `PNG_FIGURES`.
    ``--full`` の原寸版は PNG とし、縮小版は `PNG_FIGURES` にあるもの以外は JPEG とする。
    """
    suffix = "png" if out_dir == FULL_DIR or name in PNG_FIGURES else "jpg"
    return out_dir / (f"{name}.ja.{suffix}" if lang == "ja" else f"{name}.{suffix}")


def _save(fig, path: Path, dpi: int) -> None:
    """
    Write a figure to `path`, with `JPEG_OPTIONS` for a JPEG.
    図を `path` に書き出す。JPEG なら `JPEG_OPTIONS` を使う。
    """
    options = {"pil_kwargs": JPEG_OPTIONS} if path.suffix == ".jpg" else {}
    fig.savefig(path, dpi=dpi, bbox_inches="tight", **options)


def _legend(fig, handles, columns: int) -> None:
    """
    Put a legend below the panels, so it never covers an image.
    凡例をパネルの下に置き、画像に重ならないようにする。
    """
    bottom = min(ax.get_position().y0 for ax in fig.axes if ax.get_visible() and ax.axison)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, bottom - 0.01),
               ncol=columns, fontsize=26, frameon=False, handlelength=2.5,
               columnspacing=2.5)


def _kink_handles(lang: str):
    """
    Return the legend entries of the kink markers and the marks.
    キンクの印と人の印の凡例項目を返す。
    """
    from matplotlib.lines import Line2D
    return [
        Line2D([], [], linestyle="", marker="o", markersize=16, markerfacecolor="#00e000",
               markeredgecolor="black", label=LABELS[lang]["kink_at_mark"]),
        Line2D([], [], linestyle="", marker="o", markersize=16, markerfacecolor="#ff00ff",
               markeredgecolor="black", label=LABELS[lang]["kink_no_mark"]),
    ]


def figure_binarization(cache: Path, out_dir: Path, dpi: int, lang: str = "en") -> None:
    """
    Draw every version's binarized mask of the same calibrated images.
    同じ補正後の画像に対する各版の二値化マスクを描く。

    One row per scan: the calibrated image of the newest version in grey, then
    one panel per distinct mask, versions whose masks are identical sharing a
    panel. A mask is drawn in blue over the grey image, and the components a
    version adds to the previous distinct mask are circled in green, or in
    magenta for those it removes, because at the size of a whole scan such a
    component is a few pixels across.
    スキャンごとに 1 段で、最新版の補正後の画像を灰色で示し、続けて異なるマスクごとに
    1 枚を並べる。マスクが同一の版は 1 枚を共有する。マスクは灰色の画像の上に青で描き、
    1 つ前の異なるマスクに対してその版が加えた成分を緑の円で、取り除いた成分を
    マゼンタの円で囲む。スキャン全体の大きさでは、そのような成分は数画素にしかならない
    ためである。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy import ndimage

    rows = []
    for scan_key, scan_path, title in SCANS:
        calibrated = np.load(_analyzed(cache, ERAS[-1][1], scan_key, scan_path))["calibrated"]
        groups = []
        for label, commit in ERAS:
            mask = np.load(_segmented(cache, commit, scan_key, scan_path))["binarized"]
            if groups and np.array_equal(groups[-1][1], mask):
                groups[-1][0].append(label)
            else:
                groups.append(([label], mask))
        rows.append((title, calibrated, groups))
    n_cols = 1 + max(len(groups) for _, _, groups in rows)
    fig, axes = plt.subplots(len(rows), n_cols, figsize=(11 * n_cols, 11.5 * len(rows)),
                             gridspec_kw={"wspace": 0.04, "hspace": 0.1}, squeeze=False)
    blue = np.array([0.30, 0.55, 1.00])
    for r, (title, calibrated, groups) in enumerate(rows):
        hi = float(np.percentile(calibrated, 99.5))
        grey = np.clip((calibrated + 0.5) / (hi + 0.5), 0.0, 1.0)
        axes[r, 0].imshow(grey, cmap="gray", vmin=0.0, vmax=1.0)
        axes[r, 0].set_title(f"{title}   [-0.5, {hi:.1f}] nm", fontsize=30)
        previous = None
        for j, (labels, mask) in enumerate(groups, start=1):
            rgb = np.dstack([grey] * 3) * 0.85
            rgb[mask] = 0.45 * rgb[mask] + 0.55 * blue
            axes[r, j].imshow(rgb)
            axes[r, j].set_title(", ".join(labels), fontsize=30)
            if previous is not None:
                for changed, colour in ((mask & ~previous, "#00e000"), (previous & ~mask, "#ff00ff")):
                    labelled, count = ndimage.label(changed, structure=np.ones((3, 3)))
                    for piece in ndimage.find_objects(labelled):
                        cy = (piece[0].start + piece[0].stop) / 2
                        cx = (piece[1].start + piece[1].stop) / 2
                        radius = max(30.0, 0.7 * max(piece[0].stop - piece[0].start,
                                                     piece[1].stop - piece[1].start))
                        axes[r, j].add_patch(plt.Circle((cx, cy), radius, fill=False,
                                                        edgecolor=colour, linewidth=4))
            previous = mask
        for j in range(len(groups) + 1, n_cols):
            axes[r, j].axis("off")
    for ax in axes.ravel():
        ax.set_xticks([])
        ax.set_yticks([])
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    _legend(fig, [
        Patch(facecolor=blue, label=LABELS[lang]["mask"]),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor="#00e000", markeredgewidth=4,
               label=LABELS[lang]["added_component"]),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor="#ff00ff", markeredgewidth=4,
               label=LABELS[lang]["removed_component"]),
    ], 3)
    path = _figure_path(out_dir, "binarization", lang)
    _save(fig, path, dpi)
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def _row_offsets(image):
    """
    Return each row's median less a 31-row running median of those medians.
    各行の中央値から、その 31 行の移動中央値を引いた値を返す。

    What is left is the line-to-line offset, without the slow change of the
    background over many rows.
    残るのは走査線ごとのずれで、多くの行にわたる背景のゆっくりした変化は含まない。
    """
    import numpy as np
    from scipy.ndimage import median_filter
    rows = np.median(image, axis=1)
    return rows - median_filter(rows, size=31, mode="nearest")


def run_synthetic_tophat(src: str) -> None:
    """
    Run one version's ``tophat`` on synthetic planes carrying line offsets.
    走査線のずれを載せた合成平面に、1 つの版の ``tophat`` を実行する。

    The offsets are white noise smoothed over three rows (Gaussian sigma) and
    scaled to 0.05 nm standard deviation, with 0.02 nm pixel noise on top; the
    plane is flat or rises 0.27 nm/px along the rows, about the tilt of the
    tunicate scan. Prints the standard deviation of the offsets left in the
    calibrated image for each plane. Called in a separate process, as
    `run_era` is.
    ずれは白色雑音を 3 行（ガウスの σ）で平滑化し、標準偏差 0.05 nm にそろえたもので、
    その上に 0.02 nm の画素ノイズを載せる。平面は平らなものと、行に沿って 0.27 nm/px
    上がるもの（Tunicate のスキャンの傾きとほぼ同じ）である。平面ごとに、補正後の
    画像に残ったずれの標準偏差を表示する。`run_era` と同じく別プロセスで呼ばれる。
    """
    sys.path.insert(0, src)
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
    from lib import pipeline
    from lib.processed_image import ProcessedImage

    rng = np.random.default_rng(0)
    n = 512
    offsets = gaussian_filter1d(rng.normal(0.0, 1.0, n), 3.0)
    offsets *= 0.05 / offsets.std()
    noise = rng.normal(0.0, 0.02, (n, n))
    columns = np.arange(n, dtype=float)[None, :]
    for name, plane in (("flat", 0.0 * columns), ("rising along rows", 0.27 * columns)):
        image = ProcessedImage(original_AFM=plane + offsets[:, None] + noise, name="synthetic")
        pipeline.build_stages(pipeline.ProcParams(bg_method="tophat")).bg_calibrator(image)
        rows = np.median(image.calibrated_image, axis=1)
        print(f"    {name:18s} offsets put in {offsets.std():.3f} nm, "
              f"left {np.std(rows - np.median(rows)):.3f} nm")


def check_tophat_stripes(cache: Path) -> None:
    """
    Print the measurements behind §1.3 on the horizontal stripes of ``tophat``.
    ``tophat`` の横縞について §1.3 が述べることの裏付けとなる測定値を表示する。

    For the tunicate scan, the line offsets each version leaves and their
    correlation with the line offsets of the raw scan less a least-squares
    second-order surface; then the synthetic test of `run_synthetic_tophat`
    for 1.0.0 and 2.0.0.
    Tunicate のスキャンについて、各版が残す走査線のずれと、最小二乗の 2 次曲面を
    引いた生のスキャンの走査線のずれとの相関を表示し、続けて 1.0.0 と 2.0.0 について
    `run_synthetic_tophat` の合成試験を表示する。
    """
    import numpy as np
    scan_key, scan_path, _title = SCANS[0]
    arrays = {label: np.load(_analyzed(cache, commit, scan_key, scan_path, "tophat"))
              for label, commit in ERAS}
    raw = arrays[ERAS[-1][0]]["original"].astype(np.float64)[1:, 1:]
    yy, xx = np.mgrid[0:raw.shape[0], 0:raw.shape[1]].astype(np.float64)
    terms = np.stack([np.ones_like(xx), xx, yy, xx * xx, xx * yy, yy * yy], axis=-1).reshape(-1, 6)
    coef, *_ = np.linalg.lstsq(terms, raw.ravel(), rcond=None)
    raw_offsets = _row_offsets(raw - (terms @ coef).reshape(raw.shape))
    print("[1.3] tophat line offsets, tunicate scan (standard deviation, correlation with the raw scan's):")
    print(f"    raw scan less a second-order surface: {raw_offsets.std():.3f} nm")
    for label, data in arrays.items():
        offsets = _row_offsets(data["calibrated"])
        corr = np.corrcoef(offsets, raw_offsets)[0, 1]
        print(f"    {label:8s} {offsets.std():.3f} nm, correlation {corr:+.2f}")
    print("[1.3] tophat on synthetic planes with line offsets spanning a few rows:", flush=True)
    for label, commit in ERAS[:2]:
        print(f"  {label}", flush=True)
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run-synthetic",
                        str(_source(commit))], cwd=ROOT, check=True)


# Commits whose effect §1.2 and §2.2 attribute to them, with the commit before each.
# §1.2 と §2.2 が効果をそのコミットに帰する変更と、それぞれの直前のコミット。
SCAN_AXIS_FIBER_FIX = ("34079e55fa769362705df2f627b2efb234308ad6",
                       "e53ec487ae702b58a6f2deb226f5cca1b06b9f38")
LINEARITY_FIX = ("aa6f02bb971db1d28f038adaa7566a02a93fca27",
                 "3e678668bea7bae80c61e7ac4222213736b6dcf5")

# Pixel boxes (rows, columns) of the tunicate scan that §1.2 and §2.2 describe:
# the nearly vertical fiber at the right edge, and the faint branch at the left edge.
# §1.2 と §2.2 が述べる Tunicate のスキャンの画素範囲（行, 列）。右端でほぼ縦に走る
# ファイバーと、左端の淡い枝。
RIGHT_EDGE_FIBER_BOX = (slice(500, 545), slice(975, 1000))
LEFT_EDGE_BRANCH_BOX = (slice(660, 715), slice(0, 35))


def check_attributions(cache: Path) -> None:
    """
    Print the measurements behind the changes §1.2, §2.2 and §3 attribute to commits.
    §1.2、§2.2、§3 がコミットに帰する変化の裏付けとなる測定値を表示する。

    §1.2: the lowest calibrated height in `RIGHT_EDGE_FIBER_BOX` before and
    after `SCAN_AXIS_FIBER_FIX`. §2.2: whether the masks before and after
    `LINEARITY_FIX` equal those of 2.0.0 and c43409b on every scan, and how many
    pixels of `LEFT_EDGE_BRANCH_BOX` the binarization of 2.0.0 and of c43409b
    keep on the calibrated image of each version. §3: whether the skeletons
    of the same input are equal everywhere outside the commits of
    `SKELETON_CHANGES`, from 1.0.0 to c43409b.
    §1.2: `SCAN_AXIS_FIBER_FIX` の前後での `RIGHT_EDGE_FIBER_BOX` の補正後の高さの
    最小値。§2.2: `LINEARITY_FIX` の前後のマスクが全スキャンで 2.0.0 と c43409b の
    マスクに等しいか、および 2.0.0 と c43409b の二値化が各版の補正後の画像で
    `LEFT_EDGE_BRANCH_BOX` の画素をいくつ残すか。§3: 同じ入力のスケルトンが、
    1.0.0 から c43409b まで、`SKELETON_CHANGES` のコミットの外ではどこでも等しいか。
    """
    import numpy as np
    scan_key, scan_path, _title = SCANS[0]
    print("[1.2] lowest calibrated height in the right-edge fiber box, tunicate scan:")
    for role, commit in zip(("before", "after "), SCAN_AXIS_FIBER_FIX):
        calibrated = np.load(_analyzed(cache, commit, scan_key, scan_path))["calibrated"]
        print(f"    {role} {commit[:7]}: {calibrated[RIGHT_EDGE_FIBER_BOX].min():.2f} nm")
    print("[2.2] masks before / after the linearity fix against 2.0.0 / c43409b:")
    for key, path, _ in SCANS:
        before, after = (np.load(_segmented(cache, c, key, path))["binarized"] for c in LINEARITY_FIX)
        old, new = (np.load(_segmented(cache, c, key, path))["binarized"] for c in (ERAS[1][1], ERAS[-1][1]))
        print(f"    {key:12s} before == 2.0.0: {np.array_equal(before, old)}, "
              f"after == c43409b: {np.array_equal(after, new)}")
    print("[2.2] mask pixels in the left-edge branch box, tunicate scan:")
    for seg_label, seg_commit in ERAS[1:]:
        counts = []
        for cal_label, cal_commit in ERAS:
            mask = np.load(_segmented(cache, seg_commit, scan_key, scan_path, cal_commit))["binarized"]
            counts.append(f"{cal_label} {int(mask[LEFT_EDGE_BRANCH_BOX].sum())}")
        print(f"    binarization {seg_label} on calibration " + ", ".join(counts))
    print("[3] skeletons: does each step equal the next (1.0.0, the changes of SKELETON_CHANGES, 2.0.0, c43409b)?")
    for key, path, _ in SCANS:
        chain = [ERAS[0][1]]
        for _label, before_commit, after_commit in SKELETON_CHANGES:
            chain += [before_commit, after_commit]
        chain += [ERAS[1][1], ERAS[-1][1]]
        skeletons = [np.load(_skeletonized(cache, c, key, path))["skeleton"] for c in chain]
        # (1.0.0, first before), (each after, next before), (last after, 2.0.0)
        # and (2.0.0, c43409b): every pair except those inside a change.
        pairs = [(i, i + 1) for i in range(0, len(chain) - 2, 2)] + [(len(chain) - 2, len(chain) - 1)]
        unchanged = [np.array_equal(skeletons[i], skeletons[j]) for i, j in pairs]
        print(f"    {key:12s} outside the changes, equal: {all(unchanged)} ({unchanged})")
    print("[4] kinks against the two people's marks (scan's median W; found = found + found 1-2 W away):")
    commits = [commit for _label, commit in ERAS]
    scores = kink_scores(cache, commits)
    for reference in ("A", "B", "both"):
        for label, commit in ERAS:
            total = {key: sum(scores[(commit, k, reference)][key] for k, _p, _t in SCANS)
                     for key in ("ref", "found", "displaced", "merged", "missed", "false",
                                 "exempt", "detections")}
            per_scan = ", ".join(f"{k} {scores[(commit, k, reference)]['false']}" for k, _p, _t in SCANS)
            print(f"    {reference:4s} {label:8s} marks {total['ref']:3d}, kinks {total['detections']:3d}, "
                  f"found {total['found'] + total['displaced']:3d}, merged {total['merged']:2d}, "
                  f"missed {total['missed']:2d}, matching no mark {total['false']:3d} ({per_scan}), "
                  f"near a mark not clear {total['exempt']:2d}")
    print("[4.2] interior angle stored for the kinks of 1.0.0 and c43409b at the same clear mark:")
    old_version, new_version = ERAS[0][1], ERAS[-1][1]
    scores = kink_scores(cache, [old_version, new_version])
    differences, old_angles, new_angles = [], [], []
    for key, _p, _t in SCANS:
        by_mark = [{id(ref): kink["angle"] for ref, kink in scores[(c, key, "both")]["pairs"]}
                   for c in (old_version, new_version)]
        for mark in by_mark[0].keys() & by_mark[1].keys():
            old_angles.append(np.degrees(by_mark[0][mark]))
            new_angles.append(np.degrees(by_mark[1][mark]))
            differences.append(new_angles[-1] - old_angles[-1])
    if differences:
        q1, median, q3 = np.percentile(differences, [25, 50, 75])
        print(f"    {len(differences)} marks; median angle 1.0.0 {np.median(old_angles):.1f} deg, "
              f"c43409b {np.median(new_angles):.1f} deg; difference c43409b - 1.0.0: "
              f"median {median:+.1f}, quartiles {q1:+.1f} to {q3:+.1f}, "
              f"range {min(differences):+.1f} to {max(differences):+.1f} deg")
    print("[4.1] each line judged by each rule, against the marks both call clear:")
    old_rule, new_code = ERAS[0][1], ERAS[-1][1]
    combinations = {
        "skeleton pixels, 1.0.0 polyline rule": (
            lambda k, p: _polylined(cache, old_rule, k, p, SKELETON_PIXEL_LINE)),
        "skeleton pixels, excess-turning rule": (
            lambda k, p: _kinked(cache, new_code, k, p, SKELETON_PIXEL_LINE)),
        "half-max centerline, 1.0.0 polyline rule": (
            lambda k, p: _polylined(cache, old_rule, k, p)),
        "half-max centerline, excess-turning rule": (
            lambda k, p: _kinked(cache, new_code, k, p)),
    }
    scores = kink_scores(cache, list(combinations.values()))
    for name, source in combinations.items():
        total = {key: sum(scores[(source, k, "both")][key] for k, _p, _t in SCANS)
                 for key in ("detections", "found", "displaced", "merged", "missed", "false")}
        per_scan = ", ".join(f"{k} {scores[(source, k, 'both')]['false']}" for k, _p, _t in SCANS)
        print(f"    {name:42s} kinks {total['detections']:3d}, found {total['found'] + total['displaced']:3d}, "
              f"merged {total['merged']}, missed {total['missed']:2d}, "
              f"matching no mark {total['false']:3d} ({per_scan})")
    print("[4.2] the commits after 2.0.0 against the marks both call clear:")
    chain = [ERAS[1][1], *KINK_CHANGES]
    scores = kink_scores(cache, chain)
    for commit in chain:
        total = {key: sum(scores[(commit, k, "both")][key] for k, _p, _t in SCANS)
                 for key in ("found", "displaced", "missed", "false")}
        print(f"    {commit[:7]} found {total['found'] + total['displaced']:3d}, "
              f"missed {total['missed']:2d}, matching no mark {total['false']:3d}")
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs
    print("[4.2] kinks only one of 2.0.0 and c43409b reports (more than 3 px from every kink of the other):")
    for key, path, _ in SCANS:
        width = float(np.load(_kinked(cache, ERAS[-1][1], key, path))["width_px"])
        old_kinks, new_kinks = (np.load(_kinked(cache, c, key, path))["kinks"].T
                                for c in (ERAS[1][1], ERAS[-1][1]))
        only_old = [dict(x=x, y=y) for x, y in old_kinks
                    if np.hypot(*(new_kinks - (x, y)).T).min() > 3]
        only_new = [dict(x=x, y=y) for x, y in new_kinks
                    if np.hypot(*(old_kinks - (x, y)).T).min() > 3]
        pairs = len(krs.match_marks(only_old, only_new, width))
        print(f"    {key:12s} only 2.0.0 {len(only_old):2d}, only c43409b {len(only_new):2d}, "
              f"paired within W {pairs:2d}: gone {len(only_old) - pairs}, new {len(only_new) - pairs}")


def main() -> None:
    """
    Build every figure, or run one version when called with ``--run-era``.
    すべての図を作る。``--run-era`` 付きなら 1 つの版を実行する。
    """
    if len(sys.argv) > 1 and sys.argv[1] == "--run-era":
        run_era(*sys.argv[2:6])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--run-synthetic":
        run_synthetic_tophat(sys.argv[2])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--run-segmenter":
        run_segmenter(*sys.argv[2:5])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--run-skeletonizer":
        run_skeletonizer(*sys.argv[2:6])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--run-polyline":
        run_polyline_rule(*sys.argv[2:5])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--run-kinks":
        run_kink_detector(*sys.argv[2:7])
        return
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--full", action="store_true",
                        help="write full-resolution figures to .tmp/history/full instead")
    parser.add_argument("--methods", nargs="+", default=list(BACKGROUND_METHODS),
                        help="background methods to draw ('default' for each version's default)")
    parser.add_argument("--check", action="store_true",
                        help="print the measurements behind the document's statements instead")
    args = parser.parse_args()
    if args.check:
        cache = _cache_dir()
        check_attributions(cache)
        check_tophat_stripes(cache)
        return
    out_dir = FULL_DIR if args.full else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = _cache_dir()
    dpi = FULL_DPI if args.full else REDUCED_DPI
    for method in args.methods:
        figure_background(cache, out_dir, dpi, "" if method == "default" else method)
    import matplotlib.pyplot as plt
    for lang in LABELS:
        with plt.rc_context(_font_context(lang)):
            figure_binarization(cache, out_dir, dpi, lang)
            figure_skeletonization(cache, out_dir, dpi, lang)
            figure_kinks(cache, out_dir, dpi, lang)
            figure_centerline(cache, out_dir, dpi, lang)


if __name__ == "__main__":
    main()
