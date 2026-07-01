#!/usr/bin/env bash
# Idempotent launcher for AFM Nanofiber Analyzer using a dedicated conda env.
# 専用の conda 環境を使う冪等ランチャー。
# First run creates the .conda-env prefix and installs the package; later runs
# skip setup and start the app directly. A damaged env is repaired on the next
# run (see the health check below).
# 初回は .conda-env prefix を作成してパッケージを導入し、以降はセットアップを
# 省略してアプリを直接起動する。壊れた環境は次回起動時に自動修復する。
# The default environment directory is .conda-env in the project folder.
# 既定の環境ディレクトリはプロジェクトフォルダ内の .conda-env。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

ENV_DIR="${AFM_ANALYZER_CONDA_ENV_DIR:-$SCRIPT_DIR/.conda-env}"
CONDA_CMD="${CONDA_EXE:-}"

# Marker written after a successful install. It lives inside the env so deleting
# the environment also clears it and forces a clean re-setup on the next run.
# インストール成功時に書き込むマーカー。環境内に置くため、環境を削除すると
# マーカーも消え、次回起動時にセットアップが再実行される。
MARKER="$ENV_DIR/.afm_setup_done"
ENV_PY="$ENV_DIR/bin/python"

# ---- Locate conda (needed both to create the env and to run from it) ----
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

# Editable install into the existing env; also (re)writes the setup marker.
# 既存環境への編集可能インストール。セットアップマーカーも（再）作成する。
run_install() {
    echo
    echo "Installing the package and dependencies..."
    # Editable install resolves dependencies from pyproject.toml (the single source
    # of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
    # 編集可能インストールは依存関係を単一の真実の源である pyproject.toml から解決し、
    # afm-analyzer / afm-analyzer-cli コマンドを登録する。
    "$CONDA_CMD" run -p "$ENV_DIR" python -m pip install -e .
    if [ $? -ne 0 ]; then
        echo "Failed to install the package."
        return 1
    fi

    # Record a successful setup so later launches skip straight to running.
    # セットアップ成功を記録し、以降の起動ではセットアップを省略する。
    : > "$MARKER"
    echo
    echo "Setup completed."
    echo "Conda environment: $ENV_DIR"
    return 0
}

# Full rebuild: remove any broken prefix, recreate it, then install. Used when
# the env interpreter is missing (a fundamentally broken environment).
# フル再構築: 壊れた prefix を削除して作り直し、導入する。
run_full_setup() {
    # A fresh prefix avoids the case where a deleted package still has surviving
    # dist-info metadata, which would make pip skip reinstalling it.
    # 新しい prefix にすることで、削除済みパッケージの dist-info が残り pip が
    # 再導入をスキップする問題を防ぐ。
    if [ -e "$ENV_DIR" ]; then
        echo
        echo "Removing the incomplete conda environment for a clean rebuild..."
        rm -rf "$ENV_DIR"
    fi

    echo
    echo "Creating conda environment: $ENV_DIR"
    "$CONDA_CMD" create -y -p "$ENV_DIR" python=3.11 pip
    if [ $? -ne 0 ]; then
        echo "Failed to create conda environment."
        return 1
    fi

    echo
    echo "Upgrading pip..."
    "$CONDA_CMD" run -p "$ENV_DIR" python -m pip install --upgrade pip
    if [ $? -ne 0 ]; then
        echo "Failed to upgrade pip."
        return 1
    fi

    run_install
}

# Health check: rebuild if the interpreter is gone, reinstall if only the marker
# is gone, otherwise fall through and launch.
# 健全性チェック: インタプリタが無ければ再構築、マーカーだけ無ければ再導入。
if [ ! -x "$ENV_PY" ]; then
    run_full_setup || exit 1
elif [ ! -f "$MARKER" ]; then
    echo "The setup marker is missing; reinstalling into the existing conda environment..."
    run_install || exit 1
fi

exec "$CONDA_CMD" run -p "$ENV_DIR" python "$SCRIPT_DIR/Main.py"
