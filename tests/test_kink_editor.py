# -*- coding: utf-8 -*-
"""
Tests for changing a bundle's kinks by hand and saving the edit (`bundle_edit`).
バンドルのキンクを手で変更し、その編集を保存する処理（`bundle_edit`）のテスト。

A kink a person places gets its angle from two arm ends the person chooses.
These tests pin down what that angle is, that a kink the bundle stores keeps
its values until one of its arm ends is moved, and that a saved edit is a
bundle the measuring code reads, marked as edited and never written over the
analysis it started from.
人が置くキンクの角度は、人が選ぶ 2 つの腕の端で決まる。以下のテストは、その角度が
何であるか、バンドルが保存するキンクが腕の端を動かすまで値を保つこと、そして保存
した編集が、計測のコードが読めるバンドルであり、編集済みの印が付き、元になった
解析の上に書かれることは無いことを固定する。
"""

import os
import shutil

import numpy as np
import pytest

from afm_nanofiber_analyzer.blosc2_io import load_bundle, load_bundle_meta, save_bundle
from afm_nanofiber_analyzer.bundle_edit import (
    ARM_AFTER, ARM_BEFORE, ARM_GAP_WIDTHS, DEFAULT_ARM_WIDTHS, EDITED_SUFFIX,
    MARK_KINK, MARK_UNJUDGED, RESULT_KINKS, BundleEditor, KinkEditor,
    arm_angle, edited_path_for, fiber_line, fiber_pixels, load_edit_session,
)
from afm_nanofiber_analyzer.bundle_schema import (
    BUNDLE_FORMAT_VERSION, KINK_ARMS_KEY, MANUAL_EDIT_KEY, REQUIRED_BUNDLE_KEYS,
    validate_bundle,
)
from afm_nanofiber_analyzer.measure import load_tracking_image
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt

# Values given to the kink the tests store in a bundle's arrays: any angle
# inside (0, pi) and any non-negative excess, chosen so that no measurement
# returns them by chance.
# テストがバンドルの配列に保存しておくキンクの値。(0, pi) の内側の内角と非負の
# 超過回転であれば何でもよく、測定が偶然同じ値を返さないように選んである。
STORED_ANGLE = 2.4
STORED_EXCESS = 0.7


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    """
    A synthetic scan analyzed and opened for editing, shared across this module.
    合成走査を解析し、編集のために開いたもの。モジュール内で共有する。

    The scan holds one fiber of two straight segments. No test changes the
    session itself: an editor keeps its own copy of the marks.
    走査は、2 本のまっすぐな線分からなる繊維を 1 本持つ。どのテストもセッション
    自体は変更しない。エディタは印の写しを自分で持つためである。
    """
    folder = tmp_path_factory.mktemp("kink_editor")
    txt = write_synthetic_fiber_txt(folder)
    return load_edit_session(process_file(txt, ProcParams()).bundle_path)


def _fiber(session):
    """
    Return the session's longest fiber.
    セッションで最も長い繊維を返す。
    """
    return max(session.fibers, key=lambda candidate: len(candidate.xtrack))


def _pixels(session):
    """
    Return the pixels of the longest fiber, in order along its line.
    最も長い繊維の画素を、線に沿った順で返す。
    """
    track_x, track_y = fiber_pixels(_fiber(session))
    return list(zip(track_x.tolist(), track_y.tolist()))


def _marks(arrays):
    """
    Return a bundle's kinks as ``{pixel: (angle, excess)}`` and its ``up`` pixels.
    バンドルのキンクを ``{画素: (内角, 超過回転)}`` で、``up`` の画素を集合で返す。
    """
    kinks = {
        (int(x), int(y)): (float(angle), float(excess))
        for x, y, angle, excess in zip(
            arrays["kp"][0], arrays["kp"][1], arrays["ka"], arrays["ke"])
    }
    unjudged = set(zip(arrays["up"][0].tolist(), arrays["up"][1].tolist()))
    return kinks, unjudged


def _editor(session):
    """
    Build the kink editor of a session as it was stored.
    保存されたままのセッションの、キンクエディタを作る。
    """
    return KinkEditor(session.fibers, session.arrays, session.pixel_aspect)


def _editor_with_stored_kink(session):
    """
    Build an editor whose bundle stores one kink, at the middle of the fiber.
    繊維の中央にキンクを 1 つ保存しているバンドルの、エディタを作る。

    The synthetic scan's analysis finds no kink, so the stored kink is
    written into a copy of the arrays the editor reads.
    合成走査の解析はキンクを見つけないので、保存済みのキンクは、エディタが読む
    配列の写しに書き込む。

    Returns the editor and the kink's index along the fiber.
    エディタと、繊維に沿ったキンクのインデックスを返す。
    """
    pixels = _pixels(session)
    index = len(pixels) // 2
    arrays = dict(session.arrays)
    arrays["kp"] = np.array([[pixels[index][0]], [pixels[index][1]]], dtype=np.int64)
    arrays["ka"] = np.array([STORED_ANGLE])
    arrays["ke"] = np.array([STORED_EXCESS])
    return KinkEditor(session.fibers, arrays, session.pixel_aspect), index


def _arc(session):
    """
    Arc length along the longest fiber's line at each of its points, in pixels.
    最も長い繊維の線に沿った、各点での弧長（画素）。
    """
    line_x, line_y = fiber_line(_fiber(session))
    return np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(line_x), np.diff(line_y)))])


def _angle_of(editor, pixels, index, first, second):
    """
    Angle the editor measures for a kink at `index` with ends at two indices.
    `index` のキンクについて、2 つのインデックスに端を置いたときにエディタが測る角度。
    """
    return editor.measure_arms(pixels[index], pixels[first], pixels[second])[0]


def test_arm_angle_is_the_angle_between_the_two_arms():
    """
    Arms in line give pi, folded arms 0, whatever points they start at.
    一直線の腕は pi、折り重なった腕は 0 になる。腕の始点がどこでも同じである。
    """
    assert arm_angle((0, 0), (-1, 0), (0, 0), (0, 1)) == pytest.approx(np.pi / 2)
    assert arm_angle((-1, 0), (-3, 0), (2, 0), (5, 0)) == pytest.approx(np.pi)
    assert arm_angle((1, 0), (3, 0), (1, 1), (4, 1)) == pytest.approx(0.0)
    # Arms that start apart: only their directions enter the angle.
    # 始点が離れた腕。角度に入るのは向きだけである。
    assert arm_angle((-1, 0), (-4, 0), (0, 2), (0, 7)) == pytest.approx(np.pi / 2)
    assert np.isnan(arm_angle((1, 1), (1, 1), (0, 0), (4, 5)))


def test_editor_starts_from_the_stored_marks(session):
    """
    An editor that has changed nothing gives the bundle's own arrays back.
    何も変更していないエディタは、バンドル自身の配列を返す。
    """
    editor = _editor(session)

    assert session.editable
    assert not editor.modified and not editor.can_undo
    assert not editor.off_track
    assert _marks(editor.arrays()) == _marks(session.arrays)
    assert editor.kink_arms() == []

    stored, index = _editor_with_stored_kink(session)
    kink = _pixels(session)[index]
    assert stored.kink_pixels() == [kink]
    assert stored.kink_values(kink) == (STORED_ANGLE, STORED_EXCESS)
    assert not stored.angle_is_set_by_hand(kink)
    assert not stored.modified


def test_added_kink_takes_the_angle_between_its_arms(session):
    """
    A placed kink's angle is the one between the arms its two ends give.
    置いたキンクの角度は、2 つの端で決まる腕のなす角である。
    """
    editor = _editor(session)
    pixels = _pixels(session)
    index = 40

    assert editor.add_kink(pixels[index])

    first, second, by_hand = editor.arm_ends(pixels[index])
    assert by_hand and editor.angle_is_set_by_hand(pixels[index])
    angle, excess = editor.kink_values(pixels[index])
    measured, points = editor.measure_arms(pixels[index], first, second)
    assert angle == measured
    # The angle is the one between the two drawn arms.
    # 角度は、描かれる 2 本の腕のなす角である。
    assert angle == pytest.approx(arm_angle(points[1], points[0], points[2], points[3]))
    assert excess == pytest.approx(np.pi - angle)
    assert editor.kink_arms() == [[*pixels[index], *first, *second]]
    arrays = dict(session.arrays)
    arrays.update(editor.arrays())
    assert validate_bundle(arrays, meta=session.meta, require=REQUIRED_BUNDLE_KEYS) == []
    assert not editor.add_kink(pixels[index])
    assert not editor.add_kink((-3, -3))


def test_placed_kink_gets_ends_a_set_distance_along_the_line(session):
    """
    A placed kink's ends lie `DEFAULT_ARM_WIDTHS` widths away along the line.
    置いたキンクの端は、線に沿って幅の `DEFAULT_ARM_WIDTHS` 倍だけ離れた位置にある。
    """
    editor = _editor(session)
    pixels = _pixels(session)
    arc = _arc(session)
    index = 60
    editor.add_kink(pixels[index])

    first, second, _by_hand = editor.arm_ends(pixels[index])

    reach = DEFAULT_ARM_WIDTHS * _fiber(session).width_px
    # Each end is the line point nearest that distance, within one point.
    # 各端は、その距離に最も近い線の点であり、ずれは 1 点以内である。
    assert arc[index] - arc[pixels.index(first)] == pytest.approx(reach, abs=1.5)
    assert arc[pixels.index(second)] - arc[index] == pytest.approx(reach, abs=1.5)


def test_arms_start_half_a_width_from_the_kink(session):
    """
    Each arm starts `ARM_GAP_WIDTHS` widths from the kink, or halfway to a near end.
    各腕は、キンクから幅の `ARM_GAP_WIDTHS` 倍の位置で始まる。端が近ければ、端までの
    中間で始まる。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    arc = _arc(session)
    line_x, line_y = fiber_line(_fiber(session))
    line = list(zip(line_x.tolist(), line_y.tolist()))
    gap = ARM_GAP_WIDTHS * _fiber(session).width_px

    _angle, points = editor.measure_arms(pixels[index], pixels[index - 20], pixels[index + 20])
    first_start, second_start = line.index(points[1]), line.index(points[2])
    assert arc[index] - arc[first_start] == pytest.approx(gap, abs=1.0)
    assert arc[second_start] - arc[index] == pytest.approx(gap, abs=1.0)

    # An end two points away leaves no room for the gap: the arm starts
    # halfway, at the point between the kink and the end.
    # 2 点先の端では、すき間を取る余地が無い。腕は中間、すなわちキンクと端の間の
    # 点で始まる。
    _angle, points = editor.measure_arms(pixels[index], pixels[index - 2], pixels[index + 20])
    assert line.index(points[1]) == index - 1

    # An end beside the kink still gives an arm, from the kink itself.
    # キンクの隣の端でも腕は残り、キンク自身から始まる。
    angle, points = editor.measure_arms(pixels[index], pixels[index - 1], pixels[index + 1])
    assert points[1] == points[2] == line[index]
    assert 0.0 < angle < np.pi


def test_arm_end_stops_at_a_neighbouring_mark(session):
    """
    An arm does not run through the kink next to it.
    腕は、隣のキンクを通り越さない。
    """
    editor = _editor(session)
    pixels = _pixels(session)
    editor.add_kink(pixels[60])

    assert editor.add_kink(pixels[63])

    first, _second, _by_hand = editor.arm_ends(pixels[63])
    assert first == pixels[60]


def test_kink_at_an_end_of_the_fiber_is_refused(session):
    """
    An end of the line has no point on one side, so no angle can be read.
    線の端には片側に点が無く、角度を読めない。
    """
    editor = _editor(session)
    pixels = _pixels(session)

    assert not editor.add_kink(pixels[0])
    assert not editor.add_kink(pixels[-1])
    assert editor.default_arms(pixels[0]) is None
    assert editor.add_kink(pixels[1])


def test_other_marks_never_change_a_stored_kink(session):
    """
    Adding or removing marks beside a stored kink leaves its values as stored.
    保存済みのキンクのそばで印を足したり除いたりしても、その値は保存されたままである。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)

    assert editor.add_kink(pixels[index + 3])
    assert editor.add_kink(pixels[index - 30])
    assert editor.remove_mark(pixels[index + 3])

    assert editor.kink_values(pixels[index]) == (STORED_ANGLE, STORED_EXCESS)
    assert not editor.angle_is_set_by_hand(pixels[index])


def test_moving_an_arm_end_sets_the_angle_of_a_stored_kink(session):
    """
    A stored kink keeps the rule's values until one of its arm ends is moved.
    保存済みのキンクは、腕の端のどちらかを動かすまで、規則の値を保つ。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    kink = pixels[index]
    # Before a move the ends are a starting point, not what was measured.
    # 動かす前の端は出発点であり、測った位置ではない。
    first, _second, by_hand = editor.arm_ends(kink)
    assert not by_hand
    assert not editor.modified

    assert editor.set_arm(kink, ARM_AFTER, pixels[index + 20])

    angle, excess = editor.kink_values(kink)
    assert angle == _angle_of(editor, pixels, index, pixels.index(first), index + 20)
    assert excess == pytest.approx(np.pi - angle)
    assert editor.arm_ends(kink) == (first, pixels[index + 20], True)
    assert editor.kink_arms() == [[*kink, *first, *pixels[index + 20]]]
    # The same place again, the wrong side, and a pixel off the fiber.
    # 同じ位置をもう一度、反対側の画素、繊維の上に無い画素。
    assert not editor.set_arm(kink, ARM_AFTER, pixels[index + 20])
    assert not editor.set_arm(kink, ARM_AFTER, pixels[index - 5])
    assert not editor.set_arm(kink, ARM_BEFORE, pixels[index + 5])
    assert not editor.set_arm(kink, ARM_BEFORE, (-1, -1))

    assert editor.set_arm(kink, ARM_BEFORE, pixels[index - 25])
    assert editor.kink_values(kink)[0] == _angle_of(
        editor, pixels, index, index - 25, index + 20)


def test_measured_arms_report_the_line_points_the_arms_run_between(session):
    """
    A measurement returns the angle and the four line points of the two arms.
    測定は、角度と、2 本の腕の線上の 4 点を返す。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    line_x, line_y = fiber_line(_fiber(session))

    angle, points = editor.measure_arms(pixels[index], pixels[index - 12], pixels[index + 18])

    # The outer points are the ends' own line points; the angle is the one
    # between the two arms the four points give.
    # 外側の 2 点は、端そのものの線の点である。角度は、4 点で決まる 2 本の腕の
    # なす角である。
    assert points[0] == (line_x[index - 12], line_y[index - 12])
    assert points[3] == (line_x[index + 18], line_y[index + 18])
    assert angle == pytest.approx(arm_angle(points[1], points[0], points[2], points[3]))
    # Measuring changes nothing, and both ends on one side measure nothing.
    # 測るだけでは何も変わらない。両方の端が片側にあれば、何も測らない。
    assert editor.kink_values(pixels[index]) == (STORED_ANGLE, STORED_EXCESS)
    assert editor.measure_arms(pixels[index], pixels[index + 3], pixels[index + 18]) is None


def test_nearest_arm_pixel_stays_on_its_side_of_the_kink(session):
    """
    A dragged end cannot cross the kink: it snaps to a pixel on its own side.
    ドラッグ中の端はキンクを越えられない。自分の側の画素に吸い付く。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    beyond = pixels[index + 15]

    before = editor.nearest_arm_pixel(pixels[index], ARM_BEFORE, beyond[0], beyond[1])
    after = editor.nearest_arm_pixel(pixels[index], ARM_AFTER, beyond[0], beyond[1])

    assert pixels.index(before) < index
    assert after == beyond


def test_kink_at_the_drawn_corner_reads_the_drawn_angle(session):
    """
    At the fiber's corner the arms read close to the angle it was drawn at.
    繊維の角では、腕は、描いたときの角度に近い値を読む。
    """
    editor = _editor(session)
    pixels = _pixels(session)
    # The scan draws two segments meeting at raw pixel (100, 90); the stored
    # arrays start at raw pixel (1, 1).
    # 走査は、生の画素 (100, 90) で交わる 2 本の線分を描く。保存された配列は、
    # 生の画像の画素 (1, 1) から始まる。
    corner = (99, 89)
    drawn = arm_angle((100, 90), (30, 30), (100, 90), (120, 160))
    index = int(np.argmin([np.hypot(x - corner[0], y - corner[1]) for x, y in pixels]))

    assert editor.add_kink(pixels[index])

    placed = editor.kink_values(pixels[index])[0]
    far = _angle_of(editor, pixels, index, index - 30, index + 30)
    assert np.degrees(abs(placed - drawn)) < 4.0
    assert np.degrees(abs(far - drawn)) < 2.0


def test_marks_can_be_removed_and_moved(session):
    """
    A kink is removed, or moved to another fiber pixel and measured there.
    キンクは、除くことも、別の繊維の画素へ動かしてそこで測ることもできる。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    kink, target = pixels[index], pixels[index + 30]

    assert editor.nearest_mark(kink[0] + 1.0, kink[1], 3.0) == (MARK_KINK, kink)
    assert editor.nearest_track_pixel(target[0], target[1], 0.5) == target
    assert editor.move_kink(kink, target)
    assert editor.kink_values(kink) is None
    # A moved kink is a kink placed at the target; it carries no values over.
    # 動かしたキンクは、動かした先に置いたキンクである。値を持ち越さない。
    assert editor.angle_is_set_by_hand(target)
    assert editor.kink_values(target) != (STORED_ANGLE, STORED_EXCESS)
    assert not editor.move_kink(kink, target)
    assert not editor.move_kink(target, pixels[0])
    assert editor.kink_values(target) is not None

    assert editor.remove_mark(target)
    assert editor.arrays()["kp"].shape == (2, 0)
    assert editor.kink_arms() == []
    assert not editor.remove_mark(target)


def test_unjudged_bend_is_replaced_by_a_kink_put_on_it(session):
    """
    Putting a kink on a bend that was not judged leaves the kink alone there.
    判定しなかった折れの上にキンクを置くと、そこにはキンクだけが残る。
    """
    pixel = _pixels(session)[5]
    arrays = dict(session.arrays)
    arrays["up"] = np.array([[pixel[0]], [pixel[1]]], dtype=np.int64)
    editor = KinkEditor(session.fibers, arrays, session.pixel_aspect)
    assert editor.nearest_mark(pixel[0], pixel[1], 1.0) == (MARK_UNJUDGED, pixel)

    assert editor.add_kink(pixel)

    assert editor.unjudged_pixels() == []
    assert editor.kink_values(pixel) is not None


def test_undo_and_redo_restore_the_marks_exactly(session):
    """
    Undo gives the marks before a change back, and redo the marks after it.
    元に戻すと変更前の印が、やり直すと変更後の印が、そのまま戻る。
    """
    editor, index = _editor_with_stored_kink(session)
    pixels = _pixels(session)
    before = (_marks(editor.arrays()), editor.kink_arms())
    editor.set_arm(pixels[index], ARM_BEFORE, pixels[index - 20])
    after = (_marks(editor.arrays()), editor.kink_arms())
    assert after != before

    assert editor.undo()
    assert (_marks(editor.arrays()), editor.kink_arms()) == before
    assert not editor.modified
    assert editor.redo()
    assert (_marks(editor.arrays()), editor.kink_arms()) == after
    assert not editor.redo()


def test_saved_edit_is_a_marked_bundle_the_readers_measure(session, tmp_path):
    """
    The edit is saved beside the analysis, marked, and read like any bundle.
    編集は解析結果の隣に印を付けて保存され、ほかのバンドルと同じように読まれる。
    """
    work = tmp_path / "work"
    work.mkdir()
    source = shutil.copy2(
        session.bundle_path, os.path.join(work, os.path.basename(session.bundle_path)))
    opened = load_edit_session(source)
    state = BundleEditor(opened)
    editor = state.kinks
    pixels = _pixels(opened)
    assert state.add_kink(pixels[40])
    assert state.set_arm(pixels[40], ARM_AFTER, pixels[70])
    path = edited_path_for(source, opened.meta)
    assert os.path.basename(path) == (
        os.path.splitext(os.path.basename(source))[0] + EDITED_SUFFIX + ".b2z")

    param_path = state.save(path, editor_name="  tester ")

    saved = load_bundle(path)
    meta = load_bundle_meta(path)
    assert os.path.isfile(param_path)
    assert validate_bundle(saved, meta=meta, require=REQUIRED_BUNDLE_KEYS) == []
    assert _marks(saved) == _marks(editor.arrays())
    np.testing.assert_allclose(saved["ke"], np.pi - saved["ka"])
    for key, stored in opened.arrays.items():
        if key not in ("kp", "ka", "ke", "up"):
            np.testing.assert_array_equal(saved[key], stored)
    record, = meta[MANUAL_EDIT_KEY]
    assert record["edited_layers"] == [RESULT_KINKS]
    assert record["rerun_stages"] == [] and record["stale_layers"] == []
    assert record["source_bundle"] == os.path.basename(source)
    assert record["editor"] == "tester"
    assert meta["version"] == BUNDLE_FORMAT_VERSION
    assert [list(entry) for entry in meta[KINK_ARMS_KEY]] == editor.kink_arms()

    # The function GUI03 and GUI04 measure through finds the added kink.
    # GUI03 と GUI04 が計測に使う関数が、足したキンクを見つける。
    kinks = set()
    for fiber in load_tracking_image(path, 1.0, 1.0).fibers_in_image_parallel():
        track_x, track_y = fiber_pixels(fiber)
        kinks.update((int(track_x[i]), int(track_y[i])) for i in fiber.kink_indices)
    assert pixels[40] in kinks

    # Opened again, the kink has the arm ends it was saved with.
    # 開き直すと、キンクは保存したときの腕の端を持っている。
    again = load_edit_session(path)
    reopened = KinkEditor(again.fibers, again.arrays, again.pixel_aspect,
                          kink_arms=again.meta.get(KINK_ARMS_KEY))
    assert reopened.arm_ends(pixels[40]) == editor.arm_ends(pixels[40])
    assert reopened.kink_values(pixels[40]) == editor.kink_values(pixels[40])
    assert not reopened.modified


def test_recorded_arms_that_do_not_fit_are_left_out(session):
    """
    Arm ends that are not on either side of their kink are not taken over.
    キンクの両側に無い腕の端は、取り込まない。
    """
    pixels = _pixels(session)
    arrays = dict(session.arrays)
    kink = pixels[50]
    arrays["kp"] = np.array([[kink[0]], [kink[1]]], dtype=np.int64)
    arrays["ka"] = np.array([STORED_ANGLE])
    arrays["ke"] = np.array([STORED_EXCESS])

    same_side = KinkEditor(
        session.fibers, arrays, kink_arms=[[*kink, *pixels[60], *pixels[70]]])
    no_such_kink = KinkEditor(
        session.fibers, arrays, kink_arms=[[*pixels[20], *pixels[10], *pixels[30]]])
    fitting = KinkEditor(
        session.fibers, arrays, kink_arms=[[*kink, *pixels[40], *pixels[70]]])

    assert not same_side.angle_is_set_by_hand(kink)
    assert no_such_kink.kink_arms() == []
    assert fitting.arm_ends(kink) == (pixels[40], pixels[70], True)
    # Taking recorded arms over does not measure again: the stored values stay.
    # 記録された腕を取り込むだけでは測り直さない。保存された値がそのまま残る。
    assert fitting.kink_values(kink) == (STORED_ANGLE, STORED_EXCESS)


def test_analyzed_bundle_is_never_saved_over(session, tmp_path):
    """
    An edit cannot replace the bundle the analysis wrote, only an edited one.
    編集は、解析が書いたバンドルを置き換えられない。置き換えられるのは編集済みの
    バンドルだけである。
    """
    source = shutil.copy2(
        session.bundle_path, os.path.join(tmp_path, os.path.basename(session.bundle_path)))
    opened = load_edit_session(source)
    state = BundleEditor(opened)

    with pytest.raises(ValueError):
        state.save(source)

    path = edited_path_for(source, opened.meta)
    state.save(path)
    edited = load_edit_session(path)
    assert edited_path_for(path, edited.meta) == path
    BundleEditor(edited).save(path)
    records = load_bundle_meta(path)[MANUAL_EDIT_KEY]
    assert len(records) == 2
    assert "editor" not in records[0]


def test_bundle_of_another_format_is_shown_but_not_edited(session, tmp_path):
    """
    A bundle whose format is not the current one opens and refuses a save.
    現在の形式でないバンドルは、開けるが、保存は拒否される。
    """
    arrays = load_bundle(session.bundle_path)
    meta = load_bundle_meta(session.bundle_path)
    meta["version"] = "1.7"
    older = os.path.join(tmp_path, "older.b2z")
    save_bundle(older, arrays, vlmeta=meta)

    opened = load_edit_session(older)

    assert not opened.editable
    with pytest.raises(ValueError):
        BundleEditor(opened)
