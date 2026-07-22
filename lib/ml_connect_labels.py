# -*- coding: utf-8 -*-
"""
Executable schema for the fiber-connection label sidecar (process C).
ファイバー連結ラベル sidecar の実行可能スキーマ（工程C）。

Training the connection model needs human judgement: which pairs of skeleton
fragment ends belong to the same fibril. Those judgements are stored in a JSON
file beside the bundle they describe, leaving the ``.b2z`` itself untouched --
the same "sidecar" arrangement the pipeline already uses for
``<stem>_param.json``. This module is the single in-code definition of that
file's contract: its keys, vocabularies, version, and validation rules.
連結モデルの学習には人の判断が要る。どの骨格断片の端どうしが同一フィブリルに
属するか、という判断である。その判断は、対象バンドルの隣に置く JSON へ保存し、
``.b2z`` 自体は変更しない。パイプラインが ``<stem>_param.json`` で既に使っている
「sidecar」と同じ方式である。本モジュールはそのファイル契約（キー、語彙、
バージョン、検証規則）のコード上の唯一の定義である。

Design record: ``private_docs/design/connect-label-sidecar-format.ja.md``
(internal). Where that note and this code disagree, this code is the source of
truth, matching how `lib.bundle_schema` owns the ``.b2z`` contract.
設計記録は ``private_docs/design/connect-label-sidecar-format.ja.md``（非公開）。
記録と本コードが食い違う場合は本コードを正準とする。`lib.bundle_schema` が
``.b2z`` 契約を持つのと同じ関係である。

Identity is the endpoint coordinates / 同一性は端点座標で決まる
---------------------------------------------------------------
A decision names the two endpoint pixels it joins, not the fragment indices.
Fragment enumeration is deterministic for a fixed skeleton, but it is an
artifact of connected-component labelling; endpoint coordinates come from the
skeleton itself, so they keep their meaning if the enumeration ever changes,
and a human can point at them in the image to check a label. Fragment indices
are carried alongside as a convenience only and are never used to match.
判断は結合する 2 つの端点画素を指す。断片番号ではない。断片の列挙は骨格が同じなら
決定的だが、それは連結成分ラベリングに由来する実装上の産物である。端点座標は骨格
自体に由来するため、列挙方法が変わっても意味を保ち、人が画像上で指してラベルを
確認できる。断片番号は利便のために併記するだけで、照合には決して使わない。

Coordinates are written as ``{"x": int, "y": int}`` rather than bare pairs.
This repository uses both conventions in different places -- the ``.b2z``
``kp``/``dp`` arrays put x in row 0 and y in row 1, while
`lib.fiber_connector` handles ``(y, x)`` tuples internally -- and a bare pair
that is swapped between the two raises nothing; it silently produces wrong
labels. Naming the axes makes the mistake impossible.
座標は裸のペアではなく ``{"x": int, "y": int}`` で書く。本リポジトリは 2 つの規約を
併用しており（``.b2z`` の ``kp``/``dp`` は行 0 が x・行 1 が y、
`lib.fiber_connector` は内部で ``(y, x)`` タプルを扱う）、裸のペアを取り違えても
例外は出ず、静かに誤ったラベルになる。軸に名前を付ければ取り違え自体が起こらない。

No implicit positives / 暗黙の正例を置かない
---------------------------------------------
Every candidate shown to the reviewer carries an explicit verdict, including
`VERDICT_UNREVIEWED` for ones not yet decided. Treating "not rejected" as
accepted would make an unreviewed candidate indistinguishable from one a human
looked at and approved, so an overlooked wrong connection would be learned as a
positive. Explicit verdicts also keep the file self-contained: it can be
audited without regenerating the candidate set with the exact connector version
that produced it.
検分者へ提示した候補はすべて明示的な判定を持つ。未判断のものは
`VERDICT_UNREVIEWED` とする。「否定されていない＝採用」とみなすと、未検分の候補と
人が見て承認した候補が区別できず、見落とされた誤連結を正例として学習してしまう。
明示的な判定はファイルの自己完結性も保ち、候補集合を当時の連結器バージョンで
再生成しなくても監査できる。

This module depends only on the standard library and NumPy, so a GUI can read,
write, and validate labels without pulling in the machine-learning stack.
本モジュールの依存は標準ライブラリと NumPy のみ。GUI が機械学習スタックを読み込まずに
ラベルの読み書きと検証を行える。
"""

# ===== Standard library =====
import hashlib
import json
import os
import tempfile
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# Version of the label-file layout. Bump only when keys, vocabularies, or the
# meaning of a value change.
# ラベルファイル形式のバージョン。キー・語彙・値の意味が変わるときのみ繰り上げる。
LABEL_SCHEMA_VERSION = "1.0"

# Versions this code base can read. Unknown versions are rejected loudly so a
# future format change cannot be silently misread by an older release.
# 本コードベースが読める形式バージョン。未知のバージョンは明示的に拒否し、将来の
# 形式変更を旧リリースが黙って誤読しないようにする。
SUPPORTED_LABEL_VERSIONS = ("1.0",)

# Suffix appended to a bundle stem to form the sidecar name, mirroring the
# pipeline's existing "<stem>_param.json".
# sidecar 名を作るためにバンドル stem へ付ける接尾辞。パイプライン既存の
# "<stem>_param.json" に倣う。
LABEL_SUFFIX = "_connect_labels.json"

# The task these labels train, matching `lib.ml_schema.MODEL_TASKS`.
# これらのラベルが学習するタスク。`lib.ml_schema.MODEL_TASKS` と一致する。
LABEL_TASK = "connect"

# Verdicts a reviewer can give a candidate. Fixed English identifiers, not
# user-visible text; do not translate.
# 検分者が候補に与えられる判定。固定英語の識別子でユーザー表示文字列ではない
# ため翻訳しない。
VERDICT_CONNECT = "connect"        # The two ends belong to one fibril (positive).
VERDICT_REJECT = "reject"          # They do not (negative).
VERDICT_UNCERTAIN = "uncertain"    # The reviewer cannot tell; excluded from training.
VERDICT_UNREVIEWED = "unreviewed"  # Not decided yet; excluded from training.
VERDICTS = (VERDICT_CONNECT, VERDICT_REJECT, VERDICT_UNCERTAIN, VERDICT_UNREVIEWED)

# Verdicts that carry a training signal, mapped to their class label. The other
# two verdicts deliberately produce no sample at all.
# 学習信号を持つ判定と、そのクラスラベルの対応。他の 2 判定は意図的に
# サンプルを生成しない。
TRAINING_VERDICTS = {VERDICT_CONNECT: 1, VERDICT_REJECT: 0}

# Where a candidate came from. `manual` marks a connection the reviewer added
# that the classical connector never proposed, which is how a correct join
# rejected by the distance or height gate can still become a positive example.
# 候補の出所。`manual` は連結器が提示しなかったが検分者が追加した連結を示す。
# 距離ゲートや高さゲートに落とされた正しい連結を正例にできる唯一の経路である。
SOURCE_PROPOSED = "proposed"
SOURCE_MANUAL = "manual"
SOURCES = (SOURCE_PROPOSED, SOURCE_MANUAL)


def label_path_for(bundle_path: str) -> str:
    """
    Return the label sidecar path for a bundle path.
    バンドルパスに対応するラベル sidecar のパスを返す。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle the labels describe.
        ラベルが記述する ``.b2z`` バンドルのパス。

    Returns
    -------
    str
        Sibling path ``<bundle stem>_connect_labels.json``.
        同一ディレクトリの ``<バンドル stem>_connect_labels.json``。
    """
    return os.path.splitext(bundle_path)[0] + LABEL_SUFFIX


def skeleton_sha256(skeleton: np.ndarray) -> str:
    """
    Return a stable hash identifying a skeleton image.
    骨格画像を一意に識別する安定なハッシュを返す。

    Labels are meaningful only for the exact skeleton whose fragments they
    describe, so this hash -- not the bundle's ``input_sha256`` -- is what binds
    a sidecar to its bundle. Two bundles produced from one input with different
    parameters share an ``input_sha256`` but have different skeletons, so
    matching on the input hash alone would let labels be read against the wrong
    fragments.
    ラベルは、それが記述する断片を生んだ骨格に対してのみ意味を持つ。よって
    バンドルの ``input_sha256`` ではなく本ハッシュが sidecar とバンドルを結び付ける。
    同一入力からパラメータ違いで作られた 2 つのバンドルは ``input_sha256`` を共有
    するが骨格は異なるため、入力ハッシュだけで照合すると誤った断片に対してラベルを
    読んでしまう。

    Parameters
    ----------
    skeleton
        2D skeleton mask, as stored under the bundle's ``skeletonized`` key.
        バンドルの ``skeletonized`` キーに格納される 2 次元骨格マスク。

    Returns
    -------
    str
        Hex digest over the shape and the 0/1 pixel values.
        形状と 0/1 画素値に対する 16 進ダイジェスト。

    Notes
    -----
    The mask is normalized to C-contiguous ``uint8`` before hashing, so a bundle
    that stores it as ``bool`` and one that stores it as ``uint8`` yield the
    same digest. The shape is mixed in so two different images cannot collide
    through their flattened bytes alone.
    ハッシュ前にマスクを C 連続の ``uint8`` へ正規化するため、``bool`` で格納した
    バンドルと ``uint8`` で格納したバンドルが同じダイジェストになる。形状も混ぜる
    ことで、平坦化したバイト列だけで別画像が衝突することを防ぐ。
    """
    mask = np.ascontiguousarray(np.asarray(skeleton) != 0, dtype=np.uint8)
    digest = hashlib.sha256()
    digest.update(f"{mask.shape[0]}x{mask.shape[1]}:".encode("ascii"))
    digest.update(mask.tobytes())
    return digest.hexdigest()


def point(x: int, y: int) -> Dict[str, int]:
    """
    Build an endpoint coordinate object.
    端点座標オブジェクトを作る。

    Parameters
    ----------
    x, y
        Column and row index in the skeleton's coordinate frame.
        骨格の座標系における列・行のインデックス。

    Returns
    -------
    dict
        ``{"x": int, "y": int}``; the axes are named so an x/y swap cannot
        happen silently (see the module docstring).
        ``{"x": int, "y": int}``。軸に名前を付け、x/y の取り違えが黙って起きない
        ようにする（モジュール docstring 参照）。
    """
    return {"x": int(x), "y": int(y)}


def point_xy(pt: Dict[str, int]) -> Tuple[int, int]:
    """
    Return an endpoint object as an ``(x, y)`` tuple.
    端点オブジェクトを ``(x, y)`` タプルとして返す。
    """
    return int(pt["x"]), int(pt["y"])


def decision_key(decision: Dict) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Return a canonical, order-independent key for a decision's endpoint pair.
    判断の端点ペアに対する、順序に依存しない正準キーを返す。

    A connection is undirected, so the same pair written in either order must
    compare equal; sorting the two points gives that. Used to detect duplicate
    or contradicting decisions.
    連結は無向なので、同じペアはどちらの順で書かれても等しく比較されなければ
    ならない。2 点をソートすればそうなる。重複・矛盾する判断の検出に使う。
    """
    a, b = decision["endpoints"]
    pa, pb = point_xy(a), point_xy(b)
    return (pa, pb) if pa <= pb else (pb, pa)


def make_decision(
    endpoint_a: Dict[str, int],
    endpoint_b: Dict[str, int],
    verdict: str,
    *,
    source: str = SOURCE_PROPOSED,
    fragments: Optional[Sequence[int]] = None,
) -> Dict:
    """
    Build one decision entry.
    判断エントリを 1 件作る。

    Parameters
    ----------
    endpoint_a, endpoint_b
        The two endpoints this decision joins or separates, from `point`.
        この判断が結合または分離する 2 つの端点。`point` で作る。
    verdict
        One of `VERDICTS`.
        `VERDICTS` のいずれか。
    source
        One of `SOURCES`; ``manual`` marks a reviewer-added connection the
        classical connector never proposed.
        `SOURCES` のいずれか。``manual`` は連結器が提示せず検分者が追加した連結。
    fragments
        Optional fragment indices, recorded for convenience only. They are
        never used to match a decision to the skeleton, because the enumeration
        order is an implementation detail while the endpoints are not.
        任意の断片番号。利便のためだけに記録する。判断と骨格の照合には決して
        使わない。列挙順は実装の詳細だが端点はそうではないためである。

    Returns
    -------
    dict
        A decision entry conforming to the schema.
        スキーマに適合する判断エントリ。
    """
    entry: Dict = {
        "endpoints": [endpoint_a, endpoint_b],
        "verdict": verdict,
        "source": source,
    }
    if fragments is not None:
        entry["fragments"] = [int(f) for f in fragments]
    return entry


def make_labels(
    bundle_path: str,
    skeleton_hash: str,
    candidate_params: Dict,
    decisions: Sequence[Dict],
    *,
    created_utc: str,
    input_sha256: Optional[str] = None,
    reviewer: Optional[str] = None,
) -> Dict:
    """
    Build a conforming label document.
    契約に適合するラベル文書を組み立てる。

    Parameters
    ----------
    bundle_path
        Path to the bundle these labels describe; only its base name is stored.
        ラベルが記述するバンドルのパス。保存するのはその basename のみ。
    skeleton_hash
        `skeleton_sha256` of that bundle's ``skeletonized`` image.
        当該バンドルの ``skeletonized`` 画像の `skeleton_sha256`。
    candidate_params
        The `lib.fiber_connector.ConnectParams` values used to generate the
        proposed candidates, as a plain dict. Recorded because the candidate
        set a reviewer saw depends on these gates; without them the labels
        cannot be interpreted later, and there is no way to tell which
        connections were never offered for review.
        提示候補の生成に用いた `lib.fiber_connector.ConnectParams` の値（素の辞書）。
        検分者が見た候補集合はこれらのゲートに依存するため記録する。これが無いと
        後からラベルを解釈できず、どの連結がそもそも検分に出されなかったかも
        分からない。
    decisions
        Decision entries from `make_decision`.
        `make_decision` で作った判断エントリ。
    created_utc
        ISO-8601 UTC timestamp supplied by the caller.
        呼び出し側が与える ISO-8601 UTC のタイムスタンプ。
    input_sha256
        The bundle's recorded input hash, kept for provenance only; the
        skeleton hash is what binds the file.
        バンドルに記録された入力ハッシュ。来歴のためだけに保持する。ファイルを
        結び付けるのは骨格ハッシュである。
    reviewer
        Free-form reviewer identifier, or ``None``. Do not record personal
        information here.
        自由記述の検分者識別子、または ``None``。個人情報は記録しない。

    Returns
    -------
    dict
        JSON-serializable label document.
        JSON 直列化可能なラベル文書。

    Raises
    ------
    ValueError
        If the resulting document violates the contract; the message lists
        every problem, matching `lib.pipeline.process_file`.
        生成した文書が契約に違反する場合。`lib.pipeline.process_file` と同様、
        メッセージに全問題を列挙する。
    """
    entries = list(decisions)
    labels = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "task": LABEL_TASK,
        "bundle": {
            "file": os.path.basename(bundle_path),
            "skeleton_sha256": skeleton_hash,
        },
        "candidate_params": dict(candidate_params),
        "review": {
            # Derived, never claimed: a document is complete exactly when no
            # candidate is left undecided (see `review_complete`).
            # 主張ではなく導出する。未判断の候補が 1 件も無いときにのみ完了と
            # みなす（`review_complete` 参照）。
            "complete": not _has_unreviewed(entries),
            "created_utc": created_utc,
        },
        "decisions": entries,
    }
    if input_sha256 is not None:
        labels["bundle"]["input_sha256"] = input_sha256
    if reviewer is not None:
        labels["review"]["reviewer"] = reviewer

    problems = validate_labels(labels)
    if problems:
        raise ValueError(
            "connect label contract violation: " + "; ".join(problems))
    return labels


def validate_labels(
    labels: Dict,
    *,
    expected_skeleton_hash: Optional[str] = None,
    known_endpoints: Optional[Set[Tuple[int, int]]] = None,
) -> List[str]:
    """
    Check a label document against the contract.
    ラベル文書を契約と照合する。

    Parameters
    ----------
    labels
        Parsed label document.
        解析済みのラベル文書。
    expected_skeleton_hash
        When given, the document's skeleton hash must equal it. Supply the
        hash of the skeleton the labels are about to be used with, so labels
        belonging to a different skeleton are rejected instead of silently
        misapplied.
        指定時、文書の骨格ハッシュはこれと一致しなければならない。ラベルを適用
        しようとしている骨格のハッシュを渡すことで、別の骨格に属するラベルが黙って
        誤適用されるのを防ぎ、拒否できる。
    known_endpoints
        When given, every decision's endpoints must be members. Supply the real
        fragment endpoints of the target skeleton; this is the last line of
        defense against a coordinate swap or a drifted skeleton, both of which
        otherwise produce plausible-looking but wrong labels.
        指定時、各判断の端点はこの集合に含まれなければならない。対象骨格の実際の
        断片端点を渡す。座標の取り違えや骨格のずれに対する最後の砦であり、いずれも
        放置すると一見もっともらしいが誤ったラベルになる。

    Returns
    -------
    list of str
        Fixed English problem descriptions; empty when the document conforms.
        Callers translate or wrap as needed, matching `validate_bundle`.
        固定英語の問題記述リスト。適合していれば空。`validate_bundle` と同様、
        翻訳や文脈付けは呼び出し側で行う。
    """
    problems: List[str] = []

    if not isinstance(labels, dict):
        return [f"labels must be a JSON object, got {type(labels).__name__}"]

    version = labels.get("schema_version")
    if version is None:
        problems.append("missing 'schema_version'")
    elif version not in SUPPORTED_LABEL_VERSIONS:
        problems.append(
            f"unsupported label schema version {version!r} "
            f"(supported: {', '.join(SUPPORTED_LABEL_VERSIONS)})")

    task = labels.get("task")
    if task != LABEL_TASK:
        problems.append(f"task must be {LABEL_TASK!r}, got {task!r}")

    bundle = labels.get("bundle")
    if not isinstance(bundle, dict):
        problems.append("missing or malformed 'bundle' object")
    else:
        stored_hash = bundle.get("skeleton_sha256")
        if not stored_hash:
            problems.append("bundle: missing 'skeleton_sha256'")
        elif expected_skeleton_hash is not None and stored_hash != expected_skeleton_hash:
            problems.append(
                f"skeleton hash mismatch: labels were made for "
                f"{str(stored_hash)[:12]}... but the target skeleton is "
                f"{expected_skeleton_hash[:12]}...; these labels describe a "
                f"different skeleton")

    if not isinstance(labels.get("candidate_params"), dict):
        problems.append("missing or malformed 'candidate_params' object")

    review = labels.get("review")
    if not isinstance(review, dict):
        problems.append("missing or malformed 'review' object")
    elif not review.get("created_utc"):
        problems.append("review: missing 'created_utc'")

    decisions = labels.get("decisions")
    if not isinstance(decisions, list):
        problems.append("missing or malformed 'decisions' list")
        return problems

    seen: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    for i, entry in enumerate(decisions):
        problems.extend(_decision_problems(i, entry, known_endpoints, seen))

    return problems


def _decision_problems(
    index: int,
    entry: Dict,
    known_endpoints: Optional[Set[Tuple[int, int]]],
    seen: Set[Tuple[Tuple[int, int], Tuple[int, int]]],
) -> List[str]:
    """
    Check one decision entry, accumulating duplicates through `seen`.
    判断エントリ 1 件を検査し、重複を `seen` に蓄積しながら判定する。
    """
    problems: List[str] = []
    where = f"decisions[{index}]"

    if not isinstance(entry, dict):
        return [f"{where}: must be an object, got {type(entry).__name__}"]

    endpoints = entry.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        problems.append(f"{where}: 'endpoints' must be a list of exactly 2 points")
        return problems

    coords: List[Tuple[int, int]] = []
    for j, pt in enumerate(endpoints):
        if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
            problems.append(
                f"{where}.endpoints[{j}]: must be an object with 'x' and 'y'")
            continue
        try:
            coords.append(point_xy(pt))
        except (TypeError, ValueError):
            problems.append(
                f"{where}.endpoints[{j}]: 'x' and 'y' must be integers")
    if len(coords) != 2:
        return problems

    if coords[0] == coords[1]:
        problems.append(f"{where}: the two endpoints are the same pixel")

    if known_endpoints is not None:
        for pt in coords:
            if pt not in known_endpoints:
                problems.append(
                    f"{where}: endpoint (x={pt[0]}, y={pt[1]}) is not a "
                    f"fragment endpoint of the target skeleton")

    verdict = entry.get("verdict")
    if verdict not in VERDICTS:
        problems.append(
            f"{where}: verdict must be one of {VERDICTS}, got {verdict!r}")

    source = entry.get("source")
    if source not in SOURCES:
        problems.append(
            f"{where}: source must be one of {SOURCES}, got {source!r}")

    fragments = entry.get("fragments")
    if fragments is not None:
        if (not isinstance(fragments, list)
                or not all(isinstance(f, int) and not isinstance(f, bool)
                           for f in fragments)):
            problems.append(f"{where}: 'fragments' must be a list of integers")

    key = (coords[0], coords[1]) if coords[0] <= coords[1] else (coords[1], coords[0])
    if key in seen:
        problems.append(
            f"{where}: duplicate decision for endpoint pair "
            f"(x={key[0][0]}, y={key[0][1]})-(x={key[1][0]}, y={key[1][1]})")
    seen.add(key)

    return problems


def _has_unreviewed(decisions: Iterable[Dict]) -> bool:
    """
    Return whether any decision is still undecided.
    未判断の判断が残っているかどうかを返す。
    """
    return any(d.get("verdict") == VERDICT_UNREVIEWED for d in decisions)


def review_complete(labels: Dict) -> bool:
    """
    Return whether every candidate in a document has been decided.
    文書内のすべての候補が判断済みかどうかを返す。

    Computed from the decisions rather than read from ``review.complete``, so a
    stale or wishful flag cannot make an unfinished review look finished.
    ``review.complete`` を読むのではなく判断から計算する。古い、あるいは希望的な
    フラグによって未完了の検分が完了に見えることを防ぐ。
    """
    decisions = labels.get("decisions")
    if not isinstance(decisions, list):
        return False
    return not _has_unreviewed(decisions)


def training_pairs(labels: Dict) -> List[Tuple[Tuple[int, int], Tuple[int, int], int]]:
    """
    Return the endpoint pairs that carry a training signal, with their class.
    学習信号を持つ端点ペアと、そのクラスを返す。

    Parameters
    ----------
    labels
        Validated label document.
        検証済みのラベル文書。

    Returns
    -------
    list of tuple
        ``(endpoint_a, endpoint_b, label)`` with ``label`` 1 for a connection
        and 0 for a rejection. ``uncertain`` and ``unreviewed`` decisions are
        omitted entirely: neither states what the right answer is, and turning
        either into a negative would teach the model that a connection a human
        could not judge -- or never looked at -- is wrong.
        ``(端点A, 端点B, ラベル)``。``label`` は連結が 1、非連結が 0。
        ``uncertain`` と ``unreviewed`` は完全に除外する。どちらも正解を述べて
        おらず、これらを負例に変えると、人が判断できなかった、あるいは見てすら
        いない連結を「誤り」としてモデルに教えることになる。
    """
    pairs: List[Tuple[Tuple[int, int], Tuple[int, int], int]] = []
    for entry in labels.get("decisions", []):
        target = TRAINING_VERDICTS.get(entry.get("verdict"))
        if target is None:
            continue
        a, b = decision_key(entry)
        pairs.append((a, b, target))
    return pairs


def save_labels(path: str, labels: Dict) -> str:
    """
    Write a label document atomically.
    ラベル文書を原子的に書き込む。

    Writes to a temporary sibling file and renames into place, so an
    interrupted write cannot leave a half-written label file, mirroring the
    atomic saves in `lib.pipeline` and `lib.ml_model`.
    一時的な同一ディレクトリ内ファイルへ書き込んでから所定名へリネームし、書き込み
    中断で半端なラベルファイルが残らないようにする。`lib.pipeline` と
    `lib.ml_model` の原子的保存に倣う。

    Parameters
    ----------
    path
        Destination path, normally from `label_path_for`.
        保存先パス。通常は `label_path_for` の戻り値。
    labels
        Label document to write.
        書き込むラベル文書。

    Returns
    -------
    str
        The path written.
        書き込んだパス。
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return path


def load_labels(
    path: str,
    *,
    expected_skeleton_hash: Optional[str] = None,
    known_endpoints: Optional[Set[Tuple[int, int]]] = None,
) -> Dict:
    """
    Read and validate a label document.
    ラベル文書を読み込み検証する。

    Parameters
    ----------
    path
        Path to the label sidecar.
        ラベル sidecar のパス。
    expected_skeleton_hash, known_endpoints
        Optional checks forwarded to `validate_labels`; pass both when the
        labels are about to be applied to a specific skeleton.
        `validate_labels` へ渡す任意の検査。特定の骨格へ適用する直前には両方を
        渡すこと。

    Returns
    -------
    dict
        The validated label document.
        検証済みのラベル文書。

    Raises
    ------
    ValueError
        If the file is not valid JSON or violates the contract. Failure is
        explicit rather than partial: silently dropping bad entries would train
        on a subset nobody chose.
        ファイルが正しい JSON でない、または契約に違反する場合。部分的に無視せず
        明示的に失敗する。不正なエントリを黙って捨てると、誰も選んでいない部分集合で
        学習することになるためである。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            labels = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{os.path.basename(path)}: invalid JSON: {exc}") from exc

    problems = validate_labels(
        labels,
        expected_skeleton_hash=expected_skeleton_hash,
        known_endpoints=known_endpoints,
    )
    if problems:
        raise ValueError(
            f"{os.path.basename(path)}: invalid connect labels: "
            + "; ".join(problems))
    return labels
