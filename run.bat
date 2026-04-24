@echo off
REM ============================================================
REM  Batch Humanizer - Windows Launcher
REM  Double-click file ini untuk setup (sekali) lalu run humanizer.
REM ============================================================

setlocal enabledelayedexpansion

REM Pindah ke direktori file .bat (biar bisa di-klik dari mana saja)
cd /d "%~dp0"

echo.
echo ============================================================
echo   Batch Humanizer - Windows Launcher
echo ============================================================
echo.

REM === [1/3] Cek Python ===
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan di PATH.
    echo.
    echo Install Python 3.10+ dari:
    echo    https://www.python.org/downloads/
    echo Saat install, CENTANG kotak "Add Python to PATH".
    echo Setelah install, tutup jendela ini dan klik ulang file .bat.
    echo.
    pause
    exit /b 1
)

REM === [2/3] Cek FFmpeg ===
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFmpeg tidak ditemukan di PATH.
    echo.
    echo Install dengan perintah berikut di PowerShell/CMD sebagai Administrator:
    echo    winget install Gyan.FFmpeg
    echo.
    echo Setelah install, tutup semua terminal lalu klik ulang file .bat ini.
    echo.
    pause
    exit /b 1
)

REM === [3/3] Setup virtual environment + install dependencies (hanya pertama kali) ===
if not exist venv (
    echo ------------------------------------------------------------
    echo [3.1/3] Membuat virtual environment pertama kali...
    echo         ^(tunggu ~10-30 detik^)
    echo ------------------------------------------------------------
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Gagal membuat venv. Pastikan Python 3.10+ terinstall.
        pause
        exit /b 1
    )
    echo     ^> venv created
    echo.
)

call venv\Scripts\activate.bat

if not exist venv\.installed (
    echo ------------------------------------------------------------
    echo [3.2/3] Install dependencies dari requirements.txt
    echo         ^(tunggu ~1-3 menit^)
    echo ------------------------------------------------------------
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Gagal install dependencies.
        pause
        exit /b 1
    )
    echo     ^> requirements.txt installed

    REM Marker: tandai sudah ter-install biar run berikutnya skip step ini
    type nul > venv\.installed
    echo.
    echo ============================================================
    echo [SETUP SELESAI] Semua dependencies terinstall!
    echo ============================================================
    echo.
    pause
)

REM === Jalankan workflow ===
echo.
echo ============================================================
echo   Menjalankan Batch Humanizer
echo   Input  : input\
echo   Output : output\
echo   Stop   : Ctrl+C
echo ============================================================
echo.

python humanizer.py %*

echo.
echo Selesai. Tekan tombol apa saja untuk menutup jendela.
pause
