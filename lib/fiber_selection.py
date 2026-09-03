# -*- coding: utf-8 -*-
"""
Manual fiber exclusions recorded beside a ``.b2z`` bundle.
``.b2z`` バンドルの横に記録する、手動のファイバー除外情報。

Automatic filters cannot curate a dense network: on a typical entangled scan
almost every traced fiber touches a crossing, so a topological filter leaves
too few objects to analyze. What remains is visual judgement in the fiber
tracker — "this object is debris", "this one is a scan-line artifact" — and
this module is where that judgement is stored so it survives the session,
travels with the data, and can be audited and re-applied.
自動フィルターだけでは密なネットワークをキュレーションできない。絡み合った
典型的な走査では追跡されたほぼ全てのファイバーが交差に接するため、位相的な
フィルターでは解析対象が残らない。そこで必要になるのがファイバートラッカー上
での目視判断（「これはゴミ」「これは走査線アーティファクト」）であり、その判断を
セッションを越えて保持し、データと共に持ち運び、監査・再適用できるようにする
のが本モジュールである。

An exclusion is recorded as an anchor pixel on the excluded fiber's track,
not as its index in a fiber list. Indices are not stable: turning fiber
connection on or off, or changing a filter, renumbers the list and makes a
stored index point at a different object. A pixel coordinate keeps its meaning
across every tracing mode and is readable in the file itself.
除外はファイバーリスト内のインデックスではなく、除外対象のトラック上のアンカー
画素として記録する。インデックスは安定でない。ファイバー連結の ON/OFF や
フィルターの変更でリストの採番が変わり、保存済みインデックスが別の対象を指して
しまう。画素座標であればどの追跡モードでも意味が保たれ、ファイルを開けば内容も
読み取れる。
"""

# ===== Standard library =====
import json
import os
from typing import Dict, Iterable, List, Sequence, Set, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# Sidecar file naming, matching `lib.pipeline.param_path_for`'s convention of
# a suffix on the bundle stem.
# サイドカーファイルの命名。バンドル stem に接尾辞を付ける
# `lib.pipeline.param_path_for` の規約に合わせる。
EXCLUSION_SUFFIX = "_excluded.json"

# Value of the "format" key, so a reader can tell this file apart from any
# other JSON that happens to sit beside a bundle.
# "format" キーの値。バンドル横に置かれた他の JSON と区別できるようにする。
EXCLUSION_FORMAT = "afm-nanofiber-analyzer/excluded-fibers"

# Bumped only when the stored keys or their meaning change.
# 保存キーまたはその意味が変わったときにのみ更新する。
EXCLUSION_VERSION = 1


def exclusion_path_for(bundle_path: str) -> str:
    """
    Return the exclusion sidecar path for a bundle path.
    バンドルパスに対応する除外情報サイドカーのパスを返す。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle.
        ``.b2z`` バンドルのパス。

    Returns
    -------
    str
        Sidecar path, whether or not the file exists.
        サイドカーのパス。ファイルの存在有無にかかわらず返す。
    """
    return os.path.splitext(bundle_path)[0] + EXCLUSION_SUFFIX


def fiber_anchor(fiber) -> Tuple[int, int]:
    """
    Return the global pixel that identifies one fiber.
    1 本のファイバーを識別する全体像上の画素を返す。

    Parameters
    ----------
    fiber
        Traced fiber whose `data` holds its bounding-box origin.
        `data` に外接矩形の原点を持つ追跡済みファイバー。

    Returns
    -------
    tuple of int
        ``(x, y)`` in whole-image pixel coordinates (x=column, y=row),
        matching the bundle coordinate convention.
        全体像の画素座標での ``(x, y)``（x=列, y=行）。バンドルの座標規約に一致。

    Notes
    -----
    The midpoint of the track is used rather than an endpoint. Endpoints sit
    where a fiber was cut at a crossing, so neighbouring fragments can share
    one; a midpoint is interior to the object the user actually pointed at.
    端点ではなくトラックの中点を使う。端点は交差でファイバーが切断された位置に
    あり、隣接する断片同士で共有され得るが、中点はユーザーが実際に指した対象の
    内部にある。
    """
    x0, y0 = int(fiber.data[0]), int(fiber.data[1])
    mid = len(fiber.xtrack) // 2
    return (int(fiber.xtrack[mid]) + x0, int(fiber.ytrack[mid]) + y0)


def fiber_track_pixels(fiber) -> Set[Tuple[int, int]]:
    """
    Return every whole-image pixel a fiber's track passes through.
    ファイバーのトラックが通る全体像上の全画素を返す。

    Parameters
    ----------
    fiber
        Traced fiber with bounding-box-local track arrays.
        外接矩形ローカルのトラック配列を持つ追跡済みファイバー。

    Returns
    -------
    set of tuple
        ``(x, y)`` pixel coordinates in the whole image.
        全体像における ``(x, y)`` 画素座標。
    """
    x0, y0 = int(fiber.data[0]), int(fiber.data[1])
    xs = np.asarray(fiber.xtrack, dtype=int) + x0
    ys = np.asarray(fiber.ytrack, dtype=int) + y0
    return set(zip(xs.tolist(), ys.tolist()))


def constituent_anchors(fiber, fragments: Sequence = ()) -> List[Tuple[int, int]]:
    """
    Return the anchors that record one displayed fiber as excluded.
    表示中のファイバー 1 本を除外として記録するためのアンカー列を返す。

    Parameters
    ----------
    fiber
        Fiber the user rejected, as it is displayed. With fiber connection
        on this is a whole fibril; with it off it is a single fragment.
        ユーザーが却下した、表示されているままのファイバー。ファイバー連結が
        ON なら 1 本のフィブリル、OFF なら単一の断片である。
    fragments
        Traced fragments the displayed fiber was built from. Empty falls back
        to the fiber's own anchor, which is correct when no fragment list is
        available because the fiber is then a fragment itself.
        表示中のファイバーの構成元となった追跡済み断片。空の場合はファイバー
        自身のアンカーへフォールバックする。断片リストが無い状況ではファイバー
        自体が断片なので、これで正しい。

    Returns
    -------
    list of tuple of int
        One ``(x, y)`` anchor per constituent fragment, in fragment order.
        構成断片ごとに 1 つの ``(x, y)`` アンカーを、断片の順序で返す。

    Notes
    -----
    One anchor per constituent fragment, not one for the displayed fiber,
    because exclusions are applied to the fragments before reconnection (see
    `lib.measure.curate_fibers`). A connected fibril's own midpoint lies on
    only one of the fragments it was built from, so recording that single
    anchor would remove one fragment and let the others reconnect into a
    shorter fibril — the object the user rejected would partly come back, and
    the anchor would no longer match it. On a test scan, rejecting the longest
    fibril that way brought about a quarter of it back as a separate fiber.
    表示中のファイバーに 1 つではなく、構成断片ごとに 1 つのアンカーを記録する。
    除外は再結合より前に断片へ適用されるためである（`lib.measure.curate_fibers`
    参照）。連結済みフィブリルの中点は構成断片のうち 1 本の上にしか無いため、その
    1 つだけを記録すると断片 1 本が消えるだけで、残りが再結合してより短い
    フィブリルとして復活する。ユーザーが却下した対象が部分的に戻り、しかも
    アンカーはもうそれに一致しない。あるテスト画像では、最長のフィブリルをこの
    方法で却下したところ、その約 4 分の 1 が別のファイバーとして戻った。

    A fragment counts as constituent when more than half of its track lies on
    the displayed fiber. A bare intersection test would also catch a fragment
    the fibril merely crosses in a dense region.
    断片の判定は、そのトラックの半数を超える画素が表示中のファイバー上にある
    ことを条件とする。単なる共通部分の有無で判定すると、密な領域でフィブリルが
    横切っただけの断片まで拾ってしまう。
    """
    pixels = fiber_track_pixels(fiber)
    anchors = []
    for frag in fragments:
        frag_pixels = fiber_track_pixels(frag)
        if not frag_pixels:
            continue
        if len(frag_pixels & pixels) * 2 > len(frag_pixels):
            anchors.append(fiber_anchor(frag))
    return anchors or [fiber_anchor(fiber)]


def excluded_flags(
    fibers: Sequence,
    anchors: Iterable[Tuple[int, int]],
) -> List[bool]:
    """
    Flag which fibers a set of exclusion anchors selects.
    除外アンカーの集合がどのファイバーを選ぶかを判定する。

    Parameters
    ----------
    fibers
        Fibers to classify, from any tracing mode.
        判定対象のファイバー列。どの追跡モードのものでもよい。
    anchors
        Anchor pixels loaded from the sidecar file.
        サイドカーファイルから読み込んだアンカー画素。

    Returns
    -------
    list of bool
        One flag per input fiber, in the same order; True means excluded.
        入力と同順の判定フラグ。True は除外を意味する。

    Notes
    -----
    A fiber is excluded when its track passes through any anchor, rather than
    when its own anchor matches one. That is what makes the record survive a
    change of tracing mode: the same physical object is a fragment in one mode
    and part of a longer fibril in another, but the pixels under it are the
    same either way. An anchor that no longer lies on any track — because a
    height filter removed those pixels — simply selects nothing.
    ファイバー自身のアンカーが一致するかではなく、トラックがいずれかのアンカーを
    通るかで除外と判定する。これにより追跡モードが変わっても記録が意味を保つ。
    同じ物理的対象があるモードでは断片、別のモードではより長いフィブリルの一部に
    なるが、その下にある画素はどちらでも同じである。高さフィルターで画素が
    取り除かれるなどしてどのトラック上にも無くなったアンカーは、単に何も選ばない。
    """
    anchor_set = {(int(x), int(y)) for x, y in anchors}
    if not anchor_set:
        return [False] * len(fibers)
    return [bool(fiber_track_pixels(f) & anchor_set) for f in fibers]


def load_exclusions(path: str) -> List[Dict]:
    """
    Read exclusion records from a sidecar file.
    サイドカーファイルから除外レコードを読み込む。

    Parameters
    ----------
    path
        Sidecar path, typically from `exclusion_path_for`.
        サイドカーのパス。通常は `exclusion_path_for` の戻り値。

    Returns
    -------
    list of dict
        Records with integer ``x`` / ``y`` and a string ``note``. A missing
        file yields an empty list, because "nothing was excluded" and "no
        curation has been done" are the same thing for a reader.
        整数の ``x`` / ``y`` と文字列の ``note`` を持つレコード列。ファイルが
        無ければ空リストを返す。読み取り側にとって「何も除外されていない」と
        「キュレーションが行われていない」は同じ状態であるため。

    Raises
    ------
    ValueError
        If the file exists but is not a valid exclusion record set. A
        malformed sidecar is reported rather than ignored, because silently
        treating it as empty would quietly restore fibers the user excluded.
    """
    if not os.path.isfile(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON: {e}") from e

    if not isinstance(payload, dict) or payload.get("format") != EXCLUSION_FORMAT:
        raise ValueError(
            f"{path} is not an exclusion file (missing format {EXCLUSION_FORMAT!r})"
        )

    raw = payload.get("excluded", [])
    if not isinstance(raw, list):
        raise ValueError(f"{path} has a non-list 'excluded' entry")

    records = []
    for item in raw:
        if not isinstance(item, dict) or "x" not in item or "y" not in item:
            raise ValueError(f"{path} has an exclusion entry without x/y: {item!r}")
        records.append({
            "x": int(item["x"]),
            "y": int(item["y"]),
            "note": str(item.get("note", "")),
        })
    return records


def save_exclusions(path: str, bundle_name: str, records: Sequence[Dict]) -> None:
    """
    Write exclusion records to a sidecar file, or remove an empty one.
    除外レコードをサイドカーファイルへ書き出す。空なら削除する。

    Parameters
    ----------
    path
        Sidecar path to write.
        書き出し先のサイドカーパス。
    bundle_name
        Base name of the bundle the exclusions belong to, stored so the file
        is self-describing when read outside this project.
        除外が属するバンドルのベース名。本プロジェクト外で読んだときにも内容が
        分かるよう記録する。
    records
        Records with ``x``, ``y`` and optionally ``note``.
        ``x``, ``y``（および任意の ``note``）を持つレコード列。

    Notes
    -----
    Clearing every exclusion deletes the file instead of writing an empty
    list, so "no sidecar" always means "nothing excluded" and a stale file
    cannot outlive the curation it recorded.
    全ての除外を解除した場合は空リストを書かずファイルを削除する。これにより
    「サイドカーが無い」は常に「除外なし」を意味し、記録した内容より古い
    ファイルが残り続けることがない。
    """
    if not records:
        if os.path.isfile(path):
            os.remove(path)
        return

    payload = {
        "format": EXCLUSION_FORMAT,
        "version": EXCLUSION_VERSION,
        "bundle": bundle_name,
        "excluded": [
            {"x": int(r["x"]), "y": int(r["y"]), "note": str(r.get("note", ""))}
            for r in records
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
