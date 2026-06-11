#!/usr/bin/env bash
# Create or update a dedicated conda environment for AFM Nanofiber Analyzer.
# AFM Nanofiber Analyzer 専用の conda 環境を作成または更新する。
# The default environment directory is .conda-env in the project folder.
# 既定の環境ディレクトリはプロジェクトフォルダ内の .conda-env。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

ENV_DIR="${AFM_ANALYZER_CONDA_ENV_DIR:-$SCRIPT_DIR/.conda-env}"
CONDA_CMD="${CONDA_EXE:-}"

echo "[1/6] Searching for conda..."

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

echo "Found:"
echo "$CONDA_CMD"

echo
echo "[2/6] Creating or reusing conda environment:"
echo "$ENV_DIR"
# conda run is used instead of activation so this script works from plain shells.
# 通常のシェルからも動くよう、環境の有効化ではなく conda run を使う。
if "$CONDA_CMD" run -p "$ENV_DIR" python --version >/dev/null 2>&1; then
    echo "Environment already exists."
else
    "$CONDA_CMD" create -y -p "$ENV_DIR" python=3.11 pip
    if [ $? -ne 0 ]; then
        echo "Failed to create conda environment."
        exit 1
    fi
fi

echo
echo "[3/6] Upgrading pip..."
"$CONDA_CMD" run -p "$ENV_DIR" python -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "Failed to upgrade pip."
    exit 1
fi

echo
echo "[4/6] Generating requirements..."
# check.py regenerates requirements.txt from the project imports before install.
# check.py はインストール前にプロジェクトの import から requirements.txt を再生成する。
"$CONDA_CMD" run -p "$ENV_DIR" python check.py
if [ $? -ne 0 ]; then
    echo "Failed to generate requirements.txt."
    exit 1
fi

echo
echo "[5/6] Installing requirements..."
echo "Installing mahotas with conda-forge first to avoid pip build failures..."
"$CONDA_CMD" install -y -p "$ENV_DIR" -c conda-forge mahotas
if [ $? -ne 0 ]; then
    echo "conda-forge mahotas install failed; continuing with pip requirements."
fi
"$CONDA_CMD" run -p "$ENV_DIR" python -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

echo
echo "[6/6] Writing 12_run_from_conda_env.sh..."
cat > 12_run_from_conda_env.sh <<'EOF'
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
    echo "Please run 11_setup_conda_env.sh first."
    exit 1
fi
EOF
if [ $? -ne 0 ]; then
    echo "Failed to write 12_run_from_conda_env.sh."
    exit 1
fi
chmod +x 12_run_from_conda_env.sh

echo
echo "Setup completed."
echo "Conda environment:"
echo "$ENV_DIR"
echo "You can now start the application with ./12_run_from_conda_env.sh."
