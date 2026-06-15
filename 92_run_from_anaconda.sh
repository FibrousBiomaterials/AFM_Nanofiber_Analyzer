#!/usr/bin/env bash
# Start AFM Nanofiber Analyzer with the Anaconda/Miniconda Python recorded by 91_setup_anaconda.sh.
# 91_setup_anaconda.sh が記録した Anaconda/Miniconda の Python で起動する。
# Re-run 91_setup_anaconda.sh if the Anaconda installation path changes.
# Anaconda のインストールパスが変わった場合は 91_setup_anaconda.sh を再実行する。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PATH_FILE="$SCRIPT_DIR/.afm_anaconda_python"
if [ ! -f "$PATH_FILE" ]; then
    echo "Anaconda Python path file was not found:"
    echo "$PATH_FILE"
    echo "Please run ./91_setup_anaconda.sh first."
    exit 1
fi

# Read the machine-local interpreter path recorded by the setup script.
# セットアップスクリプトが記録したマシン固有のインタープリタパスを読み込む。
IFS= read -r ANACONDA_PYTHON < "$PATH_FILE"

if [ -z "$ANACONDA_PYTHON" ] || [ ! -x "$ANACONDA_PYTHON" ]; then
    echo "Anaconda Python was not found:"
    echo "$ANACONDA_PYTHON"
    echo "Please run ./91_setup_anaconda.sh again."
    exit 1
fi

"$ANACONDA_PYTHON" Main.py
