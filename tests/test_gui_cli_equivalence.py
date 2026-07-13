# -*- coding: utf-8 -*-
"""
Assert that GUI01 and ``cli.py process`` produce identical analysis output.
GUI01 と ``cli.py process`` の解析出力が一致することを検証する。

The project claims — in the README and in the JOSS paper — that an analysis run
from the GUI and the same run from the command line produce identical numerical
results for the same input and parameters. Structurally that holds because both
call `lib.pipeline.process_file`, but nothing enforced it: a single line of
parameter massaging added on the GUI side would silently make the claim false,
and the difference would show up in published measurements rather than in CI.
本プロジェクトは README と JOSS 論文で「同一入力・同一パラメータなら GUI と CLI
の数値結果は一致する」と主張している。両者が `lib.pipeline.process_file` を呼ぶ
という構造からそうなるはずだが、それを強制する仕組みは無かった。GUI 側に
パラメータ加工が 1 行入るだけでこの主張は静かに偽となり、その差異は CI ではなく
公表される測定値に現れる。

This test drives GUI01 through its action methods (never through widget lookup,
so UI changes do not break it), runs the CLI on the same input as a subprocess,
and compares every required array in the two bundles.
本テストは GUI01 をアクションメソッド経由で駆動し（ウィジェット探索はしないため
UI 変更で壊れない）、同じ入力に対して CLI を別プロセスで実行し、2 つのバンドルの
必須配列をすべて比較する。
"""

import json
import subprocess
import sys

import numpy as np
import pytest

from conftest import PROJECT_ROOT, pump_until, requires_tk, write_synthetic_fiber_txt

from lib.blosc2_io import load_bundle
from lib.bundle_schema import REQUIRED_BUNDLE_KEYS

import guis.GUI01_Image_Preprocessor as gui01

pytestmark = [requires_tk, pytest.mark.slow]

# Any scan size works; it only has to be the same on both sides, because it is
# what converts pixel counts into physical lengths.
SCAN_SIZE_UM = 2.0


def _run_gui01(input_dir, monkeypatch, tk_app, silence_dialogs) -> None:
    """
    Run a full GUI01 batch over ``input_dir`` and return once it has finished.
    ``input_dir`` に対する GUI01 の一括解析を実行し、完了後に戻る。
    """
    settings = input_dir / "gui01_settings.json"
    monkeypatch.setattr(gui01, "_settings_path", lambda: str(settings))
    # Patching the dialog, rather than clicking the button that opens it, keeps
    # the test independent of the toolbar's layout and labels.
    monkeypatch.setattr(gui01.filedialog, "askdirectory", lambda **kw: str(input_dir))

    app = tk_app(gui01.App)
    dialogs = silence_dialogs(gui01)

    app.on_select_folder()
    assert app.items, "GUI01 listed no input files"

    # GUI01 refuses to run without a scan size, which the synthetic input has no
    # header to supply; assign it as the manual-entry path would.
    # GUI01 は走査範囲が無いと実行を拒否する。合成入力にはヘッダが無いため、
    # 手入力の経路と同じ形で設定する。
    for item in app.items:
        item.scale_x_um = SCAN_SIZE_UM
        item.scale_y_um = SCAN_SIZE_UM
        item.scale_source = "manual"

    app.on_run_all()
    pump_until(app, lambda: not app.is_running)

    assert not dialogs, f"GUI01 reported a problem: {dialogs}"


def _run_cli(txt_path, output_dir) -> None:
    """
    Run ``cli.py process`` on the same input, writing outputs elsewhere.
    同じ入力に対して ``cli.py process`` を実行し、出力を別の場所に書き出す。
    """
    result = subprocess.run(
        [
            sys.executable, "cli.py", "process", str(txt_path),
            "--output-dir", str(output_dir),
            "--scale-um", str(SCAN_SIZE_UM),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"cli.py process failed:\n{result.stderr}"


def test_gui01_and_cli_produce_identical_bundles(
    tmp_path, monkeypatch, tk_app, silence_dialogs
):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    cli_out = tmp_path / "cli_out"
    cli_out.mkdir()

    txt_path = write_synthetic_fiber_txt(str(input_dir))

    _run_gui01(input_dir, monkeypatch, tk_app, silence_dialogs)
    _run_cli(txt_path, cli_out)

    gui_bundle = input_dir / "synthetic_fiber.b2z"
    cli_bundle = cli_out / "synthetic_fiber.b2z"
    assert gui_bundle.exists(), "GUI01 wrote no bundle"
    assert cli_bundle.exists(), "cli.py process wrote no bundle"

    # Compare the recorded parameters before the arrays. Not every ProcParams
    # field changes the output of every image — a parameter the front ends
    # disagree on can leave this synthetic scan pixel-identical — so comparing
    # only the arrays would let that drift through. The parameter record catches
    # it whether or not it happens to move a pixel.
    # 配列より先にパラメータ記録を比較する。ProcParams の全フィールドが常に出力を
    # 変えるわけではなく、front end 間で食い違ったパラメータでもこの合成スキャンでは
    # 画素が一致しうる。配列だけを比較するとそのずれを見逃すため、画素が動くか
    # どうかに依らず検出できるパラメータ記録を先に確認する。
    gui_params = json.loads((input_dir / "synthetic_fiber_param.json").read_text())
    cli_params = json.loads((cli_out / "synthetic_fiber_param.json").read_text())
    assert gui_params == cli_params, "GUI and CLI recorded different parameters"

    gui_arrays = load_bundle(str(gui_bundle))
    cli_arrays = load_bundle(str(cli_bundle))

    for key in REQUIRED_BUNDLE_KEYS:
        gui_value = np.asarray(gui_arrays[key])
        cli_value = np.asarray(cli_arrays[key])
        assert gui_value.shape == cli_value.shape, f"{key}: shape differs"
        # Bit-for-bit equality is the right bar here: both sides run the same
        # deterministic pipeline on the same array, so any drift at all means
        # one front end is no longer doing what the other does.
        # ここでは完全一致を要求する。両者は同一配列に同一の決定的パイプラインを
        # 適用するため、わずかな差異でも一方の front end が他方と異なる処理を
        # していることを意味する。
        assert np.array_equal(gui_value, cli_value), f"{key}: values differ"
