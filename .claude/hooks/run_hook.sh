#!/bin/sh
# Run a project hook script with the first usable Python interpreter.
# プロジェクトのフックスクリプトを、最初に見つかった利用可能な Python で実行する。
#
# Why this wrapper exists: .claude/settings.json is version-controlled and
# shared with contributors, so it must not hard-code the Windows-only
# .venv/Scripts/python.exe path that the maintainer's machine happens to use.
# なぜ必要か: .claude/settings.json は共有対象のため、メンテナ環境固有の
# .venv/Scripts/python.exe を直書きできない。
#
# The hooks import only the standard library (json, os, re, sys), so any
# CPython 3 works and the project virtual environment is not required.
# フックは標準ライブラリしか import しないので、任意の CPython 3 で動作し、
# プロジェクトの仮想環境は必須ではない。
#
# Usage: sh run_hook.sh <path-to-hook-script>
#
# Invoked through `sh` rather than a shebang so no executable bit has to survive
# a clone on Windows.
# シェバンではなく `sh` 経由で起動する。Windows の clone で実行ビットが
# 保持されないため。
#
# Exits 0 whenever it cannot run the hook, so a machine without a usable Python
# fails open and stays silent. A non-zero exit would print a hook error notice
# on every single turn, and a guard must never wedge or spam the session.
# フックを実行できない場合は常に終了コード 0 (fail open)。非0で終了すると
# 毎ターン hook error 通知が出るため、意図的に静かに抜ける。

hook="$1"
[ -n "$hook" ] || exit 0
[ -f "$hook" ] || exit 0

# Prefer the project virtual environment: Windows layout first, then the POSIX
# layout used on Linux and macOS.
# プロジェクトの仮想環境を優先する。Windows 配置を先に、次に Linux/macOS 配置。
for py in \
    "$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe" \
    "$CLAUDE_PROJECT_DIR/.venv/bin/python"
do
    [ -x "$py" ] && exec "$py" "$hook"
done

# Fall back to PATH. The extra `-c ""` probe rejects the Windows "App execution
# alias" stub, which is present on PATH but only opens the Microsoft Store.
# PATH 上の Python にフォールバックする。`-c ""` の追加確認は、PATH には存在
# するが Microsoft Store を開くだけの Windows の実行エイリアスを弾くため。
for py in python3 python
do
    command -v "$py" >/dev/null 2>&1 || continue
    "$py" -c "" >/dev/null 2>&1 </dev/null || continue
    exec "$py" "$hook"
done

exit 0
