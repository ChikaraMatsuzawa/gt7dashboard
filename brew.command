#!/bin/bash

set -euo pipefail

# This script should be used on MacOS when Python is a managed environment;
# i.e.: when Python is installed via Homebrew or similar package managers

cd "$(dirname "$0")"

# Use C telemetry by default while allowing callers to request another format.
export GT7_PACKET_FORMAT="${GT7_PACKET_FORMAT:-C}"

# Python 3.14 does not have precompiled wheels for scipy/pandas, causing compilation errors.
# Prefer Python 3.13 or 3.12 if they are available.
PYTHON_BIN="python3"
if command -v python3.13 &>/dev/null; then
    PYTHON_BIN="python3.13"
elif command -v python3.12 &>/dev/null; then
    PYTHON_BIN="python3.12"
fi

echo "Using Python binary: $PYTHON_BIN"
echo "Using GT7 packet format: $GT7_PACKET_FORMAT"

# Reuse the virtual environment unless the selected Python version changed.
# Set GT7_REBUILD_VENV=true to explicitly recreate it.
VENV_DIR="./venv"
VENV_PYTHON="$VENV_DIR/bin/python"
SELECTED_PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
VENV_NEEDS_CREATE=false

if [ "${GT7_REBUILD_VENV:-false}" = "true" ]; then
    echo "Recreating virtual environment on request..."
    VENV_NEEDS_CREATE=true
elif [ ! -x "$VENV_PYTHON" ]; then
    echo "Creating virtual environment..."
    VENV_NEEDS_CREATE=true
else
    VENV_PYTHON_VERSION=$("$VENV_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [ "$VENV_PYTHON_VERSION" != "$SELECTED_PYTHON_VERSION" ]; then
        echo "Recreating virtual environment for Python $SELECTED_PYTHON_VERSION..."
        VENV_NEEDS_CREATE=true
    fi
fi

if [ "$VENV_NEEDS_CREATE" = true ]; then
    rm -rf "$VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

REQUIREMENTS_STAMP="$VENV_DIR/.requirements-sha256"
REQUIREMENTS_HASH=$(shasum -a 256 requirements.txt | awk '{print $1}')
if [ "$VENV_NEEDS_CREATE" = true ] || [ ! -f "$REQUIREMENTS_STAMP" ] || [ "$(cat "$REQUIREMENTS_STAMP")" != "$REQUIREMENTS_HASH" ]; then
    echo "Installing Python dependencies..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    printf '%s\n' "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
else
    echo "Reusing existing virtual environment."
fi

if [ ! -f "db/cars.csv" ]; then
    python helper/download_cars_csv.py
fi

python -m bokeh serve .
