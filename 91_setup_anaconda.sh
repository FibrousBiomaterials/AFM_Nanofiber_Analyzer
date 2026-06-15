#!/usr/bin/env bash
# Set up this project against an existing Anaconda or Miniconda installation.
# 既存の Anaconda または Miniconda 環境を使って、このプロジェクトをセットアップする。
# Run from an activated conda environment if automatic conda detection fails.
# conda の自動検出に失敗する場合は、有効化済みの conda 環境から実行する。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "[1/4] Searching for Anaconda or Miniconda Python..."
ANACONDA_PYTHON=""
CONDA_ROOT=""

# Prefer the already-active conda environment so users can choose their own install.
# ユーザーが選んだ環境を使えるよう、まず現在有効な conda 環境を優先する。
if [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    ANACONDA_PYTHON="$CONDA_PREFIX/bin/python"
    CONDA_ROOT="$CONDA_PREFIX"
fi

if [ -z "$ANACONDA_PYTHON" ]; then
    # Check the common Unix/macOS install locations used by Anaconda and Miniconda.
    # Anaconda と Miniconda でよく使われる Unix/macOS のインストール先を確認する。
    for candidate in \
        "$HOME/anaconda3/bin/python" \
        "$HOME/miniconda3/bin/python" \
        "$HOME/opt/anaconda3/bin/python" \
        "$HOME/opt/miniconda3/bin/python" \
        "/opt/anaconda3/bin/python" \
        "/opt/miniconda3/bin/python"; do
        if [ -x "$candidate" ]; then
            ANACONDA_PYTHON="$candidate"
            CONDA_ROOT="$(cd "$(dirname "$candidate")/.." && pwd)"
            break
        fi
    done
fi

if [ -z "$ANACONDA_PYTHON" ] && command -v conda >/dev/null 2>&1; then
    # Fall back to conda on PATH when the installation is not in a standard location.
    # 標準的な場所にない場合は、PATH 上の conda から Python を探す。
    candidate="$(conda run python -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        ANACONDA_PYTHON="$candidate"
        CONDA_ROOT="$(cd "$(dirname "$candidate")/.." && pwd)"
    fi
fi

if [ -z "$ANACONDA_PYTHON" ] || [ ! -x "$ANACONDA_PYTHON" ]; then
    echo "Anaconda or Miniconda Python was not found."
    echo "Please install Anaconda/Miniconda, or run this file from an activated conda environment."
    exit 1
fi

echo "Found:"
echo "$ANACONDA_PYTHON"

if [ -n "$CONDA_ROOT" ] && [ -f "$CONDA_ROOT/etc/profile.d/conda.sh" ]; then
    echo
    echo "Activating Anaconda environment..."
    # Activation helps conda-managed shared-library paths resolve during package installs.
    # 有効化しておくと、パッケージ導入時に conda 管理の共有ライブラリパスを解決しやすい。
    # shellcheck source=/dev/null
    . "$CONDA_ROOT/etc/profile.d/conda.sh"
    conda activate "$CONDA_ROOT"
fi

echo
echo "[2/4] Upgrading pip..."
"$ANACONDA_PYTHON" -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "Failed to upgrade pip."
    exit 1
fi

echo
echo "[3/4] Installing the package and dependencies..."
# Editable install resolves dependencies from pyproject.toml (the single source
# of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
# 編集可能インストールは依存関係を単一の真実の源である pyproject.toml から解決し、
# afm-analyzer / afm-analyzer-cli コマンドを登録する。
"$ANACONDA_PYTHON" -m pip install -e .
if [ $? -ne 0 ]; then
    echo "Failed to install the package."
    exit 1
fi

echo
echo "[4/4] Recording the Anaconda Python path for 92_run_from_anaconda.sh..."
# The static launcher reads this machine-local path; the file stays gitignored.
# 静的ランチャーはこのマシン固有パスを読み込む。ファイルは gitignore 対象のまま。
printf '%s\n' "$ANACONDA_PYTHON" > .afm_anaconda_python
if [ $? -ne 0 ]; then
    echo "Failed to record the Anaconda Python path."
    exit 1
fi

echo
echo "Setup completed."
echo "You can now start the application with ./92_run_from_anaconda.sh."
