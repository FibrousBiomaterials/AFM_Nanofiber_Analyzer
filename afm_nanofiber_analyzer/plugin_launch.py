"""
Launch a GUI plugin in its own process, optionally handing it a path.
GUI プラグインを別プロセスで起動し、必要ならパスを渡す。

Both the launcher (`Main.py`) and GUI01, which opens GUI02, GUI03 and GUI04 on
what it has just analyzed, start plugins through `launch_plugin`, so the two
build the same command. The command always goes through `Main.py`'s
``--run-plugin`` subcommand: a frozen PyInstaller build cannot run a module
with ``-c`` or ``-m``, and the subcommand is where the splash window and the
plugin's ``main()`` call live.
ランチャー（`Main.py`）と、解析した結果を GUI02・GUI03・GUI04 で開く GUI01 は、
どちらも `launch_plugin` でプラグインを起動するため、両者は同じコマンドを組み
立てる。コマンドは常に `Main.py` の ``--run-plugin`` サブコマンドを経由する。
凍結した PyInstaller ビルドは ``-c`` や ``-m`` でモジュールを実行できず、
スプラッシュウィンドウとプラグインの ``main()`` 呼び出しもこのサブコマンドに
あるためである。

Arguments after the module name reach the plugin as ``sys.argv[1:]``, the same
place they arrive when the plugin file is run directly as a script, so a
plugin reads them the same way in both cases.
モジュール名の後ろの引数は ``sys.argv[1:]`` としてプラグインに届く。これは
プラグインファイルをスクリプトとして直接実行したときと同じ場所であり、
プラグインはどちらの場合も同じ方法で引数を読める。

Any number of paths is handed over through a list file
(`path_list_arguments`, read back by `read_path_arguments`), because a command
line holds a limited number of characters. GUI01 and GUI05 hand GUI03 its
bundles this way.
任意の数のパスは一覧ファイルで渡す（`path_list_arguments`。読む側は
`read_path_arguments`）。コマンドラインに入る文字数には上限があるためである。
GUI01 と GUI05 は、この方法で GUI03 にバンドルを渡す。
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Sequence

#: Subcommand of `Main.py` that imports a plugin module and calls its main().
#: プラグインモジュールを import して main() を呼ぶ `Main.py` のサブコマンド。
RUN_PLUGIN_FLAG = "--run-plugin"

#: Plugin argument naming a file that lists the paths handed over, one per line.
#: 渡すパスを 1 行に 1 つ書いたファイルを指すプラグイン引数。
PATH_LIST_FLAG = "--path-list"


def app_base_dir() -> Path:
    """
    Return the folder that holds `Main.py` (source) or `Main.exe` (frozen).
    `Main.py`（ソース実行）または `Main.exe`（凍結ビルド）のあるフォルダを返す。

    Returns
    -------
    Path
        Repository root for a source run; the folder of the executable for a
        frozen build, where `build.py` copies `afm_nanofiber_analyzer/` and `guis/`.
        ソース実行ではリポジトリのルート。凍結ビルドでは実行ファイルのフォルダ
        で、`build.py` が `afm_nanofiber_analyzer/` と `guis/` をそこへコピーする。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def plugin_command(module_import_path: str, args: Sequence[str] = ()) -> List[str]:
    """
    Build the command line that runs one plugin through `Main.py`.
    1 つのプラグインを `Main.py` 経由で実行するコマンドラインを組み立てる。

    Parameters
    ----------
    module_import_path
        Import path of the plugin module, such as ``guis.GUI04_Tracking_fiber``.
        プラグインモジュールの import パス（例: ``guis.GUI04_Tracking_fiber``）。
    args
        Arguments handed to the plugin, which it reads as ``sys.argv[1:]``.
        プラグインに渡す引数。プラグインは ``sys.argv[1:]`` として読む。

    Returns
    -------
    list of str
        ``[Main.exe, --run-plugin, module, *args]`` in a frozen build and
        ``[python, Main.py, --run-plugin, module, *args]`` in a source run.
        凍結ビルドでは ``[Main.exe, --run-plugin, module, *args]``、ソース実行
        では ``[python, Main.py, --run-plugin, module, *args]``。
    """
    if getattr(sys, "frozen", False):
        head = [sys.executable]
    else:
        head = [sys.executable, str(app_base_dir() / "Main.py")]
    return head + [RUN_PLUGIN_FLAG, module_import_path] + [str(a) for a in args]


def path_list_arguments(paths: Sequence[str]) -> List[str]:
    """
    Write paths to a list file and return the plugin arguments that name it.
    パスを一覧ファイルに書き、そのファイルを指すプラグイン引数を返す。

    Parameters
    ----------
    paths
        Paths to hand to the plugin, in the order it should receive them.
        プラグインに渡すパス。プラグインが受け取る順に並べる。

    Returns
    -------
    list of str
        ``[PATH_LIST_FLAG, list_file]``, to pass as the ``args`` of
        `launch_plugin`.
        ``[PATH_LIST_FLAG, 一覧ファイル]``。`launch_plugin` の ``args`` に渡す。

    Notes
    -----
    Windows does not start a process whose command line reaches 32,767
    characters, which a few hundred bundle paths can do. The file is UTF-8,
    one path per line, in the system's temporary folder, and
    `read_path_arguments` removes it after reading; it is left behind only
    when the plugin never starts.
    Windows は、コマンドラインが 32,767 文字に達するプロセスを起動しない。数百個の
    バンドルのパスはこれに達しうる。ファイルは UTF-8 で 1 行に 1 パス、システムの
    一時フォルダに置き、`read_path_arguments` が読んだ後に消す。残るのは
    プラグインが起動しなかった場合だけである。
    """
    fd, list_path = tempfile.mkstemp(prefix="afm_paths_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        for path in paths:
            f.write(str(path) + "\n")
    return [PATH_LIST_FLAG, list_path]


def read_path_arguments(args: Sequence[str]) -> List[str]:
    """
    Return the paths a plugin was handed, reading any list file among them.
    プラグインに渡されたパスを返す。引数に一覧ファイルがあればそれを読む。

    Parameters
    ----------
    args
        The plugin's arguments (``sys.argv[1:]``).
        プラグインの引数（``sys.argv[1:]``）。

    Returns
    -------
    list of str
        The paths in the order given: each argument as it is, and the lines of
        a list file in place of ``PATH_LIST_FLAG`` and the file that follows
        it. A list file that cannot be read contributes nothing.
        与えられた順のパス。各引数はそのまま、``PATH_LIST_FLAG`` とそれに続く
        ファイルは、その一覧ファイルの各行に置き換える。読めない一覧ファイルは
        何も加えない。

    Notes
    -----
    A plugin started by hand with paths as plain arguments reads them through
    the same call. The list file is removed once read, because only the
    process it was written for reads it.
    パスをそのまま引数に書いて手で起動したプラグインも、同じ呼び出しで読める。
    一覧ファイルは読んだら消す。読むのは、それを渡されたプロセスだけだからである。
    """
    paths: List[str] = []
    args = [str(a) for a in args]
    i = 0
    while i < len(args):
        if args[i] == PATH_LIST_FLAG and i + 1 < len(args):
            list_path = args[i + 1]
            try:
                with open(list_path, encoding="utf-8") as f:
                    paths.extend(line.rstrip("\r\n") for line in f
                                 if line.strip())
            except OSError:
                pass
            try:
                os.remove(list_path)
            except OSError:
                pass
            i += 2
            continue
        paths.append(args[i])
        i += 1
    return paths


def call_when_shown(window, callback: Callable[..., object], *args) -> None:
    """
    Call `callback` once `window` is mapped on screen.
    `window` が画面に表示されたら `callback` を呼ぶ。

    Parameters
    ----------
    window
        Tk main window of the plugin.
        プラグインの Tk メインウインドウ。
    callback
        Function that opens what the plugin was handed, such as GUI04's
        ``App.open_bundle``.
        渡されたものを開く関数（例: GUI04 の ``App.open_bundle``）。
    *args
        Arguments for `callback`.
        `callback` の引数。

    Notes
    -----
    Opening a file can raise a modal dialog — a missing scan size, a warning
    about the file. A dialog raised before the main window is mapped grabs the
    input while the window stays hidden, so the user sees a lone prompt with
    no window behind it. The main loop's first idle moment comes before the
    window manager maps the window, which is why this polls rather than using
    ``after_idle`` alone.
    ファイルを開く処理はモーダルダイアログ（走査範囲の未記録やファイルについての
    警告）を出すことがある。メインウインドウが表示される前にダイアログを出すと、
    ダイアログが入力を握ったままウインドウは隠れたままになり、ユーザーには背後に
    ウインドウの無いダイアログだけが見える。メインループ最初のアイドル時点は
    ウインドウマネージャがウインドウを表示する前に来るため、``after_idle`` だけ
    ではなく表示されるまで確かめ続ける。
    """
    def attempt() -> None:
        try:
            mapped = window.winfo_ismapped()
        except Exception:
            # The window was closed before it was shown; nothing to open.
            # 表示前にウインドウが閉じられたので、開くものは無い。
            return
        if mapped:
            callback(*args)
        else:
            window.after(50, attempt)

    window.after_idle(attempt)


def launch_plugin(module_import_path: str, args: Sequence[str] = ()) -> None:
    """
    Start one plugin in a detached child process.
    1 つのプラグインを切り離した子プロセスで起動する。

    Parameters
    ----------
    module_import_path
        Import path of the plugin module.
        プラグインモジュールの import パス。
    args
        Arguments handed to the plugin, which it reads as ``sys.argv[1:]``.
        プラグインに渡す引数。プラグインは ``sys.argv[1:]`` として読む。

    Raises
    ------
    OSError
        When the child process cannot be started.

    Notes
    -----
    Each plugin owns a Tk main loop, and tkinter and Matplotlib expect to own
    the main thread, so a plugin cannot run inside the process that starts it.
    On Windows the child is detached, so closing the window that started it
    does not close the plugin, and no console window appears in a windowed
    build.
    各プラグインは Tk のメインループを持ち、tkinter と Matplotlib はメイン
    スレッドを占有する前提で動くため、起動元と同じプロセス内では実行できない。
    Windows では子プロセスを切り離すため、起動元のウインドウを閉じてもプラグイン
    は閉じず、windowed ビルドでコンソールウインドウも出ない。
    """
    popen_kwargs: dict = {"cwd": str(app_base_dir())}
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
    subprocess.Popen(plugin_command(module_import_path, args), **popen_kwargs)
