#!/usr/bin/env bash
# Start AFM Nanofiber Analyzer from the local .venv created by 01_setup_venv.sh.
# 01_setup_venv.sh で作成したローカル .venv から AFM Nanofiber Analyzer を起動する。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo ".venv was not found."
    echo "Please run 01_setup_venv.sh first."
    exit 1
fi

".venv/bin/python" Main.py
