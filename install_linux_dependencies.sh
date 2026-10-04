#!/usr/bin/env bash
set -e

echo "=========================================="
echo "AutoRO Linux Dependencies Installer"
echo "=========================================="
echo "This helper script installs the required system packages"
echo "so you can run AutoRO natively on this Linux machine."
echo "Dependencies: Python 3, venv, and poppler-utils (for PDF extraction)."
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo or as root:"
  echo "sudo bash install_linux_dependencies.sh"
  exit 1
fi

echo "Updating package lists..."
apt-get update

echo "Installing python3, python3-venv, and poppler-utils..."
apt-get install -y python3 python3-venv poppler-utils

echo "=========================================="
echo "Success! You can now run AutoRO using:"
echo "./start_autoro_linux.sh"
echo "=========================================="
