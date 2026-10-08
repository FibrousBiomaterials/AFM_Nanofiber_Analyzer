#!/usr/bin/env python3
"""
Move files and folders inside the repository to the recycle bin instead of deleting them.
リポジトリ内のファイルとフォルダを、削除せずにごみ箱へ移す。

Agents working in this repository delete through this script, so a deletion
can always be undone: on Windows the items go to the recycle bin (the Shell's
``SHFileOperationW`` with undo allowed), and elsewhere they are moved under
``.tmp/trash/<timestamp>/``. Commands that delete irreversibly (``rm``,
``rmdir``, ``Remove-Item``, ``find -delete``) are denied in
``.claude/settings.json``. Paths outside the repository are refused.
このリポジトリで作業するエージェントは、このスクリプトを通して削除する。そのため
削除はいつでも取り消せる。Windows では項目をごみ箱へ送り（undo を許可した Shell の
``SHFileOperationW``）、それ以外の環境では ``.tmp/trash/<日時>/`` の下へ移す。
不可逆に削除するコマンド（``rm``、``rmdir``、``Remove-Item``、``find -delete``）は
``.claude/settings.json`` で拒否している。リポジトリの外のパスは拒否する。

Usage
-----
``.venv\\Scripts\\python.exe scripts/trash.py PATH [PATH ...]``

Windows deletes an item permanently when it does not fit the recycle bin
(too large, or on a drive without one); this script asks Windows to warn
before that happens rather than let it pass silently.
Windows は、ごみ箱に入らない項目（大きすぎる、またはごみ箱の無いドライブ上）を
完全に削除する。このスクリプトは、それを黙って通さず、その前に警告を出すよう
Windows に求める。
"""

from __future__ import annotations

# ===== Standard library =====
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
FALLBACK_TRASH = ROOT / ".tmp" / "trash"

# SHFileOperationW operation and flags (shellapi.h).
# SHFileOperationW の操作とフラグ（shellapi.h）。
_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
_FOF_WANTNUKEWARNING = 0x4000


def _inside_repository(path: Path) -> Path:
    """
    Resolve a path and refuse it unless it lies inside the repository.
    パスを解決し、リポジトリの内側でなければ拒否する。

    Raises
    ------
    ValueError
        If the path is the repository itself or lies outside it.
    FileNotFoundError
        If the path does not exist.
    """
    resolved = Path(path).resolve()
    if resolved == ROOT or ROOT not in resolved.parents:
        raise ValueError(f"refusing to trash a path outside the repository: {path}")
    if not resolved.exists():
        raise FileNotFoundError(path)
    return resolved


def _recycle_windows(paths: List[Path]) -> None:
    """
    Send paths to the Windows recycle bin through the Shell.
    Shell を通してパスを Windows のごみ箱へ送る。
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # pFrom is a list of paths, each ending in NUL, closed by an extra NUL.
    # pFrom は NUL で終わるパスの並びで、最後にもう 1 つ NUL を置く。
    source = "".join(str(p) + "\0" for p in paths) + "\0"
    op = SHFILEOPSTRUCTW(
        hwnd=None, wFunc=_FO_DELETE, pFrom=source, pTo=None,
        fFlags=(_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
                | _FOF_NOERRORUI | _FOF_WANTNUKEWARNING),
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperationW failed with code {result:#x} "
                      f"(aborted: {bool(op.fAnyOperationsAborted)})")


def _move_to_fallback(paths: List[Path]) -> Path:
    """
    Move paths under a timestamped folder of ``.tmp/trash`` (non-Windows).
    パスを ``.tmp/trash`` の日時付きフォルダの下へ移す（Windows 以外）。
    """
    folder = FALLBACK_TRASH / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for p in paths:
        target = folder / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target))
    return folder


def send_to_trash(paths: Iterable) -> None:
    """
    Move files or folders inside the repository to the recycle bin.
    リポジトリ内のファイルやフォルダをごみ箱へ移す。

    Parameters
    ----------
    paths
        Files or folders to remove; each must exist inside the repository.
        取り除くファイルやフォルダ。いずれもリポジトリ内に存在しなければならない。

    Raises
    ------
    ValueError
        If a path lies outside the repository; nothing is moved then.
    OSError
        If Windows reports that the operation failed or was aborted.
    """
    resolved = [_inside_repository(Path(p)) for p in paths]
    if not resolved:
        return
    if sys.platform == "win32":
        _recycle_windows(resolved)
    else:
        _move_to_fallback(resolved)


def main(argv=None) -> int:
    """
    Trash the paths given on the command line.
    コマンドラインで与えたパスをごみ箱へ移す。
    """
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print(__doc__)
        return 2
    send_to_trash(paths)
    for p in paths:
        print(f"trashed {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
