# -*- coding: utf-8 -*-
"""
Convert AFM files this software cannot read into Gwyddion ``.gwy`` files.
本ソフトが読めない AFM ファイルを Gwyddion の ``.gwy`` ファイルへ変換する。

The project reads text/CSV exports (`afm_io`) and ``.gwy`` files (`gwy_io`)
but no vendor binary format. Gwyddion's file modules read most of them, and
the ``gwyconvert`` program from the ``gwyddionpy-converter`` package runs
those modules without the Gwyddion user interface: given one input file, it
writes the ``.gwy`` file Gwyddion would save. Converting through it lets every
format Gwyddion reads reach the analysis through the existing ``.gwy`` path,
instead of the project carrying one reader per vendor format.
本プロジェクトはテキスト/CSV（`afm_io`）と ``.gwy``（`gwy_io`）を読めるが、
各社のバイナリ形式は読めない。Gwyddion のファイルモジュールはその大半を
読み、``gwyddionpy-converter`` パッケージの ``gwyconvert`` はそれらを
Gwyddion の画面なしで実行して、入力 1 ファイルから Gwyddion が保存する
``.gwy`` を書き出す。これを経由すれば、形式ごとの読み込み処理を持たずに、
Gwyddion が読める形式をすべて既存の ``.gwy`` 経路で解析へ渡せる。

Which files are converted is decided by extension alone: everything except the
inputs the project already reads (``.txt``, ``.csv``, ``.gwy``) and the files
it writes (``.b2z``, ``.json``, ``.npy``). The output is written beside the
input as ``<input file name>_converted.gwy`` (`converted_path_for`), and an
input whose output already exists is left alone.
変換するかどうかは拡張子だけで決める。本プロジェクトが既に読める入力
（``.txt``・``.csv``・``.gwy``）と、本プロジェクトが書き出すファイル
（``.b2z``・``.json``・``.npy``）以外がすべて対象になる。出力は入力と同じ
フォルダに ``<入力ファイル名>_converted.gwy`` として書き（`converted_path_for`）、
出力が既にある入力は変換しない。

A converted file is kept only when it holds a channel with a length unit.
Gwyddion also opens ordinary images (a PNG screenshot becomes a unitless
"Value" channel one metre wide), and such a file would otherwise be analyzed
as a height map.
変換結果は、長さの単位を持つチャンネルがあるときだけ残す。Gwyddion は通常の
画像も開ける（PNG のスクリーンショットは幅 1 m の単位なし "Value" チャンネル
になる）ため、検査しなければ高さ像として解析されてしまう。

``gwyconvert`` links the GPL-licensed Gwyddion libraries, so this module only
runs it as a separate process and imports ``gwyddionpy_converter`` solely to
locate it. The package is the optional ``convert`` dependency (installed by
the ``run_venv`` / ``run_conda`` launchers, or by `INSTALL_COMMAND`) and is
deliberately left out of the PyInstaller build (`build.py`).
``gwyconvert`` は GPL の Gwyddion ライブラリをリンクしているため、本モジュールは
それを別プロセスとして実行するだけで、``gwyddionpy_converter`` は場所を調べる
ためにのみ import する。このパッケージは任意依存の ``convert``（``run_venv`` /
``run_conda`` の起動スクリプト、または `INSTALL_COMMAND` で入る）で、
PyInstaller ビルド（`build.py`）には意図的に含めない。
"""

# ===== Standard library =====
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Optional

# ===== Project libraries =====
from . import gwy_io
from .gwy_io import GWY_EXT

# Extensions never sent to the converter: the inputs the project reads
# directly, then the files the project writes beside them (the order the GUI
# lists them in).
# 変換にかけない拡張子。本プロジェクトが直接読める入力、続いてその横に
# 本プロジェクトが書き出すファイル（GUI に表示する順）。
SKIPPED_EXTENSIONS = (".txt", ".csv", GWY_EXT, ".b2z", ".json", ".npy")

# Outcome keys of `convert_file`; fixed identifiers, not display text.
# `convert_file` の結果を表す固定の識別子（表示文字列ではない）。
STATUS_CONVERTED = "converted"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"

# Appended to the input file name, before ``.gwy``, to name the output.
# 出力名を作るとき、入力ファイル名の後ろ（``.gwy`` の前）に付ける文字列。
CONVERTED_SUFFIX = "_converted"

# Seconds one conversion may run before it is stopped. Generous on purpose:
# it turns a hung converter into a reported failure and is not a speed limit,
# and the first converter run after installation can be much slower than later
# ones.
# 1 ファイルの変換を打ち切るまでの秒数。意図的に長くしている。止まった変換を
# 失敗として報告するためのもので、速度の上限ではない。インストール直後の初回の
# 実行は、それ以降よりずっと遅いことがある。
DEFAULT_TIMEOUT_S = 300.0

# Environment variable naming a gwyconvert executable; the same name
# gwyddionPy reads, so one setting serves both.
# gwyconvert の実行ファイルを指定する環境変数。gwyddionPy と同じ名前なので
# 1 つの設定で両方に効く。
CONVERTER_ENV_VAR = "GWYDDIONPY_CONVERT"

# Command that installs the converter into the running environment, whichever
# way the project itself was installed.
# プロジェクト自体のインストール方法によらず、実行中の環境へ変換プログラムを
# 入れるコマンド。
INSTALL_COMMAND = 'python -m pip install "gwyddionpy-converter>=0.1.0,<0.2"'

INSTALL_HINT = (
    f"install the converter with: {INSTALL_COMMAND} "
    f"(or set {CONVERTER_ENV_VAR} to a gwyconvert executable)"
)


class ConverterNotFoundError(RuntimeError):
    """
    Raised when no gwyconvert executable can be located.
    gwyconvert の実行ファイルが見つからないときに送出する。
    """


@dataclass(frozen=True)
class ConversionResult:
    """
    Outcome of converting one input file.
    1 入力ファイルの変換結果。

    Attributes
    ----------
    source
        Input file path.
        入力ファイルのパス。
    output
        Path of the ``.gwy`` file the input converts to, whether or not it was
        written by this call.
        入力の変換先 ``.gwy`` のパス（この呼び出しで書いたかどうかによらない）。
    status
        One of `STATUS_CONVERTED`, `STATUS_EXISTS`, `STATUS_FAILED`.
        `STATUS_CONVERTED`・`STATUS_EXISTS`・`STATUS_FAILED` のいずれか。
    module
        Name of the Gwyddion file module that read the input, when known.
        入力を読んだ Gwyddion ファイルモジュール名（分かる場合）。
    message
        Reason for a failure; empty otherwise.
        失敗の理由。それ以外は空。
    """

    source: str
    output: str
    status: str
    module: Optional[str] = None
    message: str = ""


def converted_path_for(path: str) -> str:
    """
    Return the ``.gwy`` path an input file converts to.
    入力ファイルの変換先 ``.gwy`` パスを返す。

    Parameters
    ----------
    path
        Input file path.
        入力ファイルのパス。

    Returns
    -------
    str
        ``path`` with `CONVERTED_SUFFIX` and ``.gwy`` appended, so
        ``scan.ssp`` converts to ``scan.ssp_converted.gwy``.
        ``path`` の末尾に `CONVERTED_SUFFIX` と ``.gwy`` を付けたパス。
        ``scan.ssp`` は ``scan.ssp_converted.gwy`` になる。

    Notes
    -----
    GUI01 names a bundle after its input with only the last extension removed
    (`pipeline.process_file`), so the output name must differ from every other
    input the folder may hold once that extension is gone. Keeping the input's
    extension keeps ``scan.000`` and ``scan.001`` apart. The suffix keeps the
    output apart from a text export of the same measurement, because
    instruments name those after the raw file too (``scan.ssp.txt``,
    ``NDTOC250306.000.txt``): ``scan.ssp.gwy`` would be analyzed into the same
    ``scan.ssp.b2z`` as ``scan.ssp.txt``.
    GUI01 はバンドル名を、入力のファイル名から最後の拡張子だけを外して作る
    （`pipeline.process_file`）。そのため出力名は、その拡張子を外した後でも、
    フォルダにある他のどの入力とも異なる必要がある。入力の拡張子を残すことで
    ``scan.000`` と ``scan.001`` は区別できる。接尾辞は、同じ測定のテキスト
    出力と区別するためにある。装置はテキスト出力にも元ファイルの名前を付ける
    （``scan.ssp.txt``、``NDTOC250306.000.txt``）ため、``scan.ssp.gwy`` では
    ``scan.ssp.txt`` と同じ ``scan.ssp.b2z`` に解析されてしまう。
    """
    return path + CONVERTED_SUFFIX + GWY_EXT


def is_conversion_candidate(path: str) -> bool:
    """
    Return whether a file is sent to the converter, judged by its name.
    ファイル名から、そのファイルを変換にかけるかどうかを返す。

    Parameters
    ----------
    path
        File path or file name.
        ファイルパスまたはファイル名。

    Returns
    -------
    bool
        False for an extension in `SKIPPED_EXTENSIONS` and for hidden files
        (names starting with ``.``, which hold operating-system metadata);
        True otherwise, including for files without an extension.
        `SKIPPED_EXTENSIONS` の拡張子と隠しファイル（``.`` で始まる名前。
        OS のメタデータ）なら False。拡張子のないファイルを含め、それ以外は True。
    """
    name = os.path.basename(path)
    if name.startswith("."):
        return False
    return os.path.splitext(name)[1].lower() not in SKIPPED_EXTENSIONS


def list_conversion_candidates(folder: str) -> List[str]:
    """
    List the files directly inside a folder that are sent to the converter.
    フォルダ直下のファイルのうち、変換にかけるものを列挙する。

    Subfolders are not searched, matching GUI01's batch-folder input.
    GUI01 のフォルダ入力と同じく、サブフォルダは探さない。

    Parameters
    ----------
    folder
        Folder to scan.
        走査するフォルダ。

    Returns
    -------
    list of str
        Full paths sorted by file name, including inputs whose ``.gwy``
        already exists (`convert_file` reports those as `STATUS_EXISTS`).
        ファイル名順の完全パス。``.gwy`` が既にある入力も含む（`convert_file`
        がそれを `STATUS_EXISTS` として報告する）。
    """
    paths = []
    for name in sorted(os.listdir(folder), key=str.lower):
        full = os.path.join(folder, name)
        if os.path.isfile(full) and is_conversion_candidate(name):
            paths.append(full)
    return paths


def find_converter(explicit: Optional[str] = None) -> str:
    """
    Locate the gwyconvert executable.
    gwyconvert の実行ファイルを探す。

    Parameters
    ----------
    explicit
        Executable path given by the caller; tried first.
        呼び出し側が指定した実行ファイルのパス。最初に試す。

    Returns
    -------
    str
        Path of the executable: ``explicit``, then the `CONVERTER_ENV_VAR`
        environment variable, then the ``gwyddionpy-converter`` package, then
        ``gwyconvert`` on ``PATH``.
        実行ファイルのパス。``explicit``、環境変数 `CONVERTER_ENV_VAR`、
        ``gwyddionpy-converter`` パッケージ、``PATH`` 上の ``gwyconvert`` の順。

    Raises
    ------
    ConverterNotFoundError
        When ``explicit`` or the environment variable names a missing file,
        or when no executable is found at all.
    """
    # A path the user named is reported when wrong rather than silently
    # replaced by another converter.
    for given, origin in ((explicit, "the given path"),
                          (os.environ.get(CONVERTER_ENV_VAR), CONVERTER_ENV_VAR)):
        if given:
            if os.path.isfile(given):
                return given
            raise ConverterNotFoundError(
                f"gwyconvert not found at {given!r} (from {origin})"
            )
    try:
        # Imported here: the package is an optional dependency, and it is only
        # asked where its executable lives, never loaded into this process.
        from gwyddionpy_converter import binary_path
        return str(binary_path())
    except (ImportError, FileNotFoundError):
        pass
    found = shutil.which("gwyconvert")
    if found:
        return found
    raise ConverterNotFoundError(f"gwyconvert not found; {INSTALL_HINT}")


def _converter_environment() -> dict:
    """
    Return the environment the converter process runs in.
    変換プロセスを実行する環境変数を返す。

    Pins the decimal mark so numbers Gwyddion parses from text metadata do not
    follow the machine's locale, and disables GTK modules the headless
    converter never uses.
    Gwyddion がテキストのメタデータから読む数値が PC のロケールに左右されない
    よう小数点を固定し、画面を持たない変換で使わない GTK モジュールを無効にする。
    """
    env = dict(os.environ)
    env["LC_NUMERIC"] = "C"
    env["GTK_MODULES"] = ""
    return env


def _has_length_channel(gwy_path: str) -> bool:
    """
    Return whether a ``.gwy`` file holds a channel with a length unit.
    ``.gwy`` ファイルが長さ単位のチャンネルを持つかどうかを返す。
    """
    return any(
        gwy_io._is_length_unit(channel.z_unit)
        for channel in gwy_io.list_gwy_channels(gwy_path)
    )


def convert_file(path: str, *, converter: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT_S) -> ConversionResult:
    """
    Convert one input file into ``<input file name>_converted.gwy`` beside it.
    1 つの入力ファイルを、同じフォルダの ``<入力ファイル名>_converted.gwy`` へ変換する。

    The converter writes into a temporary folder inside the output folder, and
    the result is moved into place only once it has passed the length-channel
    check. A failed or interrupted conversion therefore never leaves a
    ``.gwy`` under the final name, which would otherwise be skipped as
    already converted on every later run.
    変換プログラムは出力先フォルダ内の一時フォルダに書き、長さチャンネルの
    検査を通った結果だけを最終的な名前へ移す。失敗や中断した変換が最終的な
    名前の ``.gwy`` を残すことはない。残すと、以降の実行で毎回「変換済み」と
    して飛ばされてしまう。

    Parameters
    ----------
    path
        Input file path.
        入力ファイルのパス。
    converter
        gwyconvert executable; located with `find_converter` when omitted.
        gwyconvert の実行ファイル。省略時は `find_converter` で探す。
    timeout
        Seconds the conversion may run before it is stopped.
        変換を打ち切るまでの秒数。

    Returns
    -------
    ConversionResult
        `STATUS_EXISTS` without running the converter when the output exists;
        otherwise `STATUS_CONVERTED` or `STATUS_FAILED` with the reason.
        出力が既にあれば変換せずに `STATUS_EXISTS`。それ以外は
        `STATUS_CONVERTED`、または理由を添えた `STATUS_FAILED`。

    Raises
    ------
    ConverterNotFoundError
        When ``converter`` is omitted and no executable can be located.
    """
    output = converted_path_for(path)
    if os.path.exists(output):
        return ConversionResult(path, output, STATUS_EXISTS)
    binary = converter or find_converter()

    def failed(message: str, module: Optional[str] = None) -> ConversionResult:
        return ConversionResult(path, output, STATUS_FAILED, module, message)

    # A console program started from a windowed process opens a console
    # window for every file unless asked not to.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        with tempfile.TemporaryDirectory(
            prefix=".gwyconvert-", dir=os.path.dirname(os.path.abspath(output))
        ) as tmpdir:
            tmp_output = os.path.join(tmpdir, "converted" + GWY_EXT)
            try:
                proc = subprocess.run(
                    [binary, os.path.abspath(path), tmp_output],
                    capture_output=True, timeout=timeout,
                    env=_converter_environment(), creationflags=creationflags,
                )
            except subprocess.TimeoutExpired:
                return failed(f"conversion did not finish within {timeout:g} s")
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0 or not os.path.isfile(tmp_output):
                # gwyconvert prefixes its own name and repeats the input path;
                # keep only the reason after the last ": ".
                reason = stderr.splitlines()[-1] if stderr else f"exit code {proc.returncode}"
                return failed(reason.rsplit(": ", 1)[-1])
            try:
                module = json.loads(proc.stdout.decode("utf-8", errors="replace")).get("module")
            except (ValueError, AttributeError):
                module = None
            try:
                has_length = _has_length_channel(tmp_output)
            except Exception as exc:  # noqa: BLE001 - reported per file, never aborts a batch
                return failed(f"converted file could not be read back: {exc}", module)
            if not has_length:
                return failed(
                    "no channel with a length unit (not a height measurement)", module
                )
            if os.path.exists(output):
                return ConversionResult(path, output, STATUS_EXISTS, module)
            os.replace(tmp_output, output)
    except OSError as exc:
        return failed(f"{type(exc).__name__}: {exc}")
    return ConversionResult(path, output, STATUS_CONVERTED, module)
