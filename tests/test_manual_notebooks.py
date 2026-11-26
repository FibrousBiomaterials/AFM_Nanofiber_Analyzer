"""
Run the example notebooks of the manual (docs/manual/notebooks).
マニュアルの例ノートブック（docs/manual/notebooks）を実行する。

The notebooks are stored without outputs, so nothing they show can go stale
in the repository; running them here is what keeps their code working against
the current API. Each notebook's cell tagged ``parameters`` reads the bundled
scans through a path relative to the notebook and writes beside it, so the
test points both at the repository's ``testdata/`` and a temporary folder.
ノートブックは出力なしで保存するので、表示内容がリポジトリ内で古くなることは
ない。ここで実行することで、コードが現在の API で動き続けることを確かめる。
``parameters`` タグのセルは同梱スキャンをノートブックからの相対パスで読み、
出力をノートブックの横に書くので、テストではそれぞれをリポジトリの
``testdata/`` と一時フォルダに向ける。
"""

import os
import re
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = PROJECT_ROOT / "docs" / "manual" / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))

DATA_LINE = re.compile(r'^DATA_DIR = Path\(.*\)$', re.MULTILINE)
OUTPUT_LINE = re.compile(r'^OUTPUT_DIR = Path\(.*\)$', re.MULTILINE)


def _ids(paths):
    return [p.name for p in paths]


def test_notebooks_exist():
    assert NOTEBOOKS, f"no notebook in {NOTEBOOK_DIR}"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=_ids(NOTEBOOKS))
def test_notebook_is_stored_without_outputs(path):
    """
    A saved output would show numbers and figures the code no longer makes.
    保存された出力は、コードがもう作らない数値や図を見せてしまう。
    """
    nb = nbformat.read(path, as_version=4)
    executed = [
        i for i, cell in enumerate(nb.cells)
        if cell.cell_type == "code" and (cell.outputs or cell.execution_count)
    ]
    assert not executed, (
        f"{path.name}: cells {executed} hold outputs; clear them before saving"
    )


def test_language_versions_share_code():
    """
    The English and Japanese notebooks differ only in their explanations.
    英語版と日本語版のノートブックは説明文だけが異なる。
    """
    def code(path):
        nb = nbformat.read(path, as_version=4)
        return [c.source for c in nb.cells if c.cell_type == "code"]

    for path in NOTEBOOKS:
        if path.name.endswith(".ja.ipynb"):
            english = path.with_name(path.name.replace(".ja.ipynb", ".ipynb"))
            assert english.exists(), f"{path.name} has no English version"
            assert code(path) == code(english), (
                f"{path.name} and {english.name} have different code cells"
            )


def run_notebook(path, workdir):
    """
    Execute one notebook on the bundled scans and return it with its outputs.
    1 つのノートブックを同梱スキャンで実行し、出力付きで返す。

    Parameters
    ----------
    path
        Notebook file.
        ノートブックのファイル。
    workdir
        Folder the kernel starts in and the outputs are written to.
        カーネルを起動し、出力を書き出すフォルダ。

    Returns
    -------
    nbformat.NotebookNode
        The executed notebook; the file on disk is not changed.
        実行後のノートブック。ディスク上のファイルは変更しない。
    """
    workdir = Path(workdir).resolve()
    nb = nbformat.read(path, as_version=4)
    params = [c for c in nb.cells if "parameters" in c.metadata.get("tags", [])]
    assert len(params) == 1, f"{path.name}: expected one cell tagged 'parameters'"
    cell = params[0]
    # A function replacement keeps re from reading the backslashes of a
    # Windows path as escapes.
    data_line = f"DATA_DIR = Path({str(PROJECT_ROOT / 'testdata')!r})"
    output_line = f"OUTPUT_DIR = Path({str(workdir / 'afm_output')!r})"
    source, n_data = DATA_LINE.subn(lambda _m: data_line, cell.source)
    source, n_output = OUTPUT_LINE.subn(lambda _m: output_line, source)
    assert (n_data, n_output) == (1, 1), (
        f"{path.name}: the parameters cell no longer sets DATA_DIR and OUTPUT_DIR"
    )
    cell.source = source

    # The kernel imports the package from this checkout, and Matplotlib draws
    # into the notebook (the backend Jupyter uses) rather than into a window
    # that an inherited MPLBACKEND might name.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(PROJECT_ROOT), env.get("PYTHONPATH")) if p
    )
    env["MPLBACKEND"] = "module://matplotlib_inline.backend_inline"
    client = nbclient.NotebookClient(
        nb, timeout=600, kernel_name="python3",
        resources={"metadata": {"path": str(workdir)}},
    )
    client.execute(env=env)
    return nb


@pytest.mark.slow
# pyzmq warns on Windows that the default asyncio loop lacks add_reader and
# falls back to a selector thread; the kernel runs normally.
@pytest.mark.filterwarnings("ignore:Proactor event loop:RuntimeWarning")
@pytest.mark.parametrize("path", NOTEBOOKS, ids=_ids(NOTEBOOKS))
def test_notebook_runs(path, tmp_path):
    run_notebook(path, tmp_path)
