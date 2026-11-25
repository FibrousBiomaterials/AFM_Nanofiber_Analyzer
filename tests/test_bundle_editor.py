# -*- coding: utf-8 -*-
"""
Tests for painting masks and running stages again on an opened bundle.
開いたバンドルで、マスクを塗り、段を再実行する処理のテスト。

`bundle_edit.BundleEditor` lets a person change a result and then compute the
later ones again. These tests pin down that a stage run again on unchanged
results gives the stored ones back -- the ground for calling a rerun on edited
results "what the analysis would have computed from them" -- that the editor
keeps track of which results no longer follow from the ones before them, and
that every change can be taken back exactly.
`bundle_edit.BundleEditor` は、人が結果を変更し、そのあとの結果を計算し直せるように
する。以下のテストは、変更していない結果に対して再実行した段が保存済みの結果を
返すこと（編集した結果に対する再実行を「解析がそこから計算したはずのもの」と呼べる
根拠）、前の結果から導かれなくなった結果をエディタが把握していること、そして
どの変更も正確に取り消せることを固定する。
"""

import os
import shutil
from dataclasses import replace

import numpy as np
import pytest

from afm_nanofiber_analyzer.blosc2_io import load_bundle, load_bundle_meta
from afm_nanofiber_analyzer.bundle_edit import (
    RESULT_BINARIZED, RESULT_CALIBRATED, RESULT_FIBER_MASK, RESULT_KINKS,
    RESULT_SKELETON, STAGE_BACKGROUND, STAGE_BINARIZE, STAGE_KINKS, STAGE_MASK,
    STAGE_SKELETONIZE, BundleEditor, edited_path_for, fiber_pixels,
    load_edit_session,
)
from afm_nanofiber_analyzer.bundle_schema import (
    FIBER_MASK_KEY, MANUAL_EDIT_KEY, PARAMS_KEY,
)
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """
    A synthetic scan analyzed beside itself, shared across this module.
    合成走査を、その隣に解析結果を書く形で解析したもの。モジュール内で共有する。
    """
    folder = tmp_path_factory.mktemp("bundle_editor")
    txt = write_synthetic_fiber_txt(folder)
    return process_file(txt, ProcParams()).bundle_path


@pytest.fixture
def editor(bundle):
    """
    A fresh editor of the shared bundle; the bundle itself is never changed.
    共有バンドルの、新しいエディタ。バンドル自体は変更されない。
    """
    return BundleEditor(load_edit_session(bundle))


def _fiber_middle(editor):
    """
    Return ``(x, y)`` of the middle pixel of the editor's longest fiber.
    エディタで最も長い繊維の、中央の画素の ``(x, y)`` を返す。
    """
    fiber = max(editor.fibers, key=lambda candidate: len(candidate.xtrack))
    track_x, track_y = fiber_pixels(fiber)
    middle = len(track_x) // 2
    return int(track_x[middle]), int(track_y[middle])


def _results(editor):
    """
    Copy the editor's results, to compare states before and after changes.
    エディタの結果を複製する。変更の前後の状態を比べるためのもの。
    """
    return {
        "calibrated": np.array(editor.calibrated),
        "fiber_mask": np.array(editor.fiber_mask),
        "binarized": np.array(editor.binarized),
        "skeleton": np.array(editor.skeleton),
        "kinks": {key: np.array(value) for key, value in editor.kinks.arrays().items()},
        "params": editor.params,
    }


def _same(first, second):
    """
    Whether two copies made by `_results` hold the same values.
    `_results` で作った 2 つの複製が、同じ値を持つかどうか。
    """
    return (
        all(np.array_equal(first[key], second[key])
            for key in ("calibrated", "fiber_mask", "binarized", "skeleton"))
        and all(np.array_equal(first["kinks"][key], second["kinks"][key])
                for key in first["kinks"])
        and first["params"] == second["params"]
    )


@pytest.mark.parametrize("stage,name", [
    (STAGE_MASK, "fiber_mask"),
    (STAGE_BACKGROUND, "calibrated"),
    (STAGE_BINARIZE, "binarized"),
    (STAGE_SKELETONIZE, "skeleton"),
])
def test_stage_run_again_on_unchanged_results_gives_the_stored_one(editor, stage, name):
    """
    Nothing changed, so each stage computes what the analysis stored.
    何も変更していなければ、各段は解析が保存したものを計算する。
    """
    computed = editor.compute(stage)

    assert np.array_equal(computed[name], getattr(editor, name))


def test_kink_stage_run_again_gives_the_stored_kinks(editor):
    """
    The kink stage on the stored skeleton returns the stored kink arrays.
    保存済みのスケルトンに対するキンク検出は、保存済みのキンクの配列を返す。
    """
    stored = editor.session.arrays

    computed = editor.compute(STAGE_KINKS)

    for key in ("kp", "ka", "ke", "up"):
        assert np.array_equal(computed["kinks"][key], stored[key])
    assert len(computed["fibers"]) == len(editor.fibers)


def test_painting_sets_and_clears_pixels_under_the_brush(editor):
    """
    A stroke changes the pixels within half the brush diameter of its path.
    ストロークは、その経路からブラシの直径の半分以内にある画素を変える。
    """
    editor.begin_stroke(RESULT_BINARIZED, True)
    region = editor.paint(10.0, 20.0, 14.0, 20.0, 3.0)
    assert editor.end_stroke()

    # With a radius of 1.5 pixels the brush reaches one pixel to either side
    # of the path, and the diagonal neighbours of its two ends (1.41 away).
    # 半径 1.5 画素のブラシは、経路の両側 1 画素と、両端の斜め隣（距離 1.41）に届く。
    painted = np.zeros_like(editor.binarized)
    painted[19:22, 9:16] = True
    assert region == (19, 22, 9, 16)
    assert editor.binarized[painted].all()
    # Nothing outside the brush changed.
    # ブラシの外は何も変わらない。
    stored = np.asarray(editor.session.arrays["binarized"]).astype(bool)
    assert np.array_equal(editor.binarized[~painted], stored[~painted])

    editor.begin_stroke(RESULT_BINARIZED, False)
    editor.paint(12.0, 20.0, 12.0, 20.0, 1.0)
    assert editor.end_stroke()
    assert not editor.binarized[20, 12]
    assert editor.binarized[20, 11] and editor.binarized[20, 13]


def test_one_pixel_brush_leaves_no_gap_at_a_pixel_corner(editor):
    """
    The pixel the pointer is in is painted even at a corner of four pixels.
    ポインタが入っている画素は、4 画素の角にあっても塗られる。
    """
    editor.begin_stroke(RESULT_BINARIZED, True)
    editor.paint(30.5, 40.5, 30.5, 40.5, 1.0)
    assert editor.end_stroke()

    assert editor.binarized[round(40.5), round(30.5)]


def test_stroke_that_changes_nothing_is_not_a_change(editor):
    """
    Painting pixels the value they already have records nothing.
    すでにその値である画素を塗っても、何も記録されない。
    """
    stored = np.asarray(editor.session.arrays["binarized"]).astype(bool)
    row, column = np.argwhere(~stored)[0]

    editor.begin_stroke(RESULT_BINARIZED, False)
    assert editor.paint(float(column), float(row), float(column), float(row), 1.0) is None
    assert not editor.end_stroke()

    assert not editor.modified and not editor.can_undo
    assert not editor.stale and not editor.edited


def test_skeleton_can_be_cleared_but_not_set(editor):
    """
    The skeleton takes the eraser only, and erasing it calls for a new trace.
    スケルトンには消しゴムだけが使え、消すと繊維の追跡し直しが必要になる。
    """
    x, y = _fiber_middle(editor)
    with pytest.raises(ValueError):
        editor.begin_stroke(RESULT_SKELETON, True)

    editor.begin_stroke(RESULT_SKELETON, False)
    editor.paint(x, y, x, y, 1.0)
    assert editor.end_stroke()

    assert not editor.skeleton[y, x]
    assert editor.tracks_stale
    assert editor.stale == {RESULT_KINKS}
    # The fiber is cut in two where the pixel was taken out.
    # 画素を除いた場所で、繊維は 2 本に分かれる。
    before = len(editor.fibers)
    editor.set_fibers(editor.compute_fibers())
    assert len(editor.fibers) == before + 1
    assert not editor.tracks_stale


def test_changing_a_result_marks_what_is_computed_from_it(editor):
    """
    A painted mask leaves the later results stale, and a rerun clears its own.
    マスクを塗ると後の結果が古くなり、再実行するとその段自身の結果の印が消える。
    """
    x, y = _fiber_middle(editor)
    editor.begin_stroke(RESULT_FIBER_MASK, False)
    editor.paint(x - 6, y, x + 6, y, 9.0)
    editor.end_stroke()
    assert editor.edited == {RESULT_FIBER_MASK}
    assert editor.stale == {
        RESULT_CALIBRATED, RESULT_BINARIZED, RESULT_SKELETON, RESULT_KINKS}

    before = np.array(editor.calibrated)
    editor.apply(STAGE_BACKGROUND, editor.compute(STAGE_BACKGROUND))

    assert editor.stale == {RESULT_BINARIZED, RESULT_SKELETON, RESULT_KINKS}
    assert editor.rerun == [STAGE_BACKGROUND]
    # Unmasked, the fiber is taken for background there and subtracted.
    # マスクを外した場所では、繊維が背景とみなされて差し引かれる。
    assert editor.calibrated[y, x] < before[y, x]

    editor.apply(STAGE_BINARIZE, editor.compute(STAGE_BINARIZE))
    editor.apply(STAGE_SKELETONIZE, editor.compute(STAGE_SKELETONIZE))
    editor.apply(STAGE_KINKS, editor.compute(STAGE_KINKS))
    assert not editor.stale
    assert not editor.tracks_stale
    assert editor.rerun == [
        STAGE_BACKGROUND, STAGE_BINARIZE, STAGE_SKELETONIZE, STAGE_KINKS]


def test_rerun_replaces_hand_edits_of_its_own_result(editor):
    """
    A stage run again computes its result afresh, dropping what was painted.
    再実行した段は結果を計算し直し、塗った内容は残らない。
    """
    stored = np.asarray(editor.session.arrays["binarized"]).astype(bool)
    editor.begin_stroke(RESULT_BINARIZED, True)
    editor.paint(5.0, 5.0, 25.0, 5.0, 5.0)
    editor.end_stroke()
    assert RESULT_BINARIZED in editor.edited

    editor.apply(STAGE_BINARIZE, editor.compute(STAGE_BINARIZE))

    assert np.array_equal(editor.binarized, stored)
    assert RESULT_BINARIZED not in editor.edited


def test_settings_change_marks_the_stage_result_stale(editor):
    """
    New settings leave the stage's result as the earlier settings computed it.
    設定を変えると、その段の結果は、以前の設定で計算されたままになる。
    """
    changed = replace(editor.params, global_threshold=editor.params.global_threshold + 1.0)

    editor.set_params(changed, STAGE_BINARIZE)

    assert editor.params == changed
    assert editor.stale == {RESULT_BINARIZED, RESULT_SKELETON, RESULT_KINKS}
    assert RESULT_CALIBRATED not in editor.stale
    with pytest.raises(ValueError):
        editor.set_params(replace(editor.params, wsize_localbin=-1), STAGE_BINARIZE)
    # A higher threshold keeps fewer pixels.
    # しきい値を上げると、残る画素が減る。
    before = int(editor.binarized.sum())
    editor.apply(STAGE_BINARIZE, editor.compute(STAGE_BINARIZE))
    assert int(editor.binarized.sum()) < before


def test_every_change_is_undone_and_redone_exactly(editor):
    """
    Undoing everything gives the opened bundle back; redoing, the edited one.
    すべて元に戻すと開いたバンドルに、やり直すと編集後の状態に、そのまま戻る。
    """
    opened = _results(editor)
    x, y = _fiber_middle(editor)
    editor.begin_stroke(RESULT_FIBER_MASK, False)
    editor.paint(x - 6, y, x + 6, y, 9.0)
    editor.end_stroke()
    editor.apply(STAGE_BACKGROUND, editor.compute(STAGE_BACKGROUND))
    editor.set_params(
        replace(editor.params, global_threshold=editor.params.global_threshold * 2),
        STAGE_BINARIZE)
    editor.apply(STAGE_BINARIZE, editor.compute(STAGE_BINARIZE))
    editor.apply(STAGE_SKELETONIZE, editor.compute(STAGE_SKELETONIZE))
    editor.apply(STAGE_KINKS, editor.compute(STAGE_KINKS))
    track_x, track_y = fiber_pixels(max(editor.fibers, key=lambda f: len(f.xtrack)))
    assert editor.add_kink((int(track_x[10]), int(track_y[10])))
    edited = _results(editor)
    flags = (set(editor.stale), set(editor.edited), list(editor.rerun))
    assert not _same(opened, edited)

    steps = 0
    while editor.undo():
        steps += 1
    assert steps == 7
    assert _same(_results(editor), opened)
    assert not editor.modified
    assert not editor.stale and not editor.edited and not editor.rerun

    while editor.redo():
        pass
    assert _same(_results(editor), edited)
    assert (set(editor.stale), set(editor.edited), list(editor.rerun)) == flags
    # The skeleton was replaced on the way, so the fibers are traced again.
    # 途中でスケルトンが置き換わったので、繊維は追跡し直す必要がある。
    assert editor.tracks_stale


def test_saved_edit_keeps_the_mask_and_reopens_as_it_was_saved(bundle, tmp_path):
    """
    An edited bundle stores the mask it was computed with and names its edits.
    編集したバンドルは、計算に使ったマスクを保存し、編集の内容を記録する。
    """
    source = shutil.copy2(bundle, os.path.join(tmp_path, os.path.basename(bundle)))
    shutil.copy2(os.path.splitext(bundle)[0] + ".txt",
                 os.path.join(tmp_path, os.path.basename(os.path.splitext(bundle)[0] + ".txt")))
    editor = BundleEditor(load_edit_session(source))
    x, y = _fiber_middle(editor)
    editor.begin_stroke(RESULT_FIBER_MASK, False)
    editor.paint(x - 6, y, x + 6, y, 9.0)
    editor.end_stroke()
    editor.apply(STAGE_BACKGROUND, editor.compute(STAGE_BACKGROUND))
    changed = replace(editor.params, area_min=editor.params.area_min + 1)
    editor.set_params(changed, STAGE_BINARIZE)
    path = edited_path_for(source, editor.session.meta)

    editor.save(path, editor_name="tester")

    assert not editor.modified
    saved = load_bundle(path)
    meta = load_bundle_meta(path)
    assert np.array_equal(saved[FIBER_MASK_KEY].astype(bool), editor.fiber_mask)
    assert np.array_equal(saved["calibrated"], editor.calibrated)
    assert meta[PARAMS_KEY]["area_min"] == changed.area_min
    record = meta[MANUAL_EDIT_KEY][-1]
    assert record["edited_layers"] == [RESULT_FIBER_MASK]
    assert record["rerun_stages"] == [STAGE_BACKGROUND]
    assert record["stale_layers"] == [RESULT_BINARIZED, RESULT_SKELETON, RESULT_KINKS]

    # Reopened, the stored mask gives the stored heights back, which the mask
    # detected from the raw image would not.
    # 開き直すと、保存したマスクが保存した高さを再現する。生の画像から検出した
    # マスクでは、そうならない。
    again = load_edit_session(path)
    assert again.editable
    assert again.background.reproduces
    assert np.array_equal(again.fiber_mask, editor.fiber_mask)
    assert again.params.area_min == changed.area_min
    # Opening computes nothing again, so the marks are those the bundle was
    # saved with.
    # 開くだけでは何も計算し直さないので、印はバンドルを保存したときのものである。
    reopened = BundleEditor(again)
    assert reopened.stale == {RESULT_BINARIZED, RESULT_SKELETON, RESULT_KINKS}
    assert reopened.edited == {RESULT_FIBER_MASK}
    assert not reopened.rerun and not reopened.modified


def test_mask_is_not_stored_when_nothing_ties_it_to_the_bundle(bundle, tmp_path):
    """
    A kink-only edit of a bundle without its raw image stores no mask.
    生の画像が無いバンドルでキンクだけを編集した場合、マスクは保存しない。
    """
    source = shutil.copy2(bundle, os.path.join(tmp_path, os.path.basename(bundle)))
    editor = BundleEditor(load_edit_session(source))
    assert editor.fiber_mask is None
    assert not editor.can_run(STAGE_BACKGROUND) and not editor.can_run(STAGE_MASK)
    assert editor.can_run(STAGE_BINARIZE)
    track_x, track_y = fiber_pixels(max(editor.fibers, key=lambda f: len(f.xtrack)))
    assert editor.add_kink((int(track_x[20]), int(track_y[20])))
    path = edited_path_for(source, editor.session.meta)

    editor.save(path)

    assert FIBER_MASK_KEY not in load_bundle(path)
    assert load_bundle_meta(path)[MANUAL_EDIT_KEY][-1]["edited_layers"] == [RESULT_KINKS]
