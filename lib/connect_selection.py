# -*- coding: utf-8 -*-
"""
Fiber-connection settings recorded beside a ``.b2z`` bundle.
``.b2z`` バンドルの横に記録する、ファイバー連結の設定。

GUI04 decides whether skeleton fragments are reconnected into whole fibrils
and with which thresholds. That decision changes what a "fiber" is, so a
measurement made elsewhere — GUI03, the CLI — has to be able to reproduce it
instead of silently measuring fragments. This module is where the decision is
stored so it survives the session and travels with the data.
GUI04 は、骨格断片を 1 本のフィブリルへ再結合するか、そしてどのしきい値で
行うかを決める。この決定は「ファイバー」が何を指すかを変えるため、他の場所
（GUI03、CLI）での計測がそれを再現できなければならない。さもなければ黙って
断片を計測することになる。本モジュールはその決定を保存し、セッションを越えて
保持しデータと共に持ち運べるようにする。

The file is a sibling of `lib.fiber_selection`'s exclusion sidecar but is not
the same kind of record. An exclusion is an irreproducible human judgement, so
it must be stored as data. Connection is, today, a deterministic function of
the bundle and `ConnectParams`, so only the settings are stored and the
connector is re-run at measurement time — a stored result would be a cache
that can silently disagree with the bundle it sits beside.
本ファイルは `lib.fiber_selection` の除外サイドカーと兄弟関係にあるが、記録の
種類は同じでない。除外は再現できない人間の判断であるため、データとして保存
するほかない。連結は現状、バンドルと `ConnectParams` から決まる決定的な関数
であるため、保存するのは設定だけとし、計測時にコネクタを実行し直す。結果を
保存すればそれは横に置かれたバンドルと黙って食い違いうるキャッシュになる。

Notes
-----
The ``links`` key is reserved for manual, per-pair connection decisions, which
are planned but not implemented. It is written from the first version so that
adding them later does not have to break the file format; a version 1 reader
requires it to be empty, and a writer that starts filling it must raise
`CONNECT_VERSION` so that an older reader refuses the file instead of quietly
measuring without the manual decisions it carries.
``links`` キーは、ペア単位の手動連結判断のために予約している。実装は将来だが、
後から追加する際にファイル形式を壊さずに済むよう第 1 版から書き出す。
バージョン 1 の読み取り側はこのキーが空であることを要求し、書き込み側が中身を
入れ始めるときは `CONNECT_VERSION` を上げること。そうすれば古い読み取り側は、
ファイルが持つ手動判断を無視したまま黙って計測するのではなく、読み込みを拒否
する。
"""

# ===== Standard library =====
import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

# ===== Project libraries =====
from .fiber_connector import ConnectParams

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
class ConnectSettings:
    """
    Fiber-connection decision recorded for one bundle.
    1 つのバンドルについて記録されたファイバー連結の決定。

    Attributes
    ----------
    enabled
        Whether the connection stage runs for this bundle.
        このバンドルで連結ステージを実行するかどうか。
    params
        Thresholds handed to `lib.fiber_connector.connect_fiber_fragments`.
        `lib.fiber_connector.connect_fiber_fragments` へ渡すしきい値。
    links
        Reserved for manual per-pair connection decisions; always empty at
        `CONNECT_VERSION` 1.
        ペア単位の手動連結判断のための予約領域。`CONNECT_VERSION` 1 では常に空。
    """

    enabled: bool
    params: ConnectParams
    links: Tuple[Dict, ...] = ()


def connect_path_for(bundle_path: str) -> str:
    """
    Return the connection-settings sidecar path for a bundle path.
    バンドルパスに対応する連結設定サイドカーのパスを返す。

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


def load_connect_settings(path: str) -> Optional[ConnectSettings]:
    """
    Read connection settings from a sidecar file.
    サイドカーファイルから連結設定を読み込む。

    Parameters
    ----------
    path
        Sidecar path, typically from `connect_path_for`.
        サイドカーのパス。通常は `connect_path_for` の戻り値。

    Returns
    -------
    ConnectSettings or None
        ``None`` when no sidecar exists, which is distinct from a stored
        ``enabled: false``: the first means nobody has decided, the second
        means somebody decided not to connect. Both measure as fragments, but
        a caller reporting how many bundles carry a decision needs to tell
        them apart.
        サイドカーが無ければ ``None``。保存された ``enabled: false`` とは区別
        する。前者は「誰も決めていない」、後者は「連結しないと決めた」を意味する。
        計測結果はどちらも断片だが、決定を持つバンドルが何個あるかを報告する
        呼び出し側には両者の区別が必要である。

    Raises
    ------
    ValueError
        If the file exists but is not a valid, readable settings file. A
        malformed or too-new sidecar is reported rather than ignored, because
        silently falling back to "not connected" would measure fragments while
        the user believes whole fibrils were measured.

    Notes
    -----
    A file whose ``version`` exceeds `CONNECT_VERSION` is refused rather than
    parsed for the keys this version happens to understand. The keys a newer
    version adds change what the connector does, so partial understanding
    produces a wrong population with no warning.
    ``version`` が `CONNECT_VERSION` を超えるファイルは、このバージョンが理解
    できるキーだけを拾うのではなく拒否する。新しいバージョンが追加するキーは
    コネクタの動作を変えるため、部分的な理解は警告なしに誤った母集団を生む。
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
            f"{path} is not a connection-settings file "
            f"(missing format {CONNECT_FORMAT!r})"
        )

    version = payload.get("version", CONNECT_VERSION)
    if not isinstance(version, int) or version > CONNECT_VERSION:
        raise ValueError(
            f"{path} has format version {version!r}, newer than the supported "
            f"{CONNECT_VERSION}; update the software to read it"
        )

    if "enabled" not in payload:
        raise ValueError(f"{path} has no 'enabled' entry")
    enabled = bool(payload["enabled"])

    raw_params = payload.get("params", {})
    if not isinstance(raw_params, dict):
        raise ValueError(f"{path} has a non-object 'params' entry")

    raw_links = payload.get("links", [])
    if not isinstance(raw_links, list):
        raise ValueError(f"{path} has a non-list 'links' entry")
    if raw_links:
        raise ValueError(
            f"{path} carries manual connection links, which format version "
            f"{CONNECT_VERSION} cannot apply"
        )

    return ConnectSettings(
        enabled=enabled,
        params=params_from_dict(raw_params),
        links=(),
    )


def save_connect_settings(
    path: str,
    bundle_name: str,
    enabled: bool,
    params: ConnectParams,
    links: Sequence[Dict] = (),
) -> None:
    """
    Write connection settings to a sidecar file.
    連結設定をサイドカーファイルへ書き出す。

    Parameters
    ----------
    path
        Sidecar path to write.
        書き出し先のサイドカーパス。
    bundle_name
        Base name of the bundle the settings belong to, stored so the file is
        self-describing when read outside this project.
        設定が属するバンドルのベース名。本プロジェクト外で読んだときにも内容が
        分かるよう記録する。
    enabled
        Whether the connection stage runs for this bundle.
        このバンドルで連結ステージを実行するかどうか。
    params
        Thresholds to record.
        記録するしきい値。
    links
        Reserved; must be empty at `CONNECT_VERSION` 1.
        予約領域。`CONNECT_VERSION` 1 では空でなければならない。

    Raises
    ------
    ValueError
        If `links` is non-empty, which this format version cannot record.

    Notes
    -----
    Unlike `lib.fiber_selection.save_exclusions`, turning the feature off
    writes ``enabled: false`` instead of deleting the file. Deleting is right
    for exclusions because a stale file would restore fibers the user
    rejected; here the two states measure identically, and keeping the file
    preserves the thresholds the user tuned as well as the fact that "do not
    connect this bundle" was a decision rather than an omission.
    `lib.fiber_selection.save_exclusions` と異なり、機能を OFF にした場合は
    ファイルを削除せず ``enabled: false`` を書き出す。除外で削除が正しいのは、
    古いファイルがユーザーの却下したファイバーを復活させるからである。ここでは
    両者の計測結果は同じであり、ファイルを残すことでユーザーが調整したしきい値
    と、「このバンドルは連結しない」が省略ではなく決定であったことの両方を保て
    る。
    """
    if links:
        raise ValueError(
            f"format version {CONNECT_VERSION} cannot record manual "
            f"connection links"
        )

    payload = {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "bundle": bundle_name,
        "enabled": bool(enabled),
        "params": params_to_dict(params),
        "links": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def connect_state_key(enabled: bool, params: ConnectParams) -> str:
    """
    Return a comparable key for one connection state.
    1 つの連結状態を比較可能なキーとして返す。

    Parameters
    ----------
    enabled
        Whether the connection stage runs.
        連結ステージを実行するかどうか。
    params
        Thresholds in effect.
        有効なしきい値。

    Returns
    -------
    str
        Stable string identifying the state, for comparing what is in memory
        against what was last written.
        状態を一意に表す安定した文字列。メモリ上の状態と最後に書き出した内容の
        比較に用いる。

    Notes
    -----
    Used by GUI04 to decide whether there is anything left to save, so that
    editing a threshold and then restoring it leaves nothing pending, exactly
    as the exclusion set's key does.
    GUI04 が「保存すべきものが残っているか」を判定するために使う。しきい値を
    変更してから元に戻した場合に保留を残さないためであり、除外集合のキーと同じ
    考え方である。

    Every disabled state collapses to one key, because the thresholds change
    nothing while the connection stage does not run. This is what lets a
    missing sidecar be compared as "not connected": absence and a stored
    ``enabled: false`` measure identically, so neither may be reported as
    something still to write when connection is off.
    無効状態は全て 1 つのキーに collapse する。連結ステージが動かない間、しきい値
    は何も変えないためである。これによりサイドカーが無い状態を「連結なし」として
    比較できる。ファイルの不在と保存された ``enabled: false`` は計測上等価であり、
    連結が OFF のときにどちらも「まだ書き出すものがある」と報告してはならない。
    """
    if not enabled:
        return "False"
    body = json.dumps(params_to_dict(params), sort_keys=True)
    return f"True|{body}"
