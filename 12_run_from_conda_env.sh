#!/usr/bin/env bash
# Start AFM Nanofiber Analyzer inside the dedicated conda environment.
# 専用の conda 環境内で AFM Nanofiber Analyzer を起動する。
# The default environment directory is .conda-env in the project folder.
# 既定の環境ディレクトリはプロジェクトフォルダ内の .conda-env。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

ENV_DIR="${AFM_ANALYZER_CONDA_ENV_DIR:-$SCRIPT_DIR/.conda-env}"
CONDA_CMD="${CONDA_EXE:-}"

# Prefer CONDA_EXE when running from an initialized conda shell.
# conda 初期化済みのシェルでは CONDA_EXE を優先する。
if [ -z "$CONDA_CMD" ] || [ ! -x "$CONDA_CMD" ]; then
    if command -v conda >/dev/null 2>&1; then
        CONDA_CMD="$(command -v conda)"
    fi
fi

if [ -z "$CONDA_CMD" ]; then
    # Then check common Unix/macOS install locations.
    # 次に Unix/macOS でよく使われるインストール先を確認する。
    for candidate in \
        "$HOME/anaconda3/bin/conda" \
        "$HOME/miniconda3/bin/conda" \
        "$HOME/opt/anaconda3/bin/conda" \
        "$HOME/opt/miniconda3/bin/conda" \
        "/opt/anaconda3/bin/conda" \
        "/opt/miniconda3/bin/conda"; do
        if [ -x "$candidate" ]; then
            CONDA_CMD="$candidate"
            break
        fi
    done
fi

if [ -z "$CONDA_CMD" ] || [ ! -x "$CONDA_CMD" ]; then
    echo "conda was not found."
    echo "Please install Anaconda/Miniconda, or run this file from a terminal where conda is available."
    exit 1
fi

"$CONDA_CMD" run -p "$ENV_DIR" python Main.py
if [ $? -ne 0 ]; then
    echo
    echo "Failed to start the application."
    echo "Please run ./11_setup_conda_env.sh first."
    exit 1
fi
