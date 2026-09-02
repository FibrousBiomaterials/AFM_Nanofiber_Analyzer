# -*- coding: utf-8 -*-
"""
Contract tests for manual fiber exclusions.
手動ファイバー除外の契約テスト。
"""

import json
import os

import pytest

from lib.fiber_selection import (
    EXCLUSION_FORMAT,
    exclusion_path_for,
    excluded_flags,
    fiber_anchor,
    fiber_track_pixels,
    load_exclusions,
    save_exclusions,
)
from lib.measure import measure_bundle
from lib.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt

FAST_PARAMS = ProcParams(bg_method="tophat")
SCALE_UM = 1.92


@pytest.fixture(scope="module")
def traced(tmp_path_factory):
    """Run the pipeline once and trace it, shared across this module."""
    tmp_path = tmp_path_factory.mktemp("selection")
    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    result = process_file(txt, FAST_PARAMS, output_dir=out_dir)
    measured = measure_bundle(result.bundle_path, scale_um=SCALE_UM)
    return result.bundle_path, measured


def test_exclusion_path_sits_beside_the_bundle(traced):
    """The sidecar shares the bundle's stem and directory."""
    bundle_path, _measured = traced
    path = exclusion_path_for(bundle_path)
    assert os.path.dirname(path) == os.path.dirname(bundle_path)
    assert path.endswith("_excluded.json")


def test_anchor_lies_on_its_own_fiber(traced):
    """A fiber's anchor is one of the pixels its own track passes through."""
    _bundle_path, measured = traced
    fiber = measured.fibers[0]
    assert fiber_anchor(fiber) in fiber_track_pixels(fiber)


def test_anchor_selects_only_its_own_fiber(traced):
    """An anchor flags the fiber it came from and no other."""
    _bundle_path, measured = traced
    flags = excluded_flags(measured.fibers, [fiber_anchor(measured.fibers[0])])
    assert flags[0] is True
    assert sum(flags) == 1


def test_no_anchors_excludes_nothing(traced):
    """An empty anchor set leaves every fiber in the population."""
    _bundle_path, measured = traced
    assert excluded_flags(measured.fibers, []) == [False] * len(measured.fibers)


def test_round_trip_preserves_records(tmp_path):
    """Saved records reload with the same coordinates and note."""
    path = os.path.join(tmp_path, "sample_excluded.json")
    records = [{"x": 12, "y": 34, "note": "debris"}, {"x": 56, "y": 78, "note": ""}]
    save_exclusions(path, "sample.b2z", records)
    assert load_exclusions(path) == records


def test_saved_file_is_self_describing(tmp_path):
    """The sidecar names its format and the bundle it belongs to."""
    path = os.path.join(tmp_path, "sample_excluded.json")
    save_exclusions(path, "sample.b2z", [{"x": 1, "y": 2}])
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["format"] == EXCLUSION_FORMAT
    assert payload["bundle"] == "sample.b2z"


def test_clearing_removes_the_sidecar(tmp_path):
    """
    Clearing every exclusion deletes the file rather than emptying it.
    全ての除外を解除するとファイルを空にするのではなく削除する。

    A stale empty sidecar and a missing one must not mean different things to
    a reader, and a file must never outlive the curation it recorded.
    読み取り側にとって「空のサイドカーが残っている」と「無い」が別々の意味に
    なってはならず、記録した内容より古いファイルが残り続けてもならない。
    """
    path = os.path.join(tmp_path, "sample_excluded.json")
    save_exclusions(path, "sample.b2z", [{"x": 1, "y": 2}])
    assert os.path.isfile(path)
    save_exclusions(path, "sample.b2z", [])
    assert not os.path.exists(path)


def test_missing_sidecar_reads_as_no_exclusions(tmp_path):
    """No file means nothing was excluded."""
    assert load_exclusions(os.path.join(tmp_path, "absent_excluded.json")) == []


def test_malformed_sidecar_is_reported(tmp_path):
    """
    A broken sidecar raises instead of silently reading as empty.
    壊れたサイドカーは黙って空として読まれず、例外を送出する。

    Treating it as empty would quietly restore fibers the user had excluded,
    changing the analyzed population without saying so.
    空として扱うと、ユーザーが除外したファイバーを黙って復活させ、解析対象の
    母集団を無言で変えてしまう。
    """
    path = os.path.join(tmp_path, "broken_excluded.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(ValueError):
        load_exclusions(path)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"excluded": []}, f)
    with pytest.raises(ValueError):
        load_exclusions(path)


def test_anchor_survives_fiber_connection(traced):
    """
    An anchor recorded on a fragment still selects it once fibers connect.
    断片に記録したアンカーは、ファイバー連結後も同じ対象を選び続ける。

    This is why exclusions are anchors rather than list indices: connection
    renumbers the fiber list, so a stored index would point at a different
    object after the mode changes.
    除外をリストのインデックスではなくアンカーにしている理由がこれである。連結は
    ファイバーリストを採番し直すため、保存したインデックスはモード変更後に別の
    対象を指してしまう。
    """
    bundle_path, measured = traced
    anchors = [fiber_anchor(measured.fibers[0])]
    connected = measure_bundle(
        bundle_path, scale_um=SCALE_UM, connect_fibers=True,
    )
    flags = excluded_flags(connected.fibers, anchors)
    assert sum(flags) == 1
