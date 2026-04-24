#!/usr/bin/env bash
# ============================================================
#  Batch Humanizer - Linux/macOS Launcher
#  Jalankan: ./run.sh   (atau bash run.sh)
# ============================================================

set -e

# Pindah ke direktori script
cd "$(dirname "$0")"

echo
echo "============================================================"
echo "  Batch Humanizer - Launcher"
echo "============================================================"
echo

# === [1/3] Cek Python ===
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 tidak ditemukan."
    echo
    echo "Install Python 3.10+:"
    echo "  Ubuntu/Debian : sudo apt install python3 python3-venv -y"
    echo "  Fedora        : sudo dnf install python3 -y"
    echo "  macOS         : brew install python"
    echo
    exit 1
fi

# === [2/3] Cek FFmpeg ===
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[ERROR] ffmpeg tidak ditemukan."
    echo
    echo "Install FFmpeg:"
    echo "  Ubuntu/Debian : sudo apt install ffmpeg -y"
    echo "  Fedora        : sudo dnf install ffmpeg -y"
    echo "  macOS         : brew install ffmpeg"
    echo
    exit 1
fi

# === [3/3] Setup virtual environment + install dependencies (hanya pertama kali) ===
if [ ! -d venv ]; then
    echo "------------------------------------------------------------"
    echo "[3.1/3] Membuat virtual environment pertama kali..."
    echo "         (tunggu ~10-30 detik)"
    echo "------------------------------------------------------------"
    python3 -m venv venv
    echo "    > venv created"
    echo
fi

# Aktifkan venv
# shellcheck source=/dev/null
source venv/bin/activate

if [ ! -f venv/.installed ]; then
    echo "------------------------------------------------------------"
    echo "[3.2/3] Install dependencies dari requirements.txt"
    echo "         (tunggu ~1-3 menit)"
    echo "------------------------------------------------------------"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo "    > requirements.txt installed"
    touch venv/.installed
    echo
    echo "============================================================"
    echo "[SETUP SELESAI] Semua dependencies terinstall!"
    echo "============================================================"
    echo
fi

# === Pilih mode: CLI atau Web UI ===
# Kalau ada argumen CLI (misal --all), langsung ke mode CLI skip menu.
if [ $# -gt 0 ]; then
    MODE="1"
else
    echo
    echo "============================================================"
    echo "  Pilih Mode"
    echo "============================================================"
    echo "    1. CLI       (humanizer.py - mode interaktif / batch folder input)"
    echo "    2. Web UI    (app.py - Gradio di browser)"
    echo "============================================================"
    read -r -p "  Pilihan [1]: " MODE
    MODE="${MODE:-1}"
fi

case "$MODE" in
    2)
        echo
        echo "============================================================"
        echo "  Menjalankan Web UI Gradio"
        echo "  Buka browser ke: http://127.0.0.1:7860"
        echo "  Stop           : Ctrl+C"
        echo "============================================================"
        echo
        python app.py
        ;;
    *)
        echo
        echo "============================================================"
        echo "  Menjalankan Batch Humanizer (CLI)"
        echo "  Input  : input/"
        echo "  Output : output/"
        echo "  Stop   : Ctrl+C"
        echo "============================================================"
        echo
        python humanizer.py "$@"
        ;;
esac
