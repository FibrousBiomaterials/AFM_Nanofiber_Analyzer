# -*- coding: utf-8 -*-
"""
Tests for the fiber-connection settings sidecar.
ファイバー連結設定サイドカーのテスト。

The sidecar is an analysis input: GUI03 aggregates whatever it says, so a file
that reads back as something other than what was written, or that is
misinterpreted by a version that cannot understand it, silently changes what a
published number means.
サイドカーは解析入力である。GUI03 はその内容に従って集計するため、書いた内容と
違うものとして読み戻されたり、理解できないバージョンに誤って解釈されたりすると、
公表された数値の意味が黙って変わってしまう。
"""

import json
import os

import pytest

from lib.connect_selection import (
    CONNECT_FORMAT,
    CONNECT_SUFFIX,
    CONNECT_VERSION,
    connect_path_for,
    connect_state_key,
    load_connect_settings,
    save_connect_settings,
)
from lib.fiber_connector import ConnectParams


def _write_raw(path: str, payload: dict) -> None:
    """Write a payload verbatim, bypassing the writer's own validation."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_sidecar_path_sits_beside_the_bundle():
    """The sidecar replaces the bundle extension with the settings suffix."""
    assert connect_path_for("/data/scan.b2z") == "/data/scan" + CONNECT_SUFFIX


def test_round_trip_preserves_every_threshold(tmp_path):
    """Saved thresholds read back exactly, so a re-run reproduces the run."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    params = ConnectParams(
        clusters_range=31.5, angle_threshold=95.0, lookback_length=9,
        num_avg_points=3, height_diff_ratio=0.4, trim_points=7,
    )
    save_connect_settings(path, "scan.b2z", True, params)

    settings = load_connect_settings(path)
    assert settings is not None
    assert settings.enabled is True
    assert settings.params == params
    assert settings.links == ()


def test_missing_sidecar_is_distinct_from_a_disabled_one(tmp_path):
    """
    "Nobody decided" and "decided not to connect" are different states.
    「誰も決めていない」と「連結しないと決めた」は別の状態である。

    Both measure as fragments, but only the second is a decision, and GUI03
    counts how many bundles carry one.
    計測結果はどちらも断片だが、決定であるのは後者だけであり、GUI03 は決定を
    持つバンドル数を数える。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    assert load_connect_settings(path) is None

    save_connect_settings(path, "scan.b2z", False, ConnectParams())
    settings = load_connect_settings(path)
    assert settings is not None
    assert settings.enabled is False


def test_disabling_keeps_the_file_and_its_thresholds(tmp_path):
    """
    Turning connection off records the decision instead of deleting the file.
    連結を OFF にすると、ファイルを削除せず決定として記録する。

    This is the deliberate difference from the exclusion sidecar, which is
    removed when it becomes empty: a stale exclusion file would restore fibers
    the user rejected, while a stored "off" measures the same as no file and
    keeps the thresholds the user tuned.
    空になったら削除される除外サイドカーとの意図的な違いである。古い除外ファイル
    はユーザーが却下したファイバーを復活させるが、保存された "off" はファイルが
    無い場合と同じ計測結果になり、調整済みのしきい値を保持できる。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    tuned = ConnectParams(clusters_range=42.0)
    save_connect_settings(path, "scan.b2z", False, tuned)

    assert os.path.isfile(path)
    settings = load_connect_settings(path)
    assert settings.enabled is False
    assert settings.params.clusters_range == 42.0


def test_missing_thresholds_fall_back_to_defaults(tmp_path):
    """A hand-written file naming only one threshold still loads."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "enabled": True,
        "params": {"clusters_range": 12.0},
        "links": [],
    })
    settings = load_connect_settings(path)
    assert settings.params.clusters_range == 12.0
    assert settings.params.angle_threshold == ConnectParams().angle_threshold


@pytest.mark.parametrize("payload", [
    {"enabled": True},
    {"format": "something/else", "enabled": True},
    {"format": CONNECT_FORMAT, "version": CONNECT_VERSION},
    {"format": CONNECT_FORMAT, "version": CONNECT_VERSION,
     "enabled": True, "params": []},
    {"format": CONNECT_FORMAT, "version": CONNECT_VERSION,
     "enabled": True, "params": {"clusters_range": "wide"}},
])
def test_malformed_sidecar_raises_instead_of_reading_as_absent(tmp_path, payload):
    """
    A broken file is reported, never treated as "not connected".
    壊れたファイルは報告する。「連結なし」として扱ってはならない。

    Falling back silently would measure fragments while the user believes
    whole fibrils were measured.
    黙ってフォールバックすると、ユーザーがフィブリル全体を計測したつもりでいる
    のに断片を計測することになる。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, payload)
    with pytest.raises(ValueError):
        load_connect_settings(path)


def test_invalid_json_raises(tmp_path):
    """A truncated file is an error, not an empty setting."""
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(ValueError):
        load_connect_settings(path)


def test_a_newer_format_version_is_refused(tmp_path):
    """
    A file from a future version is refused rather than partly understood.
    将来のバージョンのファイルは、部分的に解釈せず拒否する。

    This is what lets manual connection links be added later without a silent
    wrong answer here: the writer that fills ``links`` raises the version, and
    this reader stops instead of measuring without them.
    これにより、手動連結リンクを後から追加してもここで黙って誤答することがない。
    ``links`` を埋める書き込み側がバージョンを上げ、この読み取り側はリンクを
    無視して計測する代わりに停止する。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION + 1,
        "enabled": True,
        "params": {},
        "links": [{"a": [1, 2], "b": [3, 4], "mode": "join"}],
    })
    with pytest.raises(ValueError):
        load_connect_settings(path)


def test_manual_links_are_reserved_but_not_yet_accepted(tmp_path):
    """
    Version 1 records the ``links`` key and refuses to carry entries in it.
    バージョン 1 は ``links`` キーを記録するが、その中身を扱うことは拒否する。
    """
    path = os.path.join(tmp_path, "scan" + CONNECT_SUFFIX)
    save_connect_settings(path, "scan.b2z", True, ConnectParams())
    with open(path, "r", encoding="utf-8") as f:
        assert json.load(f)["links"] == []

    with pytest.raises(ValueError):
        save_connect_settings(
            path, "scan.b2z", True, ConnectParams(),
            links=[{"a": [1, 2], "b": [3, 4], "mode": "join"}],
        )

    _write_raw(path, {
        "format": CONNECT_FORMAT,
        "version": CONNECT_VERSION,
        "enabled": True,
        "params": {},
        "links": [{"a": [1, 2], "b": [3, 4], "mode": "join"}],
    })
    with pytest.raises(ValueError):
        load_connect_settings(path)


def test_state_key_tracks_content_not_identity():
    """
    The key is equal for equal settings, so an edit and its undo leave nothing
    to save.
    等しい設定には等しいキーが対応するため、編集して元に戻せば保存対象は残らない。
    """
    base = connect_state_key(True, ConnectParams())
    assert base == connect_state_key(True, ConnectParams())
    assert base != connect_state_key(False, ConnectParams())
    assert base != connect_state_key(True, ConnectParams(clusters_range=21.0))
