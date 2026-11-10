# -*- coding: utf-8 -*-
"""
Render what a change to the GUI01 analysis stages does, and record its review.
GUI01 の解析段階への変更が何をするかを描き、その確認を記録する。

A change to what the analysis computes is judged by looking at its effect on
whole images of the bundled scans, not by numbers alone (AGENTS.md §8.18).
This script runs the code of a base commit and of the working tree on the
three bundled scans and draws, stage by stage, what differs::

    .venv\\Scripts\\python.exe scripts\\visual_diff.py compare [BASE]
    .venv\\Scripts\\python.exe scripts\\visual_diff.py record [BASE] --stage background=improved:"..."
    .venv\\Scripts\\python.exe scripts\\visual_diff.py approve --by NAME

``compare`` writes figures and a summary to ``.tmp/visual_diff/<base>_<fingerprint>/``
(``BASE`` defaults to ``HEAD``). Each later stage is given the working tree's
output of the earlier stages in both versions, as in ``docs/history.md``, so a
figure shows the change of that stage alone. When every stage's output is
bit-identical, ``compare`` records the fingerprint as ``identical`` and there
is nothing to look at. Otherwise ``record`` stores, per stage, a verdict
(`VERDICTS`) and where it was seen, as a ``pending`` review, and ``approve``
marks the review approved by the person who looked. An agent may run
``approve`` only after that person has approved the recorded review in the
conversation. The record is ``tests/visual_review.json``, read by
``scripts/check_visual_review.py``.
解析の計算を変えた変更は、数値だけでなく、同梱スキャンの画像全体での効果を見て判断
する（AGENTS.md §8.18）。本スクリプトは基準のコミットと作業ツリーのコードを同梱の
3 スキャンで実行し、段階ごとに違いを描く。``compare`` は図とまとめを
``.tmp/visual_diff/<基準>_<指紋>/`` に書く（``BASE`` の既定は ``HEAD``）。後の段階には、
``docs/history.ja.md`` と同じく、どちらの版にも作業ツリーの前の段階の出力を与えるので、
図はその段階の変化だけを示す。全段階の出力がビット単位で同一なら、``compare`` は指紋を
``identical`` として記録し、見るものはない。そうでなければ ``record`` が段階ごとの判定
（`VERDICTS`）と、それを見た場所を ``pending`` の確認として記録し、``approve`` が、見た人が
承認したことを記録する。エージェントが ``approve`` を実行してよいのは、その人が会話の中で
記録された確認を承認した後だけである。記録は ``tests/visual_review.json`` で、
``scripts/check_visual_review.py`` が読む。
"""

# ===== Standard library =====
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import check_visual_review as cvr  # noqa: E402
import make_history_figures as history  # noqa: E402

OUT_BASE = ROOT / ".tmp" / "visual_diff"
STAGES = ("background", "binarization", "skeletonization", "kinks")
VERDICTS = ("improved", "worse", "mixed", "unchanged")
WORKTREE = "worktree"


def _resolve(base: str) -> str:
    """
    Return the full hash of commit `base`.
    コミット `base` の完全なハッシュを返す。
    """
    return subprocess.run(["git", "rev-parse", f"{base}^{{commit}}"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _src(version: str) -> Path:
    """
    Return the folder holding `version`'s ``lib`` (the repository for the working tree).
    `version` の ``lib`` を含むフォルダを返す（作業ツリーならリポジトリ）。
    """
    return ROOT if version == WORKTREE else history._source(version)


def _run(*args: str) -> None:
    """
    Run one stage runner of ``scripts/make_history_figures.py`` in its own process.
    ``scripts/make_history_figures.py`` の段階の実行関数を 1 つ、別プロセスで実行する。
    """
    subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "make_history_figures.py"),
                    *args], cwd=ROOT, check=True)


def _analyze(out: Path, base: str) -> Dict[str, Dict[str, Path]]:
    """
    Run every stage of both versions on every scan and return the array files.
    両方の版の全段階を全スキャンで実行し、配列のファイルを返す。

    Returns
    -------
    dict
        (version, scan key) -> stage -> ``.npz`` path; the later stages of both
        versions take the working tree's earlier outputs.
        (版, スキャンのキー) -> 段階 -> ``.npz`` のパス。両方の版の後の段階は、作業
        ツリーの前の段階の出力を入力にする。
    """
    arrays: Dict = {}
    for scan_key, scan_path, _title in history.SCANS:
        files = {v: {s: out / "arrays" / f"{v[:12]}_{scan_key}_{s}.npz" for s in STAGES}
                 for v in (base, WORKTREE)}
        for version in (WORKTREE, base):
            _run("--run-era", str(_src(version)), str(ROOT / scan_path),
                 str(files[version]["background"]), "")
        for version in (WORKTREE, base):
            _run("--run-segmenter", str(_src(version)), str(files[WORKTREE]["background"]),
                 str(files[version]["binarization"]))
        for version in (WORKTREE, base):
            _run("--run-skeletonizer", str(_src(version)), str(files[WORKTREE]["background"]),
                 str(files[WORKTREE]["binarization"]), str(files[version]["skeletonization"]))
        for version in (WORKTREE, base):
            _run("--run-kinks", str(_src(version)), str(files[WORKTREE]["background"]),
                 str(files[WORKTREE]["skeletonization"]), str(files[version]["kinks"]), "")
        for version in (base, WORKTREE):
            arrays[(version, scan_key)] = files[version]
    return arrays


def _components(mask) -> int:
    """
    Count the 8-connected components of `mask`.
    `mask` の 8 連結成分を数える。
    """
    import numpy as np
    from scipy import ndimage
    return int(ndimage.label(mask, structure=np.ones((3, 3)))[1])


def _summarize(arrays: Dict, base: str) -> Dict:
    """
    Compare the two versions stage by stage and return the summary.
    2 つの版を段階ごとに比べ、まとめを返す。
    """
    import numpy as np
    from scipy.spatial import cKDTree
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs

    human = krs.load_human_reference()
    summary: Dict = {}
    for scan_key, _path, _title in history.SCANS:
        old = {s: np.load(arrays[(base, scan_key)][s]) for s in STAGES}
        new = {s: np.load(arrays[(WORKTREE, scan_key)][s]) for s in STAGES}
        a, b = old["background"]["calibrated"], new["background"]["calibrated"]
        diff = np.abs(a.astype(float) - b.astype(float))
        background = dict(identical=bool(np.array_equal(a, b)), max_abs_nm=float(diff.max()),
                          pixels_over_0_1_nm=int((diff > 0.1).sum()))
        a, b = old["binarization"]["binarized"], new["binarization"]["binarized"]
        binarization = dict(identical=bool(np.array_equal(a, b)),
                            components_added=_components(b & ~a),
                            components_removed=_components(a & ~b))
        a, b = old["skeletonization"]["skeleton"], new["skeletonization"]["skeleton"]
        skeleton = dict(identical=bool(np.array_equal(a, b)), pixels_added=int((b & ~a).sum()),
                        pixels_removed=int((a & ~b).sum()))
        width = float(new["kinks"]["width_px"])
        names = history.MARK_SCAN_NAMES[scan_key]
        marks = history._both_marks(human[names]["A"], human[names]["B"], width)
        kinks: Dict = dict(identical=all(
            old["kinks"][k].shape == new["kinks"][k].shape
            and np.array_equal(old["kinks"][k], new["kinks"][k])
            for k in ("kinks", "line_x", "line_y")))
        for label, data in (("base", old["kinks"]), ("worktree", new["kinks"])):
            found = [dict(x=float(x), y=float(y), w=width) for x, y in zip(*data["kinks"])]
            score = krs.score(marks, found, [])
            kinks[label] = dict(kinks=len(found), found=score["found"] + score["displaced"],
                                missed=score["missed"], matching_no_mark=score["false"])
        if old["kinks"]["line_x"].size and new["kinks"]["line_x"].size:
            tree = cKDTree(np.column_stack([old["kinks"]["line_x"], old["kinks"]["line_y"]]))
            shift, _ = tree.query(np.column_stack([new["kinks"]["line_x"], new["kinks"]["line_y"]]))
            kinks["centerline_shift_px"] = dict(median=float(np.median(shift)),
                                                p95=float(np.percentile(shift, 95)),
                                                max=float(shift.max()))
        summary[scan_key] = dict(background=background, binarization=binarization,
                                 skeletonization=skeleton, kinks=kinks)
    return summary


def _draw(out: Path, arrays: Dict, base: str) -> List[Path]:
    """
    Draw the comparison figures of every stage; return the files written.
    全段階の比較の図を描き、書いたファイルを返す。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from scipy import ndimage
    sys.path.insert(0, str(ROOT))
    from lib.ui_tools import compute_auto_vrange

    labels = (f"base {base[:7]}", "working tree")
    blue, green, magenta, yellow = (0.30, 0.55, 1.00), "#00e000", "#ff00ff", "#ffd000"
    widen = np.ones((3, 3), dtype=bool)
    written: List[Path] = []
    rows = len(history.SCANS)

    def grey_of(calibrated):
        hi = float(np.percentile(calibrated, 99.5))
        return np.clip((calibrated + 0.5) / (hi + 0.5), 0.0, 1.0)

    def circle(ax, mask, colour):
        labelled, _count = ndimage.label(mask, structure=np.ones((3, 3)))
        for piece in ndimage.find_objects(labelled):
            cy = (piece[0].start + piece[0].stop) / 2
            cx = (piece[1].start + piece[1].stop) / 2
            radius = max(25.0, 0.7 * max(piece[0].stop - piece[0].start,
                                         piece[1].stop - piece[1].start))
            ax.add_patch(plt.Circle((cx, cy), radius, fill=False, edgecolor=colour, linewidth=3))

    def finish(fig, axes, name, handles, columns):
        for ax in np.ravel(axes):
            ax.set_xticks([])
            ax.set_yticks([])
        if handles:
            history._legend(fig, handles, columns)
        path = out / f"{name}.jpg"
        history._save(fig, path, history.REDUCED_DPI)
        plt.close(fig)
        written.append(path)

    # Background: rows A (GUI auto range) and B (-1..+1 nm) of both versions.
    # 背景補正: 両方の版の A 段（GUI の自動範囲）と B 段（-1〜+1 nm）。
    fig, axes = plt.subplots(rows, 4, figsize=(44, 11.5 * rows), squeeze=False,
                             gridspec_kw={"wspace": 0.04, "hspace": 0.12})
    for r, (scan_key, _p, title) in enumerate(history.SCANS):
        old = np.load(arrays[(base, scan_key)]["background"])["calibrated"]
        new = np.load(arrays[(WORKTREE, scan_key)]["background"])["calibrated"]
        vmin, vmax = compute_auto_vrange(new)
        lo, hi = history.BACKGROUND_RANGE_NM
        for j, (image, label, rng) in enumerate(((old, labels[0], (vmin, vmax)), (new, labels[1], (vmin, vmax)),
                                                 (old, labels[0], (lo, hi)), (new, labels[1], (lo, hi)))):
            axes[r, j].imshow(image, cmap="afmhot", vmin=rng[0], vmax=rng[1])
            axes[r, j].set_title(f"{'A' if j < 2 else 'B'}   {label}   [{rng[0]:g}, {rng[1]:g}] nm",
                                 fontsize=26)
        axes[r, 0].set_ylabel(title, fontsize=28)
    finish(fig, axes, "background", [], 0)

    # Binarization: each version's mask on the working tree's calibrated image.
    # 二値化: 作業ツリーの補正後の画像に対する各版のマスク。
    fig, axes = plt.subplots(rows, 2, figsize=(22, 11.5 * rows), squeeze=False,
                             gridspec_kw={"wspace": 0.04, "hspace": 0.12})
    for r, (scan_key, _p, title) in enumerate(history.SCANS):
        grey = grey_of(np.load(arrays[(WORKTREE, scan_key)]["background"])["calibrated"])
        old = np.load(arrays[(base, scan_key)]["binarization"])["binarized"]
        new = np.load(arrays[(WORKTREE, scan_key)]["binarization"])["binarized"]
        for j, (mask, label) in enumerate(((old, labels[0]), (new, labels[1]))):
            rgb = np.dstack([grey] * 3) * 0.85
            rgb[mask] = 0.45 * rgb[mask] + 0.55 * np.array(blue)
            axes[r, j].imshow(rgb)
            axes[r, j].set_title(label, fontsize=28)
        circle(axes[r, 1], new & ~old, green)
        circle(axes[r, 1], old & ~new, magenta)
        axes[r, 0].set_ylabel(title, fontsize=28)
    finish(fig, axes, "binarization", [
        Patch(facecolor=blue, label="binarized mask"),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor=green, markeredgewidth=4, label="component the working tree adds"),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor=magenta, markeredgewidth=4, label="component the working tree removes"),
    ], 3)

    # Skeletonization: the working tree's skeleton with what it adds and removes.
    # 細線化: 作業ツリーのスケルトンと、それが加えたもの・取り除いたもの。
    fig, axes = plt.subplots(rows, 1, figsize=(11, 11.5 * rows), squeeze=False,
                             gridspec_kw={"hspace": 0.12})
    for r, (scan_key, _p, title) in enumerate(history.SCANS):
        grey = grey_of(np.load(arrays[(WORKTREE, scan_key)]["background"])["calibrated"])
        old = np.load(arrays[(base, scan_key)]["skeletonization"])["skeleton"]
        new = np.load(arrays[(WORKTREE, scan_key)]["skeletonization"])["skeleton"]
        rgb = np.dstack([grey] * 3) * 0.7
        rgb[ndimage.binary_dilation(new & old, widen)] = blue
        rgb[ndimage.binary_dilation(old & ~new, widen)] = (1.0, 0.0, 1.0)
        rgb[ndimage.binary_dilation(new & ~old, widen)] = (0.0, 0.88, 0.0)
        axes[r, 0].imshow(rgb)
        circle(axes[r, 0], old ^ new, yellow)
        axes[r, 0].set_title(f"{title}   {labels[1]} against {labels[0]}", fontsize=24)
    finish(fig, axes, "skeletonization", [
        Line2D([], [], color=blue, linewidth=6, label="unchanged skeleton"),
        Line2D([], [], color=green, linewidth=6, label="pixels the working tree adds"),
        Line2D([], [], color=magenta, linewidth=6, label="pixels the working tree removes"),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor=yellow, markeredgewidth=4, label="place that changed"),
    ], 2)

    # Kinks: each version's kinks and lines, scored against the marks both authors call clear.
    # キンク: 各版のキンクと線を、2 人とも明瞭とした印に対して採点して描く。
    sys.path.insert(0, str(ROOT / "scripts"))
    import kink_reference_score as krs
    human = krs.load_human_reference()
    fig, axes = plt.subplots(rows, 2, figsize=(22, 11.5 * rows), squeeze=False,
                             gridspec_kw={"wspace": 0.04, "hspace": 0.12})
    for r, (scan_key, _p, title) in enumerate(history.SCANS):
        calibrated = np.load(arrays[(WORKTREE, scan_key)]["background"])["calibrated"]
        data_new = np.load(arrays[(WORKTREE, scan_key)]["kinks"])
        width = float(data_new["width_px"])
        names = history.MARK_SCAN_NAMES[scan_key]
        marks = history._both_marks(human[names]["A"], human[names]["B"], width)
        for j, (version, label) in enumerate(((base, labels[0]), (WORKTREE, labels[1]))):
            ax = axes[r, j]
            data = np.load(arrays[(version, scan_key)]["kinks"])
            ax.imshow(calibrated, cmap="gray", vmin=-0.5, vmax=float(np.percentile(calibrated, 99.5)))
            for line in np.unique(data["line_id"]):
                on = data["line_id"] == line
                ax.plot(data["line_x"][on], data["line_y"][on], color="#4a8cff", linewidth=1.2)
            found = [dict(x=float(x), y=float(y), w=width) for x, y in zip(*data["kinks"])]
            score = krs.score(marks, found, [])
            unmatched = {(k["x"], k["y"]) for k in score["false_list"]}
            for kink in found:
                colour = magenta if (kink["x"], kink["y"]) in unmatched else green
                ax.plot(kink["x"], kink["y"], "o", markersize=9, markerfacecolor=colour,
                        markeredgecolor="black", markeredgewidth=0.8)
            for mark in score["missed_list"]:
                ax.add_patch(plt.Circle((mark["x"], mark["y"]), 16, fill=False,
                                        edgecolor=yellow, linewidth=3))
            ax.set_xlim(-0.5, calibrated.shape[1] - 0.5)
            ax.set_ylim(calibrated.shape[0] - 0.5, -0.5)
            ax.set_title(label, fontsize=28)
        axes[r, 0].set_ylabel(title, fontsize=28)
    finish(fig, axes, "kinks", [
        Line2D([], [], color="#4a8cff", linewidth=4, label="line the kinks are judged on"),
        *history._kink_handles("en"),
        Line2D([], [], linestyle="", marker="o", markersize=26, markerfacecolor="none",
               markeredgecolor=yellow, markeredgewidth=4, label="mark both authors call clear, missed"),
    ], 2)

    # Centerline: the place on each scan where the working tree's line moved most.
    # 中心線: 各スキャンで、作業ツリーの線が最も動いた場所。
    from scipy.spatial import cKDTree
    fig, axes = plt.subplots(1, rows, figsize=(11 * rows, 12), squeeze=False)
    for r, (scan_key, _p, title) in enumerate(history.SCANS):
        ax = axes[0, r]
        calibrated = np.load(arrays[(WORKTREE, scan_key)]["background"])["calibrated"]
        old = np.load(arrays[(base, scan_key)]["kinks"])
        new = np.load(arrays[(WORKTREE, scan_key)]["kinks"])
        ax.imshow(calibrated, cmap="gray", vmin=-0.5, vmax=float(np.percentile(calibrated, 99.5)),
                  interpolation="nearest")
        cy, cx = calibrated.shape[0] / 2, calibrated.shape[1] / 2
        if old["line_x"].size and new["line_x"].size:
            tree = cKDTree(np.column_stack([old["line_x"], old["line_y"]]))
            shift, _ = tree.query(np.column_stack([new["line_x"], new["line_y"]]))
            worst = int(np.argmax(shift))
            cx, cy = float(new["line_x"][worst]), float(new["line_y"][worst])
            ax.set_title(f"{title}   largest shift {shift[worst]:.2f} px", fontsize=24)
        for data, colour, width in ((old, "#ff9900", 3.5), (new, "#4a8cff", 2.0)):
            for line in np.unique(data["line_id"]):
                on = data["line_id"] == line
                ax.plot(data["line_x"][on], data["line_y"][on], color=colour, linewidth=width)
        ax.set_xlim(cx - 40, cx + 40)
        ax.set_ylim(cy + 40, cy - 40)
    history._legend(fig, [
        Line2D([], [], color="#ff9900", linewidth=5, label=f"centerline of the {labels[0]}"),
        Line2D([], [], color="#4a8cff", linewidth=3, label="centerline of the working tree"),
    ], 2)
    for ax in np.ravel(axes):
        ax.set_xticks([])
        ax.set_yticks([])
    path = out / "centerline.png"
    fig.savefig(path, dpi=history.REDUCED_DPI, bbox_inches="tight")
    plt.close(fig)
    written.append(path)
    return written


def _load_record() -> Dict:
    """
    Return the review record, empty when it does not exist yet.
    確認の記録を返す。まだ無ければ空。
    """
    text = cvr.read_worktree(cvr.RECORD)
    return json.loads(text) if text else {"reviews": []}


def _save_record(record: Dict) -> None:
    """
    Write the review record, one review per fingerprint.
    確認の記録を書く。指紋ごとに 1 件。
    """
    (ROOT / cvr.RECORD).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")


def _put_review(review: Dict) -> None:
    """
    Add `review`, replacing an earlier one of the same fingerprint.
    `review` を加える。同じ指紋の以前の確認は置き換える。
    """
    record = _load_record()
    record["reviews"] = [r for r in record["reviews"] if r.get("fingerprint") != review["fingerprint"]]
    record["reviews"].append(review)
    _save_record(record)


def _out_dir(base: str, print_: str) -> Path:
    """
    Return the folder of one comparison.
    1 回の比較のフォルダを返す。
    """
    return OUT_BASE / f"{base[:12]}_{print_}"


def compare(base_name: str) -> int:
    """
    Run, draw and summarize the comparison of the working tree with `base_name`.
    作業ツリーと `base_name` の比較を実行し、描き、まとめる。
    """
    base = _resolve(base_name)
    print_ = cvr.fingerprint(cvr.read_worktree)
    out = _out_dir(base, print_)
    (out / "arrays").mkdir(parents=True, exist_ok=True)
    arrays = _analyze(out, base)
    summary = _summarize(arrays, base)
    identical = all(summary[scan][stage]["identical"] for scan in summary for stage in STAGES)
    (out / "summary.json").write_text(json.dumps(
        dict(base=base, fingerprint=print_, identical=identical, scans=summary), indent=2) + "\n",
        encoding="utf-8")
    if identical:
        _put_review(dict(fingerprint=print_, base=base, date=str(datetime.date.today()),
                         status="identical"))
        print(f"every stage's output equals that of {base[:7]} on the bundled scans; "
              f"recorded fingerprint {print_} as identical")
        return 0
    written = _draw(out, arrays, base)
    print(json.dumps(summary, indent=2))
    print("figures:")
    for path in written:
        print(f"  {path.relative_to(ROOT)}")
    print("Look at every figure (the full stage and the whole scan), then record what you saw "
          "with `visual_diff.py record`.")
    return 0


def record(base_name: str, stages: List[str]) -> int:
    """
    Record the verdicts of a comparison as a review awaiting approval.
    比較の判定を、承認待ちの確認として記録する。
    """
    base = _resolve(base_name)
    print_ = cvr.fingerprint(cvr.read_worktree)
    out = _out_dir(base, print_)
    if not (out / "summary.json").is_file():
        print(f"no comparison of {base[:7]} with this code; run `visual_diff.py compare` first",
              file=sys.stderr)
        return 1
    verdicts: Dict[str, Dict[str, str]] = {}
    for item in stages:
        name, _, rest = item.partition("=")
        verdict, _, note = rest.partition(":")
        if name not in STAGES or verdict not in VERDICTS or not note.strip():
            print(f"--stage must be STAGE=VERDICT:NOTE with STAGE in {STAGES}, VERDICT in "
                  f"{VERDICTS} and a note saying where it was seen; got {item!r}", file=sys.stderr)
            return 1
        verdicts[name] = dict(verdict=verdict, note=note.strip())
    missing = [s for s in STAGES if s not in verdicts]
    if missing:
        print(f"every stage needs a verdict; missing {missing}", file=sys.stderr)
        return 1
    _put_review(dict(fingerprint=print_, base=base, date=str(datetime.date.today()),
                     status="pending", figures=str(out.relative_to(ROOT)).replace("\\", "/"),
                     stages=verdicts))
    print(f"recorded review of fingerprint {print_} as pending; a person approves it with "
          "`visual_diff.py approve --by NAME`")
    return 0


def approve(by: str) -> int:
    """
    Mark the pending review of the working tree's code approved by `by`.
    作業ツリーのコードの承認待ちの確認を、`by` が承認したと記録する。
    """
    print_ = cvr.fingerprint(cvr.read_worktree)
    record_ = _load_record()
    for review in record_["reviews"]:
        if review.get("fingerprint") == print_ and review.get("status") == "pending":
            if not by.strip():
                print("--by must name the person who approves", file=sys.stderr)
                return 1
            review.update(status="approved", approved_by=by.strip(),
                          approved_date=str(datetime.date.today()))
            _save_record(record_)
            print(f"review of fingerprint {print_} approved by {by.strip()}")
            return 0
    print(f"no pending review of fingerprint {print_}; run `compare` and `record` first",
          file=sys.stderr)
    return 1


def main() -> int:
    """
    Run the subcommand named on the command line.
    コマンドラインで指定したサブコマンドを実行する。
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("compare", help="render the change against BASE")
    p.add_argument("base", nargs="?", default="HEAD")
    p = sub.add_parser("record", help="record per-stage verdicts as a pending review")
    p.add_argument("base", nargs="?", default="HEAD")
    p.add_argument("--stage", action="append", default=[], metavar="STAGE=VERDICT:NOTE")
    p = sub.add_parser("approve", help="approve the pending review (a person, or an agent "
                                      "only after that person approved it in the conversation)")
    p.add_argument("--by", required=True)
    args = parser.parse_args()
    if args.command == "compare":
        return compare(args.base)
    if args.command == "record":
        return record(args.base, args.stage)
    return approve(args.by)


if __name__ == "__main__":
    sys.exit(main())
