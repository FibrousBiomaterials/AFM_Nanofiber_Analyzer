# -*- coding: utf-8 -*-
"""
Tests for lib/gwy_convert.py and the ``cli.py convert`` subcommand.
lib/gwy_convert.py と ``cli.py convert`` サブコマンドのテスト。

The selection rules and the converter lookup run everywhere. The conversions
themselves need the optional ``gwyddionpy-converter`` package and are skipped
without it.
対象の選び方と変換プログラムの探索はどの環境でも実行する。変換そのものは任意の
``gwyddionpy-converter`` パッケージが必要で、無い環境では飛ばす。
"""

import os
import re
import shutil
import tomllib

import numpy as np
import pytest

import cli
from lib import gwy_convert
from lib.afm_io import load_afm_image
from lib.gwy_io import load_gwy_image
from tests.conftest import HIGHER_PLANT_DATA, PROJECT_ROOT


def _converter_or_skip() -> str:
    """Return the gwyconvert path, or skip the test when it is not installed."""
    try:
        return gwy_convert.find_converter()
    except gwy_convert.ConverterNotFoundError:
        pytest.skip("gwyconvert (optional 'convert' dependency) is not installed")


@pytest.mark.parametrize("name, expected", [
    ("scan.000", True),
    ("scan.spm", True),
    ("scan.JPK", True),
    ("no_extension", True),
    ("scan.txt", False),
    ("scan.CSV", False),
    ("scan.gwy", False),
    ("scan.b2z", False),
    ("scan_param.json", False),
    ("array.npy", False),
    (".DS_Store", False),
])
def test_conversion_candidates_are_chosen_by_extension(name, expected):
    """Everything except the readable and written extensions is converted."""
    assert gwy_convert.is_conversion_candidate(name) is expected


def test_output_keeps_the_input_extension():
    """``scan.000`` and ``scan.001`` convert to different ``.gwy`` names."""
    assert gwy_convert.converted_path_for("d/scan.000") == "d/scan.000_converted.gwy"
    assert gwy_convert.converted_path_for("d/scan.001") == "d/scan.001_converted.gwy"


@pytest.mark.parametrize("raw, text_export", [
    ("scan.ssp", "scan.ssp.txt"),
    ("NDTOC250306.000", "NDTOC250306.000.txt"),
])
def test_output_and_text_export_analyze_into_different_bundles(raw, text_export):
    """
    A converted file and the text export of the same scan get different bundles.
    変換したファイルと、同じスキャンのテキスト出力は別のバンドルになる。

    GUI01 names a bundle after its input less the last extension
    (`pipeline.process_file`), and instruments name text exports after the raw
    file, so the plain ``<raw>.gwy`` would share the text export's bundle.
    """
    converted = gwy_convert.converted_path_for(raw)
    assert os.path.splitext(converted)[0] != os.path.splitext(text_export)[0]


def test_folder_listing_takes_candidates_directly_inside(tmp_path):
    """Subfolders and skipped extensions are left out; names are sorted."""
    for name in ("b.000", "A.spm", "c.txt", "c.txt.b2z", ".hidden"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.000").write_bytes(b"x")

    found = gwy_convert.list_conversion_candidates(str(tmp_path))
    assert [os.path.basename(p) for p in found] == ["A.spm", "b.000"]


def test_existing_output_is_skipped_without_running_the_converter(tmp_path):
    """An input whose ``.gwy`` exists is reported, and the file is untouched."""
    src = tmp_path / "scan.000"
    src.write_bytes(b"raw")
    out = tmp_path / "scan.000_converted.gwy"
    out.write_bytes(b"earlier conversion")

    # A converter path that does not exist proves it was never started.
    result = gwy_convert.convert_file(str(src), converter=str(tmp_path / "missing.exe"))
    assert result.status == gwy_convert.STATUS_EXISTS
    assert out.read_bytes() == b"earlier conversion"


def test_a_wrong_converter_setting_is_reported(tmp_path, monkeypatch):
    """A converter path the user named is never silently replaced."""
    monkeypatch.setenv(gwy_convert.CONVERTER_ENV_VAR, str(tmp_path / "nope.exe"))
    with pytest.raises(gwy_convert.ConverterNotFoundError, match="GWYDDIONPY_CONVERT"):
        gwy_convert.find_converter()
    with pytest.raises(gwy_convert.ConverterNotFoundError, match="given path"):
        gwy_convert.find_converter(str(tmp_path / "also_missing.exe"))


def test_install_command_matches_the_optional_dependency():
    """The install hint names the same requirement as the ``convert`` extra."""
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        extra = tomllib.load(f)["project"]["optional-dependencies"]["convert"]
    assert len(extra) == 1
    assert re.search(r'"([^"]+)"', gwy_convert.INSTALL_COMMAND).group(1) == extra[0]


@pytest.mark.skipif(not HIGHER_PLANT_DATA.exists(), reason="bundled test scan not present")
def test_vendor_file_converts_to_the_heights_the_text_loader_reads(tmp_path):
    """
    A Shimadzu file under an unread extension converts to the same heights.
    読めない拡張子にした島津ファイルが、同じ高さへ変換される。
    """
    converter = _converter_or_skip()
    # A Japanese folder name also checks that non-ASCII paths reach gwyconvert.
    folder = tmp_path / "日本語 フォルダ"
    folder.mkdir()
    src = folder / "scan.dat"
    shutil.copyfile(HIGHER_PLANT_DATA, src)

    result = gwy_convert.convert_file(str(src), converter=converter)
    assert result.status == gwy_convert.STATUS_CONVERTED, result.message
    assert result.module == "shimadzu"

    converted = load_gwy_image(result.output)
    expected = load_afm_image(str(HIGHER_PLANT_DATA))
    assert converted.data.shape == expected.shape
    assert np.max(np.abs(converted.data - expected)) < 1e-9
    assert converted.scan_size.x_um == pytest.approx(2.0)
    assert converted.scan_size.y_um == pytest.approx(2.0)
    # Nothing but the input and its .gwy is left in the folder.
    assert sorted(os.listdir(folder)) == ["scan.dat", "scan.dat_converted.gwy"]


def test_image_without_a_length_channel_is_rejected(tmp_path):
    """
    An ordinary image converts in Gwyddion but is not kept as a height map.
    通常の画像は Gwyddion では変換できるが、高さ像としては残さない。
    """
    converter = _converter_or_skip()
    src = tmp_path / "screenshot.png"
    shutil.copyfile(PROJECT_ROOT / "figures" / "pipeline.png", src)

    result = gwy_convert.convert_file(str(src), converter=converter)
    assert result.status == gwy_convert.STATUS_FAILED
    assert "length unit" in result.message
    assert sorted(os.listdir(tmp_path)) == ["screenshot.png"]


def test_unreadable_file_fails_and_leaves_nothing(tmp_path):
    """A file no Gwyddion module reads fails without leaving an output."""
    converter = _converter_or_skip()
    src = tmp_path / "notes.md"
    src.write_text("# not a measurement\n", encoding="utf-8")

    result = gwy_convert.convert_file(str(src), converter=converter)
    assert result.status == gwy_convert.STATUS_FAILED
    assert result.message
    assert sorted(os.listdir(tmp_path)) == ["notes.md"]


@pytest.mark.skipif(not HIGHER_PLANT_DATA.exists(), reason="bundled test scan not present")
def test_cli_convert_reports_each_outcome(tmp_path, capsys):
    """``cli.py convert`` converts once, skips on the second run, and exits 1 on a failure."""
    _converter_or_skip()
    shutil.copyfile(HIGHER_PLANT_DATA, tmp_path / "scan.dat")
    (tmp_path / "notes.md").write_text("# not a measurement\n", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("1 2\n3 4\n", encoding="utf-8")

    assert cli.main(["convert", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "1 converted, 0 skipped (already converted), 1 failed" in out
    assert "plain.txt" not in out

    assert cli.main(["convert", str(tmp_path / "scan.dat")]) == 0
    assert "0 converted, 1 skipped" in capsys.readouterr().out


def test_cli_convert_without_inputs_exits_2(tmp_path):
    """A folder with nothing to convert is an input error, not a success."""
    (tmp_path / "plain.txt").write_text("1 2\n3 4\n", encoding="utf-8")
    assert cli.main(["convert", str(tmp_path)]) == 2
