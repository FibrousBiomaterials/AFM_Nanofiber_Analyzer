#!/usr/bin/env bash
# Idempotent launcher for AFM Nanofiber Analyzer using a local .venv.
# ローカル .venv を使う冪等ランチャー。
# First run creates .venv, checks tkinter, and installs the package; later runs
# skip setup and start the app directly. A damaged .venv is repaired on the next
# run (see the health check below).
# 初回は .venv 作成・tkinter 確認・パッケージ導入を行い、以降はセットアップを
# 省略してアプリを直接起動する。壊れた .venv は次回起動時に自動修復する。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Marker written after a successful install. It lives inside .venv so deleting
# the environment also clears it and forces a clean re-setup on the next run.
# インストール成功時に書き込むマーカー。.venv 内に置くため、環境を削除すると
# マーカーも消え、次回起動時にセットアップが再実行される。
MARKER=".venv/.afm_setup_done"
VENV_PY=".venv/bin/python"

install_tkinter_package() {
    py_cmd="$1"
    py_version="$("$py_cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    echo
    echo "tkinter is not available for $py_cmd (Python $py_version)."

    if [ "$OS_NAME" != "Linux" ]; then
        echo "Automatic tkinter installation is only supported for common Linux package managers."
        return 1
    fi

    if command -v apt-get >/dev/null 2>&1; then
        package_name="python${py_version}-tk"
        if ! apt-cache show "$package_name" >/dev/null 2>&1; then
            package_name="python3-tk"
        fi

        echo "Installing $package_name with apt-get..."
        sudo apt-get update
        if [ $? -ne 0 ]; then
            echo "Failed to update apt package lists."
            return 1
        fi
        sudo apt-get install -y "$package_name"
        return $?
    fi

    if command -v dnf >/dev/null 2>&1; then
        echo "Installing python3-tkinter with dnf..."
        sudo dnf install -y python3-tkinter
        return $?
    fi

    if command -v yum >/dev/null 2>&1; then
        echo "Installing tkinter with yum..."
        sudo yum install -y python3-tkinter
        return $?
    fi

    if command -v zypper >/dev/null 2>&1; then
        echo "Installing python3-tk with zypper..."
        sudo zypper install -y python3-tk
        return $?
    fi

    if command -v pacman >/dev/null 2>&1; then
        echo "Installing tk with pacman..."
        sudo pacman -Sy --needed tk
        return $?
    fi

    echo "No supported package manager was found for automatic tkinter installation."
    return 1
}

ensure_tkinter() {
    py_cmd="$1"

    if "$py_cmd" -c 'import tkinter' >/dev/null 2>&1; then
        echo "tkinter: available"
        return 0
    fi

    install_tkinter_package "$py_cmd"
    if [ $? -ne 0 ]; then
        echo "Failed to install tkinter for $py_cmd."
        return 1
    fi

    if "$py_cmd" -c 'import tkinter' >/dev/null 2>&1; then
        echo "tkinter: available after installation"
        return 0
    fi

    echo "tkinter is still not available after installation."
    return 1
}

# Editable install into the existing .venv; also (re)writes the setup marker.
# 既存 .venv への編集可能インストール。セットアップマーカーも（再）作成する。
run_install() {
    echo
    echo "Installing the package and dependencies..."
    # Editable install resolves dependencies from pyproject.toml (the single source
    # of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
    # 編集可能インストールは依存関係を単一の真実の源である pyproject.toml から解決し、
    # afm-analyzer / afm-analyzer-cli コマンドを登録する。
    "$VENV_PY" -m pip install -e .
    if [ $? -ne 0 ]; then
        echo "Failed to install the package."
        return 1
    fi

    # Record a successful setup so later launches skip straight to running.
    # セットアップ成功を記録し、以降の起動ではセットアップを省略する。
    : > "$MARKER"
    echo
    echo "Setup completed."
    return 0
}

# Full rebuild: verify Python/tkinter, remove any broken .venv, recreate it, and
# install. Used when the interpreter is missing (a fundamentally broken env).
# フル再構築: Python/tkinter を確認し、壊れた .venv を削除して作り直し、導入する。
run_full_setup() {
    echo "Checking operating system..."
    OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
    OS_PRETTY="$OS_NAME"
    if [ -r /etc/os-release ]; then
        OS_PRETTY="$(. /etc/os-release && echo "${PRETTY_NAME:-$OS_NAME}")"
    fi
    echo "Detected OS: $OS_PRETTY"

    echo
    echo "Checking Python..."
    PYTHON_CMD=""

    # Accept python3 or python, but only if it satisfies the supported version floor.
    # python3 または python を受け入れるが、対応する最低バージョンを満たす場合に限る。
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                PYTHON_CMD="$candidate"
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo
        echo "Python 3.10 or later was not found."
        echo "Please install Python 3.10 or later, then run this file again."
        return 1
    fi

    "$PYTHON_CMD" --version

    echo
    echo "Checking tkinter..."
    ensure_tkinter "$PYTHON_CMD"
    if [ $? -ne 0 ]; then
        echo
        echo "tkinter is required by the GUI but could not be prepared automatically."
        echo "Please install the tkinter package for your Python version, then run this file again."
        return 1
    fi

    # A usable Python is available, so a broken .venv can be safely removed for a
    # clean rebuild. Removing it first avoids the case where a deleted package
    # still has surviving dist-info metadata, which would make pip skip it.
    # 使える Python が確認できたので、壊れた .venv を削除して作り直せる。先に削除する
    # ことで、削除済みパッケージの dist-info が残り pip が再導入をスキップする問題を防ぐ。
    if [ -e ".venv" ]; then
        echo
        echo "Removing the incomplete .venv for a clean rebuild..."
        rm -rf ".venv"
    fi

    echo
    echo "Creating virtual environment..."
    "$PYTHON_CMD" -m venv .venv
    if [ $? -ne 0 ]; then
        echo "Failed to create .venv."
        return 1
    fi

    echo
    echo "Upgrading pip..."
    "$VENV_PY" -m pip install --upgrade pip
    if [ $? -ne 0 ]; then
        echo "Failed to upgrade pip."
        return 1
    fi

    run_install
}

# Health check: rebuild if the interpreter is gone, reinstall if only the marker
# is gone, otherwise fall through and launch.
# 健全性チェック: インタプリタが無ければ再構築、マーカーだけ無ければ再導入。
if [ ! -x "$VENV_PY" ]; then
    run_full_setup || exit 1
elif [ ! -f "$MARKER" ]; then
    echo "The setup marker is missing; reinstalling into the existing .venv..."
    run_install || exit 1
fi

if [ ! -x "$VENV_PY" ]; then
    echo ".venv is unavailable and could not be prepared."
    echo "Delete the .venv folder and run this file again."
    exit 1
fi

exec "$VENV_PY" "$SCRIPT_DIR/Main.py"
