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
from lib.skeletonizer import DEFAULT_BORDER_PAD, thin_ignoring_image_border  # noqa: E402

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


if __name__ == "__main__":
    main()
