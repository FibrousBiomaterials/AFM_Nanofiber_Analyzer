# -*- coding: utf-8 -*-
"""
Tests for the fiber-connection sidecar.
ファイバー連結サイドカーのテスト。

The sidecar is an analysis input: GUI03 aggregates whatever it says, so a file
that reads back as something other than what was written, or that is
misinterpreted by a version that cannot understand it, silently changes what a
published number means.
サイドカーは解析入力である。GUI03 はその内容に従って集計するため、書いた内容と
違うものとして読み戻されたり、理解できないバージョンに誤って解釈されたりすると、
公表された数値の意味が黙って変わってしまう。

The file records a connection **result** rather than the settings that
produced it, so these tests are about a decision surviving a round trip intact
and about a stale file being refused rather than half applied.
本ファイルは、結果を生んだ設定ではなく連結の**結果**を記録する。したがって本
テストは、決定が往復しても損なわれないこと、および古くなったファイルが中途半端
に適用されるのではなく拒否されることを対象とする。
"""

import json
import os

import numpy as np
import pytest

from lib.connect_selection import (
    CONNECT_FORMAT,
    CONNECT_SUFFIX,
    CONNECT_VERSION,
    ChainMember,
    ConnectionPlan,
    connect_path_for,
    load_connect_plan,
    plan_state_key,
    resolve_plan_chains,
    save_connect_plan,
    skeleton_digest,
)
from lib.fiber import Fiber
from lib.fiber_connector import ConnectParams


def _write_raw(path: str, payload: dict) -> None:
    """Write a payload verbatim, bypassing the writer's own validation."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _fragment(x0: int, x1: int, y: int) -> Fiber:
    """Build a minimal horizontal fragment with a known anchor."""
    n = x1 - x0 + 1
    return Fiber(
        fiber_image=np.zeros((1, n)),
        data=(x0, y, n, 1, n),
        xtrack=np.arange(n),
        ytrack=np.zeros(n, dtype=int),
        horizon=np.arange(n, dtype=float),
        height=np.zeros(n),
        kink_indices=np.array([], dtype=int),
        ep_indices=np.array([0, n - 1]),
        kink_angles=np.array([]),
        decomposed_point_indices=np.array([0, n - 1]),
    )


def _plan(*chains, params=ConnectParams(), digest="", count=0) -> ConnectionPlan:
    """Build a plan from ``(anchor, flip)`` pairs per chain."""
    return ConnectionPlan(
        chains=tuple(
            tuple(ChainMember(anchor=a, flip=f) for a, f in chain)
            for chain in chains
        ),
        params=params,
        skeleton_digest=digest,
        fragment_count=count,
    )


def test_sidecar_path_sits_beside_the_bundle():
    """The sidecar replaces the bundle extension with the connection suffix."""
    assert connect_path_for("/data/scan.b2z") == "/data/scan" + CONNECT_SUFFIX


def test_round_trip_preserves_the_result_and_its_thresholds(tmp_path):
    """A saved plan reads back as the same fibrils, orientation included."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    params = ConnectParams(
        clusters_range=31.5, angle_threshold=95.0, lookback_length=9,
        num_avg_points=3, height_diff_ratio=0.4, trim_points=7,
    )
    plan = _plan(
        (((12, 34), False), ((56, 78), True)),
        (((90, 11), True), ((22, 33), False), ((44, 55), True)),
        params=params, digest="sha256:abc", count=9,
    )
    save_connect_plan(path, "scan.b2z", plan)

    back = load_connect_plan(path)
    assert back is not None
    assert back.params == params
    assert back.skeleton_digest == "sha256:abc"
    assert back.fragment_count == 9
    assert plan_state_key(back) == plan_state_key(plan)
    # Orientation is part of the result: losing a flip rebuilds a different
    # fibril from the same fragments.
    # 向きは結果の一部である。反転を失うと、同じ断片から別のフィブリルが再構築
    # されてしまう。
    assert [[(m.anchor, m.flip) for m in c] for c in back.chains] == \
        [[(m.anchor, m.flip) for m in c] for c in plan.chains]


def test_missing_sidecar_is_distinct_from_a_plan_that_connects_nothing(tmp_path):
    """
    No file and an empty result measure alike but are told apart.
    ファイルが無い状態と、何も繋がらないという結果は、計測上は同じだが区別する。

    GUI03 reports how many bundles in a folder carry a decision, so "nobody has
    decided" and "somebody decided nothing connects" cannot be the same value.
    GUI03 はフォルダ内で決定を持つバンドル数を報告するため、「誰も決めていない」と
    「何も繋がらないと決めた」が同じ値になってはならない。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    assert load_connect_plan(path) is None

    save_connect_plan(path, "scan.b2z", ConnectionPlan())
    back = load_connect_plan(path)
    assert back is not None
    assert back.chains == ()
    # Both measure as fragments, so neither is pending work to save.
    # どちらも断片として計測されるため、保存すべき保留作業ではない。
    assert plan_state_key(back) == plan_state_key(None)


def test_an_empty_result_keeps_the_file(tmp_path):
    """
    Deciding that nothing connects leaves the file, unlike an exclusion set.
    何も繋がらないという決定はファイルを残す。除外集合とは異なる。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    save_connect_plan(path, "scan.b2z", ConnectionPlan(
        params=ConnectParams(clusters_range=42.0),
    ))
    assert os.path.isfile(path)
    assert load_connect_plan(path).params.clusters_range == 42.0


def test_missing_thresholds_fall_back_to_defaults(tmp_path):
    """A file written without every threshold still loads."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "bundle": "scan.b2z",
        "params": {"clusters_range": 25.0},
        "chains": [],
    })
    plan = load_connect_plan(path)
    assert plan.params.clusters_range == 25.0
    assert plan.params.trim_points == ConnectParams().trim_points


@pytest.mark.parametrize("payload", [
    {"format": "something/else", "version": 1, "chains": []},
    {"format": CONNECT_FORMAT, "version": 1, "chains": {}},
    {"format": CONNECT_FORMAT, "version": 1, "chains": [{"members": []}]},
    {"format": CONNECT_FORMAT, "version": 1,
     "chains": [{"members": [{"anchor": [1, 2]}]}]},
    {"format": CONNECT_FORMAT, "version": 1,
     "chains": [{"members": [{"flip": False}, {"anchor": [1, 2]}]}]},
    {"format": CONNECT_FORMAT, "version": 1,
     "chains": [{"members": [{"anchor": [1]}, {"anchor": [2, 3]}]}]},
])
def test_malformed_sidecar_raises_instead_of_reading_as_absent(tmp_path, payload):
    """
    A broken file is reported, never treated as "not connected".
    壊れたファイルは報告する。「連結なし」として扱ってはならない。

    Reading it as absent would measure fragments while the user believes whole
    fibrils were measured, and nothing in the result would say so.
    無いものとして読むと、ユーザーがフィブリルを計測したと信じている間に断片が
    計測され、結果にはそれを示すものが何も残らない。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, payload)
    with pytest.raises(ValueError):
        load_connect_plan(path)


def test_invalid_json_raises(tmp_path):
    """A truncated or hand-edited file is an error, not an empty result."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(ValueError):
        load_connect_plan(path)


def test_one_fragment_cannot_belong_to_two_fibrils(tmp_path):
    """
    An anchor used twice describes a fibril that cannot be built.
    2 度使われたアンカーは、構築できないフィブリルを記述している。

    Reading it as either interpretation would measure a population nobody
    chose, so it is refused instead.
    どちらの解釈で読んでも、誰も選んでいない母集団を計測することになるため拒否
    する。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "chains": [
            {"members": [{"anchor": [1, 1]}, {"anchor": [2, 2]}]},
            {"members": [{"anchor": [2, 2]}, {"anchor": [3, 3]}]},
        ],
    })
    with pytest.raises(ValueError, match="more than one chain member"):
        load_connect_plan(path)


def test_a_newer_format_version_is_refused(tmp_path):
    """
    A file from a newer version is refused rather than partly understood.
    新しいバージョンのファイルは、部分的に解釈せず拒否する。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION + 1,
        "chains": [],
    })
    with pytest.raises(ValueError, match="newer than the supported"):
        load_connect_plan(path)


def test_a_settings_file_from_the_development_format_is_refused(tmp_path):
    """
    The pre-release "enabled + thresholds" file cannot be read as a result.
    リリース前の「有効フラグ + しきい値」形式は、結果としては読めない。

    Which fragments it would have joined is only recoverable by running the
    search again, which is the thing the result format exists to stop doing,
    so the user is told to connect and save instead.
    どの断片が連結されたはずかは探索を再実行しない限り復元できず、その再実行こそ
    結果形式がやめるために存在するものである。したがって、連結して保存し直すよう
    ユーザーに伝える。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": 1,
        "bundle": "scan.b2z",
        "enabled": True,
        "params": {"clusters_range": 20.0},
        "links": [],
    })
    with pytest.raises(ValueError, match="rather than a connection result"):
        load_connect_plan(path)


def test_state_key_ignores_thresholds_but_tracks_the_result():
    """
    Editing a threshold with nothing connected leaves nothing to save.
    何も連結していない状態でしきい値を変えても、保存すべきものは生じない。

    Thresholds no longer change a measured fiber once the chains are fixed, so
    treating one as pending work would light the save button over a change
    that cannot alter a single number.
    連鎖が確定した後、しきい値は計測されるファイバーを変えない。それを保留作業と
    扱うと、どの数値も変えられない変更のために保存ボタンが点灯してしまう。
    """
    loose = ConnectParams(clusters_range=20.0)
    tight = ConnectParams(clusters_range=5.0)
    assert plan_state_key(ConnectionPlan(params=loose)) == \
        plan_state_key(ConnectionPlan(params=tight))

    one = _plan((((1, 1), False), ((2, 2), False)))
    other = _plan((((1, 1), False), ((3, 3), False)))
    assert plan_state_key(one) != plan_state_key(other)
    # A flip is part of the result, so reversing one is a change to save.
    # 反転は結果の一部であるため、片方を反転させれば保存すべき変更になる。
    flipped = _plan((((1, 1), False), ((2, 2), True)))
    assert plan_state_key(one) != plan_state_key(flipped)


def test_a_plan_resolves_onto_fragments_by_anchor():
    """
    Members are found by the pixels under them, not by list position.
    メンバーは、リスト内の位置ではなくその下にある画素で見つける。

    Curation renumbers the fragment list, so an index would point at a
    different object; a pixel keeps its meaning.
    キュレーションは断片リストの採番を変えるため、インデックスは別の対象を指して
    しまう。画素であれば意味が保たれる。
    """
    fragments = [_fragment(0, 10, y=5), _fragment(20, 30, y=5)]
    anchors = [(5, 5), (25, 5)]
    chains, missing, splits = resolve_plan_chains(
        fragments, _plan(((anchors[0], False), (anchors[1], True))),
    )
    assert chains == [[(0, False), (1, True)]]
    assert missing == 0 and splits == 0

    # The same plan against a list where the first fragment is gone.
    # 最初の断片が失われたリストに対して同じプランを適用する。
    chains, missing, splits = resolve_plan_chains(
        fragments[1:], _plan(((anchors[0], False), (anchors[1], True))),
    )
    assert chains == []
    assert missing == 1 and splits == 1


def test_skeleton_digest_changes_when_the_skeleton_does():
    """
    The fingerprint separates a re-analyzed bundle from an untouched one.
    指紋は、再解析されたバンドルと手つかずのバンドルを区別する。
    """
    a = np.zeros((8, 8), dtype=bool)
    a[3, 2:6] = True
    b = a.copy()
    assert skeleton_digest(a) == skeleton_digest(b)
    b[4, 4] = True
    assert skeleton_digest(a) != skeleton_digest(b)
    # Shape is part of it, so a crop is not mistaken for the same skeleton.
    # 形状も含めるため、切り出した配列が同じ骨格と誤認されることはない。
    assert skeleton_digest(a) != skeleton_digest(a[:6, :6])
