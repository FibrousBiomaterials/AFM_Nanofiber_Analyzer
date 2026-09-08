# -*- coding: utf-8 -*-
"""
Fiber-connection results recorded beside a ``.b2z`` bundle.
``.b2z`` バンドルの横に記録する、ファイバー連結の結果。

GUI04 decides which skeleton fragments are one fibril. That decision changes
what a "fiber" is, so a measurement made elsewhere — GUI03, the CLI — has to
reproduce the same fibrils instead of silently measuring something else. This
module is where the decision is stored so it survives the session and travels
with the data.
GUI04 は、どの骨格断片が 1 本のフィブリルなのかを決める。この決定は「ファイバー」
が何を指すかを変えるため、他の場所（GUI03、CLI）での計測が同じフィブリルを再現
できなければならない。さもなければ黙って別のものを計測することになる。本モジュール
はその決定を保存し、セッションを越えて保持しデータと共に持ち運べるようにする。

What is stored is the **result** — which fragments are joined, in what order
and orientation — and not the settings that produced it. Whether a join was
found automatically or made by hand is deliberately not recorded: once the
user has accepted a connection it is their decision either way, and a
distinction nothing acts on would only invite code that acts on it.
保存するのは**結果**、すなわちどの断片がどの順序と向きで繋がったかであり、それを
生んだ設定ではない。連結が自動で見つかったか手動で作られたかは意図的に記録しない。
ユーザーが受け入れた時点でどちらもその人の判断であり、何も参照しない区別を残せば、
それを参照するコードを招くだけである。

Notes
-----
Storing a result risks becoming a cache that disagrees with the bundle beside
it, which is why the record names fragments by an **anchor pixel on their
track** rather than by their pixel geometry. Re-analyzing the bundle in GUI01
changes the skeleton; an anchor then matches no fragment and the file is
refused, whereas a stored track would still "work" while describing a skeleton
that no longer exists. `skeleton_digest` makes that check immediate rather than
waiting for the anchors to miss.
結果を保存すると、横にあるバンドルと食い違うキャッシュになりかねない。そのため本
記録は断片を画素形状ではなく**トラック上のアンカー画素**で指す。GUI01 でバンドルを
再解析すると骨格が変わるが、そのときアンカーはどの断片にも一致せずファイルは拒否
される。一方、トラックそのものを保存していた場合は、既に存在しない骨格を記述した
まま「動いて」しまう。`skeleton_digest` は、アンカーが外れるのを待たずにその検査を
即座に行うためにある。

Only `ConnectParams.trim_points` and `ConnectParams.num_avg_points` affect the
fibril built from a stored chain; the other four thresholds gate the search and
cannot change a fiber once the chains are fixed. They are stored all the same,
so GUI04 can search again with what the user tuned and so the run is auditable.
保存された連鎖から作られるフィブリルに影響するのは `ConnectParams.trim_points` と
`ConnectParams.num_avg_points` だけである。残る 4 つは探索を制御するもので、連鎖が
確定した後のファイバーを変えることはできない。それでも保存するのは、GUI04 が
ユーザーの調整した値で再探索できるようにするためと、実行を監査可能にするため
である。
"""

# ===== Standard library =====
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .fiber_connector import ConnectParams
from .fiber_selection import fiber_anchor, fiber_track_pixels

# Sidecar file naming, matching `lib.fiber_selection.EXCLUSION_SUFFIX`'s
# convention of a suffix on the bundle stem.
# サイドカーファイルの命名。バンドル stem に接尾辞を付ける
# `lib.fiber_selection.EXCLUSION_SUFFIX` の規約に合わせる。
CONNECT_SUFFIX = "_connect.json"

# Value of the "format" key, so a reader can tell this file apart from the
# exclusion sidecar and from any other JSON beside a bundle.
# "format" キーの値。除外サイドカーや、バンドル横の他の JSON と区別できる
# ようにする。
CONNECT_FORMAT = "afm-nanofiber-analyzer/fiber-connection"

# Bumped when the stored keys or their meaning change. Reading a file whose
# version is newer than this is an error, not a best-effort parse.
# 保存キーまたはその意味が変わったときに更新する。この値より新しいバージョンの
# ファイルは、可能な範囲で解釈するのではなくエラーとする。
CONNECT_VERSION = 1

# `ConnectParams` field names, serialized verbatim into the "params" object.
# Renaming one silently drops the stored value back to its default, so the
# names are frozen exactly as `ProcParams` field names are (AGENTS.md §8.1).
# `ConnectParams` のフィールド名。"params" オブジェクトへそのまま直列化される。
# 名前を変えると保存値が黙って既定値へ戻るため、`ProcParams` のフィールド名と
# 同様に凍結する（AGENTS.md §8.1）。
CONNECT_PARAM_FIELDS: Tuple[str, ...] = (
    "clusters_range",
    "angle_threshold",
    "lookback_length",
    "num_avg_points",
    "height_diff_ratio",
    "trim_points",
)

# Fields stored as integers; the rest are stored as floats.
# 整数として保存するフィールド。残りは浮動小数点として保存する。
_INT_PARAM_FIELDS = frozenset(
    {"lookback_length", "num_avg_points", "trim_points"}
)


@dataclass(frozen=True)
class ChainMember:
    """
    One fragment's place in a connected fibril.
    連結されたフィブリルにおける、1 つの断片の位置づけ。

    Attributes
    ----------
    anchor
        ``(x, y)`` pixel on the fragment's track that identifies it, in whole
        image coordinates.
        断片を識別する、全体像座標での ``(x, y)`` 画素。トラック上にある。
    flip
        Whether the fragment's track runs backwards relative to the chain's
        direction and must be reversed before docking.
        断片のトラックが連鎖の向きに対して逆順であり、連結前に反転が必要か
        どうか。
    """

    anchor: Tuple[int, int]
    flip: bool


@dataclass(frozen=True)
class ConnectionPlan:
    """
    The connection result recorded for one bundle.
    1 つのバンドルについて記録された連結結果。

    Attributes
    ----------
    chains
        One chain per connected fibril, each an ordered sequence of members
        running from one terminal to the other. A fragment in no chain is
        measured on its own.
        連結されたフィブリルごとに 1 本の連鎖。各連鎖は一方の端から他方の端へ
        向かう順序付きのメンバー列である。どの連鎖にも属さない断片は単独で
        計測される。
    params
        Thresholds in effect when the result was produced.
        結果を作った時点で有効だったしきい値。
    skeleton_digest
        Fingerprint of the bundle's ``skeletonized`` array, so a bundle that
        has been re-analyzed since is detected instead of measured against a
        plan describing a skeleton it no longer has. Empty means unrecorded.
        バンドルの ``skeletonized`` 配列の指紋。以後に再解析されたバンドルを、
        既に持っていない骨格を記述したプランで計測してしまう前に検出する。空文字列
        は未記録を意味する。
    fragment_count
        How many fragments the bundle traced to when the result was made; a
        cheap secondary check. Zero means unrecorded.
        結果を作った時点でバンドルが追跡した断片数。簡便な補助検査であり、0 は
        未記録を意味する。
    """

    chains: Tuple[Tuple[ChainMember, ...], ...] = ()
    params: ConnectParams = ConnectParams()
    skeleton_digest: str = ""
    fragment_count: int = 0

    def joined_fragment_count(self) -> int:
        """
        Return how many fragments this plan places into a fibril.
        本プランがフィブリルへ組み入れる断片の数を返す。

        Returns
        -------
        int
            Total members across every chain.
            全連鎖のメンバー数の合計。
        """
        return sum(len(chain) for chain in self.chains)


def connect_path_for(bundle_path: str) -> str:
    """
    Return the connection sidecar path for a bundle path.
    バンドルパスに対応する連結サイドカーのパスを返す。

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
    return os.path.splitext(bundle_path)[0] + CONNECT_SUFFIX


def skeleton_digest(skeletonized) -> str:
    """
    Return a fingerprint of the skeleton a connection plan was built on.
    連結プランの構築元となった骨格の指紋を返す。

    Parameters
    ----------
    skeletonized
        The bundle's ``skeletonized`` array.
        バンドルの ``skeletonized`` 配列。

    Returns
    -------
    str
        ``"sha256:<hex>"`` over the array's shape and its bytes.
        配列の形状とバイト列に対する ``"sha256:<hex>"``。

    Notes
    -----
    Fingerprinting the skeleton rather than the whole bundle is deliberate: it
    is the only array the fragments — and therefore the anchors — are derived
    from, so it changes exactly when a stored plan stops describing the bundle.
    Hashing the calibrated image too would refuse plans over a re-run that
    moved a height by a rounding step without moving a single fragment.
    バンドル全体ではなく骨格に指紋を取るのは意図的である。断片、ひいてはアンカー
    が導かれる唯一の配列であり、保存済みプランがバンドルを記述しなくなるのと
    ちょうど同じタイミングで変化する。補正画像まで含めてハッシュすると、断片を
    1 つも動かさずに高さが丸め幅だけ動いた再実行に対してもプランを拒否してしまう。
    """
    arr = np.ascontiguousarray(skeletonized)
    h = hashlib.sha256()
    h.update(str(arr.shape).encode("ascii"))
    h.update(arr.astype(np.uint8, copy=False).tobytes())
    return "sha256:" + h.hexdigest()


def params_to_dict(params: ConnectParams) -> Dict:
    """
    Return the JSON-serializable form of connection thresholds.
    連結しきい値を JSON 直列化可能な形で返す。

    Parameters
    ----------
    params
        Thresholds to serialize.
        直列化するしきい値。

    Returns
    -------
    dict
        One entry per `CONNECT_PARAM_FIELDS` name.
        `CONNECT_PARAM_FIELDS` の各名前に対して 1 エントリ。
    """
    out: Dict = {}
    for name in CONNECT_PARAM_FIELDS:
        value = getattr(params, name)
        out[name] = int(value) if name in _INT_PARAM_FIELDS else float(value)
    return out


def params_from_dict(raw: Dict) -> ConnectParams:
    """
    Rebuild connection thresholds from a stored ``params`` object.
    保存された ``params`` オブジェクトから連結しきい値を復元する。

    Parameters
    ----------
    raw
        Mapping of field name to value, as written by `params_to_dict`.
        `params_to_dict` が書き出した、フィールド名から値への対応。

    Returns
    -------
    ConnectParams
        Thresholds with every missing field left at its dataclass default.
        欠けているフィールドをデータクラスの既定値のままにしたしきい値。

    Raises
    ------
    ValueError
        If a present field cannot be read as a number.
    """
    kwargs = {}
    for name in CONNECT_PARAM_FIELDS:
        if name not in raw:
            continue
        try:
            kwargs[name] = (
                int(raw[name]) if name in _INT_PARAM_FIELDS else float(raw[name])
            )
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"connection parameter {name!r} is not a number: {raw[name]!r}"
            ) from e
    return ConnectParams(**kwargs)


def plan_from_chains(
    fragments: Sequence,
    chains: Sequence[Sequence[Tuple[int, bool]]],
    params: ConnectParams,
    skeletonized=None,
    digest: str = "",
) -> ConnectionPlan:
    """
    Turn index-space chains into a storable plan.
    インデックス空間の連鎖を、保存可能なプランへ変換する。

    Parameters
    ----------
    fragments
        Traced fragments the chains index into.
        連鎖がインデックスで参照する追跡済み断片。
    chains
        ``(fragment_index, flip)`` sequences, as `plan_from_auto_connect`
        returns them or as GUI04 builds them from a manual connection.
        `plan_from_auto_connect` が返す、あるいは GUI04 が手動連結から作る
        ``(断片インデックス, 反転)`` の列。
    params
        Thresholds to record with the result.
        結果と共に記録するしきい値。
    skeletonized
        The bundle's skeleton, fingerprinted into the plan when given.
        バンドルの骨格。与えられた場合はプランへ指紋として記録する。
    digest
        A fingerprint already computed by the caller, used in preference to
        `skeletonized`. A GUI that hashes the skeleton once at load time can
        pass it here instead of holding the array for every later plan.
        呼び出し側が既に計算した指紋。`skeletonized` より優先して使う。読み込み時
        に骨格を 1 度ハッシュする GUI は、以後のプランのたびに配列を保持せず、
        こちらを渡せばよい。

    Returns
    -------
    ConnectionPlan
        Plan naming each member by its anchor pixel.
        各メンバーをアンカー画素で指すプラン。
    """
    stored = []
    for chain in chains:
        members = [
            ChainMember(anchor=fiber_anchor(fragments[int(i)]), flip=bool(flip))
            for i, flip in chain
        ]
        if len(members) >= 2:
            stored.append(tuple(members))
    if digest:
        fingerprint = digest
    elif skeletonized is not None:
        fingerprint = skeleton_digest(skeletonized)
    else:
        fingerprint = ""
    return ConnectionPlan(
        chains=tuple(stored),
        params=params,
        skeleton_digest=fingerprint,
        fragment_count=len(fragments),
    )


def resolve_plan_chains(
    fragments: Sequence,
    plan: ConnectionPlan,
) -> Tuple[List[List[Tuple[int, bool]]], int, int]:
    """
    Map a stored plan onto a fragment list, splitting where members are gone.
    保存済みプランを断片リストへ対応付け、欠けたメンバーの位置で連鎖を分割する。

    Parameters
    ----------
    fragments
        Fragments the plan is applied to, after any exclusions.
        除外適用後の、プランを適用する対象の断片列。
    plan
        Stored connection result.
        保存された連結結果。

    Returns
    -------
    tuple
        ``(chains, missing, splits)``: chains in index space ready for
        `lib.fiber_connector.build_connected_fibers`, how many members no
        longer resolve to a fragment, and how many stored chains came apart
        into more than one piece or vanished.
        ``(連鎖, 欠落数, 分割数)``。連鎖は
        `lib.fiber_connector.build_connected_fibers` へ渡せるインデックス空間の
        もの、欠落数はどの断片にも対応しなくなったメンバー数、分割数は 2 つ以上に
        割れた、または消滅した保存済み連鎖の本数である。

    Notes
    -----
    A chain whose member was excluded is **split, not discarded**. Discarding
    it would delete real fibers: dropping one speck of debris out of the middle
    of a fibril would take the whole fibril with it, which is the same failure
    `lib.measure.curate_fibers` avoids by ordering exclusion before connection.
    Splitting removes exactly the excluded fragment and leaves the surviving
    runs joined, so an exclusion can subtract from a connection but never
    create one — removing the middle of ``A-B-C`` leaves ``A`` and ``C``
    separate rather than joining them, because nobody decided they were one.
    メンバーが除外された連鎖は**破棄せず分割する**。破棄すると実在のファイバーが
    消える。フィブリルの途中からゴミを 1 粒落としただけでフィブリル全体が巻き添えに
    なり、これは `lib.measure.curate_fibers` が除外を連結より前に置くことで避けて
    いるのと同じ失敗である。分割は除外された断片だけを取り除き、残った連続部分の
    連結を保つ。したがって除外は連結を削ることはできても作ることはできない。
    ``A-B-C`` の中央を取り除くと ``A`` と ``C`` は別々に残り、繋がることはない。
    誰もそれを 1 本だと決めていないからである。
    """
    owner: Dict[Tuple[int, int], int] = {}
    for i, frag in enumerate(fragments):
        for pixel in fiber_track_pixels(frag):
            owner[pixel] = i

    resolved: List[List[Tuple[int, bool]]] = []
    missing = 0
    splits = 0
    taken: Dict[int, bool] = {}

    for chain in plan.chains:
        runs: List[List[Tuple[int, bool]]] = []
        run: List[Tuple[int, bool]] = []
        for member in chain:
            idx = owner.get((int(member.anchor[0]), int(member.anchor[1])))
            if idx is None or idx in taken:
                # A member whose fragment is gone (excluded, or the bundle no
                # longer traces to it) ends the run rather than the chain.
                # 断片が失われたメンバー（除外された、あるいはバンドルがもう
                # その断片へ追跡されない）は、連鎖ではなく連続部分を終わらせる。
                missing += 1
                if run:
                    runs.append(run)
                    run = []
                continue
            taken[idx] = True
            run.append((idx, bool(member.flip)))
        if run:
            runs.append(run)

        kept = [r for r in runs if len(r) >= 2]
        resolved.extend(kept)
        if len(kept) != 1 or len(kept[0]) != len(chain):
            splits += 1

    return resolved, missing, splits


def plan_with_chain(
    plan: ConnectionPlan,
    members: Sequence[ChainMember],
) -> ConnectionPlan:
    """
    Return the plan with one fibril replaced by a new, longer one.
    1 本のフィブリルを、新しくより長いものへ置き換えたプランを返す。

    Parameters
    ----------
    plan
        Plan to amend.
        修正対象のプラン。
    members
        The new chain, typically two fibrils the user just joined end to end.
        新しい連鎖。通常はユーザーが端どうしで繋いだ 2 本のフィブリル。

    Returns
    -------
    ConnectionPlan
        Plan with `members` added and every anchor it uses removed from
        wherever else it appeared.
        `members` を加え、そこで使われるアンカーを他の出現箇所から取り除いた
        プラン。

    Notes
    -----
    A fragment belongs to exactly one fibril, so joining it into a new chain
    takes it out of its old one. Removing it can leave the old chain in two
    pieces, and those pieces stay joined: the user connected this fragment
    elsewhere, which says nothing about the fragments that were on either side
    of it, and silently unmaking their connection would discard a decision
    they never revisited.
    1 つの断片が属するフィブリルはちょうど 1 本であるため、新しい連鎖へ組み入れる
    ことは、元の連鎖から取り出すことを意味する。取り出した結果、元の連鎖が 2 つに
    割れることがあるが、その各片は繋がったまま残す。ユーザーがこの断片を別の場所
    へ繋いだことは、その両隣にあった断片について何も述べておらず、それらの連結を
    黙って解くことは、ユーザーが見直してもいない決定を捨てることになる。
    """
    taken = {(int(m.anchor[0]), int(m.anchor[1])) for m in members}

    kept: List[Tuple[ChainMember, ...]] = []
    for chain in plan.chains:
        run: List[ChainMember] = []
        for member in chain:
            if (int(member.anchor[0]), int(member.anchor[1])) in taken:
                if len(run) >= 2:
                    kept.append(tuple(run))
                run = []
                continue
            run.append(member)
        if len(run) >= 2:
            kept.append(tuple(run))

    kept.append(tuple(members))
    return ConnectionPlan(
        chains=tuple(kept),
        params=plan.params,
        skeleton_digest=plan.skeleton_digest,
        fragment_count=plan.fragment_count,
    )


def plan_without_anchors(
    plan: ConnectionPlan,
    anchors: Sequence[Tuple[int, int]],
) -> ConnectionPlan:
    """
    Return the plan with every chain containing one of `anchors` dissolved.
    `anchors` のいずれかを含む連鎖をすべて解体したプランを返す。

    Parameters
    ----------
    plan
        Plan to amend.
        修正対象のプラン。
    anchors
        Anchor pixels of the fibrils to take apart.
        解体するフィブリルのアンカー画素。

    Returns
    -------
    ConnectionPlan
        Plan whose remaining chains contain none of `anchors`.
        残った連鎖のいずれにも `anchors` を含まないプラン。

    Notes
    -----
    Disconnecting dissolves the whole fibril rather than removing one member,
    because the user points at a fibril on screen, not at a junction inside it.
    Taking a member out of the middle would leave the two halves joined across
    the gap it left, which is a fibril they never saw.
    連結の解除は、メンバーを 1 つ取り除くのではなくフィブリル全体を解体する。
    ユーザーが指すのは画面上のフィブリルであって、その内部の接合部ではないため
    である。途中のメンバーを抜くと、空いた隙間をまたいで両側が繋がったままになり、
    それはユーザーが見たことのないフィブリルである。
    """
    drop = {(int(x), int(y)) for x, y in anchors}
    kept = tuple(
        chain for chain in plan.chains
        if not any(
            (int(m.anchor[0]), int(m.anchor[1])) in drop for m in chain
        )
    )
    return ConnectionPlan(
        chains=kept,
        params=plan.params,
        skeleton_digest=plan.skeleton_digest,
        fragment_count=plan.fragment_count,
    )


def plan_state_key(plan: Optional[ConnectionPlan]) -> str:
    """
    Return a comparable key for one connection state.
    1 つの連結状態を比較可能なキーとして返す。

    Parameters
    ----------
    plan
        Plan in effect, or ``None`` for no connection at all.
        有効なプラン。連結が全く無い場合は ``None``。

    Returns
    -------
    str
        Stable string identifying the state, for comparing what is in memory
        against what was last written.
        状態を一意に表す安定した文字列。メモリ上の状態と最後に書き出した内容の
        比較に用いる。

    Notes
    -----
    A plan with no chains keys the same as no plan at all, because the two
    measure identically and neither may be reported as something still to
    write. The thresholds are deliberately **not** part of the key: they no
    longer change any measured fiber once the chains are fixed, so a threshold
    edited while nothing is connected leaves nothing to save.
    連鎖を持たないプランは、プランが無い場合と同じキーになる。両者は計測上等価で
    あり、どちらも「まだ書き出すものがある」と報告してはならないからである。しきい値
    は意図的にキーへ含めない。連鎖が確定した後は計測されるファイバーを変えないため、
    何も連結していない状態でしきい値を変えても保存すべきものは生じない。
    """
    if plan is None or not plan.chains:
        return "()"
    body = [
        [[int(m.anchor[0]), int(m.anchor[1]), bool(m.flip)] for m in chain]
        for chain in plan.chains
    ]
    return json.dumps(body, sort_keys=True)


def load_connect_plan(path: str) -> Optional[ConnectionPlan]:
    """
    Read a connection plan from a sidecar file.
    サイドカーファイルから連結プランを読み込む。

    Parameters
    ----------
    path
        Sidecar path, typically from `connect_path_for`.
        サイドカーのパス。通常は `connect_path_for` の戻り値。

    Returns
    -------
    ConnectionPlan or None
        ``None`` when no sidecar exists, which is distinct from a stored plan
        with no chains: the first means nobody has decided, the second means
        somebody decided nothing connects. Both measure as fragments, but a
        caller reporting how many bundles carry a decision needs to tell them
        apart.
        サイドカーが無ければ ``None``。連鎖を持たない保存済みプランとは区別する。
        前者は「誰も決めていない」、後者は「何も繋がらないと決めた」を意味する。
        計測結果はどちらも断片だが、決定を持つバンドルが何個あるかを報告する
        呼び出し側には両者の区別が必要である。

    Raises
    ------
    ValueError
        If the file exists but is not a valid, readable plan. A malformed or
        too-new sidecar is reported rather than ignored, because silently
        falling back to "not connected" would measure fragments while the user
        believes whole fibrils were measured.
    """
    if not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON: {e}") from e

    if not isinstance(payload, dict) or payload.get("format") != CONNECT_FORMAT:
        raise ValueError(
            f"{path} is not a connection file "
            f"(missing format {CONNECT_FORMAT!r})"
        )

    version = payload.get("version", CONNECT_VERSION)
    if not isinstance(version, int) or version > CONNECT_VERSION:
        raise ValueError(
            f"{path} has format version {version!r}, newer than the supported "
            f"{CONNECT_VERSION}; update the software to read it"
        )

    if "chains" not in payload:
        # The development format stored a decision and its thresholds, and
        # re-ran the search at measurement time. There is no way to recover
        # which fragments it would have joined without running that search,
        # which is exactly what this format exists to stop doing.
        # 開発版の形式は決定としきい値を保存し、計測時に探索を再実行していた。
        # どの断片が連結されたはずかは、その探索を実行しない限り復元できない。
        # そして探索の再実行こそ、本形式がやめるために存在するものである。
        raise ValueError(
            f"{path} records connection settings rather than a connection "
            f"result; open the bundle in the fiber tracker, connect it, and "
            f"save to replace the file"
        )

    raw_params = payload.get("params", {})
    if not isinstance(raw_params, dict):
        raise ValueError(f"{path} has a non-object 'params' entry")

    raw_chains = payload["chains"]
    if not isinstance(raw_chains, list):
        raise ValueError(f"{path} has a non-list 'chains' entry")

    chains: List[Tuple[ChainMember, ...]] = []
    seen: Dict[Tuple[int, int], int] = {}
    for c, raw_chain in enumerate(raw_chains):
        members = raw_chain.get("members") if isinstance(raw_chain, dict) else None
        if not isinstance(members, list):
            raise ValueError(f"{path} chain {c} has no 'members' list")
        if len(members) < 2:
            raise ValueError(
                f"{path} chain {c} has {len(members)} member(s); a chain joins "
                f"at least two fragments"
            )
        built = []
        for item in members:
            if not isinstance(item, dict) or "anchor" not in item:
                raise ValueError(f"{path} chain {c} has a member without an anchor")
            anchor = item["anchor"]
            if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
                raise ValueError(
                    f"{path} chain {c} has a malformed anchor: {anchor!r}"
                )
            key = (int(anchor[0]), int(anchor[1]))
            if key in seen:
                # One fragment in two chains, or twice in one, describes a
                # fibril that cannot be built; reading it as either reading
                # would measure a population nobody chose.
                # 1 つの断片が 2 本の連鎖に、あるいは同じ連鎖に 2 度現れる記述は
                # 構築できないフィブリルを表す。どちらかに読み替えれば、誰も選んで
                # いない母集団を計測することになる。
                raise ValueError(
                    f"{path} uses anchor {key} in more than one chain member"
                )
            seen[key] = c
            built.append(ChainMember(anchor=key, flip=bool(item.get("flip", False))))
        chains.append(tuple(built))

    digest = payload.get("skeleton_digest", "")
    if not isinstance(digest, str):
        raise ValueError(f"{path} has a non-string 'skeleton_digest' entry")

    count = payload.get("fragment_count", 0)
    if not isinstance(count, int):
        raise ValueError(f"{path} has a non-integer 'fragment_count' entry")

    return ConnectionPlan(
        chains=tuple(chains),
        params=params_from_dict(raw_params),
        skeleton_digest=digest,
        fragment_count=count,
    )


def save_connect_plan(path: str, bundle_name: str, plan: ConnectionPlan) -> None:
    """
    Write a connection plan to a sidecar file.
    連結プランをサイドカーファイルへ書き出す。

    Parameters
    ----------
    path
        Sidecar path to write.
        書き出し先のサイドカーパス。
    bundle_name
        Base name of the bundle the plan belongs to, stored so the file is
        self-describing when read outside this project.
        プランが属するバンドルのベース名。本プロジェクト外で読んだときにも内容が
        分かるよう記録する。
    plan
        Result to record.
        記録する結果。

    Notes
    -----
    Unlike `lib.fiber_selection.save_exclusions`, a plan with no chains writes
    the file instead of deleting it. Deleting is right for exclusions because a
    stale file would restore fibers the user rejected; here the two states
    measure identically, and keeping the file preserves the thresholds the user
    tuned as well as the fact that "nothing in this bundle connects" was a
    decision rather than an omission.
    `lib.fiber_selection.save_exclusions` と異なり、連鎖の無いプランでもファイルを
    削除せず書き出す。除外で削除が正しいのは、古いファイルがユーザーの却下した
    ファイバーを復活させるからである。ここでは両者の計測結果は同じであり、ファイルを
    残すことでユーザーが調整したしきい値と、「このバンドルでは何も繋がらない」が
    省略ではなく決定であったことの両方を保てる。
    """
    payload = {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "bundle": bundle_name,
        "skeleton_digest": plan.skeleton_digest,
        "fragment_count": int(plan.fragment_count),
        "params": params_to_dict(plan.params),
        "chains": [
            {"members": [
                {"anchor": [int(m.anchor[0]), int(m.anchor[1])], "flip": bool(m.flip)}
                for m in chain
            ]}
            for chain in plan.chains
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
