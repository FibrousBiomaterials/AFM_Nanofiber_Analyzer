# -*- coding: utf-8 -*-
"""
Tests for lib/gwy_io.py Gwyddion .gwy loading and the afm_io/pipeline dispatch.
lib/gwy_io.py の Gwyddion .gwy 読み込みと afm_io/pipeline 振り分けのテスト。
"""

import numpy as np
import pytest

# The .gwy reader and the synthetic-.gwy fixture both require the optional
# gwyfile package; skip the whole module when it is not installed.
# .gwy リーダと合成 .gwy フィクスチャはともにオプションの gwyfile を必要とする
# ため、未インストール時はモジュール全体をスキップする。
pytest.importorskip("gwyfile")

from lib.afm_io import ScanSize, load_afm_image, read_scan_size
from lib.gwy_io import (
    list_gwy_channels,
    load_gwy_image,
    read_gwy_scan_size,
    select_default_channel,
)
from tests.conftest import REAL_GWY_DATA


@pytest.mark.skipif(not REAL_GWY_DATA.exists(), reason="bundled .gwy scan not present")
def test_load_real_gwy_scan():
    """
    Load the bundled native Gwyddion scan with its physical calibration.
    同梱 Gwyddion ネイティブスキャンを物理較正情報とともに読み込む。
    """
    channels = list_gwy_channels(str(REAL_GWY_DATA))
    assert len(channels) == 1
    assert channels[0].title == "Topography"
    assert channels[0].z_unit == "m"

    image = load_gwy_image(str(REAL_GWY_DATA))
    assert image.data.shape == (1024, 1024)
    assert image.data.dtype == np.float64
    assert np.isfinite(image.data).all()
    assert 100.0 < image.data.min() < image.data.max() < 1000.0
    assert image.scan_size.x_um == pytest.approx(2.0)
    assert image.scan_size.y_um == pytest.approx(2.0)


def test_list_channels(synthetic_fiber_gwy):
    """Both channels are listed in id order with their titles and z-units."""
    channels = list_gwy_channels(synthetic_fiber_gwy)
    assert [c.channel_id for c in channels] == [0, 1]
    assert [c.title for c in channels] == ["Phase", "Topography"]
    assert channels[0].z_unit == "rad" and not channels[0].is_length_channel
    assert channels[1].z_unit == "m" and channels[1].is_length_channel


def test_auto_select_picks_topography(synthetic_fiber_gwy):
    """Auto-selection skips the lower-id phase channel for length-unit topography."""
    channels = list_gwy_channels(synthetic_fiber_gwy)
    default = select_default_channel(channels)
    assert default.channel_id == 1
    assert default.title == "Topography"


def test_load_auto_channel_converts_to_nm(synthetic_fiber_gwy):
    """The auto-loaded topography channel is finite, 2D, and in nanometers."""
    image = load_gwy_image(synthetic_fiber_gwy)
    assert image.channel.title == "Topography"
    assert image.data.shape == (128, 128)
    assert np.isfinite(image.data).all()
    # Stored as ~3 nm heights (meters internally); a meter->nm bug would make
    # the values ~1e9x larger, so a loose finite-range check catches it.
    # 高さは約 3 nm（内部はメートル）。m->nm 変換漏れなら約 1e9 倍になるため、
    # 緩い範囲チェックで検出できる。
    assert image.data.max() < 100.0


def test_load_scan_size(synthetic_fiber_gwy):
    """xreal/yreal meters are reported as a micrometer ScanSize."""
    image = load_gwy_image(synthetic_fiber_gwy)
    assert image.scan_size == ScanSize(x_um=2.0, y_um=2.0)
    assert read_gwy_scan_size(synthetic_fiber_gwy) == ScanSize(x_um=2.0, y_um=2.0)


def test_select_channel_by_id_and_title(synthetic_fiber_gwy):
    """A channel can be chosen by integer id, title, or digit-only string."""
    by_id = load_gwy_image(synthetic_fiber_gwy, channel=0)
    by_name = load_gwy_image(synthetic_fiber_gwy, channel="Phase")
    by_digit = load_gwy_image(synthetic_fiber_gwy, channel="0")
    assert by_id.channel.title == "Phase"
    assert by_name.channel.channel_id == 0
    assert by_digit.channel.channel_id == 0
    # The phase channel is not a length, so its values pass through unconverted.
    # 位相チャンネルは長さではないため、値は無変換で通る。
    np.testing.assert_allclose(by_id.data, 0.25)


def test_select_channel_case_insensitive(synthetic_fiber_gwy):
    """Title matching ignores case."""
    image = load_gwy_image(synthetic_fiber_gwy, channel="topography")
    assert image.channel.channel_id == 1


@pytest.mark.parametrize("selector", [99, "does-not-exist"])
def test_unknown_channel_raises(synthetic_fiber_gwy, selector):
    """An id or title matching no channel is a loud error."""
    with pytest.raises(ValueError):
        load_gwy_image(synthetic_fiber_gwy, channel=selector)


def test_non_finite_channel_rejected(tmp_path):
    """A channel containing NaN/Inf is rejected at load time."""
    from gwyfile.objects import GwyContainer, GwyDataField, GwySIUnit

    data = np.ones((8, 8))
    data[0, 0] = np.nan
    field = GwyDataField(
        data * 1e-9, xreal=1e-6, yreal=1e-6, si_unit_z=GwySIUnit(unitstr="m"),
    )
    container = GwyContainer()
    container["/0/data"] = field
    container["/0/data/title"] = "Topography"
    path = str(tmp_path / "nan.gwy")
    container.tofile(path)

    with pytest.raises(ValueError):
        load_gwy_image(path)


def test_select_default_channel_empty_raises():
    """Selecting a default from no channels is an error, not a crash."""
    with pytest.raises(ValueError):
        select_default_channel([])


def test_afm_io_dispatch(synthetic_fiber_gwy):
    """load_afm_image and read_scan_size dispatch .gwy to the gwy reader."""
    data = load_afm_image(synthetic_fiber_gwy)
    assert data.shape == (128, 128)
    assert read_scan_size(synthetic_fiber_gwy) == ScanSize(x_um=2.0, y_um=2.0)


def test_pipeline_processes_gwy(synthetic_fiber_gwy, tmp_path):
    """process_file analyzes a .gwy and records gwy provenance + scan size."""
    from lib.blosc2_io import load_bundle, load_bundle_meta
    from lib.bundle_schema import REQUIRED_BUNDLE_KEYS, validate_bundle
    from lib.pipeline import ProcParams, process_file

    result = process_file(synthetic_fiber_gwy, ProcParams(), output_dir=str(tmp_path))

    arrays = load_bundle(result.bundle_path)
    assert not validate_bundle(arrays, require=REQUIRED_BUNDLE_KEYS)

    meta = load_bundle_meta(result.bundle_path)
    input_format = meta["input_format"]
    assert input_format["kind"] == "gwy"
    assert input_format["channel_title"] == "Topography"
    assert input_format["z_unit"] == "m"

    calibration = meta["spatial_calibration"]
    assert calibration["scan_size_x_um"] == 2.0
    assert calibration["scan_size_y_um"] == 2.0
    assert calibration["source"] == "input_header"


def test_pipeline_channel_override(synthetic_fiber_gwy, tmp_path):
    """A gwy_channel override selects a non-default channel for analysis."""
    from lib.blosc2_io import load_bundle_meta
    from lib.pipeline import ProcParams, process_file

    result = process_file(
        synthetic_fiber_gwy, ProcParams(), output_dir=str(tmp_path),
        gwy_channel="Phase",
    )
    meta = load_bundle_meta(result.bundle_path)
    assert meta["input_format"]["channel_title"] == "Phase"


def test_gwy_input_file_size_limit(synthetic_fiber_gwy, monkeypatch):
    """A .gwy larger than the shared input cap is rejected before parsing."""
    import lib.afm_io as afm_io

    monkeypatch.setattr(afm_io, "MAX_INPUT_FILE_BYTES", 16)
    with pytest.raises(ValueError, match="exceeding"):
        load_gwy_image(synthetic_fiber_gwy)
    with pytest.raises(ValueError, match="exceeding"):
        list_gwy_channels(synthetic_fiber_gwy)
    with pytest.raises(ValueError, match="exceeding"):
        read_gwy_scan_size(synthetic_fiber_gwy)

    # Restoring a generous limit loads the same file normally.
    monkeypatch.setattr(afm_io, "MAX_INPUT_FILE_BYTES", 2 * 1024**3)
    assert load_gwy_image(synthetic_fiber_gwy).data.shape == (128, 128)
