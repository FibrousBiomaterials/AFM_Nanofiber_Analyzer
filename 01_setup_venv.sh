#!/usr/bin/env bash
# Create or update the local .venv environment for AFM Nanofiber Analyzer.
# AFM Nanofiber Analyzer 用のローカル .venv 環境を作成または更新する。
# This path avoids conda and uses the first Python 3.10+ executable on PATH.
# conda を使わず、PATH 上で最初に見つかる Python 3.10 以上を使う。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "[1/7] Checking operating system..."
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
OS_PRETTY="$OS_NAME"
if [ -r /etc/os-release ]; then
    OS_PRETTY="$(. /etc/os-release && echo "${PRETTY_NAME:-$OS_NAME}")"
fi
echo "Detected OS: $OS_PRETTY"

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

echo
echo "[2/7] Checking Python..."
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
    exit 1
fi

"$PYTHON_CMD" --version

echo
echo "[3/7] Checking tkinter..."
ensure_tkinter "$PYTHON_CMD"
if [ $? -ne 0 ]; then
    echo
    echo "tkinter is required by the GUI but could not be prepared automatically."
    echo "Please install the tkinter package for your Python version, then run this file again."
    exit 1
fi

echo
echo "[4/7] Creating virtual environment..."
"$PYTHON_CMD" -m venv .venv
if [ $? -ne 0 ]; then
    echo "Failed to create .venv."
    exit 1
fi

echo
echo "[5/7] Upgrading pip..."
".venv/bin/python" -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "Failed to upgrade pip."
    exit 1
fi

echo
echo "[6/7] Generating requirements..."
# check.py regenerates requirements.txt from the project imports before install.
# check.py はインストール前にプロジェクトの import から requirements.txt を再生成する。
".venv/bin/python" check.py
if [ $? -ne 0 ]; then
    echo "Failed to generate requirements.txt."
    exit 1
fi

echo
echo "[7/7] Installing requirements..."
".venv/bin/python" -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

echo
echo "Writing 02_run_from_venv.sh..."
cat > 02_run_from_venv.sh <<'EOF'
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
EOF
if [ $? -ne 0 ]; then
    echo "Failed to write 02_run_from_venv.sh."
    exit 1
fi
chmod +x 02_run_from_venv.sh

echo
echo "Setup completed."
echo "You can now start the application with ./02_run_from_venv.sh."
