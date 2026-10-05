# -*- coding: utf-8 -*-
"""
Generate the figures embedded in the algorithm documents.
アルゴリズム解説文書に載せる図を生成する。

Each figure is drawn from a synthetic height image run through the code the
document explains, so it can be regenerated whenever that code changes::

    .venv\\Scripts\\python.exe scripts\\make_doc_figures.py

The PNG files are written to ``docs/images/`` and are shared by
``docs/algorithms.md`` and ``docs/algorithms.ja.md``; their labels are fixed
English, as for every plot in this project.
各図は、文書が説明するコードに合成高さ画像を通して描くため、そのコードが
変わったときはいつでも作り直せる。PNG は ``docs/images/`` に書き出し、
英語版と日本語版の両方が共有する。図中の文字は、このプロジェクトの他の図と
同じく英語で固定する。
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
        ax.contour(mask[crop].astype(float), levels=[0.5], colors="#f2c94c", linewidths=0.8)
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
        ax.contour(xx, yy + top, m.astype(float), levels=[0.5], colors="#f2c94c",
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
          "blue line: image edge   yellow: mask edge (cut low, so the skirt is inside)   "
          "red: skeleton")


def _excess_curve(sm, heading, length, width):
    """
    Turning T and excess E at every heading sample, by the formula of `KinkDetector.judge_line`.
    `KinkDetector.judge_line` の式で、向きの各標本での回転 T と超過回転 E を求める。

    Returns ``(p, core, excess, background)``, the positions at least ``c``
    from both ends and the window turning, the excess turning and the
    subtracted flank rate there.
    両端から ``c`` 以上離れた位置と、そこでの窓の回転・超過回転・差し引いた脇の
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


def _draw_heading(path, width):
    """
    Draw the heading theta(s) of three lines with the window, the flanks, T and E.
    3 本の線の向き theta(s) に、窓・脇・T・E を重ねて描く。
    """
    c = kd._CORE_WIDTHS * width
    f = kd._FLANK_WIDTHS * width
    cases = [
        ("corner between straight arms", _polyline([0, 50], [6 * width, 6 * width]), "kink"),
        ("arc of radius 3 W", _arc_line(3 * width, 150, 5 * width), "middle"),
        ("jog: two bends turning back", _polyline([0, 45, 0], [6 * width, 1.375 * width, 6 * width]),
         "kink"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.6))
    for ax, (title, (x, y), where) in zip(axes, cases):
        _, _, length, sm, heading = kd._heading_profile(x, y, width)
        p, core, excess, background = _excess_curve(sm, heading, length, width)
        positions, _ = _judged_positions(x, y, width, p, excess)
        p0 = positions[0] if where == "kink" else float(p[np.argmin(np.abs(p - length / 2))])
        i = int(np.argmin(np.abs(p - p0)))
        deg = np.degrees(heading - heading[0])
        ax.axvspan((p0 - c - f) / width, (p0 - c) / width, color="#9ecae1", alpha=0.35, lw=0)
        ax.axvspan((p0 + c) / width, (p0 + c + f) / width, color="#9ecae1", alpha=0.35, lw=0)
        ax.axvspan((p0 - c) / width, (p0 + c) / width, color="#fdae6b", alpha=0.35, lw=0)
        ax.plot(sm / width, deg, color="#333333", lw=1.4)
        th_l = np.interp(p0 - c, sm, deg)
        th_r = np.interp(p0 + c, sm, deg)
        sense = np.sign(core[i])
        ext_end = th_l + sense * np.degrees(background[i]) * 2 * c
        ax.plot([(p0 - c) / width, (p0 + c) / width], [th_l, ext_end], "--", color="#3182bd", lw=1.2)
        xb = (p0 + c) / width + 0.08
        ax.annotate("", xy=(xb, th_r), xytext=(xb, th_l),
                    arrowprops=dict(arrowstyle="<->", color="#d94801", lw=1.0))
        ax.text(xb + 0.06, (th_l + th_r) / 2, "T", color="#d94801", va="center", fontsize=9)
        xe = xb + 0.45
        if abs(th_r - ext_end) > 2.0:
            ax.annotate("", xy=(xe, th_r), xytext=(xe, ext_end),
                        arrowprops=dict(arrowstyle="<->", color="#a50f15", lw=1.0))
            ax.text(xe + 0.06, (ext_end + th_r) / 2, "E", color="#a50f15", va="center",
                    fontsize=9)
        else:
            ax.text(xe, th_r, "E = 0", color="#a50f15", va="center", fontsize=9)
        ax.set_title("%s\nT = %.0f deg, E = %.0f deg" % (title, np.degrees(abs(core[i])),
                                                        np.degrees(excess[i])), fontsize=9)
        ax.set_xlabel("arc length s / W", fontsize=8)
        ax.set_ylabel("heading theta (deg)", fontsize=8)
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.text(0.5, 0.0, "orange: window p +/- c   blue bands: flanks of length f   "
             "dashed: turning continued at the flank rate subtracted", ha="center", va="top",
             fontsize=8)
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.05)
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


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    note = ("blue line: image edge   yellow: mask edge (half maximum)   "
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
                  "yellow: mask edge   red: skeleton")

    _draw_hook(os.path.join(OUT_DIR, "terminal_hook.png"))

    # Kink figures work on synthetic centerlines given directly to the
    # detector, with an apparent width of 8 px.
    # キンクの図は、検出器に直接渡す合成の中心線で描く。見かけの幅は 8 px。
    _draw_heading(os.path.join(OUT_DIR, "kink_heading.png"), 8.0)
    _draw_arms(os.path.join(OUT_DIR, "kink_arms.png"), 8.0)


if __name__ == "__main__":
    main()
