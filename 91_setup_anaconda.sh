#!/usr/bin/env bash
# Set up this project against an existing Anaconda or Miniconda installation.
# 既存の Anaconda または Miniconda 環境を使って、このプロジェクトをセットアップする。
# Run from an activated conda environment if automatic conda detection fails.
# conda の自動検出に失敗する場合は、有効化済みの conda 環境から実行する。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "[1/5] Searching for Anaconda or Miniconda Python..."
ANACONDA_PYTHON=""
CONDA_ROOT=""
CONDA_CMD=""

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

if [ -n "$CONDA_ROOT" ] && [ -x "$CONDA_ROOT/bin/conda" ]; then
    CONDA_CMD="$CONDA_ROOT/bin/conda"
elif command -v conda >/dev/null 2>&1; then
    CONDA_CMD="$(command -v conda)"
fi

echo
echo "[2/5] Upgrading pip..."
"$ANACONDA_PYTHON" -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "Failed to upgrade pip."
    exit 1
fi

echo
echo "[3/5] Generating requirements..."
# check.py regenerates requirements.txt from the project imports before install.
# check.py はインストール前にプロジェクトの import から requirements.txt を再生成する。
"$ANACONDA_PYTHON" check.py
if [ $? -ne 0 ]; then
    echo "Failed to generate requirements.txt."
    exit 1
fi

echo
echo "[4/5] Installing requirements..."
if [ -n "$CONDA_CMD" ]; then
    echo "Installing mahotas with conda-forge first to avoid pip build failures..."
    # mahotas can require native builds; conda-forge usually provides a wheel-equivalent package.
    # mahotas はネイティブビルドが必要になることがあり、conda-forge なら通常はビルド済み相当のパッケージを使える。
    "$CONDA_CMD" install -y -c conda-forge mahotas
    if [ $? -ne 0 ]; then
        echo "conda-forge mahotas install failed; continuing with pip requirements."
    fi
fi
"$ANACONDA_PYTHON" -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

echo
echo "[5/5] Writing 92_run_from_anaconda.sh..."
cat > 92_run_from_anaconda.sh <<EOF
#!/usr/bin/env bash
# Start AFM Nanofiber Analyzer with the Anaconda/Miniconda Python detected by setup.
# setup で検出した Anaconda/Miniconda の Python で AFM Nanofiber Analyzer を起動する。
# Re-run 91_setup_anaconda.sh if this Python path changes.
# この Python パスが変わった場合は 91_setup_anaconda.sh を再実行する。
set -u

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "\$SCRIPT_DIR" || exit 1

ANACONDA_PYTHON="$ANACONDA_PYTHON"

if [ ! -x "\$ANACONDA_PYTHON" ]; then
    echo "Anaconda Python was not found:"
    echo "\$ANACONDA_PYTHON"
    echo "Please run 91_setup_anaconda.sh again."
    exit 1
fi

"\$ANACONDA_PYTHON" Main.py
EOF
if [ $? -ne 0 ]; then
    echo "Failed to write 92_run_from_anaconda.sh."
    exit 1
fi
chmod +x 92_run_from_anaconda.sh

echo
echo "Setup completed."
echo "You can now start the application with ./92_run_from_anaconda.sh."
