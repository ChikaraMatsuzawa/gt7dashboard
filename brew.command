#!/bin/bash

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

# Remove existing virtual environment to avoid Python version conflicts
if [ -d "./venv" ]; then
    echo "Cleaning up existing virtual environment..."
    rm -rf ./venv
fi

$PYTHON_BIN -m venv ./venv
source ./venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 helper/download_cars_csv.py
python3 -m bokeh serve .
