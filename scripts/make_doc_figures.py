# -*- coding: utf-8 -*-
"""
Generate the figures embedded in the algorithm documents.
アルゴリズム解説文書に載せる図を生成する。

Each figure is drawn from a synthetic height image or line run through the
code the document explains, so it can be regenerated whenever that code
changes::

    .venv\\Scripts\\python.exe scripts\\make_doc_figures.py

Two figures (``kink_point_angles`` and ``kink_real_fiber``) instead show the
kink rule on a fiber of a bundled scan, analyzed with the default settings
into the kink reference's cache; they check the statements the text makes
about that fiber and fail to build when they no longer hold.

The PNG files are written to ``docs/images/`` and are shared by
``docs/algorithms.md`` and ``docs/algorithms.ja.md``; their labels are fixed
English, as for every plot in this project. The exceptions are the three
figures explaining the kink rule that carry several sentences of reading
instructions and are drawn once in each language (``kink_point_angles``,
``kink_heading`` and ``kink_real_fiber``, with ``.ja.png`` for Japanese);
the Japanese ones need a Japanese font.
各図は、文書が説明するコードに合成の高さ画像や線を通して描くため、そのコードが
変わったときはいつでも作り直せる。

2 つの図（``kink_point_angles`` と ``kink_real_fiber``）だけは、既定の設定で解析した
同梱スキャンの繊維にキンク規則を当てはめて描く。解析結果はキンク基準のキャッシュに
置く。これらの図は、本文がその繊維について述べることを確かめ、成り立たなくなれば
作れない。

PNG は ``docs/images/`` に書き出し、英語版と日本語版の両方が共有する。図中の
文字は、このプロジェクトの他の図と同じく英語で固定する。例外はキンク規則を
説明する 3 つの図で、読み方の文をいくつも含むため言語ごとに描く
（``kink_point_angles``・``kink_heading``・``kink_real_fiber``。日本語版は ``.ja.png``）。
日本語版には日本語フォントが要る。
"""

# ===== Standard library =====
import os
import sys

# ===== Numerical / scientific libraries =====
import cv2
import numpy as np
from skimage.morphology import thin

# ===== Plotting libraries =====
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ===== Project libraries =====
from lib import kink_detector as kd  # noqa: E402
from lib.skeletonizer import (  # noqa: E402
    DEFAULT_BORDER_PAD,
    prune_terminal_hooks,
    thin_ignoring_image_border,
)

OUT_DIR = os.path.join(PROJECT_ROOT, "docs", "images")

# Ridge amplitude in nm; the mask keeps everything above half of it, so the
# mask edge sits at the ridge's half maximum.
# 尾根の高さ (nm)。マスクはその半分より高い画素とするので、マスクの縁は
# 尾根の半値の位置にくる。
RIDGE_HEIGHT_NM = 2.0


def _ridge(shape, p0, p1, sigma):
    """
    Height image of a straight Gaussian-profile ridge along a segment.
    線分に沿った、断面がガウス形の直線の尾根の高さ画像。

    Parameters
    ----------
    shape
        Image shape ``(rows, cols)``.
        画像の形 ``(行, 列)``。
    p0, p1
        Segment end points ``(row, col)``; they may lie outside the image.
        線分の両端 ``(行, 列)``。画像の外にあってもよい。
    sigma
        Standard deviation of the cross-section, in pixels.
        断面の標準偏差 (画素)。

    Returns
    -------
    numpy.ndarray
        Height in nm, zero far from the ridge.
        高さ (nm)。尾根から離れた所では 0。
    """
    rr, cc = np.mgrid[0:shape[0], 0:shape[1]].astype(float)
    p0 = np.asarray(p0, float)
    d = np.asarray(p1, float) - p0
    t = np.clip(((rr - p0[0]) * d[0] + (cc - p0[1]) * d[1]) / (d @ d), 0.0, 1.0)
    dist2 = (rr - (p0[0] + t * d[0])) ** 2 + (cc - (p0[1] + t * d[1])) ** 2
    return RIDGE_HEIGHT_NM * np.exp(-dist2 / (2.0 * sigma ** 2))


def _plain_and_padded(mask):
    """
    Return the two skeletons `thin_ignoring_image_border` chooses between.
    `thin_ignoring_image_border` が選ぶ 2 つのスケルトンを返す。

    Notes
    -----
    The function returns only its final choice, so the two candidates are
    recomputed here with the same calls, and the final choice is checked
    against the function itself so the figure cannot drift from the code.
    関数は最終結果しか返さないため、2 つの候補を同じ呼び出しで作り直し、
    最終結果を関数そのものと照合して、図がコードからずれないようにする。
    """
    m = mask.astype(np.uint8)
    pad = DEFAULT_BORDER_PAD
    plain = thin(m).astype(np.uint8)
    padded = thin(np.pad(m, pad, mode="edge")).astype(np.uint8)[pad:-pad, pad:-pad]
    # Step 4: a component whose skeleton the padded pass lost gets the plain one.
    # 手順 4: 拡張した版でスケルトンを失った成分には plain のスケルトンを使う。
    _, labels = cv2.connectedComponents(m)
    expected = padded.copy()
    for label in range(1, labels.max() + 1):
        part = labels == label
        if plain[part].any() and not padded[part].any():
            expected[part] = plain[part]
    actual = thin_ignoring_image_border(m)
    if not np.array_equal(actual, expected):
        raise RuntimeError("figure no longer matches thin_ignoring_image_border")
    return plain, padded


def _draw(height, mask, skeletons, titles, rows, cols, path, note):
    """
    Draw the height image with each skeleton overlaid, one panel per skeleton.
    スケルトンごとに 1 枚ずつ、高さ画像に重ねて描く。
    """
    crop = (slice(*rows), slice(*cols))
    n = len(skeletons) + 1
    aspect = (rows[1] - rows[0]) / (cols[1] - cols[0])
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 3.2 * aspect + 0.5))
    panels = [(None, "height and mask edge")] + list(zip(skeletons, titles))
    for ax, (skel, title) in zip(axes, panels):
        ax.imshow(height[crop], cmap="gray", interpolation="nearest", vmin=0, vmax=RIDGE_HEIGHT_NM)
        ax.contour(mask[crop].astype(float), levels=[0.5], colors="#4fd06a", linewidths=0.8)
        if skel is not None:
            overlay = np.zeros(skel[crop].shape + (4,))
            overlay[skel[crop] > 0] = (0.95, 0.2, 0.2, 1.0)
            ax.imshow(overlay, interpolation="nearest")
            if skel.sum() == 0:
                ax.text(0.5, 0.2, "no skeleton left", color="#e05050", ha="center",
                        va="center", transform=ax.transAxes, fontsize=9)
        # Mark only the sides of the panel that are image edges; a cropped
        # side is not one, and the fiber continues past it.
        # パネルの辺のうち画像の端であるものだけに印を付ける。切り出しの辺は
        # 画像の端ではなく、繊維はその先へ続く。
        h, w = height[crop].shape
        if rows[0] == 0:
            ax.plot([-0.5, w - 0.5], [-0.5, -0.5], color="#4aa3ff", linewidth=2.5)
        if rows[1] == height.shape[0]:
            ax.plot([-0.5, w - 0.5], [h - 0.5, h - 0.5], color="#4aa3ff", linewidth=2.5)
        if cols[0] == 0:
            ax.plot([-0.5, -0.5], [-0.5, h - 0.5], color="#4aa3ff", linewidth=2.5)
        if cols[1] == height.shape[1]:
            ax.plot([w - 0.5, w - 0.5], [-0.5, h - 0.5], color="#4aa3ff", linewidth=2.5)
        ax.set_xlim(-0.5, w - 0.5)
        ax.set_ylim(h - 0.5, -0.5)
        ax.set_title(title, fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout()
    fig.text(0.5, 0.0, note, ha="center", va="top", fontsize=8)
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _draw_padding(height, mask, rows, cols, path, note):
    """
    Draw how padding loses a fiber along the edge and how the last step restores it.
    拡張すると端に沿った繊維の線が消え、手順 4 でそれを戻す様子を描く。

    Notes
    -----
    Only the top of the image is shown, so the top side is the only image edge.
    The second panel shows the padded image with its top padding, before the
    padding is cropped off.
    画像の上端付近だけを表示するので、画像の端は上の辺だけである。2 枚目は、
    拡張した画像を、拡張した上の部分ごと、切り落とす前の状態で示す。
    """
    pad = DEFAULT_BORDER_PAD
    wide_height = np.pad(height, pad, mode="edge")
    wide_mask = np.pad(mask.astype(np.uint8), pad, mode="edge")
    wide_skel = thin(wide_mask).astype(np.uint8)
    _, padded = _plain_and_padded(mask)
    final = thin_ignoring_image_border(mask.astype(np.uint8))

    r0, r1 = rows
    c0, c1 = cols
    no_skel = np.zeros_like(final)
    panels = [
        ("1: original image", height[r0:r1, c0:c1], mask[r0:r1, c0:c1],
         no_skel[r0:r1, c0:c1], 0),
        ("2: padded image, thinned", wide_height[r0:pad + r1, pad + c0:pad + c1],
         wide_mask[r0:pad + r1, pad + c0:pad + c1], wide_skel[r0:pad + r1, pad + c0:pad + c1], pad),
        ("3: padding cropped off (padded)", height[r0:r1, c0:c1], mask[r0:r1, c0:c1],
         padded[r0:r1, c0:c1], 0),
        ("4: after restoring (returned)", height[r0:r1, c0:c1], mask[r0:r1, c0:c1],
         final[r0:r1, c0:c1], 0),
    ]
    width = c1 - c0
    fig, axes = plt.subplots(1, 4, figsize=(3.2 * 4, 3.2 * (pad + r1 - r0) / width + 0.5))
    for ax, (title, h, m, skel, edge_row) in zip(axes, panels):
        # Every panel spans the padded rows, so the image edge sits at the
        # same height in all four; the unpadded panels leave the padding blank.
        # どのパネルも拡張した行の範囲を描き、画像の端を 4 枚で同じ高さにそろえる。
        # 拡張していないパネルでは、拡張した部分を空白にする。
        top = -edge_row
        extent = (-0.5, width - 0.5, top + len(h) - 0.5, top - 0.5)
        ax.imshow(h, cmap="gray", interpolation="nearest", vmin=0, vmax=RIDGE_HEIGHT_NM,
                  extent=extent)
        yy, xx = np.mgrid[0:len(h), 0:width]
        ax.contour(xx, yy + top, m.astype(float), levels=[0.5], colors="#4fd06a",
                   linewidths=0.8)
        overlay = np.zeros(skel.shape + (4,))
        overlay[skel > 0] = (0.95, 0.2, 0.2, 1.0)
        ax.imshow(overlay, interpolation="nearest", extent=extent)
        ax.plot([-0.5, width - 0.5], [-0.5, -0.5], color="#4aa3ff",
                linewidth=2.0 if edge_row else 2.5, linestyle="--" if edge_row else "-")
        ax.set_xlim(-0.5, width - 0.5)
        ax.set_ylim(r1 - 0.5, -pad - 0.5)
        ax.set_title(title, fontsize=9)
        ax.axis("off")
    fig.tight_layout()
    fig.text(0.5, 0.0, note, ha="center", va="top", fontsize=8)
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _draw_hook(path):
    """
    Draw how a low skirt at a fiber tip makes a hook and how it is trimmed.
    繊維の先端の低い裾がフックを作り、それが切り取られる様子を描く。

    Notes
    -----
    The mask is cut at a low height so that it includes the skirt, which is
    the situation `prune_terminal_hooks` exists for. The skeleton is the real
    `thin_ignoring_image_border` output and the trimmed one the real
    `prune_terminal_hooks` output.
    マスクは裾まで含むよう低い高さで切る。これが `prune_terminal_hooks` の扱う
    状況である。スケルトンは実際の `thin_ignoring_image_border` の出力、切除後は
    実際の `prune_terminal_hooks` の出力である。
    """
    shape = (40, 60)
    rr, cc = np.mgrid[0:shape[0], 0:shape[1]].astype(float)
    fiber = _ridge(shape, (20, -10), (20, 38), sigma=1.6)
    skirt = 0.5 * np.exp(-((rr - 12) ** 2 / (2 * 7.0 ** 2) + (cc - 40) ** 2 / (2 * 5.0 ** 2)))
    height = np.maximum(fiber, skirt)
    mask = height > 0.3
    skeleton = thin_ignoring_image_border(mask.astype(np.uint8))
    trimmed = prune_terminal_hooks(skeleton.copy(), height)
    if trimmed.sum() >= skeleton.sum():
        raise RuntimeError("the synthetic hook is no longer trimmed by prune_terminal_hooks")
    _draw(height, mask, [skeleton, trimmed], ["thinned", "after prune_terminal_hooks"],
          (0, 40), (0, 60), path,
          "blue line: image edge   green: mask edge (cut low, so the skirt is inside)   "
          "red: skeleton")


def _excess_curve(sm, heading, length, width):
    """
    Turning T and excess E at every heading sample, by the formula of `KinkDetector.judge_line`.
    `KinkDetector.judge_line` の式で、向きの各標本での回転 T と超過回転 E を求める。

    Returns ``(p, core, excess, background)``, the positions at least ``c``
    from both ends and the window turning, the excess turning and the
    subtracted flank rate there.
    両端から ``c`` 以上離れた位置と、そこでの折れの区間の回転・超過回転・差し引いた前後の区間の
    回転率を返す。
    """
    c = kd._CORE_WIDTHS * width
    f = kd._FLANK_WIDTHS * width
    p = sm[(sm >= c) & (sm <= length - c)]
    core = np.interp(p + c, sm, heading) - np.interp(p - c, sm, heading)
    sense = np.sign(core)
    left = (np.interp(p - c, sm, heading)
            - np.interp(np.maximum(sm[0], p - c - f), sm, heading)) / f
    right = (np.interp(np.minimum(sm[-1], p + c + f), sm, heading)
             - np.interp(p + c, sm, heading)) / f
    background = np.maximum(0.0, np.minimum(sense * left, sense * right))
    return p, core, np.abs(core) - 2.0 * c * background, background


def _judged_positions(x, y, width, p, excess):
    """
    Arc positions of the kinks `KinkDetector.judge_line` finds on a line.
    `KinkDetector.judge_line` が線の上に見つけるキンクの弧長位置。

    Notes
    -----
    Each stored excess has to occur in the curve recomputed here, which checks
    that the figure's formula is still the detector's.
    保存された超過回転はどれも、ここで計算し直した曲線の中に現れなければ
    ならない。これで、図の式が検出器の式のままであることを確かめる。
    """
    judged = kd.KinkDetector().judge_line(x, y, width)
    orig, s = kd._heading_profile(x, y, width)[:2]
    positions = []
    for index, value in zip(judged.kink_indices, judged.kink_excess):
        # Bends of equal excess are told apart by where the stored index lies.
        # 超過回転が等しい折れは、保存されたインデックスの位置で見分ける。
        near = s[int(np.searchsorted(orig, index))]
        same = np.nonzero(np.abs(excess - value) <= 1e-9)[0]
        if same.size == 0:
            raise RuntimeError("figure no longer matches KinkDetector.judge_line")
        positions.append(float(p[same[np.argmin(np.abs(p[same] - near))]]))
    return positions, judged


def _polyline(headings_deg, lengths):
    """
    A line of unit steps made of straight runs with the given headings.
    指定した向きのまっすぐな区間をつないだ、1 画素刻みの線。
    """
    pts = [np.zeros(2)]
    for heading, run in zip(headings_deg, lengths):
        step = np.array([np.cos(np.radians(heading)), np.sin(np.radians(heading))])
        for _ in range(int(run)):
            pts.append(pts[-1] + step)
    pts = np.array(pts)
    return pts[:, 0], pts[:, 1]


def _arc_line(radius, total_deg, lead):
    """
    A straight run, an arc of the given radius and turn, and another straight run.
    まっすぐな区間・指定した半径と回転角の円弧・まっすぐな区間をつないだ線。
    """
    xs = list(np.arange(0.0, lead))
    ys = [0.0] * len(xs)
    for t in np.arange(0.0, np.radians(total_deg), 1.0 / radius):
        xs.append(lead + radius * np.sin(t))
        ys.append(radius * (1.0 - np.cos(t)))
    t = np.radians(total_deg)
    x0, y0 = lead + radius * np.sin(t), radius * (1.0 - np.cos(t))
    for s in np.arange(1.0, lead):
        xs.append(x0 + s * np.cos(t))
        ys.append(y0 + s * np.sin(t))
    return np.array(xs), np.array(ys)


def _corner_on_arc(radius, corner_deg, length):
    """
    A line that curves with the given radius and turns by a corner halfway along.
    指定した半径で曲がり、途中で角の分だけ向きを変える線。
    """
    step = 0.05
    s = np.arange(0.0, length + step / 2, step)
    heading = s / radius + np.where(s >= length / 2, np.radians(corner_deg), 0.0)
    x = np.concatenate([[0.0], np.cumsum(step * np.cos(heading[:-1]))])
    y = np.concatenate([[0.0], np.cumsum(step * np.sin(heading[:-1]))])
    return x[::10], y[::10]


def _ramped_arc(radius, straight, ramp, flat):
    """
    A curve whose curvature rises evenly to 1/radius, stays there, and falls again.
    曲率が 1/radius まで一様に増え、しばらく保たれ、また減っていく曲線。

    Notes
    -----
    An arc joined straight onto straight runs ends where one flank turns and the
    other does not, which the rule reads as a corner where a curve ends; the
    gradual change keeps the figure about a curve that only curves.
    まっすぐな部分にいきなりつないだ円弧は、端で片側の前後の区間だけが回るため、
    規則はそこを「曲線が終わる所にある角」と読む。曲率を徐々に変えて、曲がって
    いるだけのカーブの図にする。
    """
    step = 0.05
    total = 2 * straight + 2 * ramp + flat
    s = np.arange(0.0, total, step)
    kappa = np.interp(s, [0.0, straight, straight + ramp, straight + ramp + flat,
                          straight + 2 * ramp + flat, total],
                      [0.0, 0.0, 1.0 / radius, 1.0 / radius, 0.0, 0.0])
    heading = np.concatenate([[0.0], np.cumsum(kappa[:-1] * step)])
    x = np.concatenate([[0.0], np.cumsum(step * np.cos(heading[:-1]))])
    y = np.concatenate([[0.0], np.cumsum(step * np.sin(heading[:-1]))])
    return x[::10], y[::10]


_HEADING_TEXT = {
    "en": dict(
        names=("A corner between\nstraight parts", "A corner partway\nalong a curve",
               "A part that curves at\na steady rate (radius 2W)"),
        notes=("The centerline's heading does not change on the flanks:\nthe angle subtracted from T is 0° (E = T).",
               "On the flanks the centerline curves to\nthe same side as the window: the angle it\n"
               "would turn over 1.5W from the front end\nat the smaller flank rate is subtracted from T.",
               "The centerline curves at the window's rate on the flanks:\n"
               "the angle subtracted becomes equal to T (E = 0°)."),
        fiber="fiber (one width W wide)",
        line="centerline (the line through the middle of the fiber's width; upper); its heading θ (lower)",
        sdir="s: position along the centerline, increasing towards the arrowhead",
        window="window: the part 1.5W long centred on a kink candidate",
        ends="front end of the window (the side of smaller s; upper)",
        back_bar="back end of the window (upper)",
        flank="flanks: the parts just before and after the window (hatched, W long each)",
        front="tangent to the centerline at the front end (upper); the heading there (lower)",
        back="tangent to the centerline at the back end, drawn to both sides (upper); the heading there (lower)",
        ghost=("assumed centerline: the centerline taken to keep turning from the front end at the "
               "smaller of the two flank rates (upper), and its heading (lower)"),
        end="tangent to the assumed centerline at its end, one window length on (upper); the heading there (lower)",
        tarc="T: angle between the tangents to the centerline at the front and back ends",
        earc=("E: angle between the tangent to the assumed centerline at its end and the tangent to the "
              "centerline at the back end"),
        kink="candidate judged a kink",
        same_flat="the black dash-dot and dotted lines lie on\nthe pink dashed line, the orange one on\nthe centerline",
        same_front="the black dash-dot and black dotted\nlines lie on the pink dashed line",
        same_back="the black dash-dot and dotted lines lie on\nthe pink dashed line, the orange one on\nthe centerline",
        zero="E = 0° (the black dash-dot line\nlies on the centerline, the dotted\none on the orange dashed line)",
        low_flat="the black dash-dot and\ndotted lines lie on the\npink dashed line",
        low_curve="the dash-dot line lies\non the black solid line\n(heading θ), the dotted\none on the orange\ndashed line",
        none="no kink",
        kink_verdict=": E is %.0f° or more, so judged a kink",
        no_verdict=": E is below %.0f°, so not judged a kink",
        values="T = %.0f°, E = %.0f°",
        key=("For each kink candidate, T and E are measured over the window centred on it; "
             "the candidate is judged a kink when E is %.0f° or more.\n"
             "T (turning across the window): the angle by which the centerline's heading changes from "
             "the front end to the back end of the window, positive whichever way it turns.\n"
             "Flank rate: the angle the centerline's heading turns per unit length, measured on each flank; "
             "a flank turning to the other side than the window has its rate taken as 0, and the smaller of "
             "the front and back flanks' rates is used.\n"
             "E (excess turning): T less the angle turned on 1.5W (the window length) at this rate "
             "(it can be negative)."),
        xlabel="position along the centerline s (in units of the fiber width W)",
        ylabel="heading θ of the centerline (degrees)\n0° at s = 0"),
    "ja": dict(
        names=("まっすぐな部分に\nはさまれた曲がり角", "カーブの途中にある\n曲がり角",
               "一定の回転率で曲がる部分\n（半径 2W）"),
        notes=("前後の区間では中心線の向きが変わらない\n→ T から差し引く角度は 0°（E = T）",
               "前後の区間でも中心線が折れの区間と同じ側へ曲がる\n→ 前の端から、前の区間と後ろの区間の回転率のうち、\n"
               "小さいほうの値のまま 1.5W 進んだと仮定したときに\n曲がる角度を、T から差し引く",
               "前後の区間でも中心線が折れの区間と同じ回転率で曲がる\n→ 差し引く角度が T と等しくなる（E = 0°）"),
        fiber="繊維（幅 W）",
        line="中心線（繊維の幅の中央を通る線。上段）、中心線の向き θ（下段）",
        sdir="s：中心線に沿った位置。矢じりの方向に大きくなる",
        window="折れの区間：キンクの候補を中心とする長さ 1.5W の区間",
        ends="折れの区間の前の端（s が小さい側。上段）",
        back_bar="折れの区間の後ろの端（上段）",
        flank="前後の区間：折れの区間の前と後ろに続く区間（斜線。それぞれ長さ W）",
        front="前の端での中心線の接線（上段）、前の端での向き（下段）",
        back="後ろの端での中心線の接線（両側へ延ばしてある。上段）、後ろの端での向き（下段）",
        ghost="仮定した中心線：前の端から、前の区間と後ろの区間の回転率のうち、小さいほうの値のまま曲がり続けると仮定した中心線（上段）と、その向き（下段）",
        end="仮定した中心線の終わり（折れの区間と同じ長さだけ進んだ所）での接線（上段）、そこでの向き（下段）",
        tarc="T：前の端での中心線の接線と後ろの端での中心線の接線がなす角",
        earc="E：仮定した中心線の終わりでの接線と後ろの端での中心線の接線がなす角",
        kink="キンクと判定された候補",
        same_flat="黒の一点鎖線と黒の点線はピンクの破線に、\nオレンジの破線は中心線に重なる",
        same_front="黒の一点鎖線と黒の点線は、\nピンクの破線に重なる",
        same_back="黒の一点鎖線と黒の点線はピンクの破線に、\nオレンジの破線は中心線に重なる",
        zero="E = 0°（黒の一点鎖線は中心線に、\n黒の点線はオレンジの破線に重なる）",
        low_flat="黒の一点鎖線と黒の点線は、\nピンクの破線に重なる",
        low_curve="黒の一点鎖線は\n黒の実線（向き θ）に、\n黒の点線は\nオレンジの破線に重なる",
        none="キンクなし",
        kink_verdict="。E が %.0f° 以上なのでキンクと判定",
        no_verdict="。E が %.0f° 未満なのでキンクと判定しない",
        values="T = %.0f°、E = %.0f°",
        key=("キンクの候補ごとに、それを中心とする折れの区間で T と E を測り、E が %.0f° 以上の候補を"
             "キンクと判定する。\n"
             "T（折れの区間での回転）：折れの区間の前の端から後ろの端までに中心線の向きが変わる角度。"
             "左右どちらに曲がっても正の値で表す。\n"
             "回転率：単位長さあたりに中心線の向きが変わる角度。前後の区間それぞれで測り、折れの区間と"
             "反対側へ曲がっている区間の回転率は 0 とみなして、前の区間と後ろの区間のうち回転率が小さいほうの値を使う。\n"
             "E（超過回転）：この回転率のまま 1.5W（折れの区間の長さ）進んだときに曲がる角度を、"
             "T から差し引いた値（負の値になることもある）。"),
        xlabel="中心線に沿った位置 s（繊維の幅 W を単位とする）", ylabel="中心線の向き θ（度）\ns = 0 での向きを 0° とする"),
}

# One colour per kind of element in this figure, chosen so that elements that
# touch (T's arc and the two direction lines, E's arc and the dash-dot and
# back-end lines) differ clearly. The centerline, the centerline the fiber
# would follow at the flank rate, and their heading graphs are one kind of
# object and share black, told apart by the line style; a kink is marked by
# the shape ×, the flanks by a hatch pattern.
# この図では要素の種類ごとに色を 1 つだけ使い、接する要素どうし（T の円弧と 2 本の
# 向きの線、E の円弧と一点鎖線・後ろの端の線）がはっきり違うように選ぶ。中心線、
# 前後の区間の回転率で進んだ場合の中心線、それらの向きのグラフは同じ種類のもので、
# 黒を共有し、線の種類で区別する。キンクは × の形、前後の区間は斜線の模様で示す。
_FIBER_COLOUR = "#dcdcdc"
_WINDOW_COLOUR = "#b5dd8f"
_FLANK_HATCH = "///"
_HATCH_COLOUR = "#7a7a7a"
_FRONT_COLOUR = "#d81b60"
_KINK_COLOUR = "#0072b2"
_BACK_COLOUR = "#d99100"
_GHOST_STYLE = (0, (6, 2, 1.2, 2))
_END_STYLE = (0, (1.2, 2.2))
_TANGENT_STYLE = (0, (4.0, 2.0))
_T_COLOUR = "#6a3d9a"
_E_COLOUR = "#00796b"


def _draw_heading(path, width, lang):
    """
    Draw four lines, their heading theta(s), the window, the flanks, T and E.
    4 本の線の形と向き theta(s) に、折れの区間・前後の区間・T・E を重ねて描く。

    Notes
    -----
    Each column shows the fiber as a band one width wide above its heading
    graph. T and E are drawn on the shape as angles between lines (the front
    end's direction continued, the back end's direction continued, and the
    end direction of the centerline the fiber would follow at the flank rate)
    and in the graph as arrows at the back end of the window. Every element
    has its own colour, the kinks `KinkDetector.judge_line` finds are marked
    with ×, and the number found on each line is checked.
    各列は、幅 1 本分の帯で描いた繊維を向きのグラフの上に置く。T と E は、線の形の
    上では線どうしの角度（前の端の向きの延長、後ろの端の向きの延長、前後の区間の
    回転率で進んだ場合の中心線の終わりの向き）として、グラフでは折れの区間の後ろの
    端の矢印として描く。要素ごとに色を分け、`KinkDetector.judge_line` が見つける
    キンクを × で示し、各線で見つかる数を確かめる。
    """
    import matplotlib.patheffects as pe
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    from matplotlib.patches import Arc, Patch

    text = _HEADING_TEXT[lang]
    family = None
    if lang == "ja":
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = next((name for name in _JAPANESE_FONTS if name in available), None)
        if family is None:
            raise RuntimeError("no Japanese font found for the Japanese figure")
    c = kd._CORE_WIDTHS * width
    f = kd._FLANK_WIDTHS * width
    threshold = 180.0 - float(np.degrees(kd.KinkDetector().threshold_angle_from_decomposed_indices))
    # Line, where the window is drawn, and how many kinks the detector must find.
    # 線、折れの区間を描く場所、検出器が見つけるべきキンクの数。
    cases = [
        (_polyline([0, 50], [6 * width, 6 * width]), "kink", 1),
        (_corner_on_arc(4 * width, 40, 8 * width), "kink", 1),
        (_ramped_arc(2 * width, 3 * width, 3 * width, 4 * width), "middle", 0),
    ]
    outline = [pe.withStroke(linewidth=4, foreground="white")]
    # The arrows below get a white edge so they stand out on the green window;
    # they are drawn under the heading curve, so the edge never hides it.
    # 下段の矢印には白い縁を付け、緑の折れの区間の上でも目立つようにする。矢印は
    # 向きの曲線の下に描くので、縁が曲線を隠すことはない。
    arrow_edge = [pe.withStroke(linewidth=4.4, foreground="white")]
    context = {"font.family": family} if family else {}
    with plt.rc_context(context):
        # The two rows get their own grids: the upper shapes have no axis
        # labels, so they can span the whole column width, while the lower
        # graphs keep room for theirs.
        # 上下の段はそれぞれ別の格子に置く。上段の形には軸ラベルが無いので列幅いっぱいに
        # 広げ、下段のグラフには軸ラベルの余地を残す。
        fig = plt.figure(figsize=(17.0, 17.0))
        upper_grid = fig.add_gridspec(1, 3, left=0.005, right=0.995, top=0.955, bottom=0.625,
                                      wspace=0.03)
        lower_grid = fig.add_gridspec(1, 3, left=0.075, right=0.985, top=0.53, bottom=0.26,
                                      wspace=0.33)
        for col, ((x, y), where, n_kinks) in enumerate(cases):
            _, s, length, sm, heading = kd._heading_profile(x, y, width)
            p, core, excess, background = _excess_curve(sm, heading, length, width)
            positions, _ = _judged_positions(x, y, width, p, excess)
            if len(positions) != n_kinks:
                raise RuntimeError("figure no longer matches KinkDetector.judge_line")
            p0 = positions[0] if where == "kink" else float(p[np.argmin(np.abs(p - length / 2))])
            i = int(np.argmin(np.abs(p - p0)))
            th0 = float(np.interp(p0 - c, sm, heading))
            th1 = float(np.interp(p0 + c, sm, heading))
            rate = float(np.sign(core[i]) * background[i])
            th_exp = th0 + rate * 2 * c
            t_deg, e_deg = float(np.degrees(abs(core[i]))), float(np.degrees(excess[i]))

            # ---- Upper panel: the fiber, the window, and T and E as angles.
            # ---- 上段: 繊維、折れの区間、角度としての T と E。
            ax = fig.add_subplot(upper_grid[0, col])
            xs, ys = np.interp(sm, s, x), np.interp(sm, s, y)
            nx, ny = -np.sin(heading), np.cos(heading)

            def band(lo, hi, colour):
                # One quadrilateral per step: a single outline would cross
                # itself on the inside of a sharp corner.
                # 1 歩ごとに四角形を塗る。1 つの輪郭にすると鋭い角の内側で輪郭が自分と交わる。
                idx = np.flatnonzero((sm >= lo) & (sm <= hi))
                lx, ly = xs + nx * width / 2, ys + ny * width / 2
                rx, ry = xs - nx * width / 2, ys - ny * width / 2
                for k0, k1 in zip(idx[:-1], idx[1:]):
                    ax.fill([lx[k0], lx[k1], rx[k1], rx[k0]], [ly[k0], ly[k1], ry[k1], ry[k0]],
                            color=colour, lw=1.2, ec=colour, zorder=1)

            def hatch(lo, hi):
                # The flanks are marked by hatching over the fiber, not by a
                # colour, so that blue can mean only the front end's direction.
                # 前後の区間は色ではなく繊維の上の斜線で示し、青を前の端の向きだけに使う。
                keep = (sm >= lo) & (sm <= hi)
                lx, ly = (xs + nx * width / 2)[keep], (ys + ny * width / 2)[keep]
                rx, ry = (xs - nx * width / 2)[keep], (ys - ny * width / 2)[keep]
                ax.fill(np.r_[lx, rx[::-1]], np.r_[ly, ry[::-1]], facecolor="none",
                        hatch=_FLANK_HATCH, edgecolor=_HATCH_COLOUR, lw=0, zorder=1.5)

            band(0.0, length, _FIBER_COLOUR)
            band(p0 - c, p0 + c, _WINDOW_COLOUR)
            hatch(p0 - c - f, p0 - c)
            hatch(p0 + c, p0 + c + f)
            # The centerline is thick, white-edged and drawn over the black
            # construction lines, so that it can be found at a glance wherever
            # they cross it. The two dashed tangents go on top, translucent: past
            # a corner between straight parts they lie along the centerline and
            # would vanish under it, and seen through them the centerline still
            # shows. The front end is pink rather than blue because translucent
            # blue over the green window turns teal, the colour of E.
            # 中心線は太くして白い縁を付け、黒の作図用の線の上に描き、それらが横切る所でも
            # ひと目で分かるようにする。2 本の接線の破線は半透明にして上に描く。まっすぐな
            # 部分にはさまれた角の先では中心線に重なり、下に描くと消えてしまうためで、透けて
            # 中心線も見える。前の端を青ではなくピンクにするのは、半透明の青が緑の折れの区間の
            # 上で E の色の青緑に見えるためである。
            ax.plot(x, y, color="black", lw=2.6, zorder=6.5,
                    path_effects=[pe.withStroke(linewidth=5.0, foreground="white")])
            # s runs towards a black arrowhead on the centerline itself, just
            # before the front flank.
            # s は、前の区間のすぐ手前の中心線上に描いた黒い矢じりの向きに増える。
            sa, sb = p0 - c - f - 1.1 * width, p0 - c - f - 0.3 * width
            ax.annotate("", xy=(np.interp(sb, s, x), np.interp(sb, s, y)),
                        xytext=(np.interp(sa, s, x), np.interp(sa, s, y)), zorder=6.6,
                        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.4,
                                        mutation_scale=18))
            # The letter sits right beside the arrowhead, just outside the band.
            # 文字は矢じりのすぐ横、帯のすぐ外に置く。
            na = float(np.interp(sb, sm, heading))
            sxl = np.interp(sb, s, x) + np.sin(na) * 0.85 * width
            syl = np.interp(sb, s, y) - np.cos(na) * 0.85 * width
            ax.text(sxl, syl, "s", fontsize=15, fontstyle="italic", color="black", ha="center",
                    va="center", zorder=6, path_effects=outline)
            # A kink is marked in blue, so that it cannot be taken for part of the
            # black centerline, and translucent, so that the centerline under it
            # still shows. Everything drawn over the centerline is translucent for
            # the same reason.
            # キンクは青で示し、黒の中心線の一部と取り違えられないようにする。また半透明に
            # して、下の中心線が見えるようにする。中心線の上に描くものは、同じ理由ですべて
            # 半透明にする。
            for q in positions:
                ax.plot(np.interp(q, s, x), np.interp(q, s, y), marker="x", color=_KINK_COLOUR,
                        mew=3.0, ms=1.6 * width, zorder=7, alpha=0.75)

            # T and E as angles between lines, drawn on the shape:
            # - the tangent at the front end (pink dashed);
            # - the tangent at the back end, drawn to both sides (orange dashed);
            #   T is the angle where it meets the pink line;
            # - the centerline assumed to keep turning at the flank rate from the
            #   front end (black dash-dot), and its tangent at the end (black
            #   dotted); E is the angle where that line meets the orange one.
            # 線の形の上に、線どうしの角度として T と E を描く。
            # - 前の端での接線（ピンクの破線）
            # - 後ろの端での接線。両側へ延ばす（オレンジの破線）。ピンクの線と交わる所の角が T
            # - 前の端から前後の区間の回転率で曲がり続けたと仮定した中心線（黒の一点鎖線）と、
            #   その終わりでの接線（黒の点線）。それがオレンジの線と交わる所の角が E
            fx, fy = float(np.interp(p0 - c, s, x)), float(np.interp(p0 - c, s, y))
            bx, by = float(np.interp(p0 + c, s, x)), float(np.interp(p0 + c, s, y))
            half = c + f + 1.5 * width
            tt = np.linspace(0.0, 2 * c, 121)
            ga = th0 + rate * tt
            gx = fx + np.concatenate([[0.0], np.cumsum(np.cos(ga[:-1]) * np.diff(tt))])
            gy = fy + np.concatenate([[0.0], np.cumsum(np.sin(ga[:-1]) * np.diff(tt))])

            def meet(px, py, a, qx, qy, b):
                det = np.sin(b - a)
                if abs(det) < np.sin(np.radians(2.0)):
                    return None
                u = ((qx - px) * np.sin(b) - (qy - py) * np.cos(b)) / det
                return px + u * np.cos(a), py + u * np.sin(a)

            reach = 0.45 * half
            t_at = meet(fx, fy, th0, bx, by, th1)
            e_at = meet(gx[-1], gy[-1], th_exp, bx, by, th1)
            # The two tangents are one kind of line, drawn alike: dashed, of one
            # width, over the centerline (whose white edge shows in the gaps),
            # and told apart only by colour, the colour of the bar at their end.
            # 2 本の接線は同じ種類の線なので同じに描く。同じ太さの破線で中心線の上に描き
            # （すき間から中心線の白い縁が見える）、色だけで区別する。色は、それぞれの端の
            # 棒と同じにする。
            ax.plot([fx, t_at[0] + reach * np.cos(th0)], [fy, t_at[1] + reach * np.sin(th0)],
                    color=_FRONT_COLOUR, lw=3.0, ls=_TANGENT_STYLE, zorder=6.55, alpha=0.5)
            start = t_at if e_at is None else min(
                (t_at, e_at), key=lambda q: (q[0] - bx) * np.cos(th1) + (q[1] - by) * np.sin(th1))
            ax.plot([start[0] - 0.1 * half * np.cos(th1), bx + reach * np.cos(th1)],
                    [start[1] - 0.1 * half * np.sin(th1), by + reach * np.sin(th1)],
                    color=_BACK_COLOUR, lw=3.0, ls=_TANGENT_STYLE, zorder=6.55, alpha=0.5)
            # The centerline the fiber would follow at the flank rate is a black
            # dash-dot line and its direction at the end a black dotted line, so
            # the two are told apart; both are translucent and drawn without an
            # edge, so the lines they cross still show.
            # 前後の区間の回転率で進んだ場合の中心線は黒の一点鎖線、その終わりでの向きは
            # 黒の点線にして区別する。どちらも半透明にして縁を付けず、交わる線が見えるように
            # する。
            ax.plot(gx, gy, color="black", lw=1.8, ls=_GHOST_STYLE, zorder=6, alpha=0.8)
            # The end direction runs well past the point where it meets the
            # back-end line, so that it can be seen even when that point is close.
            # Where it lies on a tangent, it stops where that tangent stops, so
            # that it reads as lying on it: on the pink one when the flanks do not
            # turn, on the orange one when E is 0.
            # 終わりでの向きの線は、後ろの端の線と交わる点の先まで十分に延ばし、交点が
            # 近くても見えるようにする。接線に重なる場合は、その接線と同じ所で止め、重なって
            # いると読めるようにする。前後の区間が回らないときはピンクの線、E が 0 のときは
            # オレンジの線である。
            tip = e_at if e_at is not None else (gx[-1], gy[-1])
            if e_at is None:
                stop = (bx + reach * np.cos(th1), by + reach * np.sin(th1))
            else:
                run = (1.0 if abs(rate) < 1e-9 else 1.4) * reach
                stop = (tip[0] + run * np.cos(th_exp), tip[1] + run * np.sin(th_exp))
            ax.plot([gx[-1], stop[0]], [gy[-1], stop[1]],
                    color="black", lw=2.0, ls=_END_STYLE, zorder=6, alpha=0.8)
            # A short bar across the fiber marks each end of the window, in the
            # colour of the tangent drawn there; the legend names the two, so the
            # crowded shape carries no labels for them.
            # 折れの区間の両端を、繊維を横切る短い棒で、そこで引く接線と同じ色で示す。
            # 2 つの名前は凡例に書き、混み合った形の上には書かない。
            end_bars = []
            for at in (p0 - c, p0 + c):
                ha_ = float(np.interp(at, sm, heading))
                ex, ey = float(np.interp(at, s, x)), float(np.interp(at, s, y))
                ux_, uy_ = -np.sin(ha_), np.cos(ha_)
                ax.plot([ex - ux_ * 0.75 * width, ex + ux_ * 0.75 * width],
                        [ey - uy_ * 0.75 * width, ey + uy_ * 0.75 * width],
                        color=_FRONT_COLOUR if at < p0 else _BACK_COLOUR, lw=2.6, zorder=6.6,
                        alpha=0.7)
                end_bars.append(np.c_[ex + ux_ * np.linspace(-0.75, 0.75, 7) * width,
                                      ey + uy_ * np.linspace(-0.75, 0.75, 7) * width])
            # The view takes in the window, both ends, the s arrow and the points
            # where the lines meet.
            # 表示範囲には、折れの区間、両端、s の矢印、線どうしが交わる点を含める。
            keyx = [fx, bx, gx[-1], t_at[0], sxl] + ([e_at[0]] if e_at is not None else [])
            keyy = [fy, by, gy[-1], t_at[1], syl] + ([e_at[1]] if e_at is not None else [])
            vx, vy = 0.5 * (min(keyx) + max(keyx)), 0.5 * (min(keyy) + max(keyy))
            view = max(0.5 * (max(keyx) - min(keyx)), 0.5 * (max(keyy) - min(keyy))) + 2.0 * width
            ax.set_xlim(vx - view, vx + view)
            ax.set_ylim(vy - view, vy + view)
            # Labels are placed in the free spot of the panel farthest from
            # everything drawn, and point at what they name with a thin leader
            # in their own colour, so no label sits on a line or on the fiber.
            # ラベルは、描いたものから最も離れた空き場所に置き、名前を付ける対象へ同じ色の
            # 細い引き出し線を引く。ラベルが線や繊維の上に乗らないようにする。
            drawn = [np.c_[xs, ys]]
            for xa, ya in (([fx, t_at[0] + reach * np.cos(th0)], [fy, t_at[1] + reach * np.sin(th0)]),
                           ([start[0], bx + reach * np.cos(th1)], [start[1], by + reach * np.sin(th1)]),
                           ([gx[-1], tip[0] + reach * np.cos(th_exp)],
                            [gy[-1], tip[1] + reach * np.sin(th_exp)])):
                drawn.append(np.c_[np.linspace(xa[0], xa[1], 40), np.linspace(ya[0], ya[1], 40)])
            drawn.append(np.c_[gx, gy])
            drawn.append(np.array([[sxl, syl]]))
            drawn.extend(end_bars)
            occupied = np.vstack(drawn)
            occupied_list = []
            # A 4 x 4 grid of spots, so that a crowded panel still has room.
            # 混み合ったパネルでも余地が残るよう、置き場所は 4 x 4 の格子にする。
            slots = [(fx_, fy_) for fy_ in (0.92, 0.64, 0.36, 0.08)
                     for fx_ in (0.06, 0.36, 0.64, 0.94)]

            def box(label, size, ux, uy):
                # Points covering the box a label anchored at (ux, uy) takes, in
                # data coordinates.
                # (ux, uy) を起点に置いたラベルが覆う範囲を、データ座標の点で表す。
                lines = label.split("\n") if label else [""]
                # A full-width (Japanese) character is about twice as wide.
                # 全角（日本語）の文字はおよそ 2 倍の幅がある。
                wide = max(sum(1.9 if ord(ch) > 0x2E80 else 1.0 for ch in line)
                           for line in lines) * 0.021 * size / 12.0
                tall = len(lines) * 0.055 * size / 12.0
                x0 = ux if ux < 0.3 else (ux - wide if ux > 0.7 else ux - wide / 2)
                y0 = uy if uy < 0.3 else (uy - tall if uy > 0.7 else uy - tall / 2)
                gxs, gys = np.meshgrid(np.linspace(x0, x0 + wide, 6),
                                       np.linspace(y0, y0 + tall, 3))
                return (vx - view + 2 * view * gxs.ravel(), vy - view + 2 * view * gys.ravel())

            def occupy(label, size, ux, uy):
                # A placed label takes its whole box, so the next one keeps clear of it.
                # 置いたラベルは範囲全体を占め、次のラベルがそこを避けるようにする。
                occupied_list.extend(zip(*box(label, size, ux, uy)))

            def free_spot(label="", size=14, target=None):
                # The whole box the text will cover is scored, not only its
                # anchor: a long note anchored at the edge runs inwards. A spot
                # near what the label names is preferred, to keep leaders short.
                # 文字の起点だけでなく、文字が覆う範囲全体で空き具合を測る。端に置いた
                # 長い注記は内側へ伸びるためである。引き出し線が短くなるよう、名前を
                # 付ける対象に近い場所を優先する。
                taken = np.vstack([occupied] + [np.array([q]) for q in occupied_list])
                # Spots whose text box keeps clear of everything drawn come
                # first, the one with the shortest leader among them; only when
                # none is clear is the least crowded spot taken.
                # 文字の範囲が描いたものから十分に離れる場所を先に考え、その中で引き出し線が
                # 最も短い場所を選ぶ。そういう場所が無いときだけ、最も空いている場所を取る。
                clear_by = 0.9 * width
                best_clear, best_open = None, None
                for ux, uy in slots:
                    px, py = box(label, size, ux, uy)
                    d = float(np.min(np.hypot(taken[:, 0][:, None] - px[None, :],
                                              taken[:, 1][:, None] - py[None, :])))
                    lead = (0.0 if target is None
                            else float(np.min(np.hypot(px - target[0], py - target[1]))))
                    # A leader may cross lines, but not a label already placed.
                    # 引き出し線は線を横切ってよいが、置いたラベルの上は通さない。
                    crosses = False
                    if target is not None and occupied_list:
                        ax_, ay_ = vx - view + 2 * view * ux, vy - view + 2 * view * uy
                        lx_ = np.linspace(ax_, target[0], 25)
                        ly_ = np.linspace(ay_, target[1], 25)
                        placed = np.array(occupied_list)
                        crosses = float(np.min(np.hypot(
                            placed[:, 0][:, None] - lx_[None, :],
                            placed[:, 1][:, None] - ly_[None, :]))) < 0.4 * width
                    if d >= clear_by and not crosses and (
                            best_clear is None or lead < best_clear[1]):
                        best_clear = ((ux, uy), lead)
                    if best_open is None or d > best_open[1]:
                        best_open = ((ux, uy), d)
                best = best_clear[0] if best_clear is not None else best_open[0]
                slots.remove(best)
                return best

            def place(label, colour, target, size=14, weight="bold", leader=True):
                # A leader is a thin dotted line, so it cannot be read as one of
                # the direction lines; a note about overlapping lines needs none.
                # 引き出し線は細い点線にし、向きの線と読み違えられないようにする。線の重なり
                # についての注記には引き出し線を付けない。
                ux, uy = free_spot(label, size, target)
                ha = "left" if ux < 0.3 else ("right" if ux > 0.7 else "center")
                va = "bottom" if uy < 0.3 else ("top" if uy > 0.7 else "center")
                ax.annotate(label, xy=target, xytext=(ux, uy), textcoords="axes fraction",
                            color=colour, fontsize=size, fontweight=weight, ha=ha, va=va,
                            zorder=8, path_effects=outline,
                            arrowprops=(dict(arrowstyle="-", color=colour, lw=1.0, ls=":",
                                             shrinkA=2, shrinkB=2) if leader else None))
                occupy(label, size, ux, uy)

            # E's arc is small and close to the point where its lines meet, so
            # it cannot be taken for an angle at a neighbouring bend; when both
            # angles sit at one point, it lies inside T's.
            # E の円弧は小さくし、線が交わる点の近くに描いて、隣の折れの角と取り違え
            # ないようにする。2 つの角が同じ点にあるときは、T の円弧の内側になる。
            arc_labels = []
            for centre, a0, a1, r, colour, label, value in (
                    (t_at, th0, th1, 0.42 * half, _T_COLOUR, "T", t_deg),
                    (e_at, th_exp, th1, 0.28 * half, _E_COLOUR, "E", e_deg)):
                if centre is None:
                    continue
                lo, hi = sorted((np.degrees(a0), np.degrees(a1)))
                # Each arc crosses the centerline, so it is translucent like
                # everything else drawn over it, and thick enough to stand out on
                # the green window.
                # 円弧は中心線を横切るので、その上に描くほかのものと同じく半透明にし、緑の
                # 折れの区間の上でも目立つ太さにする。
                ax.add_patch(Arc(centre, 2 * r, 2 * r, theta1=lo, theta2=hi, color=colour,
                                 lw=3.4, zorder=7, alpha=0.75))
                mid = np.radians(0.5 * (lo + hi))
                arc_labels.append(("%s = %.0f°" % (label, value), colour,
                                   (centre[0] + r * np.cos(mid), centre[1] + r * np.sin(mid))))
            # Where lines lie on one another, say so with a leader line.
            # 線が重なる所には、引き出し線でそのことを書く。
            if abs(rate) < 1e-9:
                # The note names the flank whose rate made the subtraction zero:
                # both flat, or the one that does not turn. A case where only a
                # flank turning the other way makes it zero has no note here and
                # stops the figure, so the note can never name the wrong reason.
                # 注記は、差し引く量を 0 にした前後の区間を書く。両方がまっすぐか、回らない
                # 側か。逆向きに回る区間だけで 0 になる場合はここに注記が無く、図を止めるので、
                # 注記が誤った理由を書くことはない。
                r_left = (th0 - float(np.interp(p0 - c - f, sm, heading))) / f
                r_right = (float(np.interp(p0 + c + f, sm, heading)) - th1) / f
                still = np.radians(1.0) / f
                if abs(r_left) < still and abs(r_right) < still:
                    note = text["same_flat"]
                elif abs(r_left) < still:
                    note = text["same_front"]
                elif abs(r_right) < still:
                    note = text["same_back"]
                else:
                    raise RuntimeError("the figure has no note for this case")
                place(note, "black",
                      (t_at[0] + 0.7 * reach * np.cos(th0), t_at[1] + 0.7 * reach * np.sin(th0)),
                      size=12, weight="normal", leader=False)
            if e_at is None:
                place(text["zero"], _E_COLOUR,
                      (bx + 0.6 * reach * np.cos(th1), by + 0.6 * reach * np.sin(th1)),
                      size=13, weight="bold", leader=False)
            # The angle labels go last, so that their leaders keep clear of the
            # notes placed above.
            # 角度のラベルは最後に置き、引き出し線が上で置いた注記を避けるようにする。
            for label, colour, target in arc_labels:
                place(label, colour, target)
            if not positions:
                ux, uy = free_spot(text["none"], 13)
                ax.text(ux, uy, text["none"], transform=ax.transAxes, color="black",
                        fontsize=13, fontweight="bold",
                        ha="left" if ux < 0.3 else ("right" if ux > 0.7 else "center"),
                        va="bottom" if uy < 0.3 else ("top" if uy > 0.7 else "center"),
                        zorder=8, path_effects=outline)
            ax.set_aspect("equal")
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color("0.85")
            ax.set_title(text["names"][col], fontsize=14)

            # ---- Lower panel: the heading, with T and E as arrows.
            # ---- 下段: 向きと、矢印としての T と E。
            ax = fig.add_subplot(lower_grid[0, col])
            deg = np.degrees(heading - heading[0])
            for lo, hi in ((p0 - c - f, p0 - c), (p0 + c, p0 + c + f)):
                ax.axvspan(lo / width, hi / width, facecolor="none", hatch=_FLANK_HATCH,
                           edgecolor=_HATCH_COLOUR, lw=0, zorder=0)
            ax.axvspan((p0 - c) / width, (p0 + c) / width, color=_WINDOW_COLOUR, lw=0, zorder=0)
            ax.plot(sm / width, deg, color="black", lw=2.6, zorder=4.5,
                    path_effects=[pe.withStroke(linewidth=5.0, foreground="white")])
            th_l = float(np.interp(p0 - c, sm, deg))
            th_r = float(np.interp(p0 + c, sm, deg))
            ext = th_l + float(np.degrees(rate) * 2 * c)
            xb = (p0 + c) / width
            # A straight line keeps one heading, so each tangent of the upper
            # panel is a horizontal line here, drawn exactly as there: the pink
            # and orange dashed tangents at the heading of the front and back
            # ends, and the dotted tangent of the assumed centerline at the
            # heading it ends with. T and E are then the gaps between these
            # lines, as they are the angles between them above. Like the upper
            # tangents they are translucent and drawn over the heading curve.
            # 直線は向きが一定なので、上段の接線はここでは水平線になり、上段と同じ見た目で
            # 描く。ピンクとオレンジの破線は前の端と後ろの端の向きの高さ、黒の点線は仮定した
            # 中心線が終わるときの向きの高さに引く。T と E は、上段でこれらの線がなす角で
            # あるのと同じく、ここではこれらの線の高さの差になる。上段の接線と同じく半透明に
            # して、向きの曲線の上に描く。
            xf = (p0 - c) / width
            ax.plot([xf - 0.5, xb + 0.5], [th_l, th_l], color=_FRONT_COLOUR, lw=3.0,
                    ls=_TANGENT_STYLE, zorder=4.6, alpha=0.5)
            ax.plot([xf - 0.5, xb + 0.8], [th_r, th_r], color=_BACK_COLOUR, lw=3.0,
                    ls=_TANGENT_STYLE, zorder=4.6, alpha=0.5)
            ax.plot([xf, xb], [th_l, ext], color="black", lw=2.8, ls=_GHOST_STYLE,
                    zorder=4, alpha=0.8)
            ax.plot([xb, xb + 0.8], [ext, ext], color="black", lw=2.0, ls=_END_STYLE,
                    zorder=4, alpha=0.8)
            # E stands at the back end of the window, where it is measured. T
            # stands at the front end, where the curve is still at the pink
            # line's level, so the arrow and its letter keep clear of the curve.
            # E は、それを測る折れの区間の後ろの端に立てる。T は、曲線がまだピンクの線の
            # 高さにある前の端に立て、矢印と文字が曲線から離れるようにする。
            xt, xe = xf, xb
            ax.annotate("", xy=(xt, th_r), xytext=(xt, th_l), zorder=4.4,
                        arrowprops=dict(arrowstyle="<|-|>", color=_T_COLOUR, lw=2.4,
                                        mutation_scale=16, path_effects=arrow_edge))
            # T is labelled left of its arrow, at the height farthest from the
            # ×, the heading curve and the construction lines, so it sits
            # on none of them. Distances are measured in approximate pixels of the
            # panel (about 320 x 300), over the whole box the letter covers; the ×
            # counts as a disc of its marker's size.
            # T は矢印の左に、×、向きの曲線、作図用の線から最も離れる高さに書き、
            # どれの上にも乗らないようにする。距離はパネル（およそ 320 x 300）上の
            # おおよその画素で、文字が覆う範囲全体について測る。× はマーカーの大きさの
            # 円として数える。
            span = float(deg.max() - deg.min())
            x_right = max(length / width, p0 / width + 3.0)
            px_w, px_d = 320.0 / x_right, 300.0 / (1.1 * span)
            lines_at = np.vstack(
                [np.c_[sm / width, deg],
                 np.c_[np.linspace(xf - 0.5, xb + 0.5, 30), np.full(30, th_l)],
                 np.c_[np.linspace(xf - 0.5, xb + 0.8, 30), np.full(30, th_r)],
                 np.c_[np.linspace(xf, xb, 30), np.linspace(th_l, ext, 30)]])
            marks_at = np.array([[q / width, float(np.interp(q, sm, deg))] for q in positions]
                                ).reshape(-1, 2)
            best_level, best_gap = 0.5, -np.inf
            for t_level in np.linspace(0.1, 0.9, 17):
                ly = th_l + t_level * (th_r - th_l)
                bx_, by_ = np.meshgrid(xt - 0.12 - np.linspace(0.0, 13.0, 4) / px_w,
                                       ly + np.linspace(-8.0, 8.0, 3) / px_d)
                bx_, by_ = bx_.ravel(), by_.ravel()
                gap = float(np.min(np.hypot((lines_at[:, 0][:, None] - bx_) * px_w,
                                            (lines_at[:, 1][:, None] - by_) * px_d)))
                if len(marks_at):
                    gap = min(gap, float(np.min(np.hypot(
                        (marks_at[:, 0][:, None] - bx_) * px_w,
                        (marks_at[:, 1][:, None] - by_) * px_d))) - 7.0)
                if gap > best_gap:
                    best_level, best_gap = t_level, gap
            ax.text(xt - 0.12, th_l + best_level * (th_r - th_l), "T", color=_T_COLOUR, fontsize=16,
                    fontweight="bold", ha="right", va="center", zorder=6, path_effects=outline)
            if abs(th_r - ext) > 2.0:
                ax.annotate("", xy=(xe, th_r), xytext=(xe, ext), zorder=4.4,
                            arrowprops=dict(arrowstyle="<|-|>", color=_E_COLOUR, lw=2.4,
                                            mutation_scale=16, path_effects=arrow_edge))
                ax.text(xe + 0.15, ext + 0.75 * (th_r - ext), "E", color=_E_COLOUR, fontsize=16,
                        fontweight="bold", va="center", zorder=6, path_effects=outline)
            else:
                # With no arrow to label, the value stands well away from T's arrow.
                # 名前を付ける矢印が無いので、値は T の矢印から十分離して書く。
                ax.text(xb + 0.7, th_r - 0.04 * span, "E = 0°", color=_E_COLOUR, fontsize=15,
                        fontweight="bold", ha="left", va="top", zorder=6, path_effects=outline)
            # Where the dash-dot heading is hidden under another line, say so, as
            # the upper panel does.
            # 一点鎖線の向きが別の線の下に隠れる所では、上段と同じくそのことを書く。
            if abs(rate) < 1e-9:
                ax.text(xb + f / width + 0.2, th_l + 0.05 * span, text["low_flat"], fontsize=12,
                        ha="left", va="bottom", zorder=6, path_effects=outline)
            elif abs(th_r - ext) <= 2.0:
                # Bottom right, below the curve, where the panel is empty.
                # 曲線より下の、空いている右下に書く。
                ax.text(x_right - 0.3, 0.05 * span, text["low_curve"],
                        fontsize=10.5, ha="right", va="bottom", zorder=6, path_effects=outline)
            for q in positions:
                ax.plot(q / width, float(np.interp(q, sm, deg)), marker="x", color=_KINK_COLOUR,
                        mew=3.0, ms=13, zorder=7, alpha=0.75)
            # Every graph starts where the fiber starts, so that 0° on the
            # vertical axis is the heading at the left end.
            # どのグラフも繊維の始まりから描き、縦軸の 0° が左端の向きになるようにする。
            ax.set_xlim(0.0, x_right)
            ax.tick_params(labelsize=11)
            verdict = (text["kink_verdict"] if e_deg >= threshold else text["no_verdict"]) % threshold
            values = text["values"] % (t_deg, e_deg) + verdict
            ax.set_title("%s\n%s" % (text["notes"][col], values), fontsize=12.5)
            ax.set_xlabel(text["xlabel"], fontsize=12)
            ax.set_ylabel(text["ylabel"], fontsize=12)
        # One legend for both rows, and the meaning of T and E, below the figure.
        # 上下段に共通の凡例と、T と E の意味を図の下に置く。
        handles = [Patch(color=_FIBER_COLOUR, label=text["fiber"]),
                   Patch(color=_WINDOW_COLOUR, label=text["window"]),
                   Line2D([], [], color=_FRONT_COLOUR, lw=0, marker="|", mew=2.6, ms=14,
                          label=text["ends"]),
                   Line2D([], [], color=_BACK_COLOUR, lw=0, marker="|", mew=2.6, ms=14,
                          label=text["back_bar"]),
                   Patch(facecolor="white", hatch=_FLANK_HATCH, edgecolor=_HATCH_COLOUR,
                         label=text["flank"]),
                   Line2D([], [], color="black", lw=2.6, label=text["line"]),
                   Line2D([], [], color="black", lw=0, marker=">", ms=9, label=text["sdir"]),
                   Line2D([], [], color=_KINK_COLOUR, lw=0, marker="x", mew=3, ms=11,
                          label=text["kink"]),
                   Line2D([], [], color=_FRONT_COLOUR, lw=3.0, ls=_TANGENT_STYLE,
                          label=text["front"]),
                   Line2D([], [], color=_BACK_COLOUR, lw=3.0, ls=_TANGENT_STYLE,
                          label=text["back"]),
                   Line2D([], [], color="black", lw=1.8, ls=_GHOST_STYLE, label=text["ghost"]),
                   Line2D([], [], color="black", lw=2.0, ls=_END_STYLE, label=text["end"]),
                   Line2D([], [], color=_T_COLOUR, lw=2.4, label=text["tarc"]),
                   Line2D([], [], color=_E_COLOUR, lw=2.4, label=text["earc"])]
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.075), ncol=2,
                   fontsize=12, frameon=False)
        fig.text(0.5, 0.006, text["key"] % threshold, ha="center", va="bottom", fontsize=12)
        fig.savefig(path, dpi=75, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)


def _draw_arms(path, width):
    """
    Draw the arms of the first bend of a jog, cut short at the second bend.
    段差をつくる 2 つの折れのうち 1 つ目の腕を、2 つ目の折れの手前で打ち切って描く。

    Notes
    -----
    The arm intervals follow the formula of `_arm_interior_angle`, and the
    angle read from them is checked against the angle `KinkDetector.judge_line`
    stores.
    腕の区間は `_arm_interior_angle` の式に従い、そこから読んだ角度を
    `KinkDetector.judge_line` が保存する角度と照合する。
    """
    x, y = _polyline([0, 45, 0], [6 * width, 1.375 * width, 6 * width])
    _, s, length, sm, heading = kd._heading_profile(x, y, width)
    p, _, excess, _ = _excess_curve(sm, heading, length, width)
    positions, judged = _judged_positions(x, y, width, p, excess)
    p1, p2 = sorted(positions)[:2]
    gap = kd._ARM_GAP_WIDTHS * width
    arm = kd._ARM_LENGTH_WIDTHS * width
    left = (max(float(sm[0]), p1 - gap - arm), p1 - gap)
    right = (p1 + gap, min(float(sm[-1]), p1 + gap + arm, p2 - gap))
    uncut = (p1 + gap, min(float(sm[-1]), p1 + gap + arm))

    def mean_heading(lo, hi):
        return float(np.mean(np.interp(np.linspace(lo, hi, 16), sm, heading)))

    def angle(r):
        return np.degrees(max(np.pi - abs(mean_heading(*r) - mean_heading(*left)), 0.0))

    stored = np.degrees(judged.kink_angles[0])
    if abs(angle(right) - stored) > 1e-6:
        raise RuntimeError("figure no longer matches _arm_interior_angle")

    def xy(lo, hi):
        t = np.linspace(lo, hi, 50)
        return np.interp(t, s, x), np.interp(t, s, y)

    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.plot(x, y, color="#bbbbbb", lw=6, solid_capstyle="round")
    ax.plot(*xy(*uncut), color="#e6550d", lw=2.0, ls=":")
    ax.plot(*xy(*left), color="#3182bd", lw=3.0)
    ax.plot(*xy(*right), color="#e6550d", lw=3.0)
    for q, name in ((p1, "bend 1"), (p2, "bend 2")):
        qx, qy = np.interp(q, s, x), np.interp(q, s, y)
        ax.plot(qx, qy, "o", color="black", ms=5)
        ax.text(qx + 1.5, qy - 1.5, name, ha="left", va="bottom", fontsize=8)
    ax.set_aspect("equal")
    ax.set_xlim(p1 - 2.5 * width, p1 + 3.0 * width)
    ax.set_ylim(-0.6 * width, 1.3 * width)
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_title("corner drawn: 135 deg   stored angle of bend 1: %.0f deg   "
                 "with the uncut right arm: %.0f deg" % (stored, angle(uncut)), fontsize=9)
    fig.text(0.5, 0.02, "grey: centerline   blue: left arm   orange: right arm, cut "
             "short before bend 2   dotted orange: the right arm without the cut",
             ha="center", va="top", fontsize=8)
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


# Meiryo first: Yu Gothic sets the degree sign with a full-width gap after it.
# Meiryo を先にする。Yu Gothic は度記号の後ろに全角幅の空きを入れる。
_JAPANESE_FONTS = ("Meiryo", "Yu Gothic", "MS Gothic", "Noto Sans CJK JP", "IPAexGothic")

# The fiber of the real-scan kink figure: a bundled scan and a point next to the
# corner on it.
# 実データのキンクの図に使う繊維。同梱スキャンと、その繊維の角のそばの点。
REAL_FIBER_SCAN = "tunicate"
REAL_FIBER_CORNER_XY = (49.0, 788.0)

_REAL_TEXT = {
    "en": dict(
        a="a  Calibrated height and the fiber's centerline",
        b="b  Around the kink: the window and the flanks on the centerline",
        c="c  Heading θ(s) along the centerline",
        d="d  Turning T and excess E at every position p along the centerline",
        line="centerline", window="window (p ± c)", flank="flanks (length f)",
        width="W", kink="kink\nE = %.0f°", kink_short="kink", zoom="b",
        heading="heading θ(s)", expected="flank rate continued",
        t_curve="|T(p)|", e_curve="E(p)", threshold="threshold %.0f°",
        unjudged="not judged (within 1.5W of an end)",
        xlabel="position along the centerline s (px)", ylabel="heading (°)",
        ylabel_c="turning (°)", t_label="T = %.0f°", e_label="E = %.0f°"),
    "ja": dict(
        a="a  補正後の高さ像と、この繊維の中心線",
        b="b  キンクのまわり：中心線上の折れの区間と前後の区間",
        c="c  中心線に沿った向き θ(s)",
        d="d  中心線上の各位置 p での回転 T と超過回転 E",
        line="中心線", window="折れの区間（p ± c）", flank="前後の区間（長さ f）",
        width="W", kink="キンク\nE = %.0f°", kink_short="キンク", zoom="b",
        heading="向き θ(s)", expected="前後の区間の回転率を延ばした線",
        t_curve="|T(p)|", e_curve="E(p)", threshold="しきい値 %.0f°",
        unjudged="判定しない範囲（端から 1.5W 以内）",
        xlabel="中心線に沿った位置 s（画素）", ylabel="向き（°）",
        ylabel_c="回転（°）", t_label="T = %.0f°", e_label="E = %.0f°"),
}


def _real_fiber(scan, point):
    """
    Trace a bundled scan and return its calibrated image and the fiber line through a point.
    同梱スキャンを追跡し、補正後の画像と、ある点を通る繊維の線を返す。

    Notes
    -----
    The scan is analyzed with the default `ProcParams` into the kink reference's
    cache (`bundle_cache`), and the fiber is the one whose centerline passes
    within 2 px of `point`, so the figure does not depend on the order the
    fibers are listed in.
    スキャンは既定の `ProcParams` で解析し、キンク基準と同じキャッシュ
    （`bundle_cache`）に置く。繊維は中心線が `point` から 2 px 以内を通るものとし、
    繊維の並び順に図が左右されないようにする。
    """
    # Imported here: they pull in the whole pipeline, which the synthetic
    # figures do not need.
    # ここで読み込む。パイプライン全体を読み込むが、合成の図には要らない。
    from pathlib import Path

    import bundle_cache
    import kink_reference_score as krs
    from lib.pipeline import ProcParams

    cache = str(bundle_cache.cache_root(Path(PROJECT_ROOT) / ".tmp" / "kink_reference_cache"))
    image, fibers = krs.prepare_scan(scan, cache, ProcParams())
    cx, cy = point
    for fiber in fibers:
        x = np.asarray(fiber.xtrack, float) + float(fiber.data[0])
        y = np.asarray(fiber.ytrack, float) + float(fiber.data[1])
        if np.hypot(x - cx, y - cy).min() <= 2.0:
            return image.calibrated_image, x, y, float(fiber.width_px)
    raise RuntimeError("no fiber passes %s of %s any more; choose the fiber again"
                       % (point, scan))


def _draw_real_fiber(path, lang):
    """
    Draw the kink rule applied to one fiber of a bundled scan.
    同梱スキャンの繊維 1 本にキンク規則を当てはめた様子を描く。

    Notes
    -----
    The window, flanks, T and E are recomputed with `_excess_curve`, and the
    kink drawn is the one `KinkDetector.judge_line` finds next to
    `REAL_FIBER_CORNER_XY`; the figure fails to build when that kink is no
    longer found.
    折れの区間・前後の区間・T・E は `_excess_curve` で計算し直し、描くキンクは
    `KinkDetector.judge_line` が `REAL_FIBER_CORNER_XY` のそばに見つけるものとする。
    そのキンクが見つからなくなれば図は作れない。
    """
    import matplotlib.patheffects as pe
    from matplotlib import font_manager

    text = _REAL_TEXT[lang]
    family = None
    if lang == "ja":
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = next((name for name in _JAPANESE_FONTS if name in available), None)
        if family is None:
            raise RuntimeError("no Japanese font found for the Japanese figure")
    cal, x, y, width = _real_fiber(REAL_FIBER_SCAN, REAL_FIBER_CORNER_XY)
    c = kd._CORE_WIDTHS * width
    f = kd._FLANK_WIDTHS * width
    margin = kd.END_MARGIN_WIDTHS * width
    _, s, length, sm, heading = kd._heading_profile(x, y, width)
    p, core, excess, background = _excess_curve(sm, heading, length, width)
    positions, judged = _judged_positions(x, y, width, p, excess)
    cx, cy = REAL_FIBER_CORNER_XY
    near = [q for q in positions
            if np.hypot(np.interp(q, s, x) - cx, np.interp(q, s, y) - cy) <= width]
    if len(near) != 1:
        raise RuntimeError("figure no longer matches KinkDetector.judge_line")
    p0 = near[0]
    # The text says this is the fiber's only kink.
    # 本文は、これがこの繊維の唯一のキンクだと述べる。
    if len(positions) != 1:
        raise RuntimeError("the text on the real-fiber figure no longer matches the fiber")
    kx, ky = float(np.interp(p0, s, x)), float(np.interp(p0, s, y))
    i0 = int(np.argmin(np.abs(p - p0)))
    threshold = 180.0 - float(np.degrees(kd.KinkDetector().threshold_angle_from_decomposed_indices))
    outline = [pe.withStroke(linewidth=4, foreground="white")]

    def stretch(lo, hi):
        u = np.linspace(max(lo, 0.0), min(hi, length), 60)
        return np.interp(u, s, x), np.interp(u, s, y)

    # The text says nothing is subtracted at this kink because its left flank
    # turns the other way; check that it still does.
    # 本文は、左の前後の区間が逆向きに回るためこのキンクでは何も差し引かないと述べる。
    # それが今も成り立つことを確かめる。
    left = np.interp(p0 - c, sm, heading) - np.interp(p0 - c - f, sm, heading)
    if background[i0] != 0.0 or np.sign(left) == np.sign(core[i0]):
        raise RuntimeError("the text on the real-fiber figure no longer matches the fiber")

    context = {"font.family": family} if family else {}
    with plt.rc_context(context):
        fig = plt.figure(figsize=(13.5, 14.0))
        grid = fig.add_gridspec(3, 2, height_ratios=(1.25, 0.9, 0.9))
        half = c + f + 1.5 * width

        def show(ax, x0, x1, y0, y1):
            x0, x1 = int(max(0, x0)), int(min(cal.shape[1], x1))
            y0, y1 = int(max(0, y0)), int(min(cal.shape[0], y1))
            crop = cal[y0:y1, x0:x1]
            ax.imshow(crop, cmap="gray", interpolation="nearest",
                      extent=(x0 - 0.5, x1 - 0.5, y1 - 0.5, y0 - 0.5),
                      vmin=np.percentile(crop, 1), vmax=np.percentile(crop, 99.5))
            ax.set_xlim(x0 - 0.5, x1 - 0.5)
            ax.set_ylim(y1 - 0.5, y0 - 0.5)
            ax.set_xticks([])
            ax.set_yticks([])

        ax = fig.add_subplot(grid[0, 0])
        pad = 3.0 * width
        show(ax, x.min() - pad, x.max() + pad, y.min() - pad, y.max() + pad)
        ax.plot(x, y, color="#00c8ff", lw=1.6, label=text["line"])
        ax.plot(kx, ky, "o", mfc="none", mec="#d7191c", mew=2.5, ms=18)
        ax.add_patch(plt.Rectangle((kx - half, ky - half), 2 * half, 2 * half, fill=False,
                                   ec="#ffd400", lw=2, ls="--"))
        ax.text(kx, ky + half + 2, text["zoom"], color="#7a5c00", fontsize=13,
                fontweight="bold", ha="center", va="top", path_effects=outline)
        ax.legend(fontsize=11, loc="upper right", framealpha=0.9)
        ax.set_title(text["a"], fontsize=13)

        ax = fig.add_subplot(grid[0, 1])
        show(ax, kx - half, kx + half, ky - half, ky + half)
        for lo, hi in ((p0 - c - f, p0 - c), (p0 + c, p0 + c + f)):
            ax.plot(*stretch(lo, hi), color="#3182bd", lw=14, alpha=0.8, solid_capstyle="butt")
        ax.plot(*stretch(p0 - c, p0 + c), color="#6cbf4a", lw=14, alpha=0.85,
                solid_capstyle="butt")
        ax.plot([], [], color="#3182bd", lw=8, label=text["flank"])
        ax.plot([], [], color="#6cbf4a", lw=8, label=text["window"])
        ax.plot(x, y, color="#00c8ff", lw=2, label=text["line"])
        # W drawn across the fiber just beyond the flank on the longer side.
        # W は長い側の前後の区間のすぐ先で、繊維を横切る向きに描く。
        pw = p0 + c + f + 0.75 * width if length - p0 > p0 else p0 - c - f - 0.75 * width
        hw = np.interp(pw, sm, heading)
        wx, wy = np.interp(pw, s, x), np.interp(pw, s, y)
        nx, ny = -np.sin(hw), np.cos(hw)
        ax.plot([wx - nx * width / 2, wx + nx * width / 2],
                [wy - ny * width / 2, wy + ny * width / 2], color="#ffd400", lw=5,
                solid_capstyle="butt")
        ax.text(wx + nx * (width / 2 + 2.5), wy + ny * (width / 2 + 2.5), text["width"],
                color="#7a5c00", fontsize=14, fontweight="bold", ha="center", va="center",
                path_effects=outline)
        ax.plot(kx, ky, "o", mfc="none", mec="#d7191c", mew=3, ms=30)
        ax.text(kx, ky + 0.6 * half, text["kink"] % np.degrees(excess[i0]), color="#d7191c",
                fontsize=14, fontweight="bold", ha="center", va="top", path_effects=outline)
        ax.legend(fontsize=11, loc="upper left", framealpha=0.9)
        ax.set_title(text["b"], fontsize=13)

        deg = np.degrees(heading)
        ax = fig.add_subplot(grid[1, :])
        for lo, hi in ((0.0, margin), (length - margin, length)):
            ax.axvspan(lo, hi, color="0.88", lw=0)
        ax.axvspan(p0 - c - f, p0 - c, color="#9ecae1", alpha=0.45, lw=0, label=text["flank"])
        ax.axvspan(p0 + c, p0 + c + f, color="#9ecae1", alpha=0.45, lw=0)
        ax.axvspan(p0 - c, p0 + c, color="#b5dd8f", alpha=0.8, lw=0, label=text["window"])
        ax.plot(sm, deg, color="black", lw=2.0, label=text["heading"])
        th_l = float(np.interp(p0 - c, sm, deg))
        th_r = float(np.interp(p0 + c, sm, deg))
        sense = np.sign(core[i0])
        ext = th_l + sense * np.degrees(background[i0]) * 2 * c
        ax.plot([p0 - c, p0 + c], [th_l, ext], "--", color="#3182bd", lw=2,
                label=text["expected"])
        # T on the left of the window and E on the right, so their labels
        # never overlap when nothing is subtracted.
        # T は折れの区間の左、E は右に描き、何も差し引かないときもラベルが重ならないようにする。
        xb = p0 - c - f - 1.5
        ax.annotate("", xy=(xb, th_r), xytext=(xb, th_l),
                    arrowprops=dict(arrowstyle="<->", color="#d94801", lw=2))
        ax.plot([xb, p0 - c], [th_l, th_l], ":", color="#d94801", lw=1.2)
        ax.plot([xb, p0 + c], [th_r, th_r], ":", color="#d94801", lw=1.2)
        ax.text(xb - 1.5, (th_l + th_r) / 2, text["t_label"] % np.degrees(abs(core[i0])),
                color="#d94801", fontsize=13, fontweight="bold", ha="right", va="center",
                path_effects=outline)
        xe = p0 + c + f + 1.5
        ax.annotate("", xy=(xe, th_r), xytext=(xe, ext),
                    arrowprops=dict(arrowstyle="<->", color="#6a3d9a", lw=2))
        ax.plot([p0 + c, xe], [ext, ext], ":", color="#6a3d9a", lw=1.2)
        ax.plot([p0 + c, xe], [th_r, th_r], ":", color="#6a3d9a", lw=1.2)
        ax.text(xe + 1.5, (ext + th_r) / 2, text["e_label"] % np.degrees(excess[i0]),
                color="#6a3d9a", fontsize=13, fontweight="bold", va="center",
                path_effects=outline)
        ax.set_xlim(0, length)
        ax.set_xlabel(text["xlabel"], fontsize=12)
        ax.set_ylabel(text["ylabel"], fontsize=12)
        ax.legend(fontsize=10, loc="best", framealpha=0.9)
        ax.set_title(text["c"], fontsize=13)

        ax = fig.add_subplot(grid[2, :])
        for k, (lo, hi) in enumerate(((0.0, margin), (length - margin, length))):
            ax.axvspan(lo, hi, color="0.88", lw=0, label=text["unjudged"] if k == 0 else None)
        ax.plot(p, np.degrees(np.abs(core)), color="#d94801", lw=1.8, label=text["t_curve"])
        ax.plot(p, np.degrees(excess), color="#6a3d9a", lw=2.4, label=text["e_curve"])
        ax.axhline(threshold, color="0.3", ls=":", lw=1.8)
        ax.text(length - margin - 1, threshold + 1.5, text["threshold"] % threshold,
                ha="right", va="bottom", fontsize=12, color="0.25")
        for q in positions:
            j = int(np.argmin(np.abs(p - q)))
            ax.plot(q, np.degrees(excess[j]), "o", mfc="none", mec="#d7191c", mew=2.5, ms=14)
            ax.text(q + 2.5, np.degrees(excess[j]), text["kink_short"], color="#d7191c",
                    fontsize=13, fontweight="bold", va="center", path_effects=outline)
        ax.set_xlim(0, length)
        ax.set_ylim(bottom=min(0.0, float(np.degrees(excess).min())) - 2)
        ax.set_xlabel(text["xlabel"], fontsize=12)
        ax.set_ylabel(text["ylabel_c"], fontsize=12)
        ax.legend(fontsize=11, loc="upper left", framealpha=0.9)
        ax.set_title(text["d"], fontsize=13)

        fig.tight_layout()
        fig.savefig(path, dpi=90, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
    return judged


_POINT_TEXT = {
    "en": dict(
        a="a  The centerline's points around the corner",
        b="b  Angle at each point, and the turning across the window",
        points="centerline points", pair="segments to the neighbours",
        window="window (p ± c)", neigh="angle between the segments to the neighbours",
        turn="|T(p)| across the window", threshold="threshold %.0f°",
        neigh_max="largest: %.0f°", xlabel="position along the centerline s (px)",
        ylabel="angle (°)"),
    "ja": dict(
        a="a  角のまわりの中心線の点",
        b="b  各点での角度と、折れの区間での回転",
        points="中心線の点", pair="隣の点との線分",
        window="折れの区間（p ± c）", neigh="隣の点との線分がなす角度",
        turn="折れの区間での回転 |T(p)|", threshold="しきい値 %.0f°",
        neigh_max="最大 %.0f°", xlabel="中心線に沿った位置 s（画素）",
        ylabel="角度（°）"),
}


def _draw_point_angles(path, lang):
    """
    Draw the angle at each point of a real centerline beside the turning across the window.
    実在の中心線の各点での角度を、折れの区間での回転と並べて描く。

    Notes
    -----
    The fiber is the one of `_draw_real_fiber`. The text says that along this
    fiber the angle between the segments to the neighbouring points stays below
    the threshold, at the corner as well, while the turning across the window
    at the corner reaches it; the figure fails to build when either no longer
    holds.
    繊維は `_draw_real_fiber` と同じもの。本文は、この繊維では隣の点との線分が
    なす角度が角でもしきい値に届かず、角での折れの区間の回転はしきい値に届くと
    述べる。どちらかが成り立たなくなれば図は作れない。
    """
    import matplotlib.patheffects as pe
    from matplotlib import font_manager

    text = _POINT_TEXT[lang]
    family = None
    if lang == "ja":
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = next((name for name in _JAPANESE_FONTS if name in available), None)
        if family is None:
            raise RuntimeError("no Japanese font found for the Japanese figure")
    cal, x, y, width = _real_fiber(REAL_FIBER_SCAN, REAL_FIBER_CORNER_XY)
    c = kd._CORE_WIDTHS * width
    margin = kd.END_MARGIN_WIDTHS * width
    _, s, length, sm, heading = kd._heading_profile(x, y, width)
    p, core, excess, _ = _excess_curve(sm, heading, length, width)
    positions, _ = _judged_positions(x, y, width, p, excess)
    threshold = 180.0 - float(np.degrees(kd.KinkDetector().threshold_angle_from_decomposed_indices))

    # Angle between the segments from each centerline point to its two
    # neighbours, at the arc length of that point.
    # 中心線の各点から両隣の点への線分がなす角度を、その点の弧長に置く。
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    step = np.arctan2(np.diff(y), np.diff(x))
    neigh = np.degrees(np.abs((np.diff(step) + np.pi) % (2.0 * np.pi) - np.pi))
    neigh_s = arc[1:-1]
    judged = (neigh_s >= margin) & (neigh_s <= length - margin)
    cx, cy = REAL_FIBER_CORNER_XY
    near = [q for q in positions
            if np.hypot(np.interp(q, arc, x) - cx, np.interp(q, arc, y) - cy) <= width]
    if len(near) != 1:
        raise RuntimeError("figure no longer matches KinkDetector.judge_line")
    p0 = near[0]
    i0 = int(np.argmin(np.abs(p - p0)))
    if neigh[judged].max() >= threshold or np.degrees(abs(core[i0])) < threshold:
        raise RuntimeError("the text on the point-angle figure no longer matches the fiber")
    around = judged & (np.abs(neigh_s - p0) <= width)
    k0 = int(np.flatnonzero(around)[np.argmax(neigh[around])]) + 1
    outline = [pe.withStroke(linewidth=4, foreground="white")]

    context = {"font.family": family} if family else {}
    with plt.rc_context(context):
        fig, axs = plt.subplots(1, 2, figsize=(14.0, 5.8),
                                gridspec_kw=dict(width_ratios=(1.0, 1.7)))
        ax = axs[0]
        kx, ky = float(np.interp(p0, arc, x)), float(np.interp(p0, arc, y))
        half = 2.0 * width
        x0, x1 = int(max(0, kx - half)), int(min(cal.shape[1], kx + half))
        y0, y1 = int(max(0, ky - half)), int(min(cal.shape[0], ky + half))
        crop = cal[y0:y1, x0:x1]
        ax.imshow(crop, cmap="gray", interpolation="nearest",
                  extent=(x0 - 0.5, x1 - 0.5, y1 - 0.5, y0 - 0.5),
                  vmin=np.percentile(crop, 1), vmax=np.percentile(crop, 99.5))
        u = np.linspace(p0 - c, p0 + c, 60)
        # Green is the window, orange its turning, blue the segments to the
        # neighbours and their angle; no warm colour is drawn over another.
        # 緑は折れの区間、橙はその回転、青は隣の点との線分とその角度。暖色の上に暖色を
        # 重ねない。
        ax.plot(np.interp(u, arc, x), np.interp(u, arc, y), color="#6cbf4a", lw=16, alpha=0.8,
                solid_capstyle="butt", label=text["window"])
        ax.plot(x, y, "-o", color="#ffd400", lw=1.2, ms=4, label=text["points"])
        ax.plot(x[k0 - 1:k0 + 2], y[k0 - 1:k0 + 2], "-o", color="#1f5fbf", lw=3.5, ms=8,
                label=text["pair"])
        ax.set_xlim(x0 - 0.5, x1 - 0.5)
        ax.set_ylim(y1 - 0.5, y0 - 0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.legend(fontsize=10, loc="lower right", framealpha=0.9)
        ax.set_title(text["a"], fontsize=13)

        ax = axs[1]
        for lo, hi in ((0.0, margin), (length - margin, length)):
            ax.axvspan(lo, hi, color="0.88", lw=0)
        ax.axvspan(p0 - c, p0 + c, color="#b5dd8f", alpha=0.6, lw=0)
        ax.plot(neigh_s, neigh, "-o", color="#1f5fbf", lw=1.2, ms=3, label=text["neigh"])
        ax.plot(p, np.degrees(np.abs(core)), color="#e6550d", lw=2.6, label=text["turn"])
        ax.axhline(threshold, color="0.3", ls=":", lw=1.8)
        ax.text(length - margin - 1, threshold + 1.0, text["threshold"] % threshold, ha="right",
                va="bottom", fontsize=12, color="0.25")
        ax.annotate(text["neigh_max"] % neigh[k0 - 1], xy=(neigh_s[k0 - 1], neigh[k0 - 1]),
                    xytext=(neigh_s[k0 - 1] - 4.0 * width, neigh[k0 - 1] + 8.0),
                    color="#1f5fbf", fontsize=12, fontweight="bold", path_effects=outline,
                    arrowprops=dict(arrowstyle="->", color="#1f5fbf", lw=1.5))
        ax.set_xlim(0, length)
        ax.set_ylim(bottom=0)
        ax.set_xlabel(text["xlabel"], fontsize=12)
        ax.set_ylabel(text["ylabel"], fontsize=12)
        ax.legend(fontsize=10, loc="upper left", framealpha=0.9)
        ax.set_title(text["b"], fontsize=13)
        fig.tight_layout()
        fig.savefig(path, dpi=90, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    note = ("blue line: image edge   green: mask edge (half maximum)   "
            "red: skeleton")

    # A fiber crossing the whole image at an angle, leaving through the top and
    # the bottom edge: unpadded thinning bends both ends of the line toward a
    # corner of the cut.
    # 画像全体を斜めに横切り、上端と下端から外へ出る繊維。拡張せずに細線化すると、
    # 線の両端が切り口の角へ曲がる。
    shape = (48, 48)
    height = _ridge(shape, (-20, 4), (68, 40), sigma=3.4)
    mask = height > RIDGE_HEIGHT_NM / 2
    plain, padded = _plain_and_padded(mask)
    _draw(height, mask, [plain, padded], ["plain (not padded)", "padded"],
          (0, 48), (0, 48), os.path.join(OUT_DIR, "thin_border_oblique.png"), note)

    # A narrow fiber lying along the top edge beside one crossing it: padding
    # pushes the first one's line out of the image, so step 4 returns only that
    # component to the plain result, while the crossing fiber keeps the padded one.
    # 上端に沿って横たわる細い繊維と、上端を横切る繊維。拡張すると前者の線は画像の
    # 外へ出るので、手順 4 はその成分だけを plain に戻し、横切る繊維は padded の
    # 結果を保つ。
    height = np.maximum(_ridge(shape, (1, 4), (1, 22), sigma=1.3),
                        _ridge(shape, (-20, 26), (60, 50), sigma=3.4))
    mask = height > RIDGE_HEIGHT_NM / 2
    _draw_padding(height, mask, (0, 14), (0, 48),
                  os.path.join(OUT_DIR, "thin_border_along_edge.png"),
                  "solid blue: image edge   dashed blue: image edge inside the padded image   "
                  "green: mask edge   red: skeleton")

    _draw_hook(os.path.join(OUT_DIR, "terminal_hook.png"))

    # Kink figures work on synthetic centerlines given directly to the
    # detector, with an apparent width of 8 px.
    # キンクの図は、検出器に直接渡す合成の中心線で描く。見かけの幅は 8 px。
    _draw_heading(os.path.join(OUT_DIR, "kink_heading.png"), 8.0, "en")
    _draw_heading(os.path.join(OUT_DIR, "kink_heading.ja.png"), 8.0, "ja")
    _draw_arms(os.path.join(OUT_DIR, "kink_arms.png"), 8.0)

    # The rule on one fiber of a bundled scan, analyzed with the defaults.
    # 既定の設定で解析した同梱スキャンの繊維 1 本に規則を当てはめる。
    _draw_real_fiber(os.path.join(OUT_DIR, "kink_real_fiber.png"), "en")
    _draw_real_fiber(os.path.join(OUT_DIR, "kink_real_fiber.ja.png"), "ja")
    _draw_point_angles(os.path.join(OUT_DIR, "kink_point_angles.png"), "en")
    _draw_point_angles(os.path.join(OUT_DIR, "kink_point_angles.ja.png"), "ja")


if __name__ == "__main__":
    main()
